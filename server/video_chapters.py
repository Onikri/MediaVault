"""Video chapters from subtitles: find a subtitle file, ask a Lite model for scenes, keep a tiny record.

Measured 2026-11-12 (three titles, three independent reference chapterings, nine Google models):
gemini-3.1-flash-lite with thinkingLevel low, a JSON schema and times copied as M:SS strings matched the
references best among the models allowed for text. Films longer than 40 minutes are cut into ~25-minute
windows at pauses and sent in parallel: one request on a 100-minute film gives a third of the scenes.

The model answers JSON (validated by schema); the VM turns it into WebVTT chapters, Matroska XML chapters
and FFmetadata. A record is a few hundred bytes, kept on the VM so an episode is marked up once.
"""
import asyncio
import gzip
import hashlib
import html
import json
import math
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape as xml_escape

PRIMARY = 'gemini-3.1-flash-lite'
FALLBACK = 'gemini-3.5-flash-lite'
VERSION = 2
WINDOW = 25 * 60
SINGLE_LIMIT = 40 * 60
MIN_GAP = 30
# Navigation, not a transcript: about one chapter per 4–5 minutes. A one-hour
# episode came back as 30 two-minute scenes (three windows of ~10 each).
SCENE = 270
RETRY_NONE = {'no-subtitles': 3 * 86400, 'invalid-subtitles': 3 * 86400, 'model-error': 3600}
RANK = {'player': 3, 'local': 3, 'collaps': 2, 'opensubtitles': 1}

SYSTEM = """Ты редактор видеоплатформы. По субтитрам размечаешь видео на главы, как автоматические главы YouTube: зритель видит их на шкале перемотки и сразу прыгает к нужной сцене.

Правила:
1. Глава — цельная сцена или сюжетный блок: меняется место, время, состав персонажей или цель происходящего. Не делай главу из пары реплик и не склеивай разные события в одну.
2. Сколько глав, решай сам по сюжету и длительности видео. Ориентируйся на то, что реально помогает навигации: у короткой серии крупных сцен немного, у полнометражного фильма их заметно больше.
3. start — момент начала сцены. Бери время из субтитров в их формате (M:SS или H:MM:SS). Если сцена явно начинается действием без слов, можно поставить start немного раньше её первой реплики, но не раньше последней реплики предыдущей сцены.
4. Первая глава начинается с начала отрезка. Главы идут по порядку и встык: end главы равен start следующей, end последней главы равен концу отрезка.
5. Длинные отрезки без реплик в начале или в конце (пролог без слов, опенинг, эндинг, титры) выдели отдельной главой, если они очевидны по таймингам.
6. title — по-русски, от 2 до 6 слов, конкретно о том, что происходит в сцене: кто, что делает, где. Без номеров, кавычек и точки в конце, не предложение. Не используй пустые слова вроде «Начало», «Продолжение», «Разговор», «Финал» без уточнения. Не раскрывай главный поворот сюжета в названиях ранних глав.
7. Субтитры могут быть на любом языке; названия всегда на русском. Имена и термины пиши так, как они приняты в русской локализации тайтла.
Отвечай только JSON по схеме."""

SCHEMA = {
    'type': 'object',
    'properties': {'chapters': {
        'type': 'array', 'description': 'Главы по порядку, встык, от начала до конца отрезка.',
        'items': {'type': 'object', 'properties': {
            'start': {'type': 'string', 'description': 'Начало главы, M:SS или H:MM:SS, как в субтитрах.'},
            'end': {'type': 'string', 'description': 'Конец главы = start следующей.'},
            'title': {'type': 'string', 'description': 'Название сцены по-русски, 2–6 слов.'}},
            'required': ['start', 'end', 'title']}}},
    'required': ['chapters'],
}
SAFETY = [{'category': c, 'threshold': 'BLOCK_NONE'} for c in
          ('HARM_CATEGORY_HARASSMENT', 'HARM_CATEGORY_HATE_SPEECH', 'HARM_CATEGORY_SEXUALLY_EXPLICIT', 'HARM_CATEGORY_DANGEROUS_CONTENT')]


class ChapterError(Exception):
    """A step failed in a way the record can name (reason is a short code)."""
    def __init__(self, reason, message=''):
        super().__init__(message or reason)
        self.reason = reason


class Blocked(ChapterError):
    def __init__(self):
        super().__init__('blocked', 'Модель отказалась обрабатывать отрывок')


# ---------- time ----------

def clock(seconds):
    t = int(round(max(0, seconds)))
    h, m, s = t // 3600, t // 60 % 60, t % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def model_seconds(value):
    text = str(value).strip()
    if not re.fullmatch(r'\d{1,3}(:\d{1,2}){1,2}', text):
        raise ValueError(f'время «{text[:20]}» не в формате M:SS')
    total = 0
    for part in text.split(':'):
        total = total * 60 + int(part)
    return total


_TIME = re.compile(r'(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?')


def cue_seconds(value):
    m = _TIME.fullmatch(value.strip())
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int((m.group(4) or '0').ljust(3, '0')) / 1000


# ---------- subtitles ----------

_ARROW = re.compile(r'^\s*([\d:.,]+)\s*-->\s*([\d:.,]+)')
_ADS = re.compile(r'https?://|www\.|\b[\w-]+\.(?:com|org|net|app|ru|tv|io|me|cc)\b|opensubtitles|subtitles?\s+by|synced?\s+(?:and|&)?\s*correct|'
                  r'субтитры\s+(?:подготовил|сделал|от)|перевод(?:ч[иы]к)?\s*:|tryray', re.I)


def clean_text(text):
    text = re.sub(r'\{[^}]*\}', '', text)          # ASS overrides
    text = re.sub(r'<[^>]+>', '', text)            # VTT/SRT tags
    text = text.replace('\\N', ' ').replace('\\n', ' ').replace('\\h', ' ')
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def parse_subtitles(text):
    """WebVTT, SRT or ASS → [(start, end, text)] sorted, ads and empty lines removed."""
    raw = str(text or '').lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    if re.search(r'^\[Events\]', raw, re.M | re.I):
        fields = None
        for line in raw.split('\n'):
            if line.lower().startswith('format:') and fields is None and 'start' in line.lower():
                fields = [f.strip().lower() for f in line.split(':', 1)[1].split(',')]
            elif line.lower().startswith('dialogue:') and fields:
                parts = line.split(':', 1)[1].split(',', len(fields) - 1)
                row = dict(zip(fields, parts))
                start, end = cue_seconds(row.get('start', '')), cue_seconds(row.get('end', ''))
                if start is not None and end is not None:
                    cues.append((start, end, clean_text(row.get('text', ''))))
    else:
        lines = raw.split('\n')
        i = 0
        while i < len(lines):
            m = _ARROW.match(lines[i])
            if not m:
                i += 1
                continue
            start, end = cue_seconds(m.group(1)), cue_seconds(m.group(2))
            body = []
            i += 1
            while i < len(lines) and lines[i].strip():
                body.append(lines[i])
                i += 1
            if start is not None and end is not None:
                cues.append((start, end, clean_text(' '.join(body))))
    out, seen = [], set()
    for start, end, body in sorted(cues):
        if not body or _ADS.search(body) or not re.search(r'\w', body):
            continue
        key = (round(start, 1), body)
        if key in seen:
            continue
        seen.add(key)
        out.append((start, max(end, start), body))
    return out


def check_subtitles(cues, duration=None):
    """Reason the file cannot be used for this video, or None."""
    if len(cues) < 25 or sum(len(c[2]) for c in cues) < 600:
        return 'мало реплик — это не полные субтитры'
    span = cues[-1][1] - cues[0][0]
    if duration:
        if cues[-1][1] > duration + 120:
            return 'субтитры длиннее видео — другая версия'
        if span < duration * 0.45:
            return 'субтитры покрывают меньше половины видео'
    return None


def transcript(cues, start=0, end=None):
    return '\n'.join(f'[{clock(s)}] {t}' for s, _, t in cues if s >= start and (end is None or s < end))


def windows(cues, duration, size=WINDOW):
    """~25-minute pieces cut at the longest pause within three minutes of each mark."""
    if duration <= SINGLE_LIMIT:
        return [(0, duration)]
    cuts, target = [0], size
    starts = [c[0] for c in cues]
    while target < duration - 10 * 60:
        gaps = [(round(starts[i + 1] - cues[i][1]), -abs(starts[i + 1] - target), starts[i + 1])
                for i in range(len(cues) - 1) if abs(starts[i + 1] - target) <= 180]
        cut = int(max(gaps)[2]) if gaps else int(target)
        if cut <= cuts[-1]:
            cut = int(target)
        cuts.append(cut)
        target = cut + size
    cuts.append(duration)
    return list(zip(cuts, cuts[1:]))


# ---------- model ----------

def user_text(meta, cues, start, end, duration, whole):
    lines = [f'Тайтл: {meta.get("title") or "без названия"}']
    if meta.get('kind') or meta.get('year'):
        lines.append('Тип: ' + ', '.join(str(v) for v in (meta.get('kind'), meta.get('year')) if v))
    if meta.get('season') or meta.get('episode'):
        lines.append('Серия: ' + ', '.join(p for p in (
            f'сезон {meta["season"]}' if meta.get('season') else '', f'серия {meta["episode"]}' if meta.get('episode') else '',
            f'«{meta["episodeTitle"]}»' if meta.get('episodeTitle') else '') if p))
    if meta.get('description'):
        lines.append('Описание: ' + meta['description'][:900])
    lines.append(f'Длительность видео: {clock(duration)}')
    target = scene_target(end - start)
    lines.append(f'Нужно около {target} глав (от {max(1, target - 2)} до {target + 2}): примерно одна на 4–5 минут. '
                 'Короткие соседние эпизоды одной линии объединяй в одну сцену.')
    if not whole:
        lines.append(f'Это фрагмент видео с {clock(start)} до {clock(end)}. Размечай только его: первая глава начинается в {clock(start)}, '
                     f'последняя заканчивается в {clock(end)}. Время пиши от начала всего видео, как в субтитрах.')
    lines += ['', 'Субтитры (время начала реплики и текст):', transcript(cues, start, end)]
    return '\n'.join(lines)


def request_body(text, history=()):
    return {'systemInstruction': {'parts': [{'text': SYSTEM}]},
            'contents': [*history, {'role': 'user', 'parts': [{'text': text}]}],
            'generationConfig': {'maxOutputTokens': 8192, 'responseMimeType': 'application/json', 'responseJsonSchema': SCHEMA,
                                 'thinkingConfig': {'thinkingLevel': 'low'}},
            'safetySettings': SAFETY}


def answer_text(data):
    if (data.get('promptFeedback') or {}).get('blockReason'):
        raise Blocked()
    cand = (data.get('candidates') or [{}])[0]
    if cand.get('finishReason') in {'SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII', 'RECITATION'}:
        raise Blocked()
    return ''.join(p.get('text', '') for p in (cand.get('content') or {}).get('parts', []) if not p.get('thought'))


def read_answer(text, lo, hi):
    data = json.loads(text)
    rows = []
    for c in data['chapters']:
        start, title = model_seconds(c['start']), re.sub(r'\s+', ' ', str(c['title'])).strip().strip('«»"\'.').strip()
        if not title:
            raise ValueError('у главы нет названия')
        rows.append([start, title[:90]])
    if not rows:
        raise ValueError('список глав пуст')
    outside = [clock(s) for s, _ in rows if not lo - 5 <= s <= hi + 5]
    if outside:
        raise ValueError(f'начало глав {", ".join(outside[:3])} вне отрезка {clock(lo)}–{clock(hi)}')
    return rows


async def ask(call, model, text, lo, hi, usage):
    """One request and, when the answer does not check out, one repair turn in the same conversation."""
    body = request_body(text)
    data = await call(model, body)
    usage.append(data.get('usageMetadata') or {})
    raw = answer_text(data)
    try:
        return read_answer(raw, lo, hi)
    except (ValueError, KeyError, TypeError) as error:
        reason = str(error)[:200]
    history = [{'role': 'user', 'parts': [{'text': text}]}, {'role': 'model', 'parts': [{'text': raw}]}]
    data = await call(model, request_body(f'Предыдущий ответ не подошёл: {reason}. Верни только JSON по схеме для субтитров выше.', history))
    usage.append(data.get('usageMetadata') or {})
    try:
        return read_answer(answer_text(data), lo, hi)
    except (ValueError, KeyError, TypeError) as error:
        raise ChapterError('model-error', f'Ответ модели не прошёл проверку: {error}') from None


async def piece(call, meta, cues, lo, hi, duration, whole, usage, depth=0):
    """Chapters of one window. A refused window is split in two (never a different model for the same text)."""
    text = user_text(meta, cues, lo, hi, duration, whole)
    try:
        try:
            return await ask(call, PRIMARY, text, lo, hi, usage)
        except Blocked:
            raise
        except ChapterError:
            raise
        except Exception as error:  # quota or overload on every key: the fallback Lite model, same prompt
            if getattr(error, 'status', 0) in (400, 403, 404):
                raise
            return await ask(call, FALLBACK, text, lo, hi, usage)
    except Blocked:
        inside = [c for c in cues if lo <= c[0] < hi]
        if depth >= 2 or len(inside) < 20:
            return [[lo, 'Сцена без описания']]
        middle = int(inside[len(inside) // 2][0])
        left = await piece(call, meta, cues, lo, middle, duration, False, usage, depth + 1)
        right = await piece(call, meta, cues, middle, hi, duration, False, usage, depth + 1)
        return left + right


def scene_target(length):
    return max(2, round(length / SCENE))


def normalize(rows, duration):
    rows = sorted((max(0, int(s)), t) for s, t in rows if s < duration - 5)
    gap = max(MIN_GAP, min(90, duration / 45))
    kept = []
    for start, title in rows:
        if kept and start - kept[-1][0] < gap:
            continue
        kept.append([start, title])
    if not kept:
        return [[0, 'Видео целиком']]
    kept[0][0] = 0
    # Too dense for a seek bar: the shortest scene joins the one before it
    # (the earlier title names the merged span) until the count fits.
    limit = max(4, math.ceil(duration / SCENE * 1.3))
    while len(kept) > limit:
        spans = [(kept[i + 1][0] if i + 1 < len(kept) else duration) - kept[i][0] for i in range(len(kept))]
        shortest = min(range(1, len(kept)), key=lambda i: spans[i] + spans[i - 1] * .25)
        del kept[shortest]
    return kept


async def generate(call, meta, cues, duration):
    usage = []
    parts = windows(cues, duration)
    results = await asyncio.gather(*(piece(call, meta, cues, lo, hi, duration, len(parts) == 1, usage) for lo, hi in parts))
    chapters = normalize([row for rows in results for row in rows], duration)
    tokens = sum(int(u.get('promptTokenCount') or 0) for u in usage)
    return chapters, {'requests': len(usage), 'inputTokens': tokens, 'windows': len(parts)}


# ---------- formats ----------

def full_rows(record, duration=None):
    """[(start, end, title)] with ends filled in; duration overrides the stored one (real video length)."""
    total = duration or record['d']
    rows = [r for r in record['c'] if r[0] < total]
    return [(s, (rows[i + 1][0] if i + 1 < len(rows) else total), t) for i, (s, t) in enumerate(rows)]


def vtt_time(seconds):
    ms = int(round(seconds * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}'


def to_webvtt(record, duration=None):
    blocks = ['WEBVTT', '']
    for i, (s, e, t) in enumerate(full_rows(record, duration), 1):
        blocks += [str(i), f'{vtt_time(s)} --> {vtt_time(e)}', t.replace('-->', '→'), '']
    return '\n'.join(blocks)


def _uid(key, index):
    value = int.from_bytes(hashlib.sha256(f'{key}:{index}'.encode()).digest()[:8], 'big') >> 1
    return value or 1


def to_matroska(record, key, duration=None):
    """Matroska chapters XML (mkvmerge --chapters, mkvpropedit --chapters)."""
    def stamp(seconds):
        ns = int(round(seconds * 1000)) * 1_000_000
        return f'{ns // 3_600_000_000_000:02d}:{ns // 60_000_000_000 % 60:02d}:{ns // 1_000_000_000 % 60:02d}.{ns % 1_000_000_000:09d}'
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<!DOCTYPE Chapters SYSTEM "matroskachapters.dtd">', '<Chapters>', '  <EditionEntry>',
           '    <EditionFlagDefault>1</EditionFlagDefault>', f'    <EditionUID>{_uid(key, "edition")}</EditionUID>']
    for i, (s, e, t) in enumerate(full_rows(record, duration)):
        out += ['    <ChapterAtom>', f'      <ChapterUID>{_uid(key, i)}</ChapterUID>',
                f'      <ChapterTimeStart>{stamp(s)}</ChapterTimeStart>', f'      <ChapterTimeEnd>{stamp(e)}</ChapterTimeEnd>',
                '      <ChapterFlagEnabled>1</ChapterFlagEnabled>', '      <ChapterDisplay>',
                f'        <ChapterString>{xml_escape(t)}</ChapterString>', '        <ChapterLanguage>rus</ChapterLanguage>',
                '        <ChapLanguageIETF>ru</ChapLanguageIETF>', '      </ChapterDisplay>', '    </ChapterAtom>']
    return '\n'.join(out + ['  </EditionEntry>', '</Chapters>', ''])


def to_ffmetadata(record, duration=None):
    def esc(value):
        return re.sub(r'([=;#\\\n])', r'\\\1', value)
    out = [';FFMETADATA1']
    for s, e, t in full_rows(record, duration):
        out += ['[CHAPTER]', 'TIMEBASE=1/1000', f'START={int(round(s * 1000))}', f'END={int(round(e * 1000))}', f'title={esc(t)}']
    return '\n'.join(out) + '\n'


# ---------- subtitle sources ----------

def _js_value(text, key, opener):
    m = re.search(r'\b"?' + key + r'"?\s*:\s*' + re.escape(opener), text)
    if not m:
        return None
    closer = ']' if opener == '[' else '}'
    start, depth, quote_open, escaped = m.end() - 1, 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if quote_open:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                quote_open = False
            continue
        if c == '"':
            quote_open = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


def collaps_tracks(text, season=0, episode=0):
    """Subtitle files a Collaps embed lists for this episode, best first: full Russian, full English, the rest."""
    seasons = _js_value(text, 'seasons', '[')
    found = []
    if isinstance(seasons, list) and seasons:
        for row in seasons:
            if not isinstance(row, dict) or season and str(row.get('season')) != str(season):
                continue
            for item in row.get('episodes') or []:
                if isinstance(item, dict) and (not episode or str(item.get('episode')) == str(episode)):
                    found += item.get('cc') or []
    else:
        found = _js_value(text, 'cc', '[') or []
    tracks = [t for t in found if isinstance(t, dict) and str(t.get('url', '')).startswith('https://')]

    def rank(track):
        name = str(track.get('name') or '').casefold()
        forced = bool(re.search(r'форс|forced|надпис|sign', name))
        russian = bool(re.search(r'рус|rus', name))
        english = bool(re.search(r'eng|англ', name))
        return (forced, 0 if russian else 1 if english else 2, 'sdh' in name)
    return sorted(tracks, key=rank)


OS_API = 'https://rest.opensubtitles.org/search/'
OS_HEADERS = {'User-Agent': 'TemporaryUserAgent', 'X-User-Agent': 'TemporaryUserAgent'}


def _norm(value):
    return re.sub(r'[^0-9a-zа-яё]+', ' ', str(value or '').casefold()).strip()


def opensubtitles_queries(meta):
    paths = []
    tail = (f'/season-{meta["season"]}' if meta.get('season') else '')
    episode = f'episode-{meta["episode"]}/' if meta.get('episode') and meta.get('season') else ''
    if meta.get('imdb'):
        paths.append(f'{episode}imdbid-{meta["imdb"][2:]}{tail}')
    names = [n for n in meta.get('names') or [] if re.search('[A-Za-z]', n)][:3]
    for name in names:
        paths.append(f'{episode}query-{quote(name.casefold()[:120])}{tail}')
    return paths


def opensubtitles_pick(rows, meta):
    """Candidates that belong to this title and episode, best first."""
    wanted = {_norm(n) for n in meta.get('names') or [] if _norm(n)}
    year = int(meta.get('year') or 0)
    picked = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get('SubBad') == '1' or row.get('SubFormat') not in {'srt', 'ass', 'ssa', 'vtt', 'sub'}:
            continue
        if row.get('SubFormat') == 'sub':
            continue
        if meta.get('season'):
            if str(row.get('SeriesSeason')) != str(meta['season']) or str(row.get('SeriesEpisode')) != str(meta.get('episode')):
                continue
        elif row.get('MovieKind') not in (None, '', 'movie'):
            continue
        if not meta.get('imdb') or row.get('MatchedBy') != 'imdbid':
            name = _norm(re.sub(r'^"([^"]+)".*', r'\1', str(row.get('MovieName') or '')))
            if not any(w and (w == name or w in name or name in w) for w in wanted):
                continue
            if year and row.get('MovieYear') and not meta.get('season') and abs(int(row['MovieYear'] or 0) - year) > 1:
                continue
        language = row.get('SubLanguageID')
        order = 0 if language == 'rus' else 1 if language == 'eng' else 2
        picked.append((order, row.get('SubHearingImpaired') == '1', -int(row.get('SubDownloadsCnt') or 0), row))
    picked.sort(key=lambda r: r[:3])
    return [r[3] for r in picked]


def decode_subtitle(raw, encoding=''):
    for name in [encoding, 'utf-8-sig', 'cp1251', 'latin-1']:
        if not name:
            continue
        try:
            return raw.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('utf-8', 'replace')


class Sources:
    """Subtitle lookups. Network calls run in threads (PublicHttp) or httpx for the fixed OpenSubtitles hosts."""
    def __init__(self, http_factory=None, client_factory=None):
        self.http_factory = http_factory
        self.client_factory = client_factory

    def _http(self):
        if self.http_factory:
            return self.http_factory()
        from source_parser import PublicHttp
        return PublicHttp(timeout=(6, 20))

    async def collaps(self, urls, meta):
        from ua_players import COLLAPS_HOSTS
        for url in urls[:4]:
            if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in COLLAPS_HOSTS:
                continue
            http = self._http()
            try:
                page, _, _ = await asyncio.to_thread(http.document, url)
                for track in collaps_tracks(page, meta.get('season') or 0, meta.get('episode') or 0)[:3]:
                    try:
                        text, _, _ = await asyncio.to_thread(http.document, track['url'])
                    except Exception:  # noqa: BLE001 - one dead file must not stop the others
                        continue
                    yield text, 'collaps', 'Collaps · ' + str(track.get('name') or 'субтитры')[:80]
            except Exception:  # noqa: BLE001 - embed gone or changed
                continue
            finally:
                getattr(http, 'close', lambda: None)()

    async def opensubtitles(self, meta):
        import httpx
        factory = self.client_factory or (lambda: httpx.AsyncClient(timeout=20, headers=OS_HEADERS, follow_redirects=True))
        async with factory() as client:
            seen = set()
            for path in opensubtitles_queries(meta):
                try:
                    response = await client.get(OS_API + path)
                except httpx.HTTPError:
                    continue
                if response.status_code == 429:
                    return
                if response.status_code != 200:
                    continue
                try:
                    rows = opensubtitles_pick(response.json(), meta)
                except ValueError:
                    continue
                for row in rows[:3]:
                    link = str(row.get('SubDownloadLink') or '')
                    if link in seen or urlsplit(link).hostname != 'dl.opensubtitles.org':
                        continue
                    seen.add(link)
                    try:
                        file = await client.get(link)
                        if file.status_code != 200 or len(file.content) > 4 * 1024 * 1024:
                            continue
                        raw = gzip.decompress(file.content) if file.content[:2] == b'\x1f\x8b' else file.content
                    except (httpx.HTTPError, OSError, EOFError):
                        continue
                    yield decode_subtitle(raw[:6 * 1024 * 1024], row.get('SubEncoding') or ''), 'opensubtitles', \
                        'OpenSubtitles · ' + str(row.get('LanguageName') or row.get('SubLanguageID') or '')[:40]
                if rows:
                    return


# ---------- storage and service ----------

def record_key(work, season, episode):
    return hashlib.sha256(f'{work}|{int(season or 0)}|{int(episode or 0)}'.encode()).hexdigest()[:32]


class Store:
    def __init__(self, directory):
        self.root = Path(directory) / 'video-chapters'

    def path(self, key):
        return self.root / key[:2] / (key + '.json')

    def read(self, key):
        try:
            record = json.loads(self.path(key).read_text('utf-8'))
        except (OSError, ValueError):
            return None
        if record.get('v', 1) < VERSION and not record.get('none') and record.get('c'):
            # Version 1 had no density limit: thin the stored chapters once, without a model call.
            record = {**record, 'v': VERSION, 'c': normalize(record['c'], record['d'])}
            try:
                self.write(key, record)
            except OSError:
                pass
        return record

    def write(self, key, value):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp' + secrets.token_hex(4))
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), 'utf-8')
        os.replace(temporary, path)


def public(key, record, job=None):
    if job:
        # A redo (player subtitles) keeps showing the markup it replaces.
        if record and not record.get('none'):
            return {**public(key, record), 'state': 'working', 'step': job['step']}
        return {'key': key, 'state': 'working', 'step': job['step']}
    if not record:
        return {'key': key, 'state': 'missing'}
    if record.get('none'):
        return {'key': key, 'state': 'none', 'reason': record.get('message') or 'Нет подходящих субтитров'}
    return {'key': key, 'state': 'ready', 'duration': record['d'], 'source': record.get('s', ''), 'rank': record.get('q', 1),
            'chapters': [{'start': s, 'title': t} for s, t in record['c']]}


class VideoChapters:
    def __init__(self, directory, call, sources=None, clock=time.time, parallel=3):
        self.store = Store(directory)
        self.call = call
        self.sources = sources or Sources()
        self.clock = clock
        self.jobs = {}
        self.gate = asyncio.Semaphore(parallel)

    def state(self, key):
        return public(key, self.store.read(key), self.jobs.get(key))

    def prepare(self, meta):
        key = record_key(meta['work'], meta.get('season'), meta.get('episode'))
        record = self.store.read(key)
        given = meta.get('subtitle')
        if key in self.jobs:
            return public(key, record, self.jobs[key])
        if record and not record.get('none'):
            if not given or RANK.get(given.get('origin'), 0) <= record.get('q', 0):
                return public(key, record)
        elif record and record.get('none') and not given and self.clock() < record.get('retry', 0):
            return public(key, record)
        if len(self.jobs) >= 40:
            return {'key': key, 'state': 'busy'}
        job = {'step': 'В очереди', 'started': self.clock()}
        self.jobs[key] = job
        job['task'] = asyncio.get_running_loop().create_task(self.run(key, meta, job, record))
        return public(key, record, job)

    async def candidates(self, meta):
        given = meta.get('subtitle')
        if given and given.get('text'):
            yield given['text'], given.get('origin') or 'player', str(given.get('label') or 'Субтитры плеера')[:120]
        if meta.get('collaps'):
            async for value in self.sources.collaps(meta['collaps'], meta):
                yield value
        async for value in self.sources.opensubtitles(meta):
            yield value

    async def run(self, key, meta, job, previous):
        started = self.clock()
        try:
            async with self.gate:
                job['step'] = 'Ищем субтитры'
                chosen, problems = None, []
                async for text, origin, label in self.candidates(meta):
                    cues = parse_subtitles(text)
                    problem = check_subtitles(cues, meta.get('duration'))
                    if problem:
                        problems.append(f'{label}: {problem}')
                        continue
                    chosen = (cues, origin, label)
                    break
                if not chosen:
                    reason = 'invalid-subtitles' if problems else 'no-subtitles'
                    if not previous or previous.get('none'):
                        self.store.write(key, {'v': VERSION, 'none': reason, 'at': int(self.clock()), 'retry': int(self.clock() + RETRY_NONE[reason]),
                                               'message': 'Субтитры не подошли' if problems else 'Субтитры не найдены'})
                    return
                cues, origin, label = chosen
                duration = int(meta.get('duration') or cues[-1][1] + 15)
                job['step'] = 'Размечаем сцены'
                chapters, stats = await generate(self.call, meta, cues, duration)
                self.store.write(key, {'v': VERSION, 'd': duration, 'c': chapters, 's': label, 'q': RANK.get(origin, 1),
                                       'm': PRIMARY, 'at': int(self.clock()), 'ms': int((self.clock() - started) * 1000), **stats})
        except Exception as error:  # noqa: BLE001 - the record names the failure, the viewer keeps watching
            if not previous or previous.get('none'):
                self.store.write(key, {'v': VERSION, 'none': 'model-error', 'at': int(self.clock()), 'retry': int(self.clock() + RETRY_NONE['model-error']),
                                       'message': 'Не удалось разметить главы' + (f': {error}' if isinstance(error, ChapterError) else '')})
        finally:
            self.jobs.pop(key, None)

    async def close(self):
        for job in list(self.jobs.values()):
            job['task'].cancel()


def install(app, viewer, directory):
    from fastapi import Depends, HTTPException
    from fastapi.responses import Response
    from pydantic import BaseModel, ConfigDict, Field
    from typing import Literal
    import google_pool

    class Subtitle(BaseModel):
        model_config = ConfigDict(extra='forbid')
        text: str = Field(min_length=20, max_length=3_000_000)
        label: str = Field(default='', max_length=160)
        origin: Literal['player', 'local'] = 'player'

    class Prepare(BaseModel):
        model_config = ConfigDict(extra='forbid')
        work: str = Field(min_length=1, max_length=120, pattern=r'^[\w:.\-]+$')
        season: int = Field(default=0, ge=0, le=500)
        episode: int = Field(default=0, ge=0, le=10000)
        title: str = Field(default='', max_length=300)
        names: list[str] = Field(default_factory=list, max_length=12)
        kind: str = Field(default='', max_length=60)
        year: int | None = Field(default=None, ge=1880, le=2100)
        description: str = Field(default='', max_length=1500)
        episodeTitle: str = Field(default='', max_length=300)
        duration: float | None = Field(default=None, ge=60, le=6 * 3600)
        imdb: str | None = Field(default=None, pattern=r'^tt\d{5,10}$')
        collaps: list[str] = Field(default_factory=list, max_length=6)
        subtitle: Subtitle | None = None

    service = VideoChapters(directory, google_pool.server_generate)
    app.state.video_chapters = service

    @app.post('/video-chapters/prepare')
    async def prepare(body: Prepare, subject=Depends(viewer)):
        meta = body.model_dump()
        meta['names'] = [n.strip()[:200] for n in meta['names'] if n and n.strip()]
        meta['subtitle'] = body.subtitle.model_dump() if body.subtitle else None
        if str(subject).startswith('guest:'):
            return service.state(record_key(meta['work'], meta['season'], meta['episode']))
        return service.prepare(meta)

    @app.get('/video-chapters/{key}')
    async def read(key: str, format: Literal['json', 'vtt', 'mkv', 'ffmetadata'] = 'json', duration: float | None = None,
                   subject=Depends(viewer)):
        if not re.fullmatch(r'[0-9a-f]{32}', key):
            raise HTTPException(404, 'Главы не найдены.')
        if format == 'json':
            return service.state(key)
        record = service.store.read(key)
        if not record or record.get('none'):
            raise HTTPException(404, 'Главы ещё не готовы.')
        length = duration if duration and 60 <= duration <= 6 * 3600 else None
        if format == 'vtt':
            return Response(to_webvtt(record, length), media_type='text/vtt; charset=utf-8')
        if format == 'mkv':
            return Response(to_matroska(record, key, length), media_type='application/xml; charset=utf-8')
        return Response(to_ffmetadata(record, length), media_type='text/plain; charset=utf-8')

    return service
