"""AstraManga and NineGrid public API adapters."""

import re
from urllib.parse import parse_qs, urlsplit

from manga_direct_catalogues import MANGA, SLUG
from manga_direct_payloads import JsonSeries, items, segment, strings
from manga_madara import image_url
from manga_series_port import NUMBER, number
from manga_source_tags import labels
from manga_webcomics import param, query_url
from source_parser import SourceError


ASTRA = 'api.astramanga.org'
NINEGRID = '9grid.cc'
NINEGRID_API = '/api/external/v1'
KEY = r'[1-9]\d{0,15}'
TRANSLATION = r'[A-Za-z0-9_-]{1,110}'
NINE_GENRES = ('Adult', 'Crime', 'Espionage', 'Fantasy', 'Historical', 'Horror', 'Humor', 'Manga', 'Martial Arts',
               'Math & Science', 'Military', 'Mystery', 'Mythology', 'Political', 'Post-Apocalyptic', 'Psychological',
               'Pulp', 'Romance', 'School Life', 'Sci-Fi', 'Slice of Life', 'Spy', 'Superhero', 'Supernatural',
               'Thriller', 'War', 'Western')


def public_api(host, path, query):
    if host not in {ASTRA, NINEGRID}:
        return False
    args = parse_qs(query)
    if not all(len(v) == 1 and 1 <= len(v[0]) <= 160 for v in args.values()):
        return False
    if host == ASTRA:
        if path == '/api/v1/search':
            return ({'sort', 'page', 'page_size'} <= set(args) <= {'sort', 'page', 'page_size', 'query', 'genres', 'tags'}
                    and args['page_size'] == ['30'] and args['sort'] in (['-popularity'], ['-updated_at'])
                    and bool(re.fullmatch(KEY, args['page'][0])))
        if re.fullmatch(rf'/api/v1/branches/{KEY}/chapters', path):
            return set(args) == {'page', 'page_size'} and args['page_size'] == ['5000'] and bool(re.fullmatch(KEY, args['page'][0]))
        return not query and bool(re.fullmatch(rf'/api/v1/(?:titles/{SLUG}|titles/{KEY}/branches|chapters/{KEY}/pages)', path))
    if path == NINEGRID_API + '/series':
        return ({'sort', 'size', 'page'} <= set(args) <= {'sort', 'size', 'page', 'q', 'genre'}
                and args['sort'] in (['popular'], ['latest']) and args['size'] == ['20']
                and bool(re.fullmatch(r'\d{1,5}', args['page'][0])))
    return not query and bool(re.fullmatch(
        rf'{NINEGRID_API}/(?:series/{KEY}(?:/issues|/thumbnail)?|translations/{TRANSLATION}/pages)', path))


class AstraManga(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, MANGA, rf'/manga/{SLUG}/read/({NUMBER})/?', interval=.45)

    def api(self, http, path, **args):
        url = f'https://{ASTRA}/api/v1{path}'
        reply = self.json(http, query_url(url, **args) if args else url)
        payload = reply.get('data') if isinstance(reply, dict) else None
        if not isinstance(payload, dict):
            raise SourceError('AstraManga изменил формат ответа.')
        return payload

    def record_data(self, data):
        slug = segment(data.get('slug'))
        title = data.get('name')
        if not slug or not isinstance(title, str) or not title.strip():
            raise SourceError('AstraManga не предоставил карточку тайтла.')
        cover = data.get('cover_versions') or {}
        path = data.get('cover_image') or cover.get('mid') or cover.get('high')
        cover = image_url(path.lstrip('/') if isinstance(path, str) else '', self.ROOT + '/media/')
        row = self.record(self.ROOT + '/manga/' + slug, title, cover, description=data.get('description') or '',
                          aliases=[data.get('secondary_name'), *strings(data.get('alternative_names'))],
                          genres=labels(data.get('genres')), tags=labels(data.get('tags')), authors=labels(data.get('publishers')),
                          status=str(data.get('status') or '').casefold())
        if data.get('type'):
            row['format'] = str(data['type']).casefold()
        if type(data.get('year')) is int:
            row['year'] = data['year']
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        options = {'sort': '-updated_at' if sort == 'updated' else '-popularity', 'page': page, 'page_size': 30}
        if query:
            options['query'] = query
        if tag:
            options['tags'] = tag[:120]
        payload = self.api(http, '/search', **options)
        return [self.record_data(row) for row in items(payload, 'titles') if isinstance(row, dict)], (
            page < (number(payload.get('total_pages')) or page))

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(SLUG, value):
            return self.ROOT + '/manga/' + value
        return super().saved_title_url(value)

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)

    def chapter_identity(self, url):
        return super().chapter_identity(url), param(url, 'chapterId')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        match = re.fullmatch(rf'/{SLUG}/({NUMBER})/({KEY})/?', urlsplit(target).path)
        return query_url(f'{self.ROOT}/manga/{match[1]}/read/{match[2]}', chapterId=match[3]) if match else target

    def source_details(self, http, url):
        slug = self.title_key(url)
        if not slug:
            raise SourceError('Некорректная ссылка на тайтл AstraManga.')
        data = self.api(http, '/titles/' + slug)
        if segment(data.get('slug')) != slug or not re.fullmatch(KEY, key := str(data.get('id', ''))):
            raise SourceError('AstraManga вернул другой тайтл.')
        return self.record_data(data), key, slug

    def details(self, http, url):
        return self.source_details(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        row, key, slug = self.source_details(http, url)
        branches = items(self.api(http, '/titles/' + key + '/branches'), 'branches')
        chapters = {}
        for branch in branches:
            if not isinstance(branch, dict) or not re.fullmatch(KEY, branch_id := str(branch.get('id', ''))):
                continue
            total = number(branch.get('count_chapters')) or 1
            pages = min(50, max(1, int(total + 4999) // 5000))
            for page in range(1, pages + 1):
                data = self.api(http, f'/branches/{branch_id}/chapters', page=page, page_size=5000)
                for item in items(data, 'items'):
                    if not isinstance(item, dict) or not re.fullmatch(KEY, chapter := str(item.get('id', ''))):
                        continue
                    n = number(item.get('number'))
                    label = f'Глава {n or 0:g}'
                    if item.get('name') and item['name'] != label:
                        label += ' — ' + str(item['name'])
                    target = query_url(f'{self.ROOT}/manga/{slug}/read/{n or 0:g}', chapterId=chapter)
                    vol = item.get('volume_number')
                    chapters[target] = self.chapter(target, label, n, str(item.get('published_at') or '')[:10],
                                                    season=vol if type(vol) is int and vol > 0 else 1,
                                                    translator=str(branch.get('name') or ''))
        return row, self.order(chapters)

    def pages(self, http, url):
        key = param(url, 'chapterId')
        if not re.fullmatch(KEY, key):
            raise SourceError('Обнови оглавление AstraManga.')
        pages = items(self.api(http, f'/chapters/{key}/pages'), 'pages')
        return [image_url(row.get('image_url'), self.ROOT) if isinstance(row, dict) else '' for row in pages]


class NineGrid(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/series/({KEY})/?', rf'/series/({KEY})/translations/({TRANSLATION})/?', interval=.35)
        self.api = self.ROOT + NINEGRID_API

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(KEY, value):
            return self.ROOT + '/series/' + value
        return super().saved_title_url(value)

    def saved_chapter(self, row, root, title):
        value = row.get('url') or ''
        if isinstance(value, str) and (match := re.fullmatch(rf'/translations/({TRANSLATION})/pages', value)):
            return title.rstrip('/') + '/translations/' + match[1]
        return super().saved_chapter(row, root, title)

    def record_data(self, row):
        key, title = str(row.get('id', '')), row.get('name')
        if not re.fullmatch(KEY, key) or not isinstance(title, str) or not title.strip():
            raise SourceError('NineGrid не предоставил карточку тайтла.')
        data = self.record(self.ROOT + '/series/' + key, title, f'{self.api}/series/{key}/thumbnail',
                           description=row.get('description') or '', genres=strings(row.get('genres')),
                           authors=[row.get('publisherName')], status={'Continuing': 'ongoing', 'Ended': 'completed'}.get(row.get('status'), ''))
        data['format'] = 'comic'
        return data

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page - 1, 'size': 20, 'sort': 'latest' if sort == 'updated' else 'popular'}
        if query:
            args['q'] = query
        if tag:
            args['genre'] = tag[:120]
        data = self.json(http, query_url(self.api + '/series', **args))
        return [self.record_data(row) for row in items(data, 'content') if isinstance(row, dict)], (
            page < (number(data.get('totalPages')) or page))

    def vocabulary(self, http):
        return [{'label': name, 'sourceId': name, 'category': 'genre'} for name in NINE_GENRES]

    def details(self, http, url):
        key = self.title_key(self.saved_title_url(url))
        if not key:
            raise SourceError('Некорректная ссылка на тайтл NineGrid.')
        row = self.json(http, self.api + '/series/' + key)
        if not isinstance(row, dict) or str(row.get('id')) != key:
            raise SourceError('NineGrid вернул другой тайтл.')
        return self.record_data(row)

    def series(self, http, url):
        row = self.details(http, url)
        key = self.title_key(url)
        data = self.json(http, f'{self.api}/series/{key}/issues')
        chapters = {}
        for item in items(data, 'issues'):
            if not isinstance(item, dict):
                continue
            count = str(item.get('number', ''))
            index = number(re.sub(r'^annual\s*', '1000.', count, flags=re.I))
            label = '#' + count + (' — ' + str(item['name']) if item.get('name') else '')
            for translation in items(item, 'translations'):
                if not isinstance(translation, dict) or not re.fullmatch(TRANSLATION, code := str(translation.get('id', ''))):
                    continue
                target = f'{self.ROOT}/series/{key}/translations/{code}'
                teams = ', '.join(strings(translation.get('teamNames')))
                chapters[target] = self.chapter(target, label + (f' [{teams}]' if teams else ''), index,
                                                str(translation.get('createdAt') or '')[:10], translator=teams)
        return row, self.order(chapters)

    def pages(self, http, url):
        _, code = self.CHAPTER_PATH.fullmatch(urlsplit(url).path).groups()
        result = self.json(http, f'{self.api}/translations/{code}/pages')
        rows = items(result, 'pages')
        if any(not isinstance(row, dict) or type(row.get('index')) is not int for row in rows):
            raise SourceError('NineGrid вернул неполный список страниц.')
        return [image_url(row.get('url'), self.ROOT) for row in sorted(rows, key=lambda row: row['index'])]
