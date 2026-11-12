#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""REAL inference benchmark of the Google-refusal fallback on the Oracle VM.

Runs inside an LMT container (`/app` on sys.path) against the real LMT OCR in
headless Chromium and the real Hy-MT2 llama.cpp server. Nothing is mocked:
this is separate from the mocked API/browser contract tests.

Usage (inside the container):
  python refusal-fallback-vm.py CASES.json CROPS_DIR OUT.json [--batch 3]

CASES.json: [{"id","language":"en|ja|ko","reference","cropFile"}] — real bubble
crops with a human transcription. Each request carries `--batch` crops of one
language, like the refused bubbles of one page.
"""
import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, '/app')
LANG = {'en': 'English', 'ja': 'Japanese', 'ko': 'Korean'}


def cer(a, b):
    a = ''.join(str(a).split()).lower()
    b = ''.join(str(b).split()).lower()
    if not b:
        return 0.0 if not a else 1.0
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return round(prev[-1] / len(b), 3)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('cases')
    parser.add_argument('crops')
    parser.add_argument('out')
    parser.add_argument('--batch', type=int, default=3)
    args = parser.parse_args()
    from lmt_runtime import LmtRuntime
    from lmt_translate import SegmentTranslator
    from lmt_fallback import FallbackBody, translate_refused
    runtime = LmtRuntime(os.getenv('LMT_ASSETS_DIR', '/assets'), Path(os.getenv('LMT_DATA_DIR', '/data')) / 'lmt-browser')
    translator = SegmentTranslator('hymt2')
    cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    crops = {c['id']: base64.b64encode((Path(args.crops) / c['cropFile']).read_bytes()).decode() for c in cases}
    requests, rows = [], []
    try:
        for code in ('ja', 'ko', 'en'):
            group = [c for c in cases if c['language'] == code]
            for offset in range(0, len(group), args.batch):
                batch = group[offset:offset + args.batch]
                body = FallbackBody(language=LANG[code], crops=[{'id': c['id'], 'image': crops[c['id']]} for c in batch])
                started = time.perf_counter()
                answer = await translate_refused(runtime, translator, body)
                seconds = round(time.perf_counter() - started, 2)
                requests.append({'language': code, 'crops': len(batch), 'seconds': seconds,
                                 'ocrMs': answer['timings']['ocrMs'], 'model': answer['model'], 'ocr': answer['ocr'],
                                 'cold': not requests})
                for case, row in zip(batch, answer['rows']):
                    rows.append({'id': case['id'], 'language': code, 'reference': case['reference'],
                                 'ocrText': row['source'], 'cer': cer(row['source'], case['reference']),
                                 'status': row['status'], 'ru': row['ru'], 'error': row.get('error'),
                                 'ocrMs': row.get('ocrMs'), 'translationMs': row.get('translationMs')})
                print(json.dumps(requests[-1], ensure_ascii=False), flush=True)
    finally:
        await runtime.close()
    warm = [r for r in requests if not r['cold']]
    per_bubble = [r['seconds'] / r['crops'] for r in warm]
    summary = {
        'requests': len(requests), 'bubbles': len(rows),
        'coldFirstRequestSeconds': requests[0]['seconds'] if requests else None,
        'warmSecondsPerRequest': {'median': statistics.median([r['seconds'] for r in warm]), 'max': max(r['seconds'] for r in warm)} if warm else None,
        'warmSecondsPerBubble': {'median': round(statistics.median(per_bubble), 2), 'max': round(max(per_bubble), 2)} if warm else None,
        'byLanguage': {code: {
            'bubbles': sum(r['language'] == code for r in rows),
            'translated': sum(r['language'] == code and r['status'] == 'translated' for r in rows),
            'meanCer': round(statistics.mean([r['cer'] for r in rows if r['language'] == code]), 3) if any(r['language'] == code for r in rows) else None,
            'medianOcrMs': statistics.median([r['ocrMs'] or 0 for r in rows if r['language'] == code]) if any(r['language'] == code for r in rows) else None,
            'medianTranslationMs': statistics.median([r['translationMs'] or 0 for r in rows if r['language'] == code and r['translationMs']]) if any(r['language'] == code and r['translationMs'] for r in rows) else None,
        } for code in ('ja', 'ko', 'en')},
    }
    Path(args.out).write_text(json.dumps({'kind': 'real-inference', 'host': 'oracle-a1-2cpu', 'batch': args.batch,
                                          'summary': summary, 'requests': requests, 'rows': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    asyncio.run(main())
