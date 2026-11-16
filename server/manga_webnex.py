"""Webnex catalogue, alternate releases and public Next.js reader."""

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_additional_catalogues import flight_objects
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Meta, SeriesPort, number, picture
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://webnex.cc'
HOST = 'webnex.cc'
TITLE = rf'/manga/({SEGMENT})/?'
CHAPTER = rf'/read/({SEGMENT})/?'
COOKIE = re.compile(r'"(wnx_(?:series|reader|read))=([a-zA-Z0-9._~%+/=:-]{1,1024})(?:;[^"]*)?"')
IDENTITY = re.compile(rf'/api/(?:image|read|reader|chapters?|pages|chapter-pages)(?:/{SEGMENT}){{0,5}}/?')
QUERY = {'id', 'page', 'token', 'key', 'chapterId', 'chapter', 'v', 'sig', 'expires', 'src', 'i', 'n', 'p'}


def public_api(host, path, query):
    if host != HOST or not IDENTITY.fullmatch(path):
        return False
    try:
        parts = parse_qsl(query, max_num_fields=10)
    except ValueError:
        return False
    return (len(parts) == len(dict(parts)) and all(key in QUERY and len(value) <= 1800 for key, value in parts))


@dataclass(frozen=True)
class WebnexPage:
    cookie: str = ''

    def decode(self, raw):
        return raw


def seed_cookie(http, raw, final):
    if urlsplit(final).netloc != HOST:
        return ''
    match = COOKIE.search(raw)
    if not match:
        return ''
    name, value = match.groups()
    if getattr(http, 'session', None) is not None:
        http.session.cookies.set(name, value, domain=HOST, path='/', secure=True)
    return f'{name}={value}'


def cookie_header(value):
    return isinstance(value, str) and bool(re.fullmatch(r'wnx_(?:series|reader|read)=[a-zA-Z0-9._~%+/=:-]{1,1024}', value))


class Webnex(SeriesPort):
    meta = Meta('h1.series-title', '.series-top-cover img', '.series-desc p',
                '.series-alt-name', '.series-badges a[href*="kind="]', '',
                '.series-credits a[href*="author="], .series-credits a[href*="artist="]',
                '.series-badges li:has(.dot)')

    def __init__(self):
        super().__init__(('319678837350572744', 'Webnex', 'en', ROOT, True),
                         TITLE, CHAPTER, interval=.35)

    def raw_document(self, http, target):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(target, action='webnex-doc')
        if '<title>Opening series</title>' in raw[:4096]:
            if not seed_cookie(http, raw[:4096], final):
                raise SourceError('Webnex не предоставил гостевой допуск к карточке.')
            raw, final, _ = http.document(target, action='webnex-doc')
        if urlsplit(final).netloc != HOST:
            raise SourceError('Webnex перенаправил запрос на другой сайт.')
        return raw, final

    def document(self, http, target):
        raw, final = self.raw_document(http, target)
        self.check_document(raw)
        return BeautifulSoup(raw, 'html.parser'), final

    @staticmethod
    def check_document(raw):
        if '<title>Opening series</title>' in raw[:4096]:
            raise SourceError('Webnex не принял гостевой допуск к карточке.')

    def title_for(self, url):
        slug = param(url, 'mv_wnx_series')
        return ROOT + '/manga/' + slug if re.fullmatch(SEGMENT, slug) else ''

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_title(target):
            return target
        slug = urlsplit(target).path.strip('/')
        return ROOT + '/manga/' + slug if re.fullmatch(SEGMENT, slug) else self.title_for(target)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        slug = urlsplit(target).path.strip('/')
        return ROOT + '/read/' + slug if re.fullmatch(SEGMENT, slug) else ''

    def saved_chapter_matches(self, target, title):
        bound = self.title_for(target)
        return bool(self.is_chapter(target) and (
            self.title_key(bound) == self.title_key(title) if bound else self.confirm_archive_membership(target, title)))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        latest = sort == 'updated' and not query and not tag
        args = {'page': page, 'sort': 'coverage'}
        if query:
            args['q'] = query
        if tag:
            key, _, value = tag.partition(':')
            args[key if key in {'genre', 'tag', 'kind', 'demographic'} and value else 'tag'] = value or tag
        target = query_url(ROOT + '/', latest=page) if latest else query_url(ROOT + '/browse', **args)
        doc, final = self.document(http, target)
        cards = 'section.latest-section li.card-item a.card-link' if latest else 'li.card-item a.card-link'
        rows = []
        for node in doc.select(cards):
            url = self.site_link(node.get('href'), final)
            title = node_text(node.select_one('.card-title'))
            if url and title and self.is_title(url):
                row = self.record(url, title, picture(node.select_one('img.cover-img'), final))
                row['format'] = node_text(node.select_one('.card-kind')).casefold() or row['format']
                rows.append(row)
        return rows, bool(doc.select_one('a[aria-label="Next page"]'))

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        props = next((n for n in flight_objects(str(doc)) if isinstance(n.get('genres'), list)
                      and isinstance(n.get('tags'), list)), {})
        row['genres'] = list(dict.fromkeys([*row['genres'], *(n for n in props.get('genres', []) if isinstance(n, str))]))
        row['tags'] = list(dict.fromkeys(n for n in props.get('tags', []) if isinstance(n, str)))
        row['format'] = node_text(doc.select_one('.series-badges a[href*="kind="]')).casefold() or row['format']
        return row

    def chapter_rows(self, doc, url, title):
        for row in doc.select('li.ch-row:not([aria-hidden="true"]):not([style*="display:none"]):not([style*="display: none"])'):
            main = row.select_one('a.ch-link[href]')
            if not main:
                continue
            label = node_text(main.select_one('.ch-num'))
            name = node_text(main.select_one('.ch-title'))
            time = row.select_one('time.ch-time[datetime]')
            date = time['datetime'][:10] if time else ''
            choices = [(main, row.select_one('.ch-source, .ch-source-name'), date)]
            choices.extend((a, a.select_one('.ch-sources-name'), '') for a in row.select('.ch-sources-menu a.ch-sources-item[href]'))
            for a, group, posted in choices:
                target = self.site_link(a['href'], url)
                if self.is_chapter(target):
                    target = query_url(target, mv_wnx_series=self.title_key(title))
                    yield self.chapter(target, f'Chapter {label}' + (f': {name}' if name else ''), number(label), posted,
                                       translator=node_text(group))

    def chapters(self, http, doc, final):
        count = max((int(node_text(a)) for a in doc.select('.pagination-page a[href$="#chapters"]')
                     if re.fullmatch(r'\d{1,4}', node_text(a))), default=1)
        rows = {row['url']: row for row in self.chapter_rows(doc, final, final)}
        for i in range(2, min(count, 80) + 1):
            page, current = self.document(http, query_url(final, page=i))
            if self.title_key(current) != self.title_key(final):
                raise SourceError('Webnex перенаправил на другое произведение.')
            rows.update((row['url'], row) for row in self.chapter_rows(page, current, final))
        return self.order(rows), count > 80

    def read(self, http, url):
        raw, final = self.raw_document(http, url.split('?', 1)[0])
        self.check_document(raw)
        if self.chapter_key(url) != self.chapter_key(final):
            raise SourceError('Webnex перенаправил на другую главу.')
        cookie = seed_cookie(http, raw, final)
        props = next((n for n in flight_objects(raw) if 'chapter' in n and isinstance(n.get('series'), dict)
                      and isinstance(n.get('pagesUrl'), str)), None)
        if not props:
            raise SourceError('Webnex не предоставил данные выпуска.')
        series = self.site_link(props['series'].get('href', ''), final)
        bound = self.title_for(url)
        if not self.is_title(series) or bound and self.title_key(bound) != self.title_key(series):
            raise SourceError('Глава Webnex относится к другому произведению.')
        endpoint = image_url(props['pagesUrl'], final)
        parts = urlsplit(endpoint)
        if not public_api(parts.netloc, parts.path, parts.query):
            raise SourceError('Некорректный публичный маршрут читалки Webnex.')
        raw, result, _ = http.document(endpoint, headers={'Referer': final}, action='native-series-json')
        if result != endpoint:
            raise SourceError('Webnex перенаправил запрос страниц.')
        urls = [img for page in json.loads(raw)['pages'] if (img := image_url(page, final))]
        refs = []
        for img in urls:
            parts = urlsplit(img)
            refs.append((img, WebnexPage(cookie if public_api(parts.netloc, parts.path, parts.query) else '')))
        return series, remember(refs, final)

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            return super().inspect(value, http)
        title_url, pages = self.read(http, url)
        slug = self.title_key(title_url)
        summary = self.record(title_url, slug.replace('-', ' '))
        return self.reader_result(summary, url, [self.chapter(url, slug)], pages)


SOURCES = (Webnex(),)
