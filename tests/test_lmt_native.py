"""Tensor/security and translation contract tests; these are not ML benchmarks."""
import asyncio
import base64
import json
import sys
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from lmt_onnx import NativeOnnx, decode_tensor, encode_tensor, weight_url_allowed
from lmt_translate import SegmentTranslator


class TensorTests(TestCase):
    def test_round_trip_preserves_integer_ids_and_floats(self):
        for value in [np.array([[2, 2**54, 3]], dtype=np.int64),
                      np.arange(24, dtype=np.float32).reshape(1, 3, 2, 4),
                      np.array([True, False]), np.array([1.5], dtype=np.float16), np.array(3, dtype=np.int32)]:
            np.testing.assert_array_equal(value, decode_tensor(encode_tensor(value)))

    def test_rejects_malformed_and_oversized_tensors(self):
        for value in [{'type': 'object', 'dims': [1], 'data': ''},
                      {'type': 'float32', 'dims': [-1], 'data': ''},
                      {'type': 'float32', 'dims': [16000000, 16000000], 'data': ''},
                      {'type': 'int64', 'dims': [1], 'data': base64.b64encode(b'x').decode()}]:
            with self.assertRaises(ValueError): decode_tensor(value)

    def test_network_boundary(self):
        self.assertTrue(weight_url_allowed('https://us.aws.cdn.hf.co/model'))
        for url in ['http://169.254.169.254/model', 'https://huggingface.co.evil.test/model',
                    'https://user:key@huggingface.co/model', 'https://huggingface.co:8443/model']:
            self.assertFalse(weight_url_allowed(url))

class BridgeTests(IsolatedAsyncioTestCase):
    async def test_model_must_be_in_build_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'native-models.json').write_text(json.dumps({'model.onnx': 'a'*64}))
            runtime = NativeOnnx(temp, temp)
            runtime._download = AsyncMock()
            with self.assertRaises(ValueError):
                await runtime.create({'url': 'https://huggingface.co/model', 'sha': 'b'*64}, True)
            runtime._download.assert_not_called()

    async def test_each_nonempty_segment_has_its_own_response(self):
        translator = SegmentTranslator()
        translator._complete = AsyncMock(side_effect=['Сегодня последний день перед пенсией.', 'Возвращаюсь домой.'])
        result = await translator.translate({'texts': ['今日', '', '帰る'], 'target': 'Russian'})
        self.assertEqual(result['translations'], ['Сегодня последний день перед пенсией.', '', 'Возвращаюсь домой.'])
        self.assertEqual(translator._complete.await_count, 2)

    async def test_untranslated_source_is_rejected(self):
        translator = SegmentTranslator()
        translator._complete = AsyncMock(return_value='家に帰る')
        with self.assertRaisesRegex(ValueError, 'untranslated'):
            await translator.translate({'texts':['家に帰る'], 'target':'Russian'})

    async def test_cancellation_keeps_cpu_work_serialized(self):
        import threading
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'native-models.json').write_text('{}')
            runtime = NativeOnnx(temp, temp)
            started, finish = threading.Event(), threading.Event()
            def kernel(): started.set(); finish.wait(2)
            task = asyncio.create_task(runtime._work(kernel))
            await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(.02)
            self.assertTrue(runtime.lock.locked())
            finish.set()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertFalse(runtime.lock.locked())
