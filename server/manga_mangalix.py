"""MangaLix static catalogue literals and ordered chapter manifests."""

from datetime import date
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit, urlunsplit

from manga_direct_payloads import JsonSeries, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import number
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://mangalix.com'
TITLE = rf'/manga/({SEGMENT})/?'
ORDINAL = r'\d{1,9}(?:\.\d{1,6})?'
CHAPTER = rf'/manga/({SEGMENT})/chapter/({ORDINAL})/?'
ASSET = re.compile(r'/assets/manga-data-[A-Za-z0-9_-]{3,64}\.js')
START = re.compile(r'\[\s*\{\s*id\s*:')
TOKEN = re.compile(r"""\s*(?:(?P<punct>[{}\[\],:])|(?P<key>[a-zA-Z_$][\w$]*)|
        (?P<number>[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)|
        (?P<string>"(?:[^"\\]|\\[\s\S])*"|'(?:[^'\\]|\\[\s\S])*'|`(?:[^`\\$]|\$(?!\{)|\\[\s\S])*`))""", re.X)
ESCAPE = re.compile(r'\\(?:u\{([a-fA-F\d]{1,6})\}|u([a-fA-F\d]{4})|x([a-fA-F\d]{2})|(\r\n|[\s\S]))')
STATES = {'ongoing': 'ongoing', 'publishing': 'ongoing', 'releasing': 'ongoing', 'active': 'ongoing',
          'completed': 'completed', 'complete': 'completed', 'finished': 'completed', 'hiatus': 'hiatus',
          'paused': 'hiatus', 'on hiatus': 'hiatus', 'dropped': 'cancelled', 'axed': 'cancelled',
          'canceled': 'cancelled', 'cancelled': 'cancelled', 'discontinued': 'cancelled'}
CDNS = {'$TEMP': 'https://temp.compsci88.com', '$HOT': 'https://scans-hot.planeptune.us',
        '$LST': 'https://scans.lastation.us', '$LOW': 'https://official.lowee.us',
        '$MFK': 'https://images.mangafreak.me', '/cdn-readmanga/': 'https://cdn.readmanga.cc/'}


def public_api(host, path, query):
    return host == 'mangalix.com' and not query and bool(re.fullmatch(rf'/chapters/{SEGMENT}\.json', path))


def quoted(value):
    def character(match):
        code = match[1] or match[2] or match[3]
        if code:
            return chr(int(code, 16))
        char = match[4]
        return {'n': '\n', 'r': '\r', 't': '\t', 'v': '\v', 'b': '\b', 'f': '\f', '0': '\0',
                '\n': '', '\r': '', '\r\n': ''}.get(char, char)

    raw = ESCAPE.sub(character, value[1:-1])
    return raw.encode('utf-16-le', 'surrogatepass').decode('utf-16-le')


class LiteralReader:
    def __init__(self, raw, pos):
        self.raw, self.pos = raw, pos
        self.count = 0

    def take(self):
        token = TOKEN.match(self.raw, self.pos)
        self.count += 1
        if not token or self.count > 800_000:
            raise ValueError('Invalid catalogue literal')
        self.pos = token.end()
        return token.lastgroup, token[token.lastgroup]

    def value(self, token=None, depth=0):
        group, raw = token or self.take()
        if depth > 48:
            raise ValueError('Invalid nesting')
        if group == 'string':
            return quoted(raw)
        if group == 'number':
            return float(raw) if '.' in raw or 'e' in raw.casefold() else int(raw)
        if group == 'key' and raw in ('true', 'false', 'null', 'undefined'):
            return {'true': True, 'false': False, 'null': None, 'undefined': None}[raw]
        if group == 'key' and raw == 'void' and self.take() == ('number', '0'):
            return None
        if group != 'punct' or raw not in ('[', '{'):
            raise ValueError('Invalid literal')
        is_list = raw == '['
        end = ('punct', ']' if is_list else '}')
        result = [] if is_list else {}
        item = self.take()
        while item != end:
            if is_list:
                result.append(self.value(item, depth + 1))
            else:
                kind, key = item
                if kind not in ('string', 'key') or self.take() != ('punct', ':'):
                    raise ValueError('Invalid object entry')
                result[quoted(key) if kind == 'string' else key] = self.value(depth=depth + 1)
            item = self.take()
            if item != end:
                if item != ('punct', ','):
                    raise ValueError('Invalid separator')
                item = self.take()
        return result


def parse_catalogue(raw):
    for index, match in enumerate(START.finditer(raw)):
        if index == 25:
            break
        try:
            rows = LiteralReader(raw, match.start()).value()
        except (ValueError, OverflowError, RecursionError):
            continue
        if rows and all(isinstance(row, dict) and isinstance(row.get('slug'), str)
                        and isinstance(row.get('title'), str) for row in rows):
            return rows
    raise SourceError('MangaLix не предоставил статический каталог.')


class MangaLix(JsonSeries):
    def __init__(self):
        super().__init__(('2280035516075993115', 'MangaLix', 'en', ROOT, True), TITLE, CHAPTER, interval=.35)
        self.guard = Lock()
        self.cache = (0., {})

    def listing(self, http):
        with self.guard:
            if self.cache[0] > monotonic():
                return self.cache[1]
            doc, final = self.document(http, ROOT + '/')
            asset = next((url for link in doc.select('link[rel="modulepreload"][href]')
                          if (url := self.site_link(link['href'], final)) and ASSET.fullmatch(urlsplit(url).path)), '')
            if not asset:
                raise SourceError('MangaLix не предоставил адрес каталога.')
            text, final, _ = http.document(asset, headers={'Referer': ROOT + '/'})
            if asset != final:
                raise SourceError('MangaLix перенаправил каталог.')
            rows = {row['slug']: row for row in parse_catalogue(text) if re.fullmatch(SEGMENT, row['slug'])}
            self.cache = (monotonic() + 180, rows)
            return rows

    def title_for(self, url):
        return ROOT + '/manga/' + self.chapter_key(url)

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/manga/' + key if re.fullmatch(SEGMENT, key) else url if self.is_title(url) else self.title_for(url)

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return (match[1], match[2], param(url, 'mv_lix_chapter')) if match else ('', '', '')

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        key = urlsplit(url).path.strip('/')
        if not re.fullmatch(SEGMENT, key) or not self.is_title(title):
            return ''
        from source_parser import PublicHttp

        http = PublicHttp(timeout=(3, 6))
        try:
            options = [self.site_link(row['url']) for row in self.series(http, title)[1] if param(row['url'], 'mv_lix_chapter') == key]
            return options[0] if len(options) == 1 else ''
        finally:
            http.close()

    def row_for(self, key, data):
        url = ROOT + '/manga/' + key
        state = ' '.join(str(data.get('status') or '').casefold().replace('-', ' ').split())
        row = self.record(url, data['title'], image_url(data.get('coverImage'), url),
                          description=str(data.get('description') or ''), authors=[data.get('author') or ''],
                          genres=strings(data.get('genres')), status=STATES.get(state, ''))
        if type(data.get('releaseYear')) is int and 1800 <= data['releaseYear'] <= date.today().year + 1:
            row['year'] = data['releaseYear']
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        rows = self.listing(http).items()
        if sort == 'updated':
            rows = sorted(rows, key=lambda item: str((item[1].get('latestChapter') or {}).get('releaseDate') or ''), reverse=True)
        terms = query.casefold().split()
        found = []
        for key, item in rows:
            haystack = ' '.join((item['title'], str(item.get('author') or ''), key)).casefold()
            if all(term in haystack for term in terms) and (not tag or tag.casefold() in {x.casefold() for x in strings(item.get('genres'))}):
                found.append(self.row_for(key, item))
        return found, False

    def vocabulary(self, http):
        labels = {tag for entry in self.listing(http).values() for tag in strings(entry.get('genres'))}
        return [{'key': tag, 'label': tag, 'kind': 'genre'} for tag in sorted(labels)]

    def chapter_list(self, http, key):
        data = self.json(http, ROOT + '/chapters/' + key + '.json')
        if not isinstance(data, list):
            raise SourceError('MangaLix вернул неизвестный формат оглавления.')
        return [entry for entry in data if isinstance(entry, dict)]

    def series(self, http, url):
        url = self.canonical(url)
        key = self.title_key(url)
        data = self.listing(http).get(key)
        if not data:
            raise SourceError('MangaLix не нашёл тайтл в каталоге.')
        chapters = {}
        for item in self.chapter_list(http, key):
            n = number(item.get('number'))
            ordinal = str(item.get('number', '')).removesuffix('.0')
            identity = str(item.get('id') or '')
            if not re.fullmatch(SEGMENT, identity) or not re.fullmatch(ORDINAL, ordinal) or n is None:
                continue
            target = query_url(url.rstrip('/') + '/chapter/' + ordinal, mv_lix_chapter=identity)
            name = str(item.get('title') or f'Chapter {n:g}')
            stamp = str(item.get('releaseDate') or '').partition('T')[0]
            chapters[target] = self.chapter(target, name, n, stamp)
        return self.row_for(key, data), self.order(chapters)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not param(url, 'mv_lix_chapter'):
            key, ordinal, _ = self.chapter_identity(url)
            entries = [item for item in self.chapter_list(http, key) if number(item.get('number')) == number(ordinal)]
            if len(entries) == 1 and re.fullmatch(SEGMENT, cid := str(entries[0].get('id') or '')):
                url = query_url(url, mv_lix_chapter=cid)
        return super().inspect(url, http)

    def pages(self, http, url):
        key, ordinal, chapter = self.chapter_identity(url)
        entry = next((item for item in self.chapter_list(http, key)
                      if str(item.get('id')) == chapter and number(item.get('number')) == number(ordinal)), {})
        pages = []
        for path in strings(entry.get('pages')):
            prefix = next((prefix for prefix in CDNS if path.startswith(prefix)), '')
            raw = CDNS[prefix] + path[len(prefix):] if prefix else path
            if target := image_url(raw, ROOT + '/'):
                pages.append(target)
        return pages


SOURCES = (MangaLix(),)
