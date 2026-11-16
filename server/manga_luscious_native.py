"""Luscious public album metadata and pages (Apache-2.0 upstream contract)."""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries, items, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import number
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ROOT = 'https://www.luscious.net'
HOSTS = {'www.luscious.net', 'members.luscious.net'}
CDN = 'https://ah-img.luscious.net/'
API = ROOT + '/graphql/nobatch/'
ID = r'[1-9]\d{0,13}'
PATH = rf'/albums/({SEGMENT})/?'
LANGUAGE = {'en': '1', 'ja': '2', 'es': '3', 'it': '4', 'de': '5', 'fr': '6', 'zh': '8',
            'ko': '9', 'pt-BR': '100', 'th': '101', 'other': '99'}
SORTS = {'rating_all_time', 'date_newest', 'date_oldest', 'search_score'}
ALBUM = 'AlbumGet'
LIST = 'AlbumList'
PAGES = 'AlbumListOwnPictures'
OPERATIONS = {
    LIST: 'query AlbumList($input:AlbumListInput!){album{list(input:$input){info{page has_next_page} items}}}',
    ALBUM: ('query AlbumGet($id:ID!){album{get(id:$id){... on Album{url title description labels created '
            'number_of_pictures language{id title} cover{url} genres{id title} tags{text} audiences{title}} '
            '... on MutationError{errors{code}}}}}'),
    PAGES: ('query AlbumListOwnPictures($input:PictureListInput!){picture{list(input:$input){'
            'info{page has_next_page} items{created title position url_to_original url_to_video thumbnails{url width height}}}}}'),
}


def public_api(host, path, query):
    if host not in HOSTS or path != '/graphql/nobatch/':
        return False
    try:
        pairs = parse_qsl(query, max_num_fields=8)
    except ValueError:
        return False
    args = dict(pairs)
    operation = args.get('operationName')
    if (len(pairs) != 3 or set(args) != {'operationName', 'query', 'variables'}
            or operation not in OPERATIONS or args['query'] != OPERATIONS[operation] or len(args['variables']) > 2048):
        return False
    try:
        variables = json.loads(args['variables'])
        if operation == ALBUM:
            return set(variables) == {'id'} and bool(re.fullmatch(ID, variables['id']))
        if set(variables) != {'input'}:
            return False
        body = variables['input']
        expected = {'display', 'page', 'filters', 'items_per_page'} if operation == PAGES else {'display', 'page', 'filters'}
        if set(body) != expected or body['display'] not in SORTS or type(body['page']) is not int or not 1 <= body['page'] <= 2000:
            return False
        filters = {row['name']: row['value'] for row in body['filters']}
        if len(filters) != len(body['filters']) or any(set(row) != {'name', 'value'} for row in body['filters']):
            return False
        if operation == PAGES:
            return (body['items_per_page'] == 50 and body['page'] <= 20 and set(filters) == {'album_id'}
                    and bool(re.fullmatch(ID, filters['album_id'])))
        return (set(filters) <= {'audience_ids', 'language_ids', 'search_query', 'tagged'} and len(filters) <= 4
                and filters.get('audience_ids') == '+1+10+2+3+5+6+8+9'
                and ('language_ids' not in filters or filters['language_ids'].removeprefix('+') in LANGUAGE.values())
                and all(isinstance(value, str) and 1 <= len(value) <= 160 for value in filters.values()))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return False


def named(rows, field):
    return [entry[field] for entry in rows if isinstance(entry, dict) and isinstance(entry.get(field), str)] if isinstance(rows, list) else []


class Luscious(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, PATH, PATH, hosts=('members.luscious.net',), interval=.4)

    def title_key(self, url):
        slug = super().title_key(url)
        key = slug.rsplit('_', 1)[-1]
        return key if re.fullmatch(ID, key) else ''

    def is_title(self, url):
        return super().is_title(url) and bool(self.title_key(url)) and not (param(url, 'picture') or param(url, 'chunk'))

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_key(url)) and (
            bool(re.fullmatch(ID, param(url, 'picture'))) or param(url, 'chunk') == '1')

    def chapter_identity(self, url):
        return self.title_key(url), param(url, 'picture'), param(url, 'chunk')

    def title_for(self, url):
        return self.ROOT + urlsplit(url).path.rstrip('/') if self.title_key(url) else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        return self.title_for(url) if self.is_title(url) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url) and self.title_key(url) == self.title_key(title):
            return url
        # Older app releases used image URLs as chapter IDs. Locate such IDs in the current public manifest.
        if not self.is_title(title) or not re.fullmatch(ID, str(row.get('number', ''))):
            return ''
        return query_url(title, picture=row['number'])

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def request(self, http, operation, variables, referer=None):
        target = query_url(API, operationName=operation, query=OPERATIONS[operation],
                           variables=json.dumps(variables, ensure_ascii=False, separators=(',', ':')))
        data = self.json(http, target, referer)
        if not isinstance(data.get('data'), dict):
            raise SourceError('Luscious не предоставил публичные данные.')
        return data['data']

    def album_row(self, data):
        target = self.site_link(data.get('url')) if isinstance(data, dict) else ''
        title = data.get('title') if target else ''
        if not self.is_title(target) or not isinstance(title, str) or not title:
            return None
        author = [value.split(':', 1)[1].strip() for value in named(data.get('tags'), 'text') if value.startswith('Artist:')]
        return self.record(self.title_for(target), title, image_url((data.get('cover') or {}).get('url'), CDN),
                           description=data.get('description') or '', genres=named(data.get('genres'), 'title'),
                           tags=[*strings(data.get('labels')), *named(data.get('tags'), 'text')],
                           authors=author, status='completed')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        filters = {'audience_ids': '+1+10+2+3+5+6+8+9'}
        if self.LANGUAGE in LANGUAGE:
            filters['language_ids'] = '+' + LANGUAGE[self.LANGUAGE]
        if query:
            filters['search_query'] = query
        if tag:
            filters['tagged'] = '+' + tag.strip().lower().replace(' ', '_')[:159]
        order = 'search_score' if query else 'date_newest' if sort == 'updated' else 'rating_all_time'
        request = {'input': {'display': order, 'page': page, 'filters': [
            {'name': key, 'value': value} for key, value in filters.items()]}}
        reply = self.request(http, LIST, request).get('album') or {}
        data = reply.get('list') or {}
        return [row for entry in items(data, 'items') if (row := self.album_row(entry))], bool(
            (data.get('info') or {}).get('has_next_page'))

    def pictures(self, http, title, page):
        query = {'input': {'display': 'date_oldest', 'page': page, 'items_per_page': 50,
                           'filters': [{'name': 'album_id', 'value': self.title_key(title)}]}}
        answer = self.request(http, PAGES, query, title).get('picture') or {}
        return (answer.get('list') or {})

    def series(self, http, url):
        key = self.title_key(url)
        data = (self.request(http, ALBUM, {'id': key}, url).get('album') or {}).get('get')
        row = self.album_row(data)
        if not row or self.title_key(row['url']) != key:
            raise SourceError('Luscious не подтвердил выбранный альбом.')
        count = number(data.get('number_of_pictures')) or 0
        if count <= 0:
            return row, []
        # Single-picture URLs were the extension default. Use positions so signed URLs need not be saved.
        entries = {}
        for page in range(1, min(20, (int(count) + 49) // 50) + 1):
            result = self.pictures(http, url, page)
            for item in items(result, 'items'):
                pos = item.get('position') if isinstance(item, dict) else None
                if type(pos) is not int or not 1 <= pos <= 1000:
                    continue
                date = item.get('created')
                date = datetime.fromtimestamp(date, tz=timezone.utc).date().isoformat() if (
                    type(date) in (int, float) and 0 < date <= 4_102_444_800) else ''
                target = query_url(url, picture=pos)
                entries[pos] = self.chapter(target, f'{pos} · {item.get("title") or ""}'.rstrip(' ·'), pos, date)
        merged = self.chapter(query_url(url, chunk=1), 'Альбом', 1)
        return row, [merged, *self.order(entries)]

    def picture_url(self, data):
        video = image_url(data.get('url_to_video'), CDN)
        if video and urlsplit(video).path.endswith('.mp4'):
            return image_url(urlsplit(video).path[:-4] + '.gif', CDN)
        original = image_url(data.get('url_to_original'), CDN)
        if original:
            return original
        choices = []
        for item in items(data, 'thumbnails'):
            target = image_url(item.get('url'), CDN) if isinstance(item, dict) else ''
            if target:
                choices.append(((number(item.get('width')) or 0) * (number(item.get('height')) or 0), target))
        return max(choices)[1] if choices else ''

    def pages(self, http, url):
        position = int(param(url, 'picture') or 0)
        title = self.title_for(url)
        if position > 1000:
            raise SourceAccessError('Эта страница за пределами открытой части альбома.')
        preferred = (position - 1) // 50 + 1 if position else 1
        pages = range(1, 21) if not position else (preferred, *(p for p in range(1, 21) if p != preferred))
        found = {}
        for page in pages:
            result = self.pictures(http, title, page)
            rows = items(result, 'items')
            for item in rows:
                if not isinstance(item, dict) or type(item.get('position')) is not int:
                    raise SourceError('Luscious изменил список изображений.')
                if not position or position == item['position']:
                    if not (target := self.picture_url(item)):
                        raise SourceError('Luscious не предоставил изображение альбома.')
                    found[item['position']] = target
                    if position:
                        return [target]
            if len(rows) < 50 and (not position or page != preferred):
                break
        return [found[key] for key in sorted(found)]


SOURCES = tuple(Luscious((sid, 'Luscious', lang, ROOT, True)) for sid, lang in (
    ('2774395484485436593', 'en'), ('356192691213044104', 'ja'), ('4290611657061143259', 'es'),
    ('80965277100704155', 'it'), ('5185485787190542529', 'de'), ('151111346668901230', 'fr'),
    ('5200417794129414472', 'zh'), ('264934399418113929', 'ko'), ('1383462828430089842', 'other'),
    ('2638955581892699679', 'th'), ('4625881812440927464', 'all'), ('5826725746643311801', 'pt-BR'),
))
