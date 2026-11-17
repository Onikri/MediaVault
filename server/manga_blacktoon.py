"""BlackToon catalogue scripts and changing public mirrors."""

import json
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import image_url, node_text, release_date
from source_parser import SourceError, public_url

ROOT = 'https://blacktoon.me'
ID = r'[\w-]{1,48}'
TITLE = rf'/webtoon/({ID})\.html'
CHAPTER = rf'/webtoons/({ID})/({ID})\.html'
GENRES = dict(zip(map(str, range(1, 21)), ('학원', '액션', 'SF', '스토리', '판타지', 'BL/백합', '개그/코미디',
                  '연애/순정', '드라마', '로맨스', '시대극', '스포츠', '일상', '추리/미스터리',
                  '공포/스릴러', '성인', '옴니버스', '에피소드', '무협', '소년')))


def endpoint(body, field, base):
    match = re.search(rf'\b{field}\s*=\s*["\']([^"\']+)["\']', body)
    if not match:
        raise SourceError('BlackToon изменил адрес выдачи.')
    url = image_url(match[1], base)
    if not url or urlsplit(url).query or urlsplit(url).fragment:
        raise SourceError('BlackToon вернул некорректный адрес.')
    return public_url(url, resolve_dns=False).rstrip('/')


def rows_for(script):
    if '=' not in script:
        raise SourceError('BlackToon не предоставил список.')
    try:
        result = json.loads(script.split('=', 1)[1].strip().removesuffix(';'))
    except ValueError:
        raise SourceError('BlackToon изменил формат списка.') from None
    if not isinstance(result, list):
        raise SourceError('BlackToon изменил формат списка.')
    return [row for row in result if isinstance(row, dict)]


class BlackToon(JsonSeries):
    def __init__(self):
        super().__init__(('7080800841003944426', '블랙툰', 'ko', ROOT, True), TITLE, CHAPTER, interval=.3)
        self.read_lock = Lock()
        self.config_cache = None
        self.catalogue_cache = None

    def get(self, http, url, ref=ROOT + '/'):
        self.origin.wait(getattr(http, 'deadline', None))
        payload, final, _ = http.document(url, headers={'Referer': ref})
        return payload, final

    def config(self, http):
        with self.read_lock:
            if self.config_cache and self.config_cache[0] > monotonic():
                return self.config_cache[1]
            raw, final = self.get(http, ROOT + '/')
            parts = urlsplit(final)
            base = public_url(parts.scheme + '://' + parts.netloc, resolve_dns=False).rstrip('/')
            config, target = self.get(http, base + '/data/config.js', base + '/')
            if urlsplit(target).netloc != parts.netloc:
                raise SourceError('BlackToon перенаправил настройки на другой домен.')
            data = (base, endpoint(raw, 'inc_url1', base), endpoint(raw, 'inc_url2', base),
                    endpoint(config, 'img_domain', base))
            self.config_cache = (monotonic() + 240, data)
            return data

    def table(self, http):
        base, _, webtoon, _ = self.config(http)
        with self.read_lock:
            if self.catalogue_cache and self.catalogue_cache[0] > monotonic() and self.catalogue_cache[1] == webtoon:
                return self.catalogue_cache[2]
            entries = {}
            for index in (0, 1):
                payload, _ = self.get(http, webtoon + f'/webtoon_{index}.js', base + '/')
                for row in rows_for(payload):
                    key = str(row.get('x') or '')
                    if re.fullmatch(ID, key) and isinstance(row.get('t'), str) and row['t'].strip():
                        entries[key] = (row, 'completed' if index == 0 else 'ongoing')
            self.catalogue_cache = (monotonic() + 240, webtoon, entries)
            return entries

    def canonical(self, value):
        target = super().canonical(value)
        if target:
            return target
        if isinstance(value, str):
            try:
                parts = urlsplit(value)
            except ValueError:
                return ''
            host = parts.hostname or ''
            current = urlsplit(self.config_cache[1][0]).hostname if self.config_cache else None
            if parts.scheme in ('http', 'https') and (host == current or re.fullmatch(r'(?:www\.)?blacktoon\d*\.[a-z]{2,8}', host)):
                return super().canonical(ROOT + parts.path)
        return ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return ROOT + f'/webtoon/{key}.html' if re.fullmatch(ID, key) else self.title_for(url)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + f'/webtoon/{key}.html' if key else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        path = urlsplit(url).path.strip('/').split('/')
        if len(path) == 2 and path[0] == self.title_key(title) and re.fullmatch(ID, path[1]):
            return ROOT + '/webtoons/' + '/'.join(path) + '.html'
        return ''

    def row_for(self, key, data, status, cdn, *, description='', cover=''):
        target = ROOT + f'/webtoon/{key}.html'
        poster = str(data.get('p') or '').replace('_x4', '').replace('_x3', '')
        genres = [GENRES[g] for g in str(data.get('tag') or '').split(',') if g in GENRES]
        return self.record(target, data['t'], cover or picture(cdn, poster), genres=genres,
                           authors=[str(data.get('au') or '')], description=description, status=status)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        entries = self.table(http)
        cdn = self.config(http)[3]
        terms = [(key, data, status) for key, (data, status) in entries.items()
                 if (not query or query in data['t'].casefold() or query in str(data.get('au', '')).casefold())
                 and (tag not in GENRES or tag in str(data.get('tag', '')).split(','))]
        field = 'g' if sort == 'updated' else 'h'
        terms.sort(key=lambda row: int(row[1][field]) if str(row[1].get(field, '')).isdigit() else 0, reverse=True)
        offset = (page - 1) * 24
        return [self.row_for(key, data, status, cdn) for key, data, status in terms[offset:offset + 24]], offset + 24 < len(terms)

    def vocabulary(self, http):
        return [{'key': key, 'label': name, 'kind': 'genre'} for key, name in GENRES.items()]

    def mirror_document(self, http, base, path):
        raw, final = self.get(http, base + path, base + '/')
        if urlsplit(final).netloc != urlsplit(base).netloc or urlsplit(final).path != path:
            raise SourceError('BlackToon перенаправил на другую страницу.')
        return BeautifulSoup(raw, 'html.parser')

    def series(self, http, url):
        key = self.title_key(url)
        base, lists, _, cdn = self.config(http)
        doc = self.mirror_document(http, base, urlsplit(url).path)
        data, status = self.table(http).get(key, ({'t': node_text(doc.select_one('h1, h2'))}, ''))
        if not data['t']:
            raise SourceError('BlackToon не вернул карточку.')
        summary = doc.select('p.mt-2')
        thumb = doc.select_one('img.thumb2[o_src]')
        row = self.row_for(key, data, status, cdn, description=node_text(summary[-1]) if summary else '',
                           cover=picture(cdn, thumb.get('o_src')) if thumb else '')
        raw, _ = self.get(http, lists + f'/data/toonlist/{key}.js', base + '/')
        chapters = {}
        for entry in reversed(rows_for(raw)):
            identifier = str(entry.get('id') or '')
            if re.fullmatch(ID, identifier):
                target = ROOT + f'/webtoons/{key}/{identifier}.html'
                chapters[target] = self.chapter(target, str(entry.get('t') or ''),
                                                date=release_date(str(entry.get('d') or '').split(' ', 1)[0], '%Y-%m-%d'))
        return row, self.order(chapters)

    def pages(self, http, url):
        base, _, _, cdn = self.config(http)
        doc = self.mirror_document(http, base, urlsplit(url).path)
        return [image for node in doc.select('#toon_content_imgs img[o_src]')
                if (image := picture(cdn, node.get('o_src')))]


def picture(cdn, key):
    return image_url(cdn + '/' + key.lstrip('/'), cdn) if isinstance(key, str) and key else ''


SOURCES = (BlackToon(),)
