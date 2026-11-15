"""Public MangaBall catalogues, localized chapters and native reader references."""

import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from manga_ball_million_profiles import BALL, BALL_TERMS
from manga_madara import SEGMENT, image_url
from manga_source_tags import labels, unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import PublicHttp, SourceError, public_url


ROOT = 'https://mangaball.com'
HOSTS = {'mangaball.com', 'mangaball.net'}
API = ROOT + '/api/v1'
ID = re.compile(r'[a-f0-9]{24}')
TITLE_PATH = re.compile(rf'/title-detail/({SEGMENT})/?')
CHAPTER_PATH = re.compile(rf'/chapter-detail/({ID.pattern})/?')
COVER_BASE = 'https://bulbasaur.poke-black-and-white.net/covers/'
TERMS = {identity: (name, category) for identity, name, category in BALL_TERMS}
GENRES = {name.casefold() for name, category in TERMS.values() if category == 'genre'}
TYPES = {'Manga': 'manga', 'Manhua': 'manhua', 'Manhwa': 'manhwa', 'Comic': 'comic'}
MARKER = 'mv_ball_page='


def request(http, endpoint, *, params=None, payload=None):
    from mangaball_reader import api_only

    target = API + endpoint + ('?' + urlencode(params) if params else '')
    reply = PublicHttp(validate=api_only(target), timeout=http.timeout, deadline=http.deadline)
    try:
        options = {'method': 'POST', 'data': json.dumps(payload).encode()} if payload else {}
        raw, final, _ = reply.document(target, headers={'Referer': ROOT + '/'}, **options)
        if final != target:
            raise SourceError('Manga Ball перенаправил запрос на другой маршрут.')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, RecursionError):
        raise SourceError('Manga Ball не предоставил данные каталога.') from None
    finally:
        reply.close()


def records(data):
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise SourceError('Manga Ball вернул некорректный список.')
    return data


def cover_url(item):
    cover = item.get('cover') or {}
    path = cover.get('path')
    if isinstance(path, str) and path.strip():
        path = path.strip().replace('\\', '/')
        if found := image_url(path, COVER_BASE):
            return found
    return next((url for key in ('file', 'cdn_mangadex', 'cdn_mangaupdate', 'cdn_mangaupdates')
                 if (url := image_url(item.get(key), ROOT + '/'))), '')


def parsed_page(value):
    parts = urlsplit(value)
    match = re.fullmatch(rf'{MARKER}({ID.pattern}),({ID.pattern}),([0-9]{{1,3}})', parts.fragment)
    if not match or int(match[3]) >= 500:
        raise SourceError('Некорректный адрес страницы Manga Ball.')
    return public_url(value, resolve_dns=False), match[1], match[2], int(match[3])


def published(item):
    return item.get('status') in (None, 'published')


class MangaBall:
    ROOT = ROOT
    NAME = 'Manga Ball'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, language, languages):
        self.SOURCE_ID, self.LANGUAGE, self.languages = sid, language, languages

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            parsed = urlsplit(raw)
            if selected not in (None, self.SOURCE_ID) or parsed.scheme != 'https' or parsed.netloc not in HOSTS:
                return ''
            parent = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=5).get('title', [])
            if parent and (len(parent) != 1 or not re.fullmatch(SEGMENT, parent[0])
                           or not CHAPTER_PATH.fullmatch(parsed.path)):
                return ''
            return public_url(ROOT + parsed.path + ('?' + urlencode({'title': parent[0]}) if parent else ''),
                              resolve_dns=False)
        except (SourceError, ValueError):
            return ''

    def reader_url(self, target):
        return reader_url(target, self.SOURCE_ID)

    def row(self, item):
        identity, title = str(item.get('id', '')), item.get('name')
        if not ID.fullmatch(identity) or not isinstance(title, str) or not title.strip():
            raise SourceError('Manga Ball не указал название или ID тайтла.')
        target = self.reader_url(ROOT + '/title-detail/' + identity)
        tags = labels(item.get('tags'))
        description = item.get('description') or []
        formats = next((TYPES[name] for name in TYPES if name in tags), '')
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'url': target, 'sourceUrl': target, 'kind': 'manga', 'language': self.LANGUAGE, 'title': title.strip()[:500],
                'aliases': unique([title, *labels(item.get('alternateName'))]),
                'genres': [name for name in tags if name.casefold() in GENRES and name not in TYPES],
                'tags': [name for name in tags if name.casefold() not in GENRES and name not in TYPES],
                'authors': labels(item.get('author')), 'status': item.get('status') or '',
                'format': formats or 'manga', 'readingMode': 'scroll' if 'Long Strip' in tags or formats == 'manhwa' else 'pages',
                'description': '\n\n'.join(part for part in description if isinstance(part, str))[:12000]
                if isinstance(description, list) else str(description)[:12000],
                'cover': cover_url(item.get('image') or {}), 'sourceOnly': True, 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or tag and tag not in TERMS:
            raise SourceError('Некорректные параметры каталога Manga Ball.')
        params = {'page': page, 'limit': 24, 'tag_mode': 'AND', 'adult_mode': 'all',
                  'chapterLanguage': ','.join(self.languages)}
        if query := query.strip()[:160]:
            params['keyword'] = query
        else:
            params.update(sort_by='lastupdate' if sort == 'updated' or tag else 'views', sort_order='desc')
        if tag:
            params['included_tags'] = tag
        result = request(http, '/title/search-advanced', params=params)
        pagination = result.get('pagination')
        if not isinstance(pagination, dict) or type(pagination.get('total_pages')) is not int or pagination.get('page') != page:
            raise SourceError('Manga Ball вернул другой номер страницы каталога.')
        return [self.row(row) for row in records(result.get('data'))], page < pagination['total_pages']

    def vocabulary(self, http):
        return [{'sourceId': sid, 'label': name, 'category': category} for sid, (name, category) in TERMS.items()]

    def work(self, http, identity):
        item = request(http, '/title/detail/' + identity).get('data')
        if (not isinstance(item, dict) or identity not in (item.get('id'), item.get('slug'))
                or ID.fullmatch(identity) and item.get('id') != identity):
            raise SourceError('Manga Ball вернул другой тайтл.')
        return item

    def details(self, http, value):
        title = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not title:
            raise SourceError('Некорректная ссылка на тайтл Manga Ball.')
        return self.row(self.work(http, title[1]))

    def episode(self, row, parent):
        identity = str(row.get('id', ''))
        if (not ID.fullmatch(identity) or (row.get('lang') or row.get('language')) not in self.languages
                or not published(row) or row.get('title_id', parent) != parent):
            return None
        number, volume = row.get('number'), row.get('volume')
        number = number if type(number) in (int, float) and 0 <= number <= 9999 else 0
        volume = volume if type(volume) in (int, float) and 0 < volume <= 999 else 1
        name = (row.get('name') or '').strip()
        number_label = format(number, 'g')
        label = name if number_label in name else ('Ch. ' + number_label + ' ' + name).strip()
        group = row.get('group')
        date = row.get('created_at')
        return {'url': self.reader_url(ROOT + '/chapter-detail/' + identity + '?title=' + parent), 'title': label,
                'number': number, 'season': max(1, int(volume)), 'language': self.LANGUAGE,
                'translator': (group or {}).get('name') or '', 'publishedAt': date[:10] if isinstance(date, str) else ''}

    def chapters(self, http, identity):
        response = request(http, '/chapter/chapter-listing-by-title-id', payload={'title_id': identity})
        return [entry for item in records(response.get('data')) if (entry := self.episode(item, identity))]

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        title, chapter = TITLE_PATH.fullmatch(path), CHAPTER_PATH.fullmatch(path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку Manga Ball.')
        pages = []
        if chapter:
            from mangaball_reader import chapter_data, page_targets
            info = chapter_data(chapter[1], http)
            parent = str(info.get('title_id', ''))
            if not ID.fullmatch(parent) or (entry := self.episode(info, parent)) is None:
                raise SourceError('Manga Ball вернул главу на другом языке или закрыл доступ.')
            work = self.work(http, parent)
            expected = parse_qs(urlsplit(target).query).get('title', [parent])[0]
            if expected not in (parent, work.get('slug')):
                raise SourceError('Глава относится к другому тайтлу Manga Ball.')
            row = self.row(work)
            episodes = [entry]
            pages = [url + f'#{MARKER}{parent},{chapter[1]},{i}' for i, url in enumerate(page_targets(info))]
        else:
            work = self.work(http, title[1])
            row, episodes = self.row(work), self.chapters(http, work['id'])
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': False, 'dubs': [], 'releases': [],
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({entry['season'] for entry in episodes})],
                'translations': unique(entry['translator'] for entry in episodes)}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        if TITLE_PATH.fullmatch(path):
            return value
        slug = path.strip('/')
        return ROOT + '/title-detail/' + slug if re.fullmatch(SEGMENT, slug) else ''

    def saved_chapter_url(self, value, slug, root):
        if not isinstance(value, str):
            return ''
        match = CHAPTER_PATH.fullmatch(urlsplit(self.site_link(value, root)).path)
        identity = value if ID.fullmatch(value) else match[1] if match else ''
        return ROOT + '/chapter-detail/' + identity + '?' + urlencode({'title': slug}) if identity else ''

    def saved_chapter_matches(self, chapter, title):
        return parse_qs(urlsplit(chapter).query).get('title') == [TITLE_PATH.fullmatch(urlsplit(title).path)[1]]


SOURCES = tuple(MangaBall(*profile) for profile in BALL)
