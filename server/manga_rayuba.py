"""War For Rayuba's public GitHub catalogue and delegated Cubari pages."""

import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from manga_madara import SEGMENT, image_url
from manga_series_port import MAX_PAGES, SeriesPort, number
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://raw.githubusercontent.com'
API = 'https://api.github.com/repos/xrabohrok/WarMap/contents/tools'
CUBARI = 'https://cubari.moe'
JSON_FILE = rf'/xrabohrok/WarMap/(?:{SEGMENT}/){{1,3}}tools/({SEGMENT}\.json)'
CUBARI_CHAPTER = rf'/(?:proxy|read)/api/({SEGMENT})/chapter/{SEGMENT}(?:/{SEGMENT}){{0,2}}/?'


def public_api(host, path, query):
    if host == 'api.github.com':
        return not query and path == '/repos/xrabohrok/WarMap/contents/tools'
    if host != 'cubari.moe' or not re.fullmatch(CUBARI_CHAPTER, path):
        return False
    fields = parse_qsl(query, keep_blank_values=True)
    if not query:
        return True
    return (len(fields) == 1 and fields[0][0] == 'mv_rayuba_title'
            and bool(re.fullmatch(JSON_FILE, fields[0][1])))


def uploaded(value):
    if type(value) not in (int, float):
        return ''
    if value > 5_000_000_000:
        value /= 1000
    if not 0 < value < 5_000_000_000:
        return ''
    return datetime.fromtimestamp(value, timezone.utc).date().isoformat()


class WarForRayuba(SeriesPort):
    def __init__(self):
        super().__init__(('9161629559428486377', 'War For Rayuba', 'en', ROOT, False),
                         JSON_FILE, CUBARI_CHAPTER, hosts=('cubari.moe', 'xrabohrok.github.io'), interval=.35)

    def is_title(self, url):
        return urlsplit(url).netloc == 'raw.githubusercontent.com' and super().is_title(url)

    def is_chapter(self, url):
        return urlsplit(url).netloc == 'cubari.moe' and super().is_chapter(url)

    def title_for(self, url):
        key = param(url, 'mv_rayuba_title')
        title = ROOT + key if key.startswith('/xrabohrok/WarMap/') else ''
        return title if self.is_title(title) else ''

    def request(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url)
        if url != final:
            raise SourceError('War For Rayuba перенаправил запрос на другой адрес.')
        return json.loads(raw)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        result = []
        for item in self.request(http, API):
            target = self.canonical(item.get('download_url'))
            name = item.get('name', '')
            if self.is_title(target) and name.endswith('.json') and query in name.casefold():
                result.append(self.record(target, name.removesuffix('.json').replace('-', ' ')))
        return result, False

    def series(self, http, url):
        item = self.request(http, url)
        name = item.get('title')
        if not isinstance(name, str) or not name.strip():
            raise SourceError('War For Rayuba не предоставил опубликованный раунд.')
        row = self.record(url, name, image_url(item.get('cover'), url), description=item.get('description') or '',
                          authors=[item.get('artist'), item.get('author')])
        row['format'] = 'comic'
        entries = {}
        for key, chapter in (item.get('chapters') or {}).items():
            target = self.site_link((chapter.get('groups') or {}).get('primary'), CUBARI + '/')
            if not self.is_chapter(target):
                continue
            target = query_url(target, mv_rayuba_title=urlsplit(url).path)
            entry = self.chapter(target, str(chapter.get('title') or key), number(key), uploaded(chapter.get('last_updated')),
                                 season=int(number(chapter.get('volume')) or 1))
            entries[target] = entry
        return row, self.order(entries)

    def details(self, http, url):
        value = self.canonical(url)
        if not self.is_title(value):
            value = self.title_for(value)
        if not self.is_title(value):
            raise SourceError('Некорректная ссылка War For Rayuba.')
        return self.series(http, value)[0]

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target):
            return False
        bound = self.title_for(target)
        return self.title_key(bound) == self.title_key(title) if bound else self.confirm_membership(target, title)

    def confirm_membership(self, target, title):
        from source_parser import PublicHttp

        http = PublicHttp(timeout=(3, 6))
        try:
            _, rows = self.series(http, title)
            return any(self.chapter_identity(self.site_link(row['url'])) == self.chapter_identity(target) for row in rows)
        finally:
            http.close()

    def pages(self, http, url):
        target = url.split('?', 1)[0]
        if not public_api('cubari.moe', urlsplit(target).path, ''):
            raise SourceError('Некорректный маршрут выпуска War For Rayuba.')
        return [src for item in self.request(http, target) if isinstance(item, dict) and (src := image_url(item.get('src'), target))]

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_title(url):
            row, chapters = self.series(http, url)
            return self.reader_result(row, url, chapters, [])
        if not self.is_chapter(url):
            raise SourceError('Некорректная ссылка War For Rayuba.')
        title = self.title_for(url)
        pages = self.pages(http, url)
        if not 1 <= len(pages) <= MAX_PAGES:
            raise SourceError('War For Rayuba не предоставил страницы.')
        if title:
            row, chapters = self.series(http, title)
            chapters = [entry for entry in chapters if self.chapter_identity(self.site_link(entry['url']))
                        == self.chapter_identity(url)]
            if not chapters:
                raise SourceError('Выпуск не входит в указанный раунд War For Rayuba.')
        else:
            row, chapters = self.record(url, 'War For Rayuba'), [self.chapter(url)]
        return self.reader_result(row, url, chapters, pages)


SOURCES = (WarForRayuba(),)
