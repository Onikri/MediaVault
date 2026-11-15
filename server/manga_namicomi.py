"""NamiComi catalogue, public chapter access checks and reader."""

import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from manga_dot_nami_http import document, json_data, mapping, records
from manga_dot_nami_profiles import NAMICOMI
from manga_madara import OriginPace, image_url
from manga_source_tags import labels, unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceAccessError, SourceError, public_url


ROOT = 'https://namicomi.com'
API = 'https://api.namicomi.com'
CDN = 'https://uploads.namicomi.com'
ID = r'[A-Za-z0-9_-]{1,96}'
LOCALE = r'[a-z]{2,3}(?:-[a-zA-Z0-9]{2,9})?'
IDENTITY = re.compile(ID)
TITLE_PATH = re.compile(rf'/{LOCALE}/title/({ID})(?:/{ID})?/?')
CHAPTER_PATH = re.compile(rf'/{LOCALE}/chapter/({ID})(?:/{ID})?/?')
FILE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,250}')
TAG_GROUPS = {'content-warnings', 'format', 'genre', 'theme'}
LANGS = {'zh-Hans': 'zh-hans', 'zh-Hant': 'zh-hant', 'pt-BR': 'pt-br', 'pt': 'pt-pt', 'es': 'es-es'}
INCLUDES = [('includes[]', include) for include in ('cover_art', 'organization', 'tag', 'primary_tag', 'secondary_tag')]
TYPES = [('types[]', name) for name in ('manhua', 'manwha', 'manga', 'comic')]
GATE = API + '/gating/check'
LIMIT = 200
CHAPTER_CAP = 6000
PACE = OriginPace()
PACE.interval = 0.35


def public_access_form(url, body):
    if url != GATE or not isinstance(body, bytes) or len(body) > 32_768:
        return False
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return False
    if not isinstance(data, dict) or data.keys() != {'entities'}:
        return False
    rows = data['entities']
    return (isinstance(rows, list) and 1 <= len(rows) <= LIMIT
            and all(isinstance(item, dict) and item.keys() == {'entityId', 'entityType'} and item['entityType'] == 'chapter'
                    and isinstance(item['entityId'], str) and IDENTITY.fullmatch(item['entityId']) for item in rows))


def get(http, path, params=()):
    PACE.wait(http.deadline)
    return mapping(json_data(document(http, API, path, params)))


def regions(item, key):
    data = item.get(key) or {}
    return {lang: title.strip() for lang, title in mapping(data).items() if isinstance(title, str) and title.strip()}


def localize(choices, language):
    return choices.get(language) or choices.get('en') or next(iter(choices.values()), '')


def relationships(row, kinds):
    return [item['attributes'] for item in records(row.get('relationships') or [])
            if item.get('type') in kinds and isinstance(item.get('attributes'), dict)]


def paginated(payload):
    return records(payload.get('data', [])), mapping(payload.get('meta') or {})


def has_more(meta, offset, count):
    if type(meta.get('total')) is not int:
        return False
    return offset + count < meta['total']


def gate(http, ids):
    access = {}
    for i in range(0, len(ids), LIMIT):
        batch = ids[i:i+LIMIT]
        body = json.dumps({'entities': [{'entityId': id_, 'entityType': 'chapter'} for id_ in batch]},
                          separators=(',', ':')).encode()
        PACE.wait(http.deadline)
        reply = json_data(document(http, API, '/gating/check', body=body, action='namicomi-access'))
        decisions = mapping(mapping(mapping(reply).get('data')).get('attributes')).get('map')
        decisions = mapping(decisions)
        if any(type(decisions.get(identity)) is not bool for identity in batch):
            raise SourceError('NamiComi не подтвердил доступ к списку глав.')
        access.update((identity, decisions[identity]) for identity in batch)
    return access


class NamiComi:
    ROOT = ROOT
    NAME = 'NamiComi'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, uid, lang):
        self.SOURCE_ID, self.LANGUAGE = uid, lang
        self.lang = LANGS.get(lang, lang)

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            parts = urlsplit(raw)
            if selected not in (None, self.SOURCE_ID) or parts.scheme != 'https' or parts.netloc != 'namicomi.com':
                return ''
            parent = parse_qs(parts.query, keep_blank_values=True, max_num_fields=6).get('title', [])
            if parent and (len(parent) != 1 or not IDENTITY.fullmatch(parent[0]) or not CHAPTER_PATH.fullmatch(parts.path)):
                return ''
            return public_url(urlunsplit(parts._replace(query=urlencode({'title': parent[0]}) if parent else '')),
                              resolve_dns=False)
        except (ValueError, SourceError):
            return ''

    def title_url(self, identity):
        return ROOT + '/' + self.lang + '/title/' + identity

    def chapter_url(self, identity, parent):
        return ROOT + '/' + self.lang + '/chapter/' + identity + '?title=' + parent

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def row(self, item):
        identity = str(item.get('id', ''))
        data = mapping(item.get('attributes'))
        options = regions(data, 'title')
        title = localize(options, self.lang)
        if not IDENTITY.fullmatch(identity) or not title:
            raise SourceError('NamiComi не указал название или ID тайтла.')
        genres, tags = [], []
        for attr in relationships(item, {'tag', 'primary_tag', 'secondary_tag'}):
            name = regions(attr, 'name')
            category = attr.get('group')
            if category in TAG_GROUPS:
                values = genres if category == 'genre' else tags
                values.extend(unique([localize(name, self.lang), name.get('en')]))
        files = relationships(item, {'cover_art'})
        file = files[0].get('fileName', '') if files else ''
        origin = data.get('originalLanguage', '')
        media_format = str(data.get('type') or '')
        media_format = {'manwha': 'manhwa', 'manhwa': 'manhwa', 'manhua': 'manhua', 'comic': 'comic',
                        'manga': 'manga'}.get(media_format, 'manhwa' if origin == 'ko' else
                                              'manhua' if str(origin).startswith('zh') else 'manga')
        adult = data.get('contentRating') == 'mature'
        url = self.reader_url(self.title_url(identity))
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'url': url, 'sourceUrl': url, 'kind': 'manga', 'language': self.LANGUAGE,
                'title': title[:500], 'aliases': unique([title, *options.values()]), 'format': media_format,
                'cover': CDN + '/covers/' + identity + '/' + file if isinstance(file, str) and FILE.fullmatch(file) else '',
                'description': localize(regions(data, 'description'), self.lang)[:12000],
                'authors': labels(relationships(item, {'organization'})), 'adult': adult, 'age': 18 if adult else None,
                'genres': unique(genres), 'tags': unique(tags), 'status': data.get('publicationStatus') or '',
                'readingMode': 'scroll' if media_format == 'manhwa' or 'Long Strip' in tags else 'pages',
                'sourceOnly': True, 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str):
            raise SourceError('Некорректные параметры каталога NamiComi.')
        if tag and not IDENTITY.fullmatch(tag):
            raise SourceError('Некорректный фильтр NamiComi.')
        offset = (page-1)*20
        order = 'views' if sort == 'popular' and not query and not tag else 'publishedAt'
        args = [('limit', 20), ('offset', offset), (f'order[{order}]', 'desc'),
                ('availableTranslatedLanguages[]', self.lang), *INCLUDES, *TYPES]
        if query := ' '.join(query.split())[:160]:
            args.append(('title', query))
        if tag:
            args.append(('includedTags[]', tag))
        rows, meta = paginated(get(http, '/title/search', args))
        return [self.row(row) for row in rows], bool(rows and has_more(meta, offset, len(rows)))

    def vocabulary(self, http):
        rows, _ = paginated(get(http, '/title/tags'))
        terms = []
        for row in rows:
            key = str(row.get('id', ''))
            data = mapping(row.get('attributes'))
            category = data.get('group')
            name = localize(regions(data, 'name'), self.lang)
            if IDENTITY.fullmatch(key) and category in TAG_GROUPS and name:
                terms.append({'sourceId': key, 'label': name, 'category': 'genre' if category == 'genre' else 'tag'})
        return terms

    def work(self, http, identity):
        row = mapping(get(http, '/title/' + identity, INCLUDES).get('data'))
        detail = self.row(row)
        return detail, row['id']

    def details(self, http, value):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл NamiComi.')
        return self.work(http, match[1])[0]

    def records(self, http, parent, *, chapter=''):
        args = [('titleId', parent), ('includes[]', 'organization'), ('limit', LIMIT),
                ('translatedLanguages[]', self.lang), ('order[volume]', 'desc'), ('order[chapter]', 'desc')]
        offset, cumulative = 0, {}
        while offset < CHAPTER_CAP:
            data, meta = paginated(get(http, '/chapter', [*args, ('offset', offset)]))
            if meta.get('offset', offset) != offset:
                raise SourceError('NamiComi вернул другую страницу оглавления.')
            for row in data:
                identity = str(row.get('id', ''))
                if not IDENTITY.fullmatch(identity):
                    raise SourceError('NamiComi вернул главу без идентификатора.')
                attributes = mapping(row.get('attributes'))
                language = attributes.get('translatedLanguage', attributes.get('language'))
                if language not in (None, self.lang) or attributes.get('titleId', parent) != parent:
                    continue
                if chapter and identity == chapter:
                    return {identity: row}, False
                if not chapter:
                    cumulative.setdefault(identity, row)
            if not data:
                return cumulative, has_more(meta, offset, 0)
            if not has_more(meta, offset, len(data)):
                return cumulative, False
            offset += len(data)
        return cumulative, True

    def episode(self, item, parent):
        from manga_sources import chapter_number

        attr = item['attributes']
        raw = str(attr.get('chapter') or '0')
        try:
            number = chapter_number(raw)
        except SourceError:
            number = 0
        volume = str(attr.get('volume') or '')
        name = ' — '.join(filter(None, ('Глава ' + raw, attr.get('name'))))
        day = attr.get('publishAt')
        return {'url': self.reader_url(self.chapter_url(item['id'], parent)), 'title': name, 'number': number,
                'season': int(volume) if re.fullmatch('[1-9][0-9]{0,2}', volume) else 1, 'language': self.LANGUAGE,
                'translator': ', '.join(labels(relationships(item, {'organization'}))),
                'publishedAt': day[:10] if isinstance(day, str) else ''}

    def pages(self, http, identity):
        try:
            payload = mapping(get(http, '/images/chapter/' + identity, {'newQualities': 'true'}).get('data'))
        except SourceError as error:
            if type(error) is SourceError and 'HTTP 402' in str(error):
                raise SourceAccessError('NamiComi требует доступ к этой главе.') from None
            raise
        cname = payload.get('hash')
        base = image_url(payload.get('baseUrl'), API + '/')
        if not base or urlsplit(base).query or not isinstance(cname, str) or not FILE.fullmatch(cname):
            raise SourceError('NamiComi не предоставил сервер изображений главы.')
        files = [row.get('filename') for row in records(payload.get('source'))]
        if not 1 <= len(files) <= 500 or any(not isinstance(name, str) or not FILE.fullmatch(name) for name in files):
            raise SourceError('NamiComi не предоставил полный список страниц.')
        return [base.rstrip('/') + f'/chapter/{identity}/{cname}/source/' + name for name in files]

    def inspect(self, value, http):
        target = self.site_link(value)
        parts = urlsplit(target)
        title, chapter = TITLE_PATH.fullmatch(parts.path), CHAPTER_PATH.fullmatch(parts.path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку NamiComi.')
        parent = title[1] if title else parse_qs(parts.query).get('title', [''])[0]
        if not parent:
            raise SourceError('Открой главу из оглавления тайтла NamiComi.')
        row, identity = self.work(http, parent)
        items, truncated = self.records(http, identity, chapter=chapter[1] if chapter else '')
        pages = []
        if chapter:
            chapter_id = chapter[1]
            if chapter_id not in items:
                raise SourceError('Глава отсутствует в оглавлении NamiComi на выбранном языке.')
            if not gate(http, [chapter_id])[chapter_id]:
                raise SourceAccessError('NamiComi ограничивает доступ к этой главе.')
            episodes, pages = [self.episode(items[chapter_id], identity)], self.pages(http, chapter_id)
        else:
            accessible = gate(http, list(items))
            episodes = [self.episode(item, identity) for key, item in items.items() if accessible[key]]
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': truncated, 'dubs': [], 'releases': [],
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({entry['season'] for entry in episodes})],
                'translations': unique(entry['translator'] for entry in episodes)}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        item = TITLE_PATH.fullmatch(path)
        identity = item[1] if item else path.strip('/')
        return self.title_url(identity) if IDENTITY.fullmatch(identity) else ''

    def saved_chapter_url(self, value, parent, root):
        if not isinstance(value, str):
            return ''
        item = CHAPTER_PATH.fullmatch(urlsplit(self.site_link(value, root)).path)
        identity = value if IDENTITY.fullmatch(value) else item[1] if item else ''
        return self.chapter_url(identity, parent) if identity else ''

    def saved_chapter_matches(self, chapter, title):
        return parse_qs(urlsplit(chapter).query).get('title') == [TITLE_PATH.fullmatch(urlsplit(title).path)[1]]


SOURCES = tuple(NamiComi(*profile) for profile in NAMICOMI)
