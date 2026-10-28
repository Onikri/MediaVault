#!/usr/bin/env python3
"""Opt-in source/CBZ/stream tests using production modules, without Drive writes.

Run inside the importer with PYTHONPATH=/app. The isolated FastAPI routes below
do not change the running server or its authentication. Video fixtures are the
public Big Buck Bunny HLS and Sintel MP4; reader cases use published pages.
"""
import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib

checkout = next((p / 'server' for p in Path(__file__).resolve().parents if (p / 'server' / 'manga_sources.py').is_file()), None)
if checkout:
    sys.path.insert(0, str(checkout))
from fastapi import FastAPI
import online_sessions as online
from manga_sources import inspect, site_for
from manga_download import download_chapter, chapter_preview, image_extension
from manga_webtoons import search
from source_parser import PublicHttp
from vault_drive import seal_chunk, open_chunk

CASES = {
    'webtoon-original': 'https://www.webtoons.com/en/fantasy/tower-of-god/list?title_no=95',
    'webtoon-canvas': 'https://www.webtoons.com/en/canvas/tower-of-god-no-mans-tower/list?title_no=726081',
    'mangaraw': 'https://mangaraw.co.uk/manga/1424',
    'naver': 'https://comic.naver.com/webtoon/list?titleId=769209',
}
HLS = 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8'
MP4 = 'https://media.w3.org/2010/05/sintel/trailer.mp4'


def endpoints():
    app = FastAPI()
    online.install(app, lambda: 'isolated-reader-test')
    return {r.endpoint.__name__: r.endpoint for r in app.routes if hasattr(r, 'endpoint')}


async def prefix(response, limit):
    if hasattr(response, 'body'):
        return response.body[:limit]
    blocks = bytearray()
    iterator = response.body_iterator
    try:
        async for block in iterator:
            blocks.extend(block)
            if len(blocks) >= limit:
                break
    finally:
        await iterator.aclose()
    return bytes(blocks[:limit])


def capability_get(routes, url, range_header=''):
    _, _, token, resource = url.split('/')
    return routes['stream'](token, resource, range_header)


def media_line(text):
    return next(v.strip() for v in text.splitlines() if v.strip() and not v.startswith('#'))


def read_case(name):
    routes = endpoints()
    http = PublicHttp(timeout=(4, 12), deadline=time.monotonic() + 150)
    token = None
    result = {}
    try:
        start = time.monotonic()
        title = inspect(CASES[name], http)
        assert title['episodes'], 'No published chapters'
        chapter_url = title['episodes'][0]['url']
        result['titleMs'] = round((time.monotonic() - start) * 1000)
        start = time.monotonic()
        prepared = routes['prepare'](online.Prepare(url=chapter_url, kind='manga'), 'isolated-reader-test')
        token = prepared['id']
        response = capability_get(routes, prepared['pages'][0])
        image = asyncio.run(prefix(response, 30 * 1024**2))
        assert image_extension(image[:32]) and len(image) > 1000
        result.update(chapters=len(title['episodes']), pages=len(prepared['pages']), firstPageBytes=len(image),
                      firstPageMs=round((time.monotonic() - start) * 1000), imageSHA256=hashlib.sha256(image).hexdigest())
        if name == 'webtoon-original':
            found = search('Tower of God', site_for(CASES[name]), http)
            assert any('title_no=95' in v['url'] for v in found), 'Exact original missing from search'
            result['searchResults'] = len(found)
            with tempfile.TemporaryDirectory(prefix='mv-reader-test-') as folder:
                start = time.monotonic()
                cbz = download_chapter(chapter_url, folder, http)
                raw = cbz.read_bytes()
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    assert len(archive.namelist()) == len(prepared['pages'])
                    assert archive.read(archive.namelist()[0]) == image
                # Use a separate fresh test key; production vault keys are never read.
                key = secrets.token_bytes(32)
                encrypted = seal_chunk(raw, key, 'isolated-cbz-check', 0)
                assert open_chunk(encrypted['ciphertext'], key, 'isolated-cbz-check', 0, encrypted['iv']) == raw
                preview = chapter_preview(cbz)
                assert preview and preview.startswith(b'\xff\xd8\xff'), 'Missing actual chapter preview'
                result.update(cbzBytes=len(raw), cbzPages=len(prepared['pages']), encryptedRoundTrip=True,
                              previewBytes=len(preview), cbzMs=round((time.monotonic() - start) * 1000))
        return result
    finally:
        if token:
            routes['close'](token, 'isolated-reader-test')
        http.close()


def video_case(name):
    routes = endpoints()
    prepared = routes['prepare'](online.Prepare(url=HLS if name == 'hls' else MP4, kind='video', quality='720' if name == 'hls' else 'best'), 'isolated-reader-test')
    token = prepared['id']
    try:
        if name == 'mp4':
            response = capability_get(routes, prepared['url'], 'bytes=0-1023')
            raw = asyncio.run(prefix(response, 1024))
            assert response.status_code == 206 and len(raw) == 1024 and raw[4:8] == b'ftyp'
            assert response.headers['content-range'].startswith('bytes 0-1023/')
            return {'rangeBytes': len(raw), 'status': response.status_code, 'prepareMs': prepared.get('preparationMs')}
        response = capability_get(routes, prepared['url'])
        master = response.body.decode()
        assert 'RESOLUTION=' in master and '1920x1080' not in master and 'https://' not in master
        child = capability_get(routes, media_line(master)).body.decode()
        response = capability_get(routes, media_line(child))
        raw = asyncio.run(prefix(response, 512 * 1024))
        assert len(raw) >= 188 and raw[0] == 0x47
        frame = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-f', 'mpegts', '-i', 'pipe:0',
                                '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-threads', '1', '-'],
                               input=raw, capture_output=True, timeout=15).stdout
        assert frame.startswith(b'\xff\xd8\xff'), 'Actual streamed segment did not decode'
        return {'segmentBytes': len(raw), 'decodedFrameBytes': len(frame), 'maxHeight': 720, 'prepareMs': prepared.get('preparationMs')}
    finally:
        routes['close'](token, 'isolated-reader-test')


def run(name):
    started = time.monotonic()
    try:
        result = read_case(name) if name in CASES else video_case(name)
        return {'case': name, 'ok': True, **result, 'totalMs': round((time.monotonic() - started) * 1000)}
    except Exception as e:
        return {'case': name, 'ok': False, 'error': type(e).__name__ + ': ' + str(e)[:250],
                'totalMs': round((time.monotonic() - started) * 1000)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', action='append', choices=[*CASES, 'hls', 'mp4'])
    p.add_argument('--output', default='/tmp/mediavault-reader-test.json')
    p.add_argument('--compact', action='store_true', help='One small compressed result for Oracle Run Command inline limits.')
    args = p.parse_args()
    results = [run(name) for name in args.case or [*CASES, 'hls', 'mp4']]
    report = {'actualNetwork': True, 'architecture': platform.machine(), 'driveWrites': False,
              'provenance': 'Production parser and online routes in isolated test app; real source bytes and ffmpeg frame decode.', 'results': results}
    path = Path(args.output)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)
    if args.compact:
        compact = {'architecture': report['architecture'], 'results': [{k: v for k, v in row.items() if k not in {'imageSHA256', 'error'}} for row in results]}
        print('MVRESULT:' + base64.b64encode(zlib.compress(json.dumps(compact, separators=(',', ':')).encode(), 9)).decode(), flush=True)
    else:
        print(json.dumps(report, ensure_ascii=False), flush=True)
    sys.exit(0 if all(row['ok'] for row in results) else 1)
