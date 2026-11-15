"""MangaDex language profiles and public reader protocol from Keiyoushi."""

import re
from threading import Lock
import time
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit

from manga_catalog_adapters import CONTENT_RATINGS, DEX_USER_AGENT, UUID, get, names
from manga_madara import OriginPace
from manga_source_tags import from_api, labels, unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceAccessError, SourceError, public_url


API = 'https://api.mangadex.org'
ROOT = 'https://mangadex.org'
LIMIT = 20
FEED_LIMIT = 500
MAX_OFFSET = 10000
TITLE_PATH = re.compile(rf'/(?:title|manga)/({UUID})(?:/[^/]+)?/?')
CHAPTER_PATH = re.compile(rf'/chapter/({UUID})(?:/[^/]+)?/?')
UUID_PATTERN = re.compile(UUID)
FILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,249}')
HASH = re.compile(r'[a-f0-9]{32,64}')
API_LANGUAGES = {'zh-Hans': 'zh', 'zh-Hant': 'zh-hk', 'fil': 'tl', 'pt-BR': 'pt-br', 'es-419': 'es-la'}
QUERY_TYPES = {'title': 'id', 'manga': 'id', 'chapter': 'ch', 'group': 'grp', 'author': 'author',
               'user': 'usr', 'list': 'list'}
ALL_RATINGS = [('contentRating[]', rating) for rating in CONTENT_RATINGS]
PUBLIC_RATINGS = ALL_RATINGS[:2]
IMAGE_MARKER = 'mv_dex_page='
IMAGE_LEASE_SECONDS = 270
PACE = OriginPace()
PACE.interval = 0.35
_leases = {}
_lease_lock = Lock()


def request(http, path, params=()):
    PACE.wait(getattr(http, 'deadline', None))
    return get(API + path + ('?' + urlencode(params) if params else ''), http)


def records(response):
    rows = response.get('data')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SourceError('MangaDex вернул некорректный список.')
    return rows


def record(response, kind, identity):
    row = response.get('data')
    if not isinstance(row, dict) or row.get('id') != identity or row.get('type') != kind:
        raise SourceError('MangaDex вернул другую запись.')
    return row


def attributes(row):
    item = row.get('attributes')
    if not isinstance(item, dict):
        raise SourceError('MangaDex вернул запись без свойств.')
    return item


def relations(row, kind):
    return [item for item in row.get('relationships', [])
            if isinstance(item, dict) and item.get('type') == kind]


def related_ids(rows, kind):
    return list(dict.fromkeys(item['id'] for row in rows for item in relations(row, kind)
                              if UUID_PATTERN.fullmatch(str(item.get('id', '')))))


def has_more(response, offset, count, limit):
    total = response.get('total')
    return count > 0 and offset + count < min(total, MAX_OFFSET) if type(total) is int else count == limit


def source_query(value):
    query = ' '.join(value.split())[:240]
    match = re.fullmatch(rf'(id|ch|grp|author|usr|list):\s*({UUID})', query, re.I)
    if match:
        return match[1].lower(), match[2].lower()
    if query.startswith(('https://', 'http://')):
        try:
            parts = urlsplit(query)
        except ValueError:
            return '', query
        if parts.hostname in {'mangadex.org', 'www.mangadex.org', 'api.mangadex.org'}:
            match = re.match(rf'/([a-z]+)/({UUID})(?:/|$)', parts.path.lower())
            if match and match[1] in QUERY_TYPES:
                return QUERY_TYPES[match[1]], match[2]
    return '', query


def name_for_lang(values, lang):
    return next((item[lang].strip() for item in values if isinstance(item, dict)
                 and isinstance(item.get(lang), str) and item[lang].strip()), '')


def lease(http, identity, replace_before=0):
    with _lease_lock:
        issued, urls = _leases.get(identity, (0, ()))
        if urls and issued > replace_before and time.time() < issued + IMAGE_LEASE_SECONDS:
            return issued, urls
    data = request(http, '/at-home/server/' + identity, [('forcePort443', 'true')])
    chapter = data.get('chapter')
    if not isinstance(chapter, dict):
        raise SourceError('MangaDex не предоставил страницы главы.')
    hash_value = chapter.get('hash')
    files = chapter.get('data')
    if (not HASH.fullmatch(str(hash_value)) or not isinstance(files, list) or not 1 <= len(files) <= 500
            or any(not isinstance(file, str) or not FILE.fullmatch(file) for file in files)
            or len(files) != len(set(files))):
        raise SourceError('MangaDex вернул неполный список страниц.')
    base = public_url(data.get('baseUrl', ''), resolve_dns=False).rstrip('/')
    if urlsplit(base).query:
        raise SourceError('MangaDex вернул некорректный сервер страниц.')
    urls = [base + '/data/' + hash_value + '/' + quote(file, safe='') for file in files]
    issued = time.time()
    with _lease_lock:
        _leases.pop(identity, None)
        if len(_leases) >= 128:
            del _leases[next(iter(_leases))]
        _leases[identity] = issued, urls
    return issued, urls


def page_urls(http, identity):
    issued, urls = lease(http, identity)
    return [url + f'#{IMAGE_MARKER}{identity},{index},{int(issued)}' for index, url in enumerate(urls)]


def image_marker(value):
    parts = urlsplit(value)
    match = re.fullmatch(rf'{IMAGE_MARKER}({UUID}),([0-9]{{1,3}}),([0-9]{{10}})', parts.fragment)
    if (not match or int(match[2]) >= 500 or int(match[3]) > time.time() + 1
            or not re.search(rf'/data/{HASH.pattern}/{FILE.pattern}$', parts.path)):
        raise SourceError('Некорректный адрес страницы MangaDex.')
    return (public_url(urlunsplit(parts._replace(fragment='')), resolve_dns=False),
            match[1], int(match[2]), int(match[3]))


def refresh_page(http, target, identity, index, replace_before=0):
    issued, urls = lease(http, identity, replace_before)
    if index >= len(urls) or urlsplit(urls[index]).path.split('/data/')[-1] != urlsplit(target).path.split('/data/')[-1]:
        raise SourceError('MangaDex изменил список страниц. Открой главу повторно.')
    return issued, urls[index]


def open_image(http, value, headers):
    target, identity, index, issued = image_marker(value)
    if time.time() >= issued + IMAGE_LEASE_SECONDS:
        issued, target = refresh_page(http, target, identity, index)
    try:
        return http._open(target, headers=headers)
    except SourceError as error:
        missing = type(error) is SourceError and re.search(r'HTTP (?:404|410)\b', str(error))
        if not missing and not isinstance(error, SourceAccessError):
            raise
        _, renewed = refresh_page(http, target, identity, index, replace_before=issued + 1)
        return http._open(renewed, headers=headers)


class MangaDex:
    ROOT = ROOT
    NAME = 'MangaDex'
    IS_NSFW = False
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, lang):
        self.SOURCE_ID, self.LANGUAGE = sid, lang
        self.lang = API_LANGUAGES.get(lang, lang)

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            parts = urlsplit(raw)
            if (selected not in {None, self.SOURCE_ID} or parts.netloc not in {'mangadex.org', 'www.mangadex.org'}
                    or parts.scheme != 'https'):
                return ''
            query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=8)
            lang = query.get('lang', [])
            if lang and (len(lang) != 1 or self.lang != 'all' and lang[0] not in (self.lang, self.LANGUAGE)):
                return ''
            parent = query.get('manga', [])
            if parent and (len(parent) != 1 or not UUID_PATTERN.fullmatch(parent[0])
                           or not CHAPTER_PATH.fullmatch(parts.path)):
                return ''
            return public_url(ROOT + parts.path + ('?manga=' + parent[0] if parent else ''), resolve_dns=False)
        except (SourceError, ValueError):
            return ''

    def reader_url(self, value):
        upstream = self.site_link(value)
        if not upstream:
            raise SourceError('Некорректная ссылка MangaDex.')
        if self.lang != 'all':
            upstream += ('&' if '?' in upstream else '?') + 'lang=' + self.lang
        return reader_url(upstream, self.SOURCE_ID)

    def language_filter(self, key):
        return [(key, self.lang)] if self.lang != 'all' else []

    def row(self, item):
        identity, a = str(item.get('id', '')), attributes(item)
        aliases = unique(names(a))
        if not UUID_PATTERN.fullmatch(identity) or not aliases:
            raise SourceError('MangaDex не указал ID или название тайтла.')
        translations = [a.get('title', {}), *a.get('altTitles', [])]
        title = name_for_lang(translations, self.lang) or aliases[0]
        original = a.get('originalLanguage')
        media_format = {'ko': 'manhwa', 'zh': 'manhua', 'zh-hk': 'manhua'}.get(original, 'manga')
        cover = next((rel.get('attributes', {}).get('fileName') for rel in relations(item, 'cover_art')
                      if isinstance(rel.get('attributes'), dict)), '')
        descriptions = [a.get('description', {})]
        vocabulary = from_api(a)
        rating = a.get('contentRating')
        target = self.reader_url(ROOT + '/title/' + identity)
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'url': target, 'sourceUrl': target, 'provider': f'suwayomi:{self.SOURCE_ID}',
                'providerName': self.NAME, 'sourceOnly': True, 'kind': 'manga', 'language': self.LANGUAGE,
                'title': title, 'aliases': aliases, 'format': media_format,
                'readingMode': 'scroll' if media_format == 'manhwa' or 'Long Strip' in vocabulary['tags'] else 'pages',
                'year': a.get('year'), 'status': a.get('status') or '', 'age': 18 if rating in CONTENT_RATINGS[2:] else None,
                'adult': rating in CONTENT_RATINGS[2:],
                'authors': labels(relations(item, 'author')), 'artists': labels(relations(item, 'artist')),
                'description': (name_for_lang(descriptions, self.lang) or name_for_lang(descriptions, 'en')
                                or name_for_lang(descriptions, original))[:12000],
                'cover': f'https://uploads.mangadex.org/covers/{identity}/{cover}.256.jpg'
                if isinstance(cover, str) and FILE.fullmatch(cover) else '',
                **vocabulary, 'ids': {'mangadex': identity}}

    def chapter_work(self, item):
        found = related_ids([item], 'manga')
        if len(found) != 1:
            raise SourceError('MangaDex не указал тайтл главы.')
        return found[0]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if (type(page) is not int or not 1 <= page <= MAX_OFFSET // LIMIT
                or not isinstance(query, str) or tag and not UUID_PATTERN.fullmatch(tag)):
            raise SourceError('Некорректные параметры каталога MangaDex.')
        mode, term = source_query(query)
        offset = LIMIT * (page - 1)
        params = [('limit', LIMIT), ('offset', offset), ('includes[]', 'cover_art'),
                  *self.language_filter('availableTranslatedLanguage[]'),
                  *(ALL_RATINGS if sort == 'updated' or tag else PUBLIC_RATINGS)]
        if tag:
            params.append(('includedTags[]', tag))
        if mode == 'ch':
            item = record(request(http, '/chapter/' + term), 'chapter', term)
            mode, term = 'id', self.chapter_work(item)
        if mode == 'id':
            return ([self.work(http, term)], False) if page == 1 else ([], False)
        if mode == 'list':
            result = record(request(http, '/list/' + term), 'custom_list', term)
            ids = related_ids([result], 'manga')
            chunks, more = ids[offset:offset + LIMIT], offset + LIMIT < len(ids)
            return self.works(http, chunks, params=[*params[2:], ('limit', LIMIT)]), more
        if mode == 'usr' or sort == 'latest' and not term and not tag:
            offset = (page - 1) * 100
            if offset >= MAX_OFFSET:
                return [], False
            args = [('limit', 100), ('offset', offset), ('order[publishAt]', 'desc'),
                    ('includeFuturePublishAt', 0), ('includeFutureUpdates', 0), ('includeEmptyPages', 0),
                    *PUBLIC_RATINGS, *self.language_filter('translatedLanguage[]')]
            if mode == 'usr':
                args.append(('uploader', term))
            feed = request(http, '/chapter', args)
            rows = records(feed)
            return self.works(http, related_ids(rows, 'manga'), params=[('includes[]', 'cover_art'), *PUBLIC_RATINGS,
                                                                      ('limit', 100)]), has_more(feed, offset, len(rows), 100)
        if term:
            params.append(({'grp': 'group', 'author': 'authorOrArtist'}.get(mode, 'title'), term[:160]))
        else:
            params.extend([('hasAvailableChapters', 'true'), ('order[updatedAt]' if sort == 'updated'
                                                               else 'order[followedCount]', 'desc')])
        response = request(http, '/manga', params)
        rows = records(response)
        return [self.row(item) for item in rows], has_more(response, offset, len(rows), LIMIT)

    def works(self, http, identities, params):
        if not identities:
            return []
        rows = records(request(http, '/manga', [*params, *(('ids[]', identity) for identity in identities)]))
        found = {row['id']: row for row in rows if row.get('id') in identities}
        return [self.row(found[identity]) for identity in identities if identity in found]

    def vocabulary(self, http):
        result = []
        for item in records(request(http, '/manga/tag')):
            data = attributes(item)
            key = str(item.get('id', ''))
            label = name_for_lang([data.get('name')], self.lang) or name_for_lang([data.get('name')], 'en')
            if UUID_PATTERN.fullmatch(key) and label:
                result.append({'label': label, 'sourceId': key, 'category': 'genre' if data.get('group') == 'genre' else 'tag'})
        return result

    def work(self, http, identity):
        params = [('includes[]', name) for name in ('cover_art', 'author', 'artist')]
        return self.row(record(request(http, '/manga/' + identity, params), 'manga', identity))

    def details(self, http, value):
        title = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not title:
            raise SourceError('Некорректная ссылка на тайтл MangaDex.')
        return self.work(http, title[1])

    def episode(self, row, identity):
        from manga_sources import chapter_number

        a = attributes(row)
        identifier, language = str(row.get('id', '')), a.get('translatedLanguage')
        if (not UUID_PATTERN.fullmatch(identifier) or type(a.get('pages')) is not int or a['pages'] < 1
                or a.get('externalUrl') or not isinstance(language, str) or self.lang not in {'all', language}):
            return None
        number = str(a.get('chapter') or '0')
        try:
            numeric = chapter_number(number)
        except SourceError:
            numeric = 0
        volume = str(a.get('volume') or '')
        published = a.get('publishAt') or a.get('createdAt') or ''
        return {'url': self.reader_url(ROOT + '/chapter/' + identifier + '?manga=' + identity), 'number': numeric,
                'title': (a.get('title') or 'Глава ' + number)[:300], 'language': language,
                'season': max(1, int(volume)) if re.fullmatch(r'[0-9]{1,4}', volume) else 1,
                'translator': ', '.join(labels(relations(row, 'scanlation_group'))),
                'publishedAt': published[:10] if isinstance(published, str) else ''}

    def chapters(self, http, identity):
        params = [('limit', FEED_LIMIT), ('includeExternalUrl', 0), ('includeEmptyPages', 0),
                  ('includeFuturePublishAt', 0), ('order[volume]', 'desc'), ('order[chapter]', 'desc'),
                  ('includes[]', 'scanlation_group'), *ALL_RATINGS, *self.language_filter('translatedLanguage[]')]
        offset, episodes = 0, {}
        while offset < MAX_OFFSET:
            response = request(http, '/manga/' + identity + '/feed', [*params, ('offset', offset)])
            rows = records(response)
            for row in rows:
                if identity in related_ids([row], 'manga'):
                    if chapter := self.episode(row, identity):
                        episodes.setdefault(row['id'], chapter)
            total = response.get('total')
            offset += len(rows)
            if not rows or (type(total) is int and offset >= total) or (type(total) is not int and len(rows) < FEED_LIMIT):
                return list(episodes.values()), type(total) is int and offset < total
        return list(episodes.values()), True

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        chapter, title = CHAPTER_PATH.fullmatch(path), TITLE_PATH.fullmatch(path)
        pages, truncated = [], False
        if chapter:
            item = record(request(http, '/chapter/' + chapter[1], [('includes[]', 'scanlation_group')]), 'chapter', chapter[1])
            identity = self.chapter_work(item)
            expected = parse_qs(urlsplit(target).query).get('manga', [identity])[0]
            if identity != expected:
                raise SourceError('Глава относится к другому тайтлу MangaDex.')
            episode = self.episode(item, identity)
            if episode is None:
                raise SourceError('У MangaDex нет открытых страниц главы на выбранном языке.')
            episodes, pages = [episode], page_urls(http, chapter[1])
        elif title:
            identity = title[1]
            episodes, truncated = self.chapters(http, identity)
        else:
            raise SourceError('Некорректная ссылка на читалку MangaDex.')
        return {**self.work(http, identity), 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': truncated, 'dubs': [], 'releases': [],
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({item['season'] for item in episodes})],
                'translations': unique(item['translator'] for item in episodes)}

    def page_headers(self, value):
        return {'Referer': ROOT + '/', 'User-Agent': DEX_USER_AGENT}

    def saved_title_url(self, value):
        title = TITLE_PATH.fullmatch(urlsplit(value).path)
        return ROOT + '/title/' + title[1] if title else ''

    def saved_chapter_url(self, value, slug, root):
        if not isinstance(value, str):
            return ''
        chapter = CHAPTER_PATH.fullmatch(urlsplit(self.site_link(value, root)).path)
        identity = value if UUID_PATTERN.fullmatch(value) else chapter[1] if chapter else ''
        return ROOT + '/chapter/' + identity + '?manga=' + slug if identity else ''

    def saved_chapter_matches(self, chapter, title):
        work = TITLE_PATH.fullmatch(urlsplit(title).path)[1]
        return parse_qs(urlsplit(chapter).query).get('manga') == [work]


SOURCES = tuple(MangaDex(sid, lang) for sid, lang in (
    ('72800122520214493', 'ur'),
    ('425785191804166217', 'da'),
    ('737986167355114438', 'lt'),
    ('764587568075398530', 'la'),
    ('954368055061084457', 'ne'),
    ('987803387023224960', 'sq'),
    ('1145824452519314725', 'sv'),
    ('1347402746269051958', 'my'),
    ('1411768577036936240', 'ja'),
    ('1424273154577029558', 'he'),
    ('1471784905273036181', 'ms'),
    ('1493666528525752601', 'zh-Hant'),
    ('1553736397938752611', 'eu'),
    ('1573550798452063564', 'jv'),
    ('1713554459881080228', 'th'),
    ('1952071260038453057', 'it'),
    ('2072928884077964642', 'cv'),
    ('2098905203823335614', 'ru'),
    ('2499283573021220255', 'en'),
    ('2655149515337070132', 'pt-BR'),
    ('2819252027406613931', 'eo'),
    ('2838715564514827672', 'uz'),
    ('2875503798326600410', 'sk'),
    ('3260701926561129943', 'el'),
    ('3285208643537017688', 'ko'),
    ('3339599426223341161', 'ar'),
    ('3507378005483435886', 'sr'),
    ('3578612018159256808', 'cs'),
    ('3601180820582582605', 'be'),
    ('3686775439235747344', 'ga'),
    ('3781216447842245147', 'fa'),
    ('3807502156582598786', 'id'),
    ('3846770256925560569', 'tr'),
    ('4150470519566206911', 'bn'),
    ('4273071356706429527', 'ta'),
    ('4284949320785450865', 'hu'),
    ('4505830566611664829', 'fr'),
    ('4638673959522768501', 'af'),
    ('4774459486579224459', 'ro'),
    ('4872213291993424667', 'no'),
    ('4938773340256184018', 'es-419'),
    ('5098537545549490547', 'de'),
    ('5148895169070562838', 'zh-Hans'),
    ('5189216366882819742', 'pt'),
    ('5463447640980279236', 'bg'),
    ('5779037855201976894', 'uk'),
    ('5860541308324630662', 'ca'),
    ('5967745367608513818', 'mn'),
    ('6400665728063187402', 'es'),
    ('6404943692147160087', 'all'),
    ('6750440049024086587', 'nl'),
    ('6840513937945146538', 'hi'),
    ('6886894829142702925', 'te'),
    ('8033579885162383068', 'pl'),
    ('8254121249433835847', 'fi'),
    ('8548374501079910130', 'hr'),
    ('8578871918181236609', 'fil'),
    ('8773024089257004344', 'et'),
    ('8884149958776527952', 'kk'),
    ('8952567078513962586', 'ka'),
    ('9127464796236242233', 'az'),
    ('9194073792736219759', 'vi'),
))
