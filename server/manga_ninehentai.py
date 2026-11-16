"""NineHentai public catalogue, tags, gallery details and image sequence."""

import json
import re
from urllib.parse import urlsplit

from manga_madara import node_text, release_date
from manga_series_port import MAX_PAGES, Meta, SeriesPort
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://9hentai.so'
IMAGES = 'https://i.9hentai.so/images'
ID = r'[1-9]\d{0,9}'
GALLERY = rf'/g/({ID})/?'
ENDPOINTS = {'/api/getBook', '/api/getBookByID', '/api/getTag'}


def public_api(host, path, query):
    return host == '9hentai.so' and not query and path in ENDPOINTS


def is_index(value, minimum=1, maximum=10**10-1):
    return type(value) is int and minimum <= value <= maximum


def form(url, content):
    if not isinstance(content, bytes) or len(content) > 16_384:
        return False
    parts = urlsplit(url)
    if not public_api(parts.netloc, parts.path, parts.query):
        return False
    try:
        entry = json.loads(content)
        if parts.path == '/api/getBookByID':
            return set(entry) == {'id'} and is_index(entry['id'])
        if parts.path == '/api/getTag':
            return (set(entry) == {'tag_name', 'tag_type'} and isinstance(entry['tag_name'], str)
                    and 1 <= len(entry['tag_name']) <= 120 and is_index(entry['tag_type'], 1, 6))
        payload = entry['search']
        if set(entry) != {'search'} or set(payload) != {'text', 'page', 'sort', 'pages', 'tag'}:
            return False
        if not (isinstance(payload['text'], str) and len(payload['text']) <= 160 and
                is_index(payload['page'], 0, 1999) and is_index(payload['sort'], 0, 4)):
            return False
        if payload['pages'] != {'range': [0, 2000]} or set(payload['tag']) != {'items'}:
            return False
        tags = payload['tag']['items']
        return set(tags) == {'included', 'excluded'} and all(
            isinstance(group, list) and len(group) <= 16 and all(
                set(t) == {'id', 'name', 'type'} and is_index(t['id']) and is_index(t['type'], 1, 6)
                and isinstance(t['name'], str) and 0 < len(t['name']) <= 120 for t in group)
            for group in tags.values())
    except (TypeError, ValueError, AttributeError, KeyError):
        return False


class NineHentai(SeriesPort):
    meta = Meta('#bigcontainer h1', 'meta[property="og:image"]', '',
                '#bigcontainer h2', '', '.field-name:-soup-contains-own("Tag:") a.tag',
                '.field-name:-soup-contains-own("Artist:") a.tag, .field-name:-soup-contains-own("Group:") a.tag')

    def __init__(self):
        super().__init__(('7689490563697355048', 'NineHentai', 'en', ROOT, True), GALLERY, GALLERY,
                         legacy_hosts=('9hentai.com', 'www.9hentai.com'), interval=.5)

    def is_title(self, url):
        return super().is_title(url) and param(url, 'mv_nine_gallery') != '1'

    def title_for(self, url):
        key = self.title_key(url)
        return ROOT + '/g/' + key if key else ''

    def chapter_identity(self, url):
        return self.title_key(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if not self.title_key(url):
            url = title
        key = self.title_key(url)
        return query_url(ROOT + '/g/' + key, mv_nine_gallery=1) if key else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def post(self, http, path, data):
        self.origin.wait(getattr(http, 'deadline', None))
        url = ROOT + path
        raw, final, _ = http.document(url, method='POST', data=json.dumps(data, separators=(',', ':')).encode(),
                                      headers={'Referer': ROOT + '/'}, action='ninehentai-api')
        if final != url:
            raise SourceError('NineHentai перенаправил публичный запрос.')
        return json.loads(raw)

    def by_id(self, http, key):
        data = self.post(http, '/api/getBookByID', {'id': int(key)}).get('results')
        if not isinstance(data, dict) or str(data.get('id')) != key:
            raise SourceError('NineHentai не предоставил указанную карточку.')
        return data

    def summary(self, entry):
        key = str(entry.get('id', ''))
        label = entry.get('title')
        if not re.fullmatch(ID, key) or not isinstance(label, str) or not label:
            return None
        return self.record(ROOT + '/g/' + key, label, f'{IMAGES}/{key}/cover.jpg', status='completed')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query.startswith('id:') and re.fullmatch(ID, query[3:]):
            row = self.summary(self.by_id(http, query[3:]))
            return ([row] if page == 1 and row else []), False
        tags = []
        if tag and len(tag) <= 120:
            found = self.post(http, '/api/getTag', {'tag_name': tag, 'tag_type': 1}).get('results') or []
            if not found:
                return [], False
            item = found[0]
            tags = [{'id': item['id'], 'name': item['name'], 'type': item.get('type', 1)}]
        payload = {'search': {'text': query, 'page': page - 1, 'sort': 1 if sort == 'popular' and not query else 0,
                              'pages': {'range': [0, 2000]}, 'tag': {'items': {'included': tags, 'excluded': []}}}}
        data = self.post(http, '/api/getBook', payload)
        result = [row for item in data.get('results') or [] if isinstance(item, dict) and (row := self.summary(item))]
        total = data.get('total_count')
        return result, bool(result and type(total) is int and total > page)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row.update(cover=f'{IMAGES}/{self.title_key(url)}/cover.jpg', status='completed')
        return row

    def chapters(self, http, doc, final):
        text = node_text(doc.select_one('#info time'))
        date = release_date(text, '%Y-%m-%d')
        return [self.chapter(query_url(self.title_for(final), mv_nine_gallery=1), 'Chapter', 1, date=date)], False

    def pages(self, http, url):
        key = self.title_key(url)
        data = self.by_id(http, key)
        size = data.get('total_page')
        if type(size) is not int or not 1 <= size <= MAX_PAGES:
            raise SourceError('NineHentai вернул недопустимое число страниц.')
        probe = f'{IMAGES}/{key}/preview/{size}t.jpg'
        try:
            response, _ = http._open(probe, headers={'Referer': self.title_for(url)}, byte_range='bytes=0-0')
            response.close()
        except SourceError as error:
            if str(error) != 'Источник вернул HTTP 404.':
                raise
            size -= 1
        return [f'{IMAGES}/{key}/{i}.jpg' for i in range(1, size + 1)]


SOURCES = (NineHentai(),)
