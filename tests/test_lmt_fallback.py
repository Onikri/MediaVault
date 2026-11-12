"""MOCKED tests of the Google-refusal fallback service: OCR and Hy-MT2 are fakes.

Real OCR + Hy-MT2 inference on the Oracle VM is measured separately by
scripts/benchmarks/refusal-fallback-vm.py (see docs/manga-refusal-fallback.md).
"""
import asyncio
import base64
import io
from pathlib import Path
import sys
import tempfile
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from PIL import Image
from lmt_fallback import FallbackBody, translate_refused, check_crops


def png(width=40, height=30):
    out = io.BytesIO()
    Image.new('L', (width, height), 255).save(out, 'PNG')
    return base64.b64encode(out.getvalue()).decode()


class FakeRuntime:
    def __init__(self, rows, engine='manga-ocr'):
        self.rows, self.engine, self.calls = rows, engine, []

    async def recognize(self, crops, language):
        self.calls.append((language, [c['id'] for c in crops]))
        return {'engine': self.engine, 'rows': [{'id': c['id'], **self.rows.get(c['id'], {})} for c in crops]}


class FakeTranslator:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def translate(self, request):
        source = request['texts'][0]
        self.calls.append(source)
        answer = self.answers[source]
        if isinstance(answer, Exception):
            raise answer
        return {'translations': [answer]}


class TranslateRefusedTests(IsolatedAsyncioTestCase):
    async def test_rows_keep_status_per_bubble_and_never_translate_noise(self):
        runtime = FakeRuntime({
            'P1_B1': {'text': 'やめて…', 'ms': 900},
            'P1_B2': {'text': '', 'gate': 'not-japanese', 'ms': 40},
            'P1_B3': {'text': '……', 'ms': 30},
            'P1_B4': {'text': 'もっと', 'ms': 800},
            'P1_B5': {'text': '中に', 'ms': 700},
        })
        translator = FakeTranslator({'やめて…': '  «Перестань…»\n', 'もっと': 'More', '中に': ValueError('Model returned untranslated source text')})
        body = FallbackBody(language='Japanese', crops=[{'id': i, 'image': png()} for i in ('P1_B1', 'P1_B2', 'P1_B3', 'P1_B4', 'P1_B5')])
        answer = await translate_refused(runtime, translator, body)
        rows = {r['id']: r for r in answer['rows']}
        self.assertEqual(runtime.calls, [('Japanese', ['P1_B1', 'P1_B2', 'P1_B3', 'P1_B4', 'P1_B5'])])
        self.assertEqual(rows['P1_B1']['status'], 'translated')
        self.assertEqual(rows['P1_B1']['ru'], 'Перестань…')
        self.assertEqual(rows['P1_B1']['source'], 'やめて…')
        self.assertEqual(rows['P1_B2']['status'], 'non_text')
        self.assertEqual(rows['P1_B2']['gate'], 'not-japanese')
        self.assertEqual(rows['P1_B3']['status'], 'non_text')
        self.assertEqual(rows['P1_B4']['status'], 'error')  # no Cyrillic in the output
        self.assertEqual(rows['P1_B5']['status'], 'error')
        self.assertNotIn('……', translator.calls)
        self.assertEqual(answer['ocr'], 'manga-ocr')
        self.assertIn('ocrMs', answer['timings'])

    async def test_invalid_crops_never_reach_ocr(self):
        runtime = FakeRuntime({})
        for image in ('not-base64!!' * 3, base64.b64encode(b'plain text, not an image').decode()):
            with self.assertRaises(ValueError):
                await translate_refused(runtime, FakeTranslator({}), FallbackBody(language='English', crops=[{'id': 'A', 'image': image}]))
        self.assertEqual(runtime.calls, [])
        with self.assertRaises(ValueError):
            check_crops(FallbackBody(language='Korean', crops=[{'id': 'A', 'image': png(2100, 2000)}]).crops)

    def test_english_caps_are_sentence_cased_before_translation(self):
        from lmt_fallback import normalize_source
        self.assertEqual(normalize_source('Since thIS JOB i WANT', 'English'), 'Since this job I want')
        self.assertEqual(normalize_source("Y-YOU'RE WEL- COME. DIREC-| TOR!", 'English'), "Y-you're welcome. Director!")
        self.assertEqual(normalize_source('やめて…', 'Japanese'), 'やめて…')

    def test_only_japanese_korean_english_and_bounded_requests(self):
        from pydantic import ValidationError
        for language in ('Chinese (Simplified)', 'Russian'):
            with self.assertRaises(ValidationError):
                FallbackBody(language=language, crops=[{'id': 'A', 'image': png()}])
        with self.assertRaises(ValidationError):
            FallbackBody(language='English', crops=[{'id': 'A' + str(i), 'image': png()} for i in range(41)])
        with self.assertRaises(ValidationError):
            FallbackBody(language='English', crops=[{'id': '../x', 'image': png()}])


class FallbackRouteTests(TestCase):
    def test_route_requires_owner_and_returns_translated_rows(self):
        from fastapi.testclient import TestClient
        from lmt_service import app, owner
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'LMT_DATA_DIR': tmp, 'LMT_ASSETS_DIR': tmp, 'LMT_LLM_URL': 'http://llm.invalid/v1', 'LMT_LLM_MODEL': 'Hy-MT2-1.8B-Q8_0'}):
            Path(tmp, 'index.html').write_text('fixture')
            with TestClient(app) as client:
                body = {'language': 'Korean', 'crops': [{'id': 'P3_B1', 'image': png()}]}
                self.assertEqual(client.post('/reader/lmt/fallback', json=body).status_code, 401)
                processor = app.state.processor
                processor.runtime.recognize = AsyncMock(return_value={'engine': 'ppocrv5-korean', 'rows': [{'id': 'P3_B1', 'text': '그만해', 'ms': 50}]})
                processor.fallback_translator.translate = AsyncMock(return_value={'translations': ['Хватит!']})
                app.dependency_overrides[owner] = lambda: 'fixture-owner'
                try:
                    response = client.post('/reader/lmt/fallback', json=body)
                    self.assertEqual(response.status_code, 200)
                    data = response.json()
                    self.assertEqual(data['rows'][0]['ru'], 'Хватит!')
                    self.assertEqual(data['ocr'], 'ppocrv5-korean')
                    self.assertEqual(data['model'], 'Hy-MT2-1.8B-Q8_0')
                    bad = client.post('/reader/lmt/fallback', json={'language': 'Chinese (Simplified)', 'crops': body['crops']})
                    self.assertEqual(bad.status_code, 422)
                    processor.runtime.recognize = AsyncMock(side_effect=RuntimeError('chromium crashed /internal/path'))
                    failed = client.post('/reader/lmt/fallback', json=body)
                    self.assertEqual(failed.status_code, 502)
                    self.assertNotIn('/internal/path', failed.text)
                finally:
                    app.dependency_overrides.clear()


class RuntimeLockTests(IsolatedAsyncioTestCase):
    async def test_fallback_ocr_waits_for_a_running_page_job(self):
        from lmt_runtime import LmtRuntime
        with tempfile.TemporaryDirectory() as tmp:
            runtime = LmtRuntime(tmp, Path(tmp) / 'browser')
            order = []
            release = asyncio.Event()

            async def page_job(*args):
                order.append('page-start')
                await release.wait()
                order.append('page-end')
                return {}

            class Page:
                def is_closed(self):
                    return False

                async def evaluate(self, script, args):
                    order.append('ocr')
                    return {'engine': 'paddle', 'rows': []}
            runtime._run = page_job
            runtime.page = Page()
            job = asyncio.create_task(runtime.run(b'', {}, lambda _: None))
            await asyncio.sleep(0)
            ocr = asyncio.create_task(runtime.recognize([], 'English'))
            await asyncio.sleep(0.01)
            self.assertEqual(order, ['page-start'])
            release.set()
            await job
            await ocr
            self.assertEqual(order, ['page-start', 'page-end', 'ocr'])
            self.assertFalse(runtime.allow_downloads)
