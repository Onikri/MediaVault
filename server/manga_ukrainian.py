"""Ukrainian manga readers with public JSON APIs: Honey Manga and Zenko.

Endpoints follow the open-source Keiyoushi extensions (Apache-2.0):
src/uk/honeymanga and src/uk/zenko. Only public, free chapters are listed;
monetized Honey chapters are skipped rather than presented as readable.
"""
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from source_parser import SourceError, public_url

HONEY = 'https://honey-manga.com.ua'
HONEY_SEARCH = 'https://search.api.honey-manga.com.ua/v2/manga/pattern'
HONEY_DATA = 'https://data.api.honey-manga.com.ua'
HONEY_IMAGES = 'https://hmvolumestorage.b-cdn.net/public-resources/'
ZENKO = 'https://zenko.online'
ZENKO_API = 'https://api.zenko.online'
ZENKO_IMAGES = 'https://storage.zenko.online/'
ZENKO_SEPARATOR = '@#%&;№%#&**#!@'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
ZENKO_FORMATS = {'MANGA': 'manga', 'MANHVA': 'manhwa', 'MANHWA': 'manhwa', 'MANHUA': 'manhua', 'COMICS': 'manga', 'WEBTOON': 'webtoon'}
FORMATS = {'манґа': 'manga', 'манга': 'manga', 'манхва': 'manhwa', 'маньхва': 'manhua', 'маньхуа': 'manhua', 'вебтун': 'webtoon', 'комікс': 'manga'}


def _json(http, url, *, method='GET', body=None):
    headers = {'Accept': 'application/json'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
        text, _, _ = http.document(url, method='POST', data=json.dumps(body).encode(), headers=headers, action='ukrainian-manga')
    else:
        text, _, _ = http.document(url, headers=headers, action='ukrainian-manga')
    try:
        return json.loads(text)
    except ValueError:
        raise SourceError('Украинская читалка вернула неизвестный формат.') from None


def _names(*values):
    names = []
    for value in values:
        for part in re.split(r'\s+/\s+', str(value or '')):
            part = ' '.join(part.split())[:300]
            if part and part not in names: names.append(part)
    return names


def _number(value):
    from manga_sources import chapter_number
    return chapter_number(value)


# ------------------------------------------------------------------ Honey Manga

def honey_search(query, http):
    data = _json(http, HONEY_SEARCH + '?' + urlencode({'query': query[:160]}))
    results = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not re.fullmatch(UUID, str(item.get('id', ''))): continue
        names = _names(item.get('title'), item.get('alternativeTitle'))
        if not names: continue
        poster = str(item.get('posterId') or '')
        results.append({'provider': 'honey-manga', 'providerName': 'Honey Manga · UA', 'title': names[0], 'aliases': names,
                        'kind': 'manga', 'language': 'uk', 'url': HONEY + '/book/' + item['id'],
                        'format': FORMATS.get(str(item.get('type') or '').casefold(), ''),
                        'cover': HONEY_IMAGES + poster if re.fullmatch(UUID, poster) else ''})
    return results


def honey_inspect(url, http):
    from manga_catalog_adapters import result
    parsed = urlsplit(url)
    route = re.fullmatch(r'/book/(' + UUID + r')/?', parsed.path)
    if parsed.hostname not in {'honey-manga.com.ua', 'www.honey-manga.com.ua'} or not route:
        raise SourceError('Нужна ссылка Honey Manga на тайтл.')
    identity = route[1]
    selected = parse_qs(parsed.query).get('mv_chapter', [''])[0]
    if selected and not re.fullmatch(UUID, selected): raise SourceError('Некорректная ссылка на главу.')
    item = _json(http, HONEY_DATA + '/manga/' + identity)
    if not isinstance(item, dict) or item.get('id') != identity: raise SourceError('Honey Manga вернула другой тайтл.')
    names = _names(item.get('title'), item.get('alternativeTitle'))
    chapters, page = [], 1
    while page <= 20:
        data = _json(http, HONEY_DATA + '/v2/chapter/cursor-list', body={'page': page, 'pageSize': 100, 'sortOrder': 'ASC', 'mangaId': identity})
        rows = data.get('data') if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows: break
        for row in rows:
            cid = str(row.get('chapterResourcesId') or row.get('id') or '')
            if not re.fullmatch(UUID, cid) or row.get('isMonetized'): continue
            number = str(row.get('chapterNum'))
            if row.get('subChapterNum'): number += '.' + str(row['subChapterNum'])
            try: number = _number(number)
            except SourceError: continue
            if selected and cid != selected: continue
            volume = row.get('volume')
            chapters.append({'number': number, 'season': volume if isinstance(volume, int) and volume > 0 else 1,
                             'title': ' '.join(str(row.get('title') or '').split())[:200] or 'Розділ ' + str(number),
                             'language': 'uk', 'translator': '', 'url': HONEY + '/book/' + identity + '?' + urlencode({'mv_chapter': cid})})
        if not data.get('cursorNext'): break
        page += 1
    pages = []
    if selected:
        if not chapters: raise SourceError('Обраний розділ недоступний або платний.')
        frames = _json(http, HONEY_DATA + '/chapter/frames/' + selected)
        ids = frames.get('resourceIds') if isinstance(frames, dict) else None
        if not isinstance(ids, dict): raise SourceError('Honey Manga не надала сторінок розділу.')
        ordered = sorted(((int(k), v) for k, v in ids.items() if str(k).isdigit() and re.fullmatch(UUID, str(v))), key=lambda pair: pair[0])
        pages = [public_url(HONEY_IMAGES + value, resolve_dns=False) for _, value in ordered[:1500]]
    chapters.sort(key=lambda row: (row['season'], row['number']))
    return {**result('honey-manga', 'Honey Manga · UA', names[0] if names else identity, url, 'uk', chapters, pages), 'aliases': names}


# ------------------------------------------------------------------ Zenko

def zenko_titles(query, http, *, novels=False):
    """Zenko hosts comics and Ukrainian web-novel translations (category RANOBE)."""
    data = _json(http, ZENKO_API + '/titles?' + urlencode({'name': query[:160], 'limit': 20}))
    rows = []
    for item in (data.get('data') if isinstance(data, dict) else None) or []:
        if not isinstance(item, dict) or not str(item.get('id', '')).isdigit(): continue
        if (str(item.get('category') or '').upper() == 'RANOBE') != novels: continue
        rows.append(item)
    return rows


def zenko_search(query, http):
    results = []
    for item in zenko_titles(query, http):
        names = _names(item.get('name'), item.get('engName'), item.get('originalName'))
        if not names: continue
        cover = str(item.get('coverImg') or '')
        results.append({'provider': 'zenko', 'providerName': 'Zenko · UA', 'title': names[0], 'aliases': names,
                        'kind': 'manga', 'language': 'uk', 'url': ZENKO + '/titles/' + str(item['id']),
                        'format': ZENKO_FORMATS.get(str(item.get('category') or '').upper(), ''),
                        'cover': ZENKO_IMAGES + cover if re.fullmatch(r'[0-9a-f-]{36}', cover) else ''})
    return results


def zenko_chapter(name):
    parts = str(name or '').split(ZENKO_SEPARATOR)
    if len(parts) >= 2: volume, number, title = parts[0], parts[1], parts[2] if len(parts) > 2 else ''
    else: volume, number, title = '1', '', parts[0]
    return (int(volume) if str(volume).isdigit() and int(volume) > 0 else 1), number, ' '.join(title.split())[:200]


def zenko_inspect(url, http):
    from manga_catalog_adapters import result
    parsed = urlsplit(url)
    route = re.fullmatch(r'/titles/(\d{1,9})/?', parsed.path)
    if parsed.hostname not in {'zenko.online', 'www.zenko.online'} or not route:
        raise SourceError('Нужна ссылка Zenko на тайтл.')
    identity = route[1]
    selected = parse_qs(parsed.query).get('mv_chapter', [''])[0]
    if selected and not selected.isdigit(): raise SourceError('Некорректная ссылка на главу.')
    item = _json(http, ZENKO_API + '/titles/' + identity)
    if not isinstance(item, dict) or str(item.get('id')) != identity: raise SourceError('Zenko повернув інший тайтл.')
    if str(item.get('category') or '').upper() == 'RANOBE': raise SourceError('Это ранобэ: открой его в разделе «Ранобэ».')
    names = _names(item.get('name'), item.get('engName'), item.get('originalName'))
    rows = _json(http, ZENKO_API + '/titles/' + identity + '/chapters')
    chapters = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not str(row.get('id', '')).isdigit() or row.get('isPublished') is False: continue
        volume, number, title = zenko_chapter(row.get('name'))
        try: number = _number(number)
        except SourceError: continue
        cid = str(row['id'])
        if selected and cid != selected: continue
        publisher = (row.get('publisher') or {}).get('name') if isinstance(row.get('publisher'), dict) else ''
        chapters.append({'number': number, 'season': volume, 'title': title or 'Розділ ' + str(number), 'language': 'uk',
                         'translator': ' '.join(str(publisher or '').split())[:120],
                         'url': ZENKO + '/titles/' + identity + '?' + urlencode({'mv_chapter': cid})})
    pages = []
    if selected:
        if not chapters: raise SourceError('Обраний розділ відсутній у Zenko.')
        data = _json(http, ZENKO_API + '/chapters/' + selected)
        frames = sorted((p for p in (data.get('pages') if isinstance(data, dict) else None) or [] if isinstance(p, dict)), key=lambda p: p.get('order', 0))
        pages = [public_url(ZENKO_IMAGES + p['content'], resolve_dns=False) for p in frames[:1500] if re.fullmatch(r'[0-9a-f-]{36}', str(p.get('content', '')))]
    chapters.sort(key=lambda row: (row['season'], row['number']))
    return {**result('zenko', 'Zenko · UA', names[0] if names else identity, url, 'uk', chapters, pages), 'aliases': names}
