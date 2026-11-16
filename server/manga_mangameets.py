"""MangaMeets Japanese creator catalogue and JSON:API episode reader."""

import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries, items, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import number
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://manga-meets.jp'
API = ROOT + '/api'
TITLE = rf'/comics/({SEGMENT})/?'
NUMBER = r'[1-9]\d{0,9}'
EPISODE = rf'/comics/({SEGMENT})/({NUMBER})/?'


def public_api(host, path, query):
    if host != 'manga-meets.jp':
        return False
    if path in {'/api/comic_genres.json', '/api/official_tags.json'}:
        return not query
    if path in {'/api/comics/search.json', '/api/episodes/latest.json'}:
        parts = parse_qsl(query)
        args = dict(parts)
        core = {'page', 'size'}
        extra = {'sort', 'keywords', 'tag', 'genre'} if path.endswith('search.json') else set()
        return (len(args) == len(parts) and core <= set(args) <= core | extra and args['size'] == '20'
                and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page']))
                and all(len(value) <= 160 for value in args.values()))
    return not query and bool(re.fullmatch(rf'/api/comics/{SEGMENT}(?:\.json|/episodes(?:/{NUMBER}/viewer)?\.json)', path))


def linked(data, field):
    return ((data.get('relationships') or {}).get(field) or {}).get('data') or {}


def properties(data):
    return data.get('attributes') or {} if isinstance(data, dict) else {}


class MangaMeets(JsonSeries):
    def __init__(self):
        super().__init__(('2561264003659474410', 'MangaMeets', 'ja', ROOT, False),
                         TITLE, EPISODE, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/comics/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        if self.is_chapter(url):
            return self.title_for(url)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/comics/' + key if re.fullmatch(SEGMENT, key) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        ordinal = number(row.get('number'))
        if self.is_title(title) and ordinal is not None and ordinal.is_integer() and 1 <= ordinal < 10**10:
            return title.rstrip('/') + f'/{int(ordinal)}'
        return ''

    def include(self, payload):
        return {str(item['id']): item for item in payload.get('included') or []
                if isinstance(item, dict) and item.get('id') is not None}

    def summary(self, url, entry, relations):
        raw = properties(entry)
        thumbnail = linked(entry, 'thumbnail_image').get('id')
        genre = linked(entry, 'comic_genre').get('id')
        title = raw.get('title')
        if not isinstance(title, str) or not title:
            raise SourceError('MangaMeets не предоставил карточку.')
        return self.record(url, title, image_url(properties(relations.get(str(thumbnail))).get('url'), url),
                           authors=strings(raw.get('authors')), description=raw.get('outline') or '',
                           genres=[properties(relations.get(str(genre))).get('name')],
                           status='completed' if raw.get('finished') is True else 'ongoing' if 'finished' in raw else '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        search = bool(query or tag or sort != 'updated')
        params = {'page': page, 'size': 20}
        if query:
            params['keywords'] = query
        if search:
            params['sort'] = 'weekly_view_count'
        field, _, value = tag.partition(':')
        if value and field in ('tag', 'genre'):
            params[field] = value[:120]
        path = '/comics/search.json' if search else '/episodes/latest.json'
        obj = self.json(http, query_url(API + path, **params))
        relation_map = self.include(obj)
        data = obj.get('data') or {}
        references = linked(data, 'comics') or linked(data, 'episodes')
        rows = {}
        for reference in references:
            item = relation_map.get(str(reference.get('id')), {})
            relation = linked(item, 'comic')
            entry = relation_map.get(str(relation.get('id')), {}) if relation else item
            slug = str(properties(entry).get('dir_name') or '')
            if not re.fullmatch(SEGMENT, slug):
                continue
            url = ROOT + '/comics/' + slug
            row = self.summary(url, entry, relation_map)
            image = linked(item, 'thumbnail_image').get('id')
            row['cover'] = row.get('cover') or image_url(properties(relation_map.get(str(image))).get('url'), url)
            rows[slug] = row
        return list(rows.values()), (number(properties(data).get('total_page')) or 0) > page

    def vocabulary(self, http):
        rows = []
        for kind, route in [('tag', '/official_tags.json'), ('genre', '/comic_genres.json')]:
            for item in items(self.json(http, API + route), 'data'):
                name = properties(item).get('name')
                if isinstance(name, str) and name:
                    rows.append({'key': kind + ':' + name, 'label': name, 'kind': kind})
        return rows

    def series(self, http, url):
        key = self.title_key(url)
        data = self.json(http, API + '/comics/' + key + '.json')
        entry = data.get('data') or {}
        actual = properties(entry).get('dir_name')
        if actual and actual != key:
            raise SourceError('MangaMeets подменил тайтл.')
        row = self.summary(url, entry, self.include(data))
        chapters = self.json(http, API + '/comics/' + key + '/episodes.json')
        result = {}
        for item in items(chapters, 'data'):
            fields = properties(item)
            cid = str(fields.get('sort_volume') or '')
            if re.fullmatch(NUMBER, cid):
                title = fields.get('title')
                name = 'Chapter ' + str(fields.get('volume') or cid)
                target = ROOT + f'/comics/{key}/{cid}'
                date = str(fields.get('published_at') or '')[:10]
                result[target] = self.chapter(target, name + (' - ' + title if title else ''), int(cid), date)
        return row, self.order(result)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        result = self.json(http, API + f'/comics/{match[1]}/episodes/{match[2]}/viewer.json')
        pages = sorted(items(result, 'episode_pages'), key=lambda item: number(item.get('order_index')) or 0)
        return [src for item in pages if (src := image_url((item.get('image') or {}).get('original_url'), url))]


SOURCES = (MangaMeets(),)
