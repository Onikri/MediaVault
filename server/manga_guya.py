"""Native reader for the public Keiyoushi Guya API (Apache-2.0)."""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceError, public_url


TITLE_PATH = re.compile(rf'/reader/series/({SEGMENT})/?')
CHAPTER_PATH = re.compile(rf'/read/manga/({SEGMENT})/([0-9]{{1,7}}(?:-[0-9]{{1,7}})?)/1/?')
NUMBER = re.compile(r'[0-9]{1,7}(?:\.[0-9]{1,7})?')
GROUP = re.compile(r'[A-Za-z0-9_-]{1,64}')
SERIES_API = re.compile(rf'/api/series/{SEGMENT}/')
GROUP_PARAM = 'mv_guya_group'
LEGACY_GROUP = 'mv_guya_scanlator'


def segment(value):
    return isinstance(value, str) and bool(re.fullmatch(SEGMENT, value))


def mapping(value):
    if not isinstance(value, dict):
        raise SourceError('Guya вернул некорректную карточку или группу.')
    return value


def published(value):
    if type(value) is int and 0 < value < 4_102_444_800:
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    return ''


class Guya:
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH

    def __init__(self, sid, name, root, language='en', adult=False, localized=False):
        self.SOURCE_ID, self.NAME, self.ROOT, self.LANGUAGE, self.IS_NSFW = sid, name, root, language, adult
        self.host = urlsplit(root).netloc
        self.scoped_urls = localized

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, url = split_reader_url(urljoin(base or self.ROOT, value))
            parts = urlsplit(url)
            if selected in (None, self.SOURCE_ID) and parts.netloc == self.host:
                return public_url(url, resolve_dns=False)
        except (SourceError, ValueError):
            pass
        return ''

    def reader_url(self, target):
        return reader_url(target, self.SOURCE_ID) if self.scoped_urls else target

    def accepts(self, slug):
        if not self.scoped_urls:
            return True
        suffix = slug[-3:]
        return {'es': '-ES', 'pl': '-PL'}.get(self.LANGUAGE) == suffix if self.LANGUAGE != 'en' else suffix not in {'-ES', '-PL'}

    def get(self, http, path):
        url = self.ROOT + path
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if url != final:
            raise SourceError('Guya перенаправил запрос на другой маршрут.')
        try:
            return mapping(json.loads(raw))
        except (ValueError, RecursionError):
            raise SourceError('Guya вернул страницу вместо данных API.') from None

    def row(self, data, label):
        from manga_sources import title_aliases

        slug = data.get('slug')
        if not segment(slug) or not isinstance(label, str) or not label.strip():
            raise SourceError('Guya не указал название или адрес произведения.')
        url = self.reader_url(self.ROOT + '/reader/series/' + slug + '/')
        description = data.get('description') or ''
        if isinstance(description, str) and '<' in description:
            soup = BeautifulSoup(description, 'html.parser')
            for anchor in soup.select('a'):
                anchor.decompose()
            description = soup.get_text(' ', strip=True)
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID, 'sourceUrl': url,
                'sourceURL': url, 'url': url, 'providerName': self.NAME, 'provider': f'suwayomi:{self.SOURCE_ID}',
                'kind': 'manga', 'language': self.LANGUAGE, 'title': label.strip()[:500], 'aliases': title_aliases(label),
                'cover': image_url(data.get('cover'), self.ROOT + '/'), 'ids': {}, 'sourceOnly': True,
                'description': description[:12000] if isinstance(description, str) else '',
                'authors': unique([data.get('author')]), 'artists': unique([data.get('artist')]),
                'genres': [], 'tags': []}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or page < 1 or not isinstance(query, str) or tag:
            raise SourceError('Некорректные параметры каталога Guya.')
        if page > 1:
            return [], False
        entries = self.get(http, '/api/get_all_series/')
        term = query.strip()
        result = []
        for title, data in entries.items():
            slug = mapping(data).get('slug')
            if not segment(slug) or not self.accepts(slug):
                continue
            matches = term[5:] == slug if term.startswith('slug:') else term.casefold() in title.casefold()
            if matches:
                stamp = data.get('last_updated')
                result.append((stamp if type(stamp) is int else 0, self.row(data, title)))
        if sort == 'updated':
            result.sort(key=lambda entry: entry[0], reverse=True)
        return [row for _, row in result], False

    def vocabulary(self, http):
        return []

    def series(self, http, slug):
        if not segment(slug) or not self.accepts(slug):
            raise SourceError('Guya не распознал выбранное языковое издание.')
        data = self.get(http, '/api/series/' + slug + '/')
        if data.get('slug') != slug:
            raise SourceError('Guya вернул другое произведение.')
        return data

    def details(self, http, value):
        title = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not title:
            raise SourceError('Некорректная ссылка на тайтл Guya.')
        data = self.series(http, title[1])
        return self.row(data, data.get('title'))

    def chapters(self, series, all_groups=False):
        names = mapping(series.get('groups'))
        for raw, item in mapping(series.get('chapters')).items():
            if not NUMBER.fullmatch(raw):
                raise SourceError('Guya вернул неизвестный номер главы.')
            chapter = mapping(item)
            groups = mapping(chapter.get('groups'))
            if not groups or any(not GROUP.fullmatch(key) for key in groups):
                raise SourceError('Guya не указал группу переводчиков главы.')
            order = chapter.get('preferred_sort')
            if order is None:
                order = series.get('preferred_sort')
            keys = list(groups)
            if not all_groups and isinstance(order, list):
                keys = [next((key for key in order if isinstance(key, str) and key in groups), keys[0])]
            release = chapter.get('release_date') or {}
            path = self.ROOT + '/read/manga/' + series['slug'] + '/' + raw.replace('.', '-') + '/1/'
            for group in keys:
                target = self.reader_url(path + '?' + urlencode({GROUP_PARAM: group}))
                yield {'url': target, 'title': raw + ' - ' + (chapter.get('title') or ''), 'number': float(raw),
                       'season': 1, 'language': self.LANGUAGE, 'translator': names.get(group) or group,
                       'publishedAt': published(mapping(release).get(group)), '_group': group}

    def inspect(self, value, http):
        target = self.site_link(value)
        parts = urlsplit(target)
        title, chapter = TITLE_PATH.fullmatch(parts.path), CHAPTER_PATH.fullmatch(parts.path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку Guya.')
        series = self.series(http, (title or chapter)[1])
        row = self.row(series, series.get('title'))
        args = {}
        if chapter:
            try:
                args = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
            except ValueError:
                raise SourceError('Некорректная ссылка на группу переводчиков Guya.') from None
            if any(len(v) != 1 for v in args.values()) or set(args) not in (set(), {GROUP_PARAM}, {LEGACY_GROUP}):
                raise SourceError('Некорректная ссылка на группу переводчиков Guya.')
        entries = sorted(self.chapters(series, all_groups=bool(args)), key=lambda item: item['number'])
        pages = []
        if chapter:
            number = chapter[2].replace('-', '.')
            candidates = [item for item in entries if urlsplit(item['url']).path.rstrip('/') == parts.path.rstrip('/')]
            if GROUP_PARAM in args:
                candidates = [item for item in candidates if item['_group'] == args[GROUP_PARAM][0]]
            elif LEGACY_GROUP in args:
                candidates = [item for item in candidates if item['translator'] == args[LEGACY_GROUP][0]]
                if len(candidates) != 1:
                    raise SourceError('Guya не сопоставил сохранённого переводчика с главой.')
            if not candidates:
                raise SourceError('Guya не нашёл выбранную главу и перевод.')
            entry = candidates[0]
            data = mapping(series['chapters'][number])
            folder = data.get('folder')
            names = mapping(data.get('groups')).get(entry['_group'])
            if not segment(folder) or not isinstance(names, list) or not 0 < len(names) <= 500:
                raise SourceError('Guya не предоставил страницы открытой главы.')
            base = f'{self.ROOT}/media/manga/{series["slug"]}/chapters/{folder}/{entry["_group"]}/'
            for name in names:
                encoded = quote(unquote(name), safe='') if isinstance(name, str) else ''
                if not segment(encoded):
                    raise SourceError('Guya вернул некорректную ссылку на страницу.')
                pages.append(base + encoded)
            entries = [entry]
        public_entries = [{key: value for key, value in entry.items() if key != '_group'} for entry in entries]
        return {**row, 'url': entries[0]['url'] if chapter else row['url'], 'episodes': public_entries, 'pages': pages,
                'available': bool(entries), 'truncated': False, 'seasons': [{'number': 1, 'name': 'Том 1'}] if entries else [],
                'dubs': [], 'releases': [], 'translations': unique(item['translator'] for item in entries)}

    def saved_title_url(self, value):
        path = urlsplit(value).path
        if TITLE_PATH.fullmatch(path):
            return value
        slug = path.strip('/')
        return self.ROOT + '/reader/series/' + slug + '/' if segment(slug) else ''

    def saved_chapter(self, row, root, title):
        slug = TITLE_PATH.fullmatch(urlsplit(title).path)[1]
        stored = (row.get('url') or '').strip('/')
        target = self.site_link(row.get('realUrl'), root)
        if not CHAPTER_PATH.fullmatch(urlsplit(target).path):
            parent, _, number = stored.partition('/')
            if parent != slug or not NUMBER.fullmatch(number):
                return ''
            target = self.ROOT + '/read/manga/' + slug + '/' + number.replace('.', '-') + '/1/'
        group = row.get('scanlator')
        if isinstance(group, str) and 0 < len(group) <= 200:
            target = target.split('?', 1)[0] + '?' + urlencode({LEGACY_GROUP: group})
        return target


SOURCES = (
    Guya('4033172788130537982', 'Magical Translators', 'https://mahoushoujobu.com', localized=True),
    Guya('8666919453546333116', 'Magical Translators', 'https://mahoushoujobu.com', 'es', localized=True),
    Guya('1289819859468493242', 'Magical Translators', 'https://mahoushoujobu.com', 'pl', localized=True),
    Guya('370316150648855996', 'Danke fürs Lesen', 'https://danke.moe', adult=True),
    Guya('4637971935551651734', 'Guya', 'https://guya.cubari.moe'),
    Guya('593241987912872030', 'Hachirumi', 'https://hachirumi.com', adult=True),
)
HOSTS = frozenset(adapter.host for adapter in SOURCES)


def public_api(host, path, query):
    return host in HOSTS and not query and (path == '/api/get_all_series/' or bool(SERIES_API.fullmatch(path)))
