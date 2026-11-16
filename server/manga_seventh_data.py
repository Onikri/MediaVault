"""Public Strapi and Qwik catalogue adapters backed by installed source IDs."""

import json
import re
from urllib.parse import parse_qsl, quote, urlsplit

from manga_direct_payloads import JsonSeries, items, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import number
from manga_webcomics import query_url
from source_parser import SourceError

HYAKURO = 'https://hyakuro.net'
PORNHWA = 'https://pornhwa18.com'
STRAPI = '/backend/api/mangas'
ORDINAL = r'\d{1,8}(?:\.\d{1,6})?'
IDENTITY = r'[1-9]\d{0,15}'
SERIES = rf'/manga/({SEGMENT})/?'
READ_HYAKURO = rf'{SERIES.removesuffix("/?")}/read/({ORDINAL})(?:/\d{{1,4}})?/?'
PORN_COMIC = rf'/comic/({SEGMENT})/?'
PORN_CHAPTER = rf'{PORN_COMIC.removesuffix("/?")}/chapter-({ORDINAL})/?'
CATEGORIES = ('Action', 'Adult', 'Adventure', 'Comedy', 'Doujinshi', 'Drama', 'Ecchi', 'Fantasy',
              'Gender Bender', 'Harem', 'Hentai', 'Historical', 'Horror', 'Josei', 'Martial Arts',
              'Mature', 'Mecha', 'Mystery', 'Psychological', 'Romance', 'School Life', 'Sci-fi',
              'Seinen', 'Shoujo', 'Shoujo Ai', 'Shounen', 'Slice of Life', 'Sports',
              'Supernatural', 'Tragedy', 'Webtoon', 'Yaoi', 'Yuri')


def public_api(host, path, query):
    if host != 'hyakuro.net' or path != STRAPI:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(pairs) != len(args) or any(len(v) > 240 for v in args.values()):
        return False
    if 'filters[slug][$eq]' in args:
        return bool(re.fullmatch(SEGMENT, args['filters[slug][$eq]'])) and (
            (set(args) == {'filters[slug][$eq]', 'populate'} and args['populate'] == 'Cover,Chapters')
            or (set(args) == {'filters[slug][$eq]', 'populate[Chapters][populate]'} and args['populate[Chapters][populate]'] == '*'))
    mandatory = {'populate', 'sort', 'pagination[page]'}
    optional = {'filters[Title][$containsi]', 'filters[$and][1][Categories][$containsi]'}
    return (mandatory <= set(args) <= mandatory | optional and args['populate'] == 'Cover,Chapters' and
            args['sort'] in {'Title:asc', 'updatedAt:desc'} and bool(re.fullmatch(r'[1-9]\d{0,3}', args['pagination[page]'])))


class Hyakuro(JsonSeries):
    def __init__(self):
        super().__init__(('4981643024311726529', 'Hyakuro Translations', 'en', HYAKURO, True),
                         SERIES, READ_HYAKURO, interval=.35)

    def chapter_url(self, key, ordinal):
        return f'{HYAKURO}/manga/{key}/read/{ordinal:g}/1'

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return (match[1], number(match[2])) if match else ('', None)

    def title_for(self, url):
        key = self.chapter_key(url)
        return HYAKURO + '/manga/' + key if key else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        parts = urlsplit(target)
        key = parts.path.strip('/')
        match = re.fullmatch(rf'({ORDINAL})#({IDENTITY})', parts.fragment)
        return self.chapter_url(key, number(match[1])) if match and re.fullmatch(SEGMENT, key) else ''

    def item(self, data):
        key = data.get('slug', '')
        title = data.get('Title')
        if not isinstance(key, str) or not re.fullmatch(SEGMENT, key) or not isinstance(title, str) or not title:
            return None
        url = HYAKURO + '/manga/' + key
        cover = (((data.get('Cover') or {}).get('data') or {}).get('attributes') or {}).get('url', '')
        status = {'ongoing': 'ongoing', 'completed': 'completed', 'dropped': 'cancelled'}
        row = self.record(url, title, image_url('/backend' + cover, HYAKURO) if isinstance(cover, str) and cover.startswith('/') else '',
                          description=data.get('Synopsis') or '', authors=[data.get('Author'), data.get('Artist')],
                          genres=strings(data.get('Categories')), status=status.get(str(data.get('Status', '')).casefold(), ''))
        if data.get('Longstrip') is True:
            row['format'] = 'webtoon'
        elif data.get('Oneshot') is True:
            row['format'] = 'oneshot'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        params = {'populate': 'Cover,Chapters', 'pagination[page]': page,
                  'sort': 'updatedAt:desc' if query or tag or sort == 'updated' else 'Title:asc'}
        if query:
            params['filters[Title][$containsi]'] = query
        if tag in CATEGORIES:
            params['filters[$and][1][Categories][$containsi]'] = tag
        data = self.json(http, query_url(HYAKURO + STRAPI, **params))
        count = number((data.get('meta', {}).get('pagination') or {}).get('pageCount')) or page
        result = [row for item in items(data, 'data') if (row := self.item(item.get('attributes') or {}))]
        return result, count > page

    def vocabulary(self, http):
        return [{'key': name, 'label': name, 'kind': 'genre'} for name in CATEGORIES]

    def get_series(self, http, key, pages=False):
        expand = {'populate[Chapters][populate]': '*'} if pages else {'populate': 'Cover,Chapters'}
        payload = self.json(http, query_url(HYAKURO + STRAPI, **{'filters[slug][$eq]': key}, **expand))
        for item in items(payload, 'data'):
            data = item.get('attributes') or {}
            if data.get('slug') == key:
                return data
        raise SourceError('Hyakuro не предоставил указанный тайтл.')

    def series(self, http, url):
        key = self.title_key(url)
        data = self.get_series(http, key)
        row = self.item(data)
        if row is None:
            raise SourceError('Hyakuro не предоставил метаданные тайтла.')
        result = {}
        for item in data.get('Chapters') or []:
            ordinal = number(item.get('Chapter'))
            if ordinal is None:
                continue
            target = self.chapter_url(key, ordinal)
            label = 'Oneshot' if data.get('Oneshot') else f'Chapter {ordinal:g}'
            if item.get('Title'):
                label += ' - ' + item['Title']
            date = str(item.get('TranslatedOn') or data.get('publishedAt') or '')[:10]
            result[target] = self.chapter(target, label, ordinal, date)
        return row, self.order(result)

    def pages(self, http, url):
        key, ordinal = self.chapter_identity(url)
        data = self.get_series(http, key, pages=True)
        chapter = next((item for item in data.get('Chapters') or [] if number(item.get('Chapter')) == ordinal), {})
        pages = ((chapter.get('Pages') or {}).get('data') or [])
        paths = sorted(p['attributes']['url'] for p in pages if isinstance(p.get('attributes', {}).get('url'), str))
        return [img for raw in paths if raw.startswith('/') and not raw.startswith('//')
                and (img := image_url('/backend' + raw, HYAKURO))]


def qwik_load(root):
    data = root.get('_objs') if isinstance(root, dict) else None
    if not isinstance(data, list) or len(data) > 250000:
        raise SourceError('Некорректные данные каталога Qwik.')
    remaining = 600000

    def resolve(ref, trail):
        nonlocal remaining
        remaining -= 1
        if (remaining < 0 or len(trail) > 50 or not isinstance(ref, str)
                or not re.fullmatch(r'[a-z\d]{1,7}', ref, re.I)):
            raise SourceError('Некорректная ссылка в данных Qwik.')
        index = int(ref, 36)
        if index >= len(data) or index in trail:
            raise SourceError('Qwik вернул циклическую или отсутствующую ссылку.')
        value = data[index]
        trail = trail | {index}
        if isinstance(value, dict):
            return {k: resolve(v, trail) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v, trail) for v in value]
        if value == '\x01':
            return None
        return value[1:] if isinstance(value, str) and value and ord(value[0]) < 32 else value

    entry = resolve(root.get('_entry'), frozenset())
    loaders = entry.get('loaders') if isinstance(entry, dict) else None
    if isinstance(loaders, dict):
        payload = next((val for val in loaders.values() if val is not None), None)
        if payload is not None:
            return payload
    raise SourceError('Qwik не предоставил данные маршрута.')


class Pornhwa(JsonSeries):
    def __init__(self):
        super().__init__(('4714693291518819083', 'Pornhwa18', 'en', PORNHWA, True),
                         PORN_COMIC, PORN_CHAPTER, interval=.35)

    def fetch(self, http, url, page=1):
        self.origin.wait(getattr(http, 'deadline', None))
        target = url.rstrip('/') + '/q-data.json'
        if page != 1:
            target = query_url(target, page=page)
        raw, final, _ = http.document(target)
        if final != target:
            raise SourceError('Pornhwa18 перенаправил данные каталога.')
        return qwik_load(json.loads(raw))

    def title_for(self, url):
        key = self.chapter_key(url)
        return PORNHWA + '/comic/' + key + '/' if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return PORNHWA + '/comic/' + key + '/' if re.fullmatch(SEGMENT, key) and not re.fullmatch(IDENTITY, key) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        ordinal = row.get('number')
        if ordinal is not None and number(ordinal) is not None and self.is_title(title):
            return title.rstrip('/') + f'/chapter-{number(ordinal):g}/'
        return ''

    def summary(self, item):
        key = item.get('slug')
        title = item.get('title')
        if not isinstance(key, str) or not re.fullmatch(SEGMENT, key) or not isinstance(title, str) or not title:
            return None
        url = PORNHWA + f'/comic/{key}/'
        poster = str(item.get('poster') or '').replace('/188.165.221.196/', '/manhwa18.com/')
        taxonomy = [row['taxonomy'] for row in item.get('taxonomy_relation', []) if isinstance(row.get('taxonomy'), dict)]
        tags = [row.get('name') for row in taxonomy if row.get('type') == 'genre']
        people = [row.get('name') for row in taxonomy if row.get('type') in {'artist', 'author'}]
        status = {'on-going': 'ongoing', 'end': 'completed', 'on-hold': 'hiatus'}.get(item.get('status'), '')
        row = self.record(url, title, image_url(poster, url), aliases=re.split(r'[;|]', str(item.get('alter') or '')),
                          description=item.get('synopsis') or '', genres=tags, authors=people, status=status)
        if item.get('type'):
            row['format'] = str(item['type']).lower()
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        url = PORNHWA + ('/search/' + quote(query, safe='') if query else '/popular' if sort == 'popular' else '/')
        data = self.fetch(http, url, page)
        if not isinstance(data, list):
            raise SourceError('Pornhwa18 изменил формат каталога.')
        start = (page - 1) * 18
        return [row for item in data[start:] if isinstance(item, dict) and (row := self.summary(item))], len(data) >= page * 18

    def series(self, http, url):
        data = self.fetch(http, url)
        row = self.summary(data)
        if not row or self.title_key(row['url']) != self.title_key(url):
            raise SourceError('Pornhwa18 подменил тайтл.')
        result = {}
        for item in data.get('chapters') or []:
            if (n := number(item.get('chapter'))) is None:
                continue
            target = url.rstrip('/') + f'/chapter-{n:g}/'
            result[target] = self.chapter(target, f'Chapter {n:g}', n, str(item.get('created_at') or '')[:10])
        return row, self.order(result)

    def pages(self, http, url):
        payload = self.fetch(http, url)
        mapped = payload.get('data') or {}
        if mapped.get('slug', self.chapter_key(url)) != self.chapter_key(url):
            raise SourceError('Pornhwa18 подменил главу.')
        chapters = mapped.get('chapters') or []
        images = (chapters[0].get('images') or {}) if chapters else {}
        values = sorted((int(key), val) for key, val in images.items() if key.isdigit())
        return [src for _, item in values if isinstance(item, dict) and (src := image_url(item.get('src'), url))]


SOURCES = (Hyakuro(), Pornhwa())
