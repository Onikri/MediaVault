"""Russian word stress for narration: RUAccent (code Apache-2.0, weights MIT).

The neural accentuator marks the stressed vowel with '+' (and restores ё).
Supertonic reads a combining acute (U+0301) after the vowel, so marks are
moved onto the ORIGINAL text word by word: the book's letters, punctuation and
spacing are never rewritten; only U+0301 is added and е may become ё.
Models are downloaded once, at a pinned revision, into the data volume; the
koziev morphology files are placed in the image at build time (Dockerfile).
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from pathlib import Path

REPO = 'ruaccent/accentuator'
REVISION = 'b78ae5ea1e62beaf138bed1865cd8c3b0b5ca855'
OMOGRAPH_MODEL = 'turbo3.1'
PATTERNS = ['dictionary/*', 'dictionary/rule_engine/*', 'nn/nn_accent/*', 'nn/nn_omograph/' + OMOGRAPH_MODEL + '/*',
            'nn/nn_stress_usage_predictor/*', 'nn/nn_yo_homograph_resolver/*']
ENGINE = 'RUAccent 1.5.8.3 · ' + OMOGRAPH_MODEL
ACUTE = '́'
VOWELS = 'аеёиоуыэюяАЕЁИОУЫЭЮЯ'
WORD = re.compile(r'[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*')
MARKED = re.compile('[А-Яа-яЁё́]+(?:-[А-Яа-яЁё́]+)*')
MAX_TEXT, MAX_TOTAL = 4000, 200_000

_lock = threading.Lock()          # one accentuator call at a time (CPU bound)
_load_lock = threading.Lock()
_engine = None
_state = {'phase': 'idle', 'error': '', 'started': 0.0, 'ready': 0.0}
_cache: OrderedDict = OrderedDict()


class Warming(Exception):
    """The model is still downloading or loading; retry shortly."""


def workdir():
    return Path(os.getenv('DATA_DIR', '/data')) / 'models' / 'ruaccent'


def _load():
    try:
        from huggingface_hub import snapshot_download
        from ruaccent import RUAccent
        root = workdir(); root.mkdir(parents=True, exist_ok=True)
        snapshot_download(REPO, revision=REVISION, allow_patterns=PATTERNS, local_dir=str(root))
        accent = RUAccent()
        accent.load(omograph_model_size=OMOGRAPH_MODEL, use_dictionary=True, tiny_mode=False, workdir=str(root))
        global _engine
        _engine = accent
        _state.update(phase='ready', error='', ready=time.time())
    except Exception as error:  # surfaced to the client as a readable state
        _state.update(phase='error', error=type(error).__name__ + ': ' + str(error)[:200])


def start():
    """Begin loading in the background (idempotent)."""
    with _load_lock:
        if _engine is not None or _state['phase'] == 'loading':
            return
        _state.update(phase='loading', error='', started=time.time())
        threading.Thread(target=_load, name='ruaccent-load', daemon=True).start()


def status():
    return {'engine': ENGINE, 'phase': 'ready' if _engine is not None else _state['phase'], 'error': _state['error']}


def plain(word):
    """Comparable form: no stress marks, ё as е, lower case."""
    value = unicodedata.normalize('NFD', word).replace(ACUTE, '')
    return unicodedata.normalize('NFC', value).replace('ё', 'е').replace('Ё', 'Е').lower()


def plus_to_acute(text):
    return re.sub(r'\+([' + VOWELS + '])', lambda m: m.group(1) + ACUTE, text)


def _stressed_index(word):
    """Index of the vowel carrying U+0301 (or ё) in an accented word, counted in letters."""
    letters, index, marks = [], None, 0
    for char in unicodedata.normalize('NFC', word):
        if char == ACUTE:
            marks += 1
            if letters: index = len(letters) - 1
            continue
        letters.append(char)
    if marks > 1:
        return None, ''.join(letters)  # ambiguous: leave the word unmarked
    if index is None:
        index = next((i for i, c in enumerate(letters) if c in 'ёЁ'), None)
    return index, ''.join(letters)


def transfer(original, accented):
    """Copy stress (and ё) from RUAccent's output onto the original text."""
    marked = [m.group(0) for m in MARKED.finditer(plus_to_acute(accented))]
    out, cursor, at = [], 0, 0
    for match in WORD.finditer(original):
        word = match.group(0)
        # Align: the next accented word with the same letters (RUAccent may drop tokens).
        found = None
        for j in range(at, min(len(marked), at + 6)):
            if plain(marked[j]) == plain(word):
                found = j; break
        out.append(original[cursor:match.start()])
        cursor = match.end()
        if found is None:
            out.append(word); continue
        at = found + 1
        index, letters = _stressed_index(marked[found])
        vowels = sum(1 for c in word if c in VOWELS)
        if index is None or vowels < 2 or index >= len(word) or word[index] not in VOWELS:
            # One-syllable words need no mark; still take ё if RUAccent restored it.
            out.append(''.join('ё' if a in 'еЕ' and b == 'ё' else 'Ё' if a == 'Е' and b == 'Ё' else a for a, b in zip(word, letters)) if len(letters) == len(word) else word)
            continue
        chars = list(word)
        for i, (a, b) in enumerate(zip(word, letters)):
            if a in 'еЕ' and b in 'ёЁ': chars[i] = 'ё' if a == 'е' else 'Ё'
        if chars[index] not in 'ёЁ':
            chars[index] = chars[index] + ACUTE
        out.append(''.join(chars))
    out.append(original[cursor:])
    return ''.join(out)


def stress(texts, language='ru'):
    if language != 'ru':
        return list(texts)  # RUAccent is Russian only
    if not isinstance(texts, list) or not texts or len(texts) > 400:
        raise ValueError('Нужен список от 1 до 400 фраз.')
    if any(not isinstance(t, str) or len(t) > MAX_TEXT for t in texts) or sum(map(len, texts)) > MAX_TOTAL:
        raise ValueError('Слишком длинный текст для расстановки ударений.')
    if _engine is None:
        start()
        if _state['phase'] == 'error':
            raise RuntimeError('Модель ударений не загрузилась: ' + _state['error'])
        raise Warming('Модель ударений загружается.')
    result = []
    for text in texts:
        key = hashlib.sha256(text.encode()).digest()
        if key in _cache:
            _cache.move_to_end(key); result.append(_cache[key]); continue
        if not WORD.search(text):
            value = text
        else:
            with _lock:
                raw = _engine.process_all(text)
            value = transfer(text, raw)
            if plain(value) != plain(text):  # never change the book's letters
                value = text
        _cache[key] = value
        while len(_cache) > 20000:
            _cache.popitem(last=False)
        result.append(value)
    return result
