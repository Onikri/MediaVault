# SPDX-License-Identifier: AGPL-3.0-or-later
"""CPU ONNX bridge for the private LMT page; never accepts arbitrary models."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import numpy as np


def weight_url_allowed(raw):
    url = urlsplit(raw)
    return url.scheme == 'https' and not url.username and not url.password and url.port in (None, 443) and (
        url.hostname in {'huggingface.co', 'hf.co'} or
        (url.hostname or '').endswith('.hf.co') or (url.hostname or '').endswith('.huggingface.co'))


DTYPES = {name: np.dtype(dtype) for name, dtype in {
    'float32': '<f4', 'float64': '<f8', 'float16': '<f2', 'int64': '<i8',
    'int32': '<i4', 'int16': '<i2', 'int8': 'i1', 'uint8': 'u1',
    'uint16': '<u2', 'uint32': '<u4', 'uint64': '<u8', 'bool': '?',
}.items()}
MAX_TENSOR_BYTES = 128 * 1024 * 1024


def decode_tensor(tensor):
    dtype = DTYPES.get(tensor.get('type'))
    dims = tensor.get('dims')
    if dtype is None or not isinstance(dims, list) or len(dims) > 8 or any(
            type(n) is not int or n < 0 or n > 16_777_216 for n in dims):
        raise ValueError('Invalid ONNX tensor')
    size = math.prod(dims) * dtype.itemsize
    data = tensor.get('data', '')
    if size > MAX_TENSOR_BYTES or not isinstance(data, str) or len(data) > (MAX_TENSOR_BYTES * 4 // 3 + 4):
        raise ValueError('ONNX tensor exceeds limit')
    raw = base64.b64decode(data, validate=True)
    if len(raw) != size:
        raise ValueError('ONNX tensor byte count mismatch')
    return np.frombuffer(raw, dtype=dtype).reshape(dims)


def encode_tensor(value):
    value = np.asarray(value)
    if not value.flags.c_contiguous:
        value = np.ascontiguousarray(value)
    name = next((k for k, v in DTYPES.items() if v == value.dtype), None)
    if name is None or value.nbytes > MAX_TENSOR_BYTES:
        raise ValueError('Unsupported ONNX output')
    return {'type': name, 'dims': list(value.shape), 'data': base64.b64encode(value.tobytes()).decode()}


class NativeOnnx:
    def __init__(self, assets, directory, threads=2):
        self.allowed = set(json.loads((Path(assets) / 'native-models.json').read_text()).values())
        self.directory = Path(directory)
        self.threads = max(1, min(4, threads))
        self.lock = asyncio.Lock()
        self.sessions = OrderedDict()
        self.known = {}

    async def _download(self, url, sha, allow_downloads):
        target = self.directory / (sha + '.onnx')
        if target.is_file():
            # Verify once per runtime, including disk cache hits.
            def file_hash():
                with target.open('rb') as source:
                    return hashlib.file_digest(source, 'sha256').hexdigest()
            if await asyncio.to_thread(file_hash) == sha:
                return target
            raise ValueError('Cached ONNX model failed integrity check')
        if not allow_downloads:
            raise ValueError('ONNX model is not cached; allow downloads explicitly')
        self.directory.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix('.partial')
        try:
            async with httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False) as client:
                for _ in range(8):
                    if not weight_url_allowed(url):
                        raise ValueError('Model redirect outside trusted weight hosts')
                    async with client.stream('GET', url) as response:
                        if response.is_redirect:
                            url = str(response.url.join(response.headers['location']))
                            continue
                        response.raise_for_status()
                        digest, size = hashlib.sha256(), 0
                        with partial.open('wb') as output:
                            async for chunk in response.aiter_bytes(1024 * 1024):
                                size += len(chunk)
                                if size > 1024 * 1024 * 1024:
                                    raise ValueError('Model exceeds size limit')
                                digest.update(chunk)
                                output.write(chunk)
                        if digest.hexdigest() != sha:
                            raise ValueError('ONNX model failed integrity check')
                        partial.replace(target)
                        return target
                raise ValueError('Too many model redirects')
        finally:
            partial.unlink(missing_ok=True)

    def _session(self, sha):
        import onnxruntime as ort
        if sha not in self.sessions:
            # Bound resident weights; an evicted JS handle lazily reloads.
            while len(self.sessions) >= 4:
                self.sessions.popitem(last=False)
            options = ort.SessionOptions()
            options.intra_op_num_threads = self.threads
            options.inter_op_num_threads = 1
            self.sessions[sha] = ort.InferenceSession(str(self.known[sha]), sess_options=options,
                                                     providers=['CPUExecutionProvider'])
        self.sessions.move_to_end(sha)
        return self.sessions[sha]

    async def _work(self, callback):
        async with self.lock:
            task = asyncio.create_task(asyncio.to_thread(callback))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # A running CPU kernel cannot be cancelled; keep serialization
                # until it finishes so the next job cannot double peak memory.
                try:
                    await task
                finally:
                    raise

    async def create(self, request, allow_downloads=False):
        sha, url = request.get('sha'), request.get('url', '')
        if sha not in self.allowed or not weight_url_allowed(url):
            raise ValueError('Model is not in the operator build manifest')
        async with self.lock:
            if sha not in self.known:
                self.known[sha] = await self._download(url, sha, allow_downloads)
        def load():
            session = self._session(sha)
            return {'id': sha, 'inputNames': [v.name for v in session.get_inputs()],
                    'outputNames': [v.name for v in session.get_outputs()]}
        return await self._work(load)

    async def run(self, request):
        sha = request.get('id')
        if sha not in self.known:
            raise ValueError('Unknown ONNX session')
        def infer():
            session = self._session(sha)
            feeds = request.get('feeds', {})
            if set(feeds) != {v.name for v in session.get_inputs()}:
                raise ValueError('ONNX input names mismatch')
            inputs = {k: decode_tensor(v) for k, v in feeds.items()}
            if sum(v.nbytes for v in inputs.values()) > MAX_TENSOR_BYTES:
                raise ValueError('ONNX input exceeds limit')
            values = session.run(None, inputs)
            return {meta.name: encode_tensor(v) for meta, v in zip(session.get_outputs(), values)}
        return await self._work(infer)

    async def release(self, request):
        await self._work(lambda: self.sessions.pop(request.get('id'), None))

    async def close(self):
        await self._work(self.sessions.clear)
