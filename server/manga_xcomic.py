"""XCOMIC title and edition routes, keeping chapter and translation identities."""

from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time
from datetime import datetime, timezone
from html import unescape
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_dot_nami_http import document, json_data, mapping, records
from manga_madara import OriginPace, image_url
from manga_source_tags import labels, unique
from manga_source_urls import reader_url, split_reader_url
from manga_xcomic_fury_profiles import XCOMIC
from manga_xcomic_queries import BROWSE, EDITION, FULL, OPERATIONS, PAGER, PAGES, PROBE, QUERIES, TITLE, UNIQUE
from source_parser import SourceAccessError, SourceError, public_url


ROOT = 'https://xcomic.me'
ENDPOINT = ROOT + '/query/'
ID = r'[A-Za-z0-9_][A-Za-z0-9_-]{0,95}'
IDENTITY = re.compile(ID)
TITLE_PATH = re.compile(rf'/(?:title|comic|source)/({ID})/?')
CHAPTER_PATH = re.compile(rf'/chapter/({ID})/?')
STORED = re.compile(rf'({ID})(?::({ID}))?')
LOOKUP = re.compile(rf'id\s*:?\s*({ID}(?::{ID})?)', re.I)
LANGS = {'pt-BR': 'pt_br', 'es-419': 'es_419', 'zh-Hant': 'zh_hk', 'other': '_t'}
CODES = {LANGS.get(lang, lang): lang for _, lang in XCOMIC}
FILTER = re.compile(r'[a-z0-9][a-z0-9_]{0,90}')
LIMIT = 12
# Long-running titles carry hundreds of editions (Chainsaw Man: 340). The site
# allows one root field per GraphQL request, so each edition is one probe, as
# in the extension; probes are cached for all language profiles of the site.
EDITIONS = 500
PROBE_TTL = 6 * 3600
PROBE_CAPACITY = 20000
CHAPTERS_LIMIT = 6000
PACE = OriginPace()
PACE.interval = .2
# Edition probes are tiny; the extension sends them five at a time unpaced.
PROBE_PACE = OriginPace()
PROBE_PACE.interval = .05
_probes = OrderedDict()
_probes_lock = Lock()


def valid_id(value):
    return isinstance(value, str) and bool(IDENTITY.fullmatch(value))


def graphql_form(url, body):
    if url != ENDPOINT or not isinstance(body, bytes) or len(body) > 8192:
        return False
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return False
    if not isinstance(payload, dict) or payload.keys() != {'query', 'variables'}:
        return False
    query, variables = payload['query'], payload['variables']
    operation = OPERATIONS.get(query) if isinstance(query, str) else None
    if operation is None or not isinstance(variables, dict):
        return False
    if operation in (TITLE, EDITION, PROBE, PAGES):
        return variables.keys() == {'id'} and valid_id(variables['id'])
    select = variables.get('select')
    if variables.keys() != {'select'} or not isinstance(select, dict):
        return False
    page = select.get('page')
    if type(page) is not int or not 1 <= page <= 2000:
        return False
    if operation in (UNIQUE, FULL):
        return (select.keys() == {'comic_id', 'page', 'size', 'sortby'} and valid_id(select['comic_id'])
                and select['size'] == (1000 if operation == UNIQUE else 100) and select['sortby'] == 'chapter_desc')
    if not {'page', 'size', 'init', 'where', 'word'} <= select.keys() <= {
            'page', 'size', 'init', 'where', 'word', 'sortby', 'incTLangs', 'incGenres'}:
        return False
    langs, genres = select.get('incTLangs', []), select.get('incGenres', [])
    return (select['init'] == (page - 1) * LIMIT and select['size'] == LIMIT and select['where'] == 'browse'
            and isinstance(select['word'], str) and len(select['word']) <= 160
            and select.get('sortby') in (None, 'field_score', 'field_update')
            and isinstance(langs, list) and len(langs) <= 1 and all(isinstance(v, str) and v in CODES for v in langs)
            and isinstance(genres, list) and len(genres) <= 1
            and all(isinstance(v, str) and FILTER.fullmatch(v) for v in genres))


def gql(http, operation, variables):
    body = json.dumps({'query': QUERIES[operation], 'variables': variables}, ensure_ascii=False).encode()
    (PROBE_PACE if operation == PROBE else PACE).wait(http.deadline)
    raw = document(http, ROOT, '/query/', body=body, action='xcomic-graphql')
    payload = mapping(json_data(raw))
    if payload.get('errors'):
        raise SourceError('XCOMIC отклонил публичный запрос.')
    data = mapping(payload.get('data'))
    field = EDITION if operation == PROBE else operation
    if field not in data:
        raise SourceError('XCOMIC не вернул данные запрошенной операции.')
    return data[field]


def node(http, operation, identity):
    result = gql(http, operation, {'id': identity})
    if result is None:
        return None
    result = mapping(result)
    if result.get('id', identity) != identity:
        raise SourceError('XCOMIC вернул другой идентификатор.')
    value = result.get('data')
    return mapping(value) if value is not None else None


def probe(http, identity):
    """An edition's language and state, shared by every language profile."""
    now = time.monotonic()
    with _probes_lock:
        hit = _probes.get(identity)
        if hit and hit[0] > now:
            _probes.move_to_end(identity)
            return hit[1]
    row = node(http, PROBE, identity)
    with _probes_lock:
        _probes[identity] = now + PROBE_TTL, row
        _probes.move_to_end(identity)
        while len(_probes) > PROBE_CAPACITY:
            _probes.popitem(last=False)
    return row


def title_node(http, identity):
    seen = set()
    for _ in range(5):
        if identity in seen:
            break
        seen.add(identity)
        title = node(http, TITLE, identity)
        if title is None:
            return None
        if title.get('id', identity) != identity:
            raise SourceError('XCOMIC вернул данные другого тайтла.')
        replacement = title.get('merged_to')
        if title.get('is_merged') is not True or not valid_id(replacement):
            return identity, title
        identity = replacement
    raise SourceError('XCOMIC вернул циклическую ссылку между тайтлами.')


def edition_label(value):
    return ' '.join(unescape(value).split()) if isinstance(value, str) else ''


def number(value):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return 0
    return value if 0 <= value <= 99999 else 0


def release_date(value):
    if type(value) is int and 0 < value < 4_102_444_800_000:
        dt = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(dt, timezone.utc).date().isoformat()
    return ''


def route_id(key):
    return key.split('-', 1)[0] if re.match(r'^\d+-', key) else key


class XComic:
    ROOT = ROOT
    NAME = 'XCOMIC'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, language):
        self.SOURCE_ID, self.LANGUAGE = sid, language
        self.lang = LANGS.get(language, language)

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            parts = urlsplit(raw)
            if selected not in (None, self.SOURCE_ID) or parts.scheme != 'https' or parts.netloc != 'xcomic.me':
                return ''
            args = parse_qs(parts.query, keep_blank_values=True, max_num_fields=8)
            query = {}
            for key in ('title', 'edition', 'legacy_id'):
                if key in args:
                    if len(args[key]) != 1 or not valid_id(args[key][0]):
                        return ''
                    query[key] = args[key][0]
            return public_url(urlunsplit(parts._replace(query=urlencode(query))), resolve_dns=False)
        except (ValueError, SourceError):
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def row(self, identity, title, edition=None):
        edition = edition or {}
        name = edition_label(title.get('title') or edition.get('name')) or identity
        url = self.reader_url(ROOT + '/title/' + identity)
        labels_by_field = [*(title.get('alt_titles') or []), title.get('native_title'), title.get('romanized_title'),
                           *(edition.get('altNames') or [])]
        kind = str(title.get('type') or title.get('type_id') or edition.get('type') or '').lower()
        media_format = kind if kind in {'manga', 'manhwa', 'manhua', 'comic', 'webtoon', 'oneshot'} else 'manga'
        status = str(title.get('status') or edition.get('originalStatus') or '').lower()
        status = 'ongoing' if status in {'releasing', 'ongoing'} else status
        rating = title.get('content_rating_id') or edition.get('contentRating')
        explicit = rating in {'erotica', 'pornographic', 'adult', 'mature'}
        summary = edition.get('summary') or {}
        ids = title.get('tracking_sites') or {}
        ids = {('mal' if key == 'myanimelist' else key): val for key, val in ids.items() if val}
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME, 'url': url, 'sourceUrl': url,
                'title': name, 'aliases': unique([name, *(edition_label(value) for value in labels_by_field)]),
                'language': self.LANGUAGE, 'kind': 'manga', 'format': media_format,
                'readingMode': 'scroll' if edition.get('readDirection') == 'ttb' or media_format == 'webtoon' else 'pages',
                'cover': image_url(title.get('cover_local_url') or title.get('cover_url') or edition.get('urlCover'), ROOT + '/'),
                'genres': unique(value.replace('_', ' ').title() for value in labels(title.get('genre_ids') or edition.get('genres'))),
                'tags': unique([*(value.replace('_', ' ').title() for field in ('format_ids', 'demographic_ids')
                                  for value in labels(title.get(field))), *labels(edition.get('tags'))]),
                'description': unescape(str(title.get('description') or summary.get('text') or ''))[:12000],
                'authors': labels(title.get('authors')), 'artists': labels(title.get('artists')), 'year': title.get('year'),
                'status': status, 'adult': explicit, 'age': 18 if explicit else None, 'sourceOnly': True, 'ids': ids}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or tag and not FILTER.fullmatch(tag):
            raise SourceError('Некорректные параметры каталога XCOMIC.')
        query = query.strip()[:160]
        if match := LOOKUP.fullmatch(query):
            if page != 1:
                return [], False
            return [self.resolve(http, match[1])[0]], False
        select = {'word': query, 'page': page, 'size': LIMIT, 'init': (page - 1) * LIMIT, 'where': 'browse'}
        if not query:
            select['sortby'] = 'field_update' if sort == 'updated' else 'field_score'
        if self.lang != 'all':
            select['incTLangs'] = [self.lang]
        if tag:
            select['incGenres'] = [tag]
        args = {'select': select}
        rows = records(gql(http, BROWSE, args) or [])
        status = mapping(gql(http, PAGER, args))
        result = {}
        for row in rows:
            identity = row.get('id')
            data = row.get('data') or {}
            known = data.get('translated_languages') or []
            if valid_id(identity) and (self.lang == 'all' or not known or self.lang in known):
                result.setdefault(identity, self.row(identity, data))
        return list(result.values()), bool(status.get('next'))

    def vocabulary(self, http):
        raw, final, _ = http.document(ROOT + '/search')
        if self.site_link(final) != ROOT + '/search':
            raise SourceError('XCOMIC перенаправил справочник тегов.')
        feeds = BeautifulSoup(raw, 'html.parser').select('details.group')
        terms = {}
        for group in feeds:
            summary = group.select_one('summary')
            if not summary or 'genre' not in summary.get_text(' ', strip=True).casefold():
                continue
            fmt = next((item.find_next_sibling() for item in group.find_all('div')
                        if ''.join(item.find_all(string=True, recursive=False)).strip() == 'Formats'), None)
            fmt_ids = {child.get(':') for child in fmt.find_all('div')} if fmt else set()
            for option in group.select('div'):
                identity = option.get(':')
                label = option.select_one('span')
                if isinstance(identity, str) and FILTER.fullmatch(identity) and label:
                    name = label.get_text(' ', strip=True)
                    if name:
                        terms.setdefault(identity, {'sourceId': identity, 'label': name,
                                                    'category': 'tag' if identity in fmt_ids else 'genre'})
        if not terms:
            raise SourceError('XCOMIC не предоставил справочник жанров и тегов.')
        return list(terms.values())

    def resolve(self, http, value, *, source=False):
        stored = STORED.fullmatch(value)
        if not stored:
            raise SourceError('Некорректный ID тайтла или издания XCOMIC.')
        identity, previous = stored.groups()
        title = title_node(http, identity) if not source else None
        edition = None
        if title is None:
            for candidate in dict.fromkeys(filter(None, (previous, identity))):
                edition = node(http, EDITION, candidate)
                title_ref = (edition or {}).get('title_titleNode') or {}
                data = title_ref.get('data') or {}
                parent = title_ref.get('id') or data.get('id')
                if valid_id(parent):
                    title = title_node(http, parent) or (parent, data)
                    break
        if title is None:
            raise SourceError('XCOMIC не нашёл тайтл или прежнее издание.')
        identity, data = title
        declared = list(dict.fromkeys(value for value in (data.get('comic_ids') or []) if valid_id(value)))
        if len(declared) > EDITIONS:
            raise SourceError('У тайтла XCOMIC слишком много изданий для одного запроса.')
        if edition and edition.get('translatedLanguage') not in (self.lang, None) and self.lang != 'all':
            edition = None
        return self.row(identity, data, edition), identity, data, declared

    def details(self, http, url):
        target = urlsplit(self.site_link(url))
        path = target.path
        matched = TITLE_PATH.fullmatch(path)
        if not matched:
            raise SourceError('Некорректная ссылка на тайтл XCOMIC.')
        identity = route_id(matched[1])
        legacy = parse_qs(target.query).get('legacy_id', [''])[0]
        lookup = identity + ':' + legacy if legacy else identity
        return self.resolve(http, lookup, source=path.startswith(('/comic/', '/source/')))[0]

    def editions(self, http, ids):
        def read(key):
            row = probe(http, key)
            if not row or row.get('isPublic') is False or row.get('dbStatus') not in (None, 'normal'):
                return None
            if self.lang != 'all' and row.get('translatedLanguage') != self.lang:
                return None
            return key, row

        with ThreadPoolExecutor(max_workers=min(5, max(len(ids), 1))) as pool:
            editions = list(pool.map(read, ids))
        return [item for item in editions if item]

    def chapter_url(self, identity, title, edition=''):
        query = {'title': title}
        if edition:
            query['edition'] = edition
        return ROOT + '/chapter/' + identity + '?' + urlencode(query)

    def release(self, row, edition_id, edition, parent):
        data = mapping(row.get('data'))
        identity = data.get('id') or row.get('id')
        if not valid_id(identity) or row.get('id', identity) != identity:
            raise SourceError('XCOMIC вернул главу без корректного ID.')
        if data.get('dbStatus') not in (None, 'normal') or data.get('count_images') == 0:
            return None
        chapter_num = number(data.get('chaNum', data.get('serial')))
        volume = number(data.get('volNum'))
        display = edition_label(data.get('dname'))
        name = ' — '.join(filter(None, (display or f'Глава {chapter_num:g}', edition_label(data.get('title')))))
        label = edition_label(edition.get('subName')) or edition_label(data.get('srcName'))
        lang = edition.get('translatedLanguage')
        published = data.get('dateModify') or data.get('dateCreate') or data.get('datePublic')
        return {'url': self.reader_url(self.chapter_url(identity, parent, edition_id)), 'title': name,
                'number': chapter_num, 'season': max(1, int(volume)), 'translator': label,
                'language': CODES.get(lang, lang) if self.lang == 'all' and isinstance(lang, str) else self.LANGUAGE,
                'publishedAt': release_date(published)}

    def releases(self, http, edition_id, edition, title, *, chosen='', full=False):
        field, size = (FULL, 100) if full else (UNIQUE, 1000)
        rows, consumed, expected = [], 0, None
        for page in range(1, CHAPTERS_LIMIT // size + 1):
            args = {'select': {'comic_id': edition_id, 'page': page, 'size': size, 'sortby': 'chapter_desc'}}
            data = mapping(gql(http, field, args))
            paging = mapping(data.get('paging'))
            items = records(data.get('items'))
            count = paging.get('total')
            if type(count) is not int or count < 0 or expected is not None and count != expected:
                raise SourceError('XCOMIC изменил размер оглавления во время запроса.')
            if not items and paging.get('next'):
                raise SourceError('XCOMIC вернул пустую страницу оглавления.')
            expected = count
            for item in items:
                if chosen and item.get('id') != chosen:
                    continue
                result = self.release(item, edition_id, edition, title)
                if result:
                    if chosen:
                        return [result], False
                    rows.append(result)
            consumed += len(items)
            if not paging.get('next'):
                if consumed != expected:
                    raise SourceError('XCOMIC не предоставил полное оглавление.')
                return rows, False
        return rows, True

    def inspect(self, value, http):
        target = self.site_link(value)
        parts = urlsplit(target)
        title, chapter = TITLE_PATH.fullmatch(parts.path), CHAPTER_PATH.fullmatch(parts.path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку XCOMIC.')
        args = parse_qs(parts.query)
        parent = route_id(title[1]) if title else args.get('title', [''])[0]
        if not parent:
            raise SourceError('Открой главу из оглавления XCOMIC.')
        legacy = args.get('legacy_id', [''])[0]
        lookup = parent + ':' + legacy if legacy else parent
        row, identity, metadata, ids = self.resolve(http, lookup, source=parts.path.startswith(('/comic/', '/source/')))
        chosen_edition = args.get('edition', [''])[0]
        if chosen_edition and chosen_edition not in ids:
            raise SourceError('Издание не относится к выбранному тайтлу XCOMIC.')
        editions = self.editions(http, [chosen_edition] if chosen_edition else ids)
        if editions:
            best = max(editions, key=lambda pair: number(pair[1].get('chaps_normal')))[0]
            row = self.row(identity, metadata, node(http, EDITION, best))
        episodes, pages, truncated = [], [], False
        chosen = route_id(chapter[1]) if chapter else ''
        for edition_id, edition in editions:
            rows, more = self.releases(http, edition_id, edition, identity, chosen=chosen)
            if chosen and not rows:
                rows, more = self.releases(http, edition_id, edition, identity, chosen=chosen, full=True)
            truncated |= more
            episodes.extend(rows)
            if chosen and rows:
                break
        if chosen and len(episodes) != 1:
            raise SourceAccessError('XCOMIC не предоставил главу в этом издании и на выбранном языке.')
        collisions = defaultdict(set)
        for episode in episodes:
            edition_id = parse_qs(urlsplit(episode['url']).query)['edition'][0]
            if episode['translator']:
                collisions[episode['translator'].casefold()].add(edition_id)
        for episode in episodes:
            name = episode['translator'].casefold()
            if len(collisions.get(name, ())) > 1:
                episode['translator'] += ' [' + parse_qs(urlsplit(episode['url']).query)['edition'][0] + ']'
        episodes.sort(key=lambda item: item['number'], reverse=True)
        if chosen:
            raw = (node(http, PAGES, chosen) or {}).get('imageUrls')
            if not isinstance(raw, list) or not 1 <= len(raw) <= 500:
                raise SourceError('XCOMIC не предоставил полный список страниц.')
            pages = [image_url(value, ROOT + '/') for value in raw]
            if not all(pages):
                raise SourceError('XCOMIC вернул недопустимый адрес страницы.')
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': truncated, 'dubs': [], 'releases': [],
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({entry['season'] for entry in episodes})],
                'translations': unique(entry['translator'] for entry in episodes)}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        if TITLE_PATH.fullmatch(path):
            return value
        stored = STORED.fullmatch(path.strip('/'))
        if not stored:
            return ''
        return ROOT + '/title/' + stored[1] + ('?legacy_id=' + stored[2] if stored[2] else '')

    def saved_chapter(self, row, root, title):
        raw = row.get('url') or ''
        path = urlsplit(self.site_link(row.get('realUrl') or raw, root)).path
        match = CHAPTER_PATH.fullmatch(path)
        identity = raw if valid_id(raw) else route_id(match[1]) if match else ''
        if not identity:
            return ''
        parts = urlsplit(title)
        parent = route_id(TITLE_PATH.fullmatch(parts.path)[1])
        legacy = parse_qs(parts.query).get('legacy_id', [''])[0]
        memo = row.get('memo')
        edition = memo.get('comicId', '') if isinstance(memo, dict) else ''
        target = self.chapter_url(identity, parent, edition if valid_id(edition) else '')
        return target + ('&legacy_id=' + legacy if legacy else '')

    def saved_chapter_matches(self, chapter, title):
        parent = route_id(TITLE_PATH.fullmatch(urlsplit(title).path)[1])
        return parse_qs(urlsplit(chapter).query).get('title') == [parent]


SOURCES = tuple(XComic(*profile) for profile in XCOMIC)
