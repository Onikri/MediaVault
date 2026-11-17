"""Mokuro catalogue and ordered HTTP Range access to volumes."""

import re
from time import monotonic
from threading import Lock
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from manga_direct_payloads import JsonSeries, segment, strings
from manga_public_zip import download_refs
from manga_rayuba import uploaded
from manga_series_port import number
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://mokuro.moe'
API = ROOT + '/catalog/api'
SEGMENT = r'[^/\s?#]{1,180}'
TITLE = r'/(catalog)/?'
CHAPTER = rf'/mokuro-reader/({SEGMENT})/({SEGMENT})\.cbz'


def public_api(host, path, query):
    if host != 'mokuro.moe':
        return False
    if path == '/catalog/api/cover':
        args = parse_qsl(query)
        return (len(args) == 1 and args[0][0] == 'path' and 0 < len(args[0][1]) <= 600
                and not re.search(r'(?:^|/|\\)\.\.(?:/|\\|$)|://|[\x00-\x1f]', args[0][1]))
    return not query and (path in ('/catalog/api/library', '/mokuro-reader/catalog.json')
                          or bool(re.fullmatch(rf'/mokuro-reader/{SEGMENT}/(?:series\.json|{SEGMENT}\.mokuro)', path)))


class Mokuro(JsonSeries):
    def __init__(self):
        super().__init__(('3707487231227345638', 'Mokuro', 'ja', ROOT, True), TITLE, CHAPTER,
                         hosts=('www.mokuro.moe',), interval=.3)
        self.lock = Lock()
        self.public_cache = None

    def title_url(self, name):
        return query_url(ROOT + '/catalog', mv_series=name)

    def title_key(self, url):
        parts = urlsplit(url)
        if self.TITLE_PATH.fullmatch(parts.path):
            return param(url, 'mv_series') or unquote(parts.fragment)
        return ''

    def is_title(self, url):
        return super().is_title(url) and bool(segment(self.title_key(url)))

    def chapter_key(self, url):
        return unquote(super().chapter_key(url))

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.title_url(key) if key else ''

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_title(target):
            return self.title_url(self.title_key(target))
        key = unquote(urlsplit(target).path.strip('/'))
        return self.title_url(key) if segment(key) else ''

    def volume_url(self, key, volume):
        path, title = segment(key), segment(volume)
        return ROOT + f'/mokuro-reader/{path}/{title}.cbz' if path and title else ''

    def saved_chapter(self, row, root, title):
        raw = row.get('realUrl') or row.get('url') or ''
        target = self.canonical(raw)
        reader = urlsplit(raw)
        if reader.netloc == 'reader.mokuro.app' and reader.fragment.startswith('/upload?'):
            target = self.site_link(param(ROOT + '/?' + reader.fragment.split('?', 1)[1], 'cbz'))
        if self.is_chapter(target):
            return target if self.saved_chapter_matches(target, title) else ''
        key, sep, volume = unquote(raw.lstrip('/')).partition('|')
        return self.volume_url(key, volume) if sep and key == self.title_key(title) else ''

    def listing(self, http):
        with self.lock:
            if self.public_cache and self.public_cache[0] > monotonic():
                return self.public_cache[1:]
            payload = self.json(http, ROOT + '/mokuro-reader/catalog.json')
            rows = {}
            for item in payload.get('series') or []:
                if isinstance(item, dict) and segment(name := item.get('series_title')):
                    rows[name] = item
            available = self.json(http, API + '/library')
            covers = {}
            for row in available.get('series') or []:
                if isinstance(row, dict) and isinstance(row.get('name'), str) and isinstance(row.get('cover'), str):
                    path = row['cover']
                    url = query_url(API + '/cover', path=path)
                    if public_api('mokuro.moe', '/catalog/api/cover', urlsplit(url).query):
                        covers.setdefault(row['name'].casefold(), url)
            self.public_cache = (monotonic() + 300, rows, covers)
            return rows, covers

    def row_for(self, key, data, covers):
        titles = data.get('titles') or {}
        names = [titles.get(lang) for lang in ('native', 'romaji', 'english') if titles.get(lang)]
        quality = str(data.get('tag') or '').strip()
        label = str(names[0] if names else key)
        if quality:
            label += ' (' + quality.strip('()[]（）【】') + ')'
        return self.record(self.title_url(key), label, covers.get(key.casefold(), ''),
                           aliases=[key, *names, *strings(data.get('synonyms'))], tags=[quality])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        data, covers = self.listing(http)
        ordered = data.items()
        if sort == 'updated':
            ordered = sorted(ordered, key=lambda item: str(item[1].get('updated_at') or ''), reverse=True)
        rows = []
        for key, item in ordered:
            row = self.row_for(key, item, covers)
            if (not query or any(query in text.casefold() for text in (row['title'], *row['aliases']))) and (
                    not tag or any(tag.casefold() in text.casefold() for text in row['tags'])):
                rows.append(row)
        return rows, False

    def vocabulary(self, http):
        data, _ = self.listing(http)
        labels = {str(row.get('tag') or '').strip() for row in data.values()} - {''}
        return [{'key': tag, 'label': tag, 'kind': 'tag'} for tag in sorted(labels)]

    def series(self, http, url):
        key = self.title_key(url)
        rows, covers = self.listing(http)
        details = self.json(http, ROOT + '/mokuro-reader/' + quote(key, safe='') + '/series.json')
        if details.get('series_title') != key:
            raise SourceError('Mokuro вернул список другого произведения.')
        data = rows.get(key, details)
        episodes = {}
        for item in reversed(details.get('volumes') or []):
            if not isinstance(item, dict) or not (target := self.volume_url(key, item.get('volume_title'))):
                continue
            name = item['volume_title']
            numbers = re.findall(r'\d+(?:\.\d+)?', name)
            n = number(numbers[-1]) if numbers else None
            episodes[target] = self.chapter(target, name, n, uploaded(item.get('mokuro_modified')))
        return self.row_for(key, data, covers), self.order(episodes)

    def pages(self, http, url):
        archive = self.site_link(url).split('?', 1)[0]
        manifest = self.json(http, archive.removesuffix('.cbz') + '.mokuro', self.title_for(url))
        names = [item.get('img_path') for item in manifest.get('pages') or [] if isinstance(item, dict)]
        if not 1 <= len(names) <= 1500 or not all(isinstance(name, str) and 0 < len(name) <= 600 for name in names):
            raise SourceError('Mokuro не предоставил полный порядок страниц тома.')
        return download_refs(http, archive, self.title_for(url), order=names)


SOURCES = (Mokuro(),)
