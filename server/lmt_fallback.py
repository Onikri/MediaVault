# SPDX-License-Identifier: AGPL-3.0-or-later
"""Translate manga bubbles that Google refused (PROHIBITED_CONTENT and other
safety blocks) without Google: the LMT production OCR reads the crops on the
VM, the local Hy-MT2 model translates the recognised text into Russian.

The reader sends only crops of bubbles that Google still refused after the
request was split; detection, cleaning and typesetting stay in the reader.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CROPS = 40
MAX_CROP_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_CROP_PIXELS = 4_000_000
LETTERS = re.compile(r'[^\W\d_]', re.UNICODE)
CYRILLIC = re.compile(r'[А-Яа-яЁё]')


class Crop(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,64}$')
    image: str = Field(min_length=20, max_length=MAX_CROP_BYTES * 4 // 3 + 4)


class FallbackBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # Japanese, Korean and English only: the VM keeps no other OCR/translation pair.
    language: Literal['Japanese', 'Korean', 'English']
    crops: list[Crop] = Field(min_length=1, max_length=MAX_CROPS)


def check_crops(crops):
    """Decode and verify every crop before Chromium sees it."""
    from PIL import Image
    total = 0
    for crop in crops:
        try:
            data = base64.b64decode(crop.image, validate=True)
        except ValueError:
            raise ValueError('Вырезка реплики повреждена.') from None
        total += len(data)
        if len(data) > MAX_CROP_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('Вырезки реплик превышают лимит запроса.')
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > MAX_CROP_PIXELS:
                    raise ValueError('Вырезка реплики слишком велика.')
                image.verify()
        except ValueError:
            raise
        except Exception:
            raise ValueError('Вырезка реплики не является изображением.') from None


def normalize_source(text, language):
    """English manga lettering is all caps; Paddle returns it in mixed case
    ("trEATING", "thIS i5"), which Hy-MT2 misreads as names or products.
    Translate a sentence-cased version; Japanese and Korean stay unchanged."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if language != 'English':
        return text
    # Line-end hyphenation (DIREC-| TOR, WEL- COME) joins; stutters (Y-YOU) stay.
    text = re.sub(r'(?<=[A-Za-z]{2})-[\s|]+(?=[A-Za-z])', '', text).replace('|', ' ')
    text = text.lower()
    text = re.sub(r"\bi\b", 'I', text)
    return re.sub(r'(^|[.!?…]\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), text).strip()


def clean_translation(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip().strip('"«»“”').strip()


async def translate_refused(runtime, translator, body):
    """OCR every crop, then translate each recognised bubble on its own.

    One bubble failing must not discard the others: every row reports its own
    status (translated, non_text or error) and timings.
    """
    started = time.perf_counter()
    check_crops(body.crops)
    ocr = await runtime.recognize([c.model_dump() for c in body.crops], body.language)
    ocr_ms = round((time.perf_counter() - started) * 1000)
    by_id = {row.get('id'): row for row in ocr.get('rows', [])}
    rows = []
    for crop in body.crops:
        found = by_id.get(crop.id) or {}
        source = str(found.get('text') or '').strip()
        row = {'id': crop.id, 'source': source, 'ru': '', 'ocrMs': found.get('ms'),
               **({'gate': found['gate']} if found.get('gate') else {})}
        # The production script gate/OCR found no lettering: a detector false
        # positive, not dialogue. Never send noise to the translator.
        if not source or not LETTERS.search(source):
            rows.append({**row, 'status': 'non_text'})
            continue
        begin = time.perf_counter()
        try:
            answer = await translator.translate({'texts': [normalize_source(source, body.language)], 'target': 'Russian'})
            ru = clean_translation(answer['translations'][0])
            if not CYRILLIC.search(ru):
                raise ValueError('Модель вернула реплику без перевода.')
            rows.append({**row, 'ru': ru, 'status': 'translated'})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else 'Запасная модель не ответила.'
            rows.append({**row, 'status': 'error', 'error': message[:200]})
        rows[-1]['translationMs'] = round((time.perf_counter() - begin) * 1000)
    return {'model': os.getenv('LMT_LLM_MODEL', 'Hy-MT2-1.8B-Q8_0'), 'ocr': ocr.get('engine', ''),
            'language': body.language, 'rows': rows,
            'timings': {'ocrMs': ocr_ms, 'totalMs': round((time.perf_counter() - started) * 1000)}}
