"""MangaDot public JSON catalogues, route records and reader payloads."""

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from manga_dot_nami_http import document, json_data, mapping, records
from manga_dot_nami_profiles import MANGA_DOT
from manga_dot_wire import route_data
from manga_madara import image_url
from manga_source_tags import clean_label, labels, unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceError, public_url


ROOT = 'https://mangadot.net'
HOST = 'mangadot.net'
ID = r'[1-9][0-9]{0,9}'
TITLE_PATH = re.compile(rf'/manga/({ID})/?')
CHAPTER_PATH = re.compile(rf'/(chapter|volume)/({ID})/?')
PARENT = re.compile(ID)
LANGS = {'pt-BR': 'pt-br', 'es-419': 'es-la', 'zh-Hant': 'zh-hk'}
FORMATS = {'JP': 'manga', 'KR': 'manhwa', 'CN': 'manhua', 'ONESHOT': 'oneshot', 'EN': 'comic'}
DEMO = {'Josei', 'Seinen', 'Shoujo', 'Shounen'}
BROWSE_ROUTE = 'pages/ViewAllPage'
TITLE_ROUTE = 'pages/MangaDetailPage'


def number(value, default=0):
    return value if type(value) in (int, float) and 0 <= value <= 99999 else default


def get(http, path, params=()):
    return json_data(document(http, ROOT, path, params))


def catalog_records(data):
    for key in ('mangaList', 'results', 'manga_list'):
        if key in data:
            return records(data[key] or [])
    return []


def vocabulary_labels(values):
    found = {}
    for value in values:
        if name := clean_label(value):
            found.setdefault(name.casefold(), name)
    return list(found.values())


def multiline(value):
    if not isinstance(value, str):
        return ''
    return re.sub(r'\n{3,}', '\n\n', value.replace('\r\n', '\n')).strip()[:12000]


def contributors(value):
    if isinstance(value, str):
        try:
            value = json_data(value)
        except SourceError:
            return []
    return labels(value)


class MangaDot:
    ROOT = ROOT
    NAME = 'MangaDot'
    TITLE_PATH = TITLE_PATH
    # This extra capture is handled by saved_chapter_matches.
    CHAPTER_PATH = CHAPTER_PATH
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'index'

    def __init__(self, sid, language):
        self.SOURCE_ID, self.LANGUAGE = sid, language
        self.lang = LANGS.get(language, language)
        self.languages = {self.lang.casefold(), self.LANGUAGE.casefold()}

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            parts = urlsplit(raw)
            if selected not in (None, self.SOURCE_ID) or parts.scheme != 'https' or parts.netloc != HOST:
                return ''
            args = parse_qs(parts.query, keep_blank_values=True, max_num_fields=8)
            query = {}
            chapter_source = args.get('source', [])
            if chapter_source in (['user'], ['official']) and CHAPTER_PATH.fullmatch(parts.path):
                query['source'] = chapter_source[0]
            parent = args.get('title', [])
            if parent:
                if len(parent) != 1 or not PARENT.fullmatch(parent[0]) or not CHAPTER_PATH.fullmatch(parts.path):
                    return ''
                query['title'] = parent[0]
            return public_url(urlunsplit(parts._replace(query=urlencode(query))), resolve_dns=False)
        except (ValueError, SourceError):
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def row(self, item):
        identity = str(item.get('id', item.get('manga_id', '')))
        name = item.get('title')
        if not PARENT.fullmatch(identity) or not isinstance(name, str) or not name.strip():
            raise SourceError('MangaDot вернул карточку без ID или названия.')
        target = self.reader_url(ROOT + '/manga/' + identity)
        genres = labels(item.get('genres'))
        adult = item.get('is_blurworthy') in (1, '1', 'true') or item.get('content_rating') in ('erotica', 'pornographic')
        form = FORMATS.get(item.get('country_of_origin'), 'manga')
        ids = {key: item[key + '_id'] for key in ('anilist', 'mal', 'kitsu', 'shikimori', 'mangadex')
               if isinstance(item.get(key + '_id'), (int, str)) and item[key + '_id']}
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'url': target, 'sourceUrl': target, 'language': self.LANGUAGE, 'kind': 'manga', 'format': form,
                'title': name.strip()[:500], 'aliases': unique([name, *labels(item.get('alt_titles'))]),
                'genres': [name for name in genres if name not in DEMO],
                'tags': unique([*(name for name in genres if name in DEMO),
                                *(name for group in records(item.get('tags') or []) for name in labels(group.get('tags')))]),
                'authors': contributors(item.get('authors')), 'artists': contributors(item.get('artists')),
                'adult': adult, 'age': 18 if adult else None, 'description': multiline(item.get('description')),
                'cover': image_url(item.get('photo'), ROOT + '/'), 'status': item.get('status') or '',
                'year': item.get('year'), 'readingMode': 'scroll' if form == 'manhwa' else 'pages',
                'ids': ids, 'sourceOnly': True}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str):
            raise SourceError('Некорректные параметры каталога MangaDot.')
        query = query.strip()[:160]
        if query or tag or sort == 'index':
            params = {'lang': self.lang, 'page': page, 'limit': 56, 'sortOrder': 'desc'}
            if query.startswith('\u200b'):
                artist = query.startswith('\u200b\u200b')
                params['artist' if artist else 'author'] = query[2 if artist else 1:].strip()
            elif query:
                params['search'] = query
            else:
                params['sortBy'] = 'latest'
            if tag:
                key, _, value = tag.partition(':')
                if key not in {'genres', 'tags'} or not value or len(value) > 120 or ',' in value or value[0] == '-':
                    raise SourceError('Некорректный фильтр MangaDot.')
                params[key] = value
            data = mapping(get(http, '/api/search', params))
        else:
            mode = 'latest-updates' if sort == 'updated' else 'most-tracked'
            params = {'adult': '0', '_routes': BROWSE_ROUTE}
            if page > 1:
                params['page'] = page
            raw = document(http, ROOT, f'/view-all/{mode}.data', params)
            data = mapping(mapping(route_data(raw, BROWSE_ROUTE).get('data')).get('data'))
        rows = [self.row(item) for item in catalog_records(data)]
        pagination = mapping(data.get('pagination') or {})
        current = next((pagination[key] for key in ('current_page', 'currentPage', 'page') if key in pagination), page)
        total = next((pagination[key] for key in ('total_pages', 'totalPages', 'last_page', 'lastPage')
                      if key in pagination), None)
        cursor = pagination.get('next_cursor') or pagination.get('nextCursor') or pagination.get('cursor')
        more = type(current) is int and type(total) is int and current < total if total is not None else bool(cursor)
        return rows, bool(rows and more)

    def vocabulary(self, http):
        facets = mapping(mapping(get(http, '/api/search', {'facets': 1})).get('facets') or {})
        genres = vocabulary_labels(row.get('key') for row in records(facets.get('genres') or []))
        raw = records(mapping(get(http, '/api/manga/tags')).get('categories') or [])
        tags = vocabulary_labels(tag.get('name') for group in raw for tag in records(group.get('tags') or []))
        return [{'sourceId': key + ':' + term, 'label': term, 'category': category}
                for key, category, terms in [('genres', 'genre', [v for v in genres if v not in DEMO]),
                                             ('tags', 'tag', tags), ('genres', 'tag', [v for v in genres if v in DEMO])]
                for term in terms if ',' not in term and not term.startswith('-')]

    def work(self, http, identity):
        raw = document(http, ROOT, f'/manga/{identity}.data', {'_routes': TITLE_ROUTE})
        payload = mapping(mapping(route_data(raw, TITLE_ROUTE).get('data')).get('mangaData'))
        manga = mapping(payload.get('manga'))
        if str(manga.get('id')) != identity:
            raise SourceError('MangaDot вернул другой тайтл.')
        return self.row(manga), payload.get('total_volumes')

    def details(self, http, value):
        title = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not title:
            raise SourceError('Некорректная ссылка на тайтл MangaDot.')
        return self.work(http, title[1])[0]

    def chapter_url(self, identity, parent, volume=False, user=False):
        path = ('/volume/' if volume else '/chapter/') + identity
        query = {'title': parent} if parent else {}
        if user and not volume:
            query = {'source': 'user', **query}
        if volume and not user:
            query = {'source': 'official', **query}
        return ROOT + path + ('?' + urlencode(query) if query else '')

    def entry(self, item, parent, volume):
        identity, language = str(item.get('id')), item.get('language')
        if not PARENT.fullmatch(identity) or (language is not None and str(language).casefold() not in self.languages):
            return None
        user = item.get('source', 'user') == 'user'
        chapter = number(item.get('chapter_number'))
        vol = number(item.get('volume_number'), 1)
        name = str(item.get('chapter_title') or '').strip()
        if volume:
            name = f'Том {vol:g}'
        elif f'{chapter:g}' not in name:
            name = f'Глава {chapter:g}' + (': ' + name if name else '')
        group = ' • '.join(labels(item.get('groups'))) or item.get('group_name') or item.get('scanlator_name') or ''
        date = item.get('date_added')
        return {'url': self.reader_url(self.chapter_url(identity, parent, volume, user)), 'title': name,
                'number': 0 if volume else chapter, 'season': max(1, int(vol)), 'language': self.LANGUAGE,
                'translator': group, 'publishedAt': date[:10] if isinstance(date, str) else ''}

    def chapters(self, http, parent, *, volume=False):
        mode = '/volumes' if volume else '/chapters/list'
        rows = records(get(http, '/api/manga/' + parent + mode, {'lang': self.lang}))
        ordered = rows if volume else reversed(rows)
        return list({item['url']: item for row in ordered if (item := self.entry(row, parent, volume))}.values())

    def inspect(self, value, http):
        target = self.site_link(value)
        parts = urlsplit(target)
        title, chapter = TITLE_PATH.fullmatch(parts.path), CHAPTER_PATH.fullmatch(parts.path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку MangaDot.')
        pages = []
        if chapter:
            params = parse_qs(parts.query)
            volume = chapter[1] == 'volume'
            upstream = params.get('source', ['user' if volume else 'official'])[0]
            segment = 'uploads' if upstream == 'user' else 'chapters'
            try:
                data = mapping(get(http, f'/api/{segment}/{chapter[2]}/images'))
            except SourceError as error:
                if volume or 'source' in params or type(error) is not SourceError or 'HTTP 404' not in str(error):
                    raise
                segment = 'uploads'
                data = mapping(get(http, f'/api/{segment}/{chapter[2]}/images'))
            parent = str(mapping(data.get('manga')).get('id'))
            if not PARENT.fullmatch(parent) or params.get('title', [parent]) != [parent]:
                raise SourceError('Глава относится к другому тайтлу MangaDot.')
            canonical = self.reader_url(self.chapter_url(chapter[2], parent, volume, segment == 'uploads'))
            episodes = [row for row in self.chapters(http, parent, volume=volume) if row['url'] == canonical]
            if len(episodes) != 1:
                raise SourceError('Глава отсутствует в оглавлении MangaDot на выбранном языке.')
            pages = [image_url(row.get('url'), ROOT + '/') for row in records(data.get('images'))]
            if not 1 <= len(pages) <= 500 or not all(pages):
                raise SourceError('MangaDot не предоставил полный список страниц.')
            row, _ = self.work(http, parent)
        else:
            row, volume_count = self.work(http, title[1])
            episodes = self.chapters(http, title[1])
            if type(volume_count) is int and volume_count > 0:
                episodes += self.chapters(http, title[1], volume=True)
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': False, 'dubs': [], 'releases': [],
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({entry['season'] for entry in episodes})],
                'translations': unique(entry['translator'] for entry in episodes)}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        title = TITLE_PATH.fullmatch(path)
        identity = title[1] if title else path.strip('/')
        return ROOT + '/manga/' + identity if PARENT.fullmatch(identity) else ''

    def saved_chapter_url(self, value, parent, root):
        if not isinstance(value, str):
            return ''
        if value.startswith('{') and len(value) <= 400:
            try:
                data = mapping(json_data(value))
            except SourceError:
                return ''
            identity = str(data.get('id', ''))
            if PARENT.fullmatch(identity) and type(data.get('isVolume')) is bool:
                return self.chapter_url(identity, parent, data['isVolume'], data.get('source') == 'user')
        else:
            target = self.site_link(value, root)
            parts = urlsplit(target)
            if found := CHAPTER_PATH.fullmatch(parts.path):
                volume = found[1] == 'volume'
                upstream = parse_qs(parts.query).get('source', ['user' if volume else 'official'])[0]
                return self.chapter_url(found[2], parent, volume, upstream == 'user')
        return ''

    def saved_chapter_matches(self, chapter, title):
        return parse_qs(urlsplit(chapter).query).get('title') == [TITLE_PATH.fullmatch(urlsplit(title).path)[1]]


SOURCES = tuple(MangaDot(*profile) for profile in MANGA_DOT)
