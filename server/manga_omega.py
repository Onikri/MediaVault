"""Manga Omega WordPress post index shared by its EN and ES sources."""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import unescape
from threading import Lock
from unicodedata import normalize
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT
from manga_series_port import SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceError, SourceTemporaryError

ROOT = 'https://mangaomega.com'
POSTS = ROOT + '/wp-json/wp/v2/posts'
FIELDS = 'id,slug,title,date_gmt,categories,content'
PART = re.compile(r'parte?\s*(\d+)', re.I)
NUMBER = re.compile(r'\d+(?:\.\d+)?')
TRAILING = re.compile(r'\s+(?:chapter\s+)?(\d+(?:\.\d+)?)(?:\s+(?:english|español))?$', re.I)
GUARD = Lock()
CACHE = {}
SYNCED = None


def title_key(title):
    return re.sub('[^a-z0-9]', '', normalize('NFD', title.lower()))


def parse_post(row):
    raw = unescape(row['title']['rendered']).strip()
    lower = raw.lower()
    categories = row.get('categories', [])
    lang = 'es' if 'español' in lower else 'en' if 'english' in lower or 5 in categories else 'es' if 6 in categories else ''
    prefix, _, bracket = raw.partition('【')
    prefix = prefix.strip()
    if match := NUMBER.search(bracket):
        ordinal = match[0]
        name = prefix.removesuffix(' ' + ordinal)
    elif match := TRAILING.search(prefix):
        ordinal = match[1]
        name = prefix[:match.start()]
    else:
        return None
    name = re.sub(r'(?:\s+(?:chapter|english|español))+$', '', name, flags=re.I).strip()
    key, slug = title_key(name), row['slug']
    if not lang or not key or not re.fullmatch(SEGMENT, slug):
        return None
    doc = BeautifulSoup(row['content']['rendered'], 'html.parser')
    part = PART.search(bracket)
    part = int(part[1]) if part else 0
    return {'id': row['id'], 'key': key, 'name': name, 'language': lang, 'slug': slug, 'ordinal': ordinal,
            'part': part, 'number': float(ordinal) + ((part - 1) / part if part else 0),
            'date': row['date_gmt'], 'cover': picture(doc.select_one('img.alignleft'), ROOT),
            'readable': doc.select_one('img:not(.alignleft)') is not None}


class MangaOmega(SeriesPort):
    def __init__(self, identity, language):
        super().__init__((identity, 'Manga Omega', language, ROOT, False), r'(/)', rf'/({SEGMENT})/?', interval=.28)

    def is_title(self, url):
        return self.title_key(url) != ''

    def title_key(self, url):
        parts = urlsplit(url)
        if parts.path != '/':
            return ''
        return title_key(param(url, 's'))

    def title_for(self, url):
        title = param(url, 'mv_omega_title')
        return query_url(ROOT + '/', s=title) if title_key(title) else ''

    def is_chapter(self, url):
        return super().is_chapter(url) and urlsplit(url).path.strip('/') not in {'wp-admin', 'wp-json', 'feed'}

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_title(target) or self.is_chapter(target):
            return target
        return ''

    def request(self, http, target):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, headers = http.document(target, headers={'Referer': ROOT + '/'})
        if target != final:
            raise SourceError('Manga Omega перенаправил API WordPress.')
        return json.loads(raw), headers

    def posts(self, http):
        global SYNCED, CACHE
        now = datetime.now(timezone.utc)
        # Queries can use the last complete snapshot while another request refreshes it.
        if not GUARD.acquire(blocking=False):
            if SYNCED is not None:
                return CACHE
            raise SourceTemporaryError('Первичная индексация Manga Omega ещё идёт.')
        try:
            if SYNCED is not None and now - SYNCED < timedelta(minutes=10):
                return CACHE
            params = {'per_page': 100, 'orderby': 'id', 'order': 'asc', '_fields': FIELDS}
            if SYNCED is not None:
                params['modified_after'] = (SYNCED - timedelta(days=1)).isoformat(timespec='seconds')
            raw, headers = self.request(http, query_url(POSTS, **params, page=1))
            pages = int(next((v for k, v in headers.items() if k.lower() == 'x-wp-totalpages'), 1))
            if not isinstance(raw, list) or not 0 <= pages <= 500:
                raise SourceError('Manga Omega не предоставил полный каталог.')
            updated = CACHE.copy()
            for page in range(1, pages + 1):
                batch = raw if page == 1 else self.request(http, query_url(POSTS, **params, page=page))[0]
                if not isinstance(batch, list):
                    raise SourceError('Manga Omega вернул ошибку при синхронизации каталога.')
                for post in batch:
                    cid = post.get('id') if isinstance(post, dict) else None
                    if type(cid) is not int or cid < 1:
                        continue
                    if entry := parse_post(post):
                        updated[cid] = entry
                    else:
                        updated.pop(cid, None)
            CACHE, SYNCED = updated, now
            return CACHE
        except (SourceError, ValueError, TypeError, KeyError):
            if SYNCED is None:
                raise
            return CACHE
        finally:
            GUARD.release()

    def grouped(self, http):
        grouped = defaultdict(list)
        for row in self.posts(http).values():
            if row['language'] == self.LANGUAGE:
                grouped[row['key']].append(row)
        return {key: sorted(rows, key=lambda p: p['date'], reverse=True) for key, rows in grouped.items()
                if any(p['readable'] for p in rows)}

    def summary(self, rows):
        title = rows[0]['name']
        return self.record(query_url(ROOT + '/', s=title), title, next((p['cover'] for p in rows if p['cover']), ''))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = title_key(self.catalogue_params(page, query, tag))
        rows = [r for k, r in self.grouped(http).items() if query in k]
        rows.sort(key=(lambda p: p[0]['date']) if sort == 'updated' else (lambda p: len(p)), reverse=True)
        size = 60
        return [self.summary(p) for p in rows[(page - 1) * size:page * size]], page * size < len(rows)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        if re.fullmatch(r'[1-9]\d{0,11}', urlsplit(target).path.strip('/')):
            return target
        return ''

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target):
            return False
        bound = self.title_key(self.title_for(target))
        if bound:
            return bound == self.title_key(title)
        slug = urlsplit(target).path.strip('/')
        with GUARD:
            return any((p['slug'] == slug or str(p['id']) == slug) and p['language'] == self.LANGUAGE and
                       p['key'] == self.title_key(title) for p in CACHE.values())

    def select(self, url, http):
        key = self.title_key(url)
        all_series = self.grouped(http)
        if key:
            return all_series.get(key, [])
        slug = urlsplit(url).path.strip('/')
        return next((rows for rows in all_series.values() if any(
            p['slug'] == slug or str(p['id']) == slug for p in rows)), [])

    def details(self, http, url):
        rows = self.select(self.canonical(url), http)
        if not rows:
            raise SourceError('Тайтл Manga Omega отсутствует в каталоге этого языка.')
        return self.summary(rows)

    def inspect(self, value, http):
        url = self.canonical(value)
        # Legacy bookmarks used the WordPress post ID or its public permalink.
        rows = self.select(url, http)
        if not rows:
            raise SourceError('Тайтл Manga Omega отсутствует в каталоге этого языка.')
        summary = self.summary(rows)
        local = 'Capítulo' if self.LANGUAGE == 'es' else 'Chapter'
        part = 'Parte' if self.LANGUAGE == 'es' else 'Part'
        chapters = []
        pages = []
        slug = urlsplit(url).path.strip('/')
        for post in sorted(rows, key=lambda p: (p['number'], p['date'])):
            if not post['readable']:
                continue
            target = query_url(ROOT + '/' + post['slug'] + '/', mv_omega_title=summary['title'])
            label = f'{local} {post["ordinal"]}' + (f' {part} {post["part"]}' if post['part'] else '')
            chapters.append(self.chapter(target, label, post['number'], post['date'][:10]))
            if slug in (post['slug'], str(post['id'])):
                payload, _ = self.request(http, query_url(POSTS + '/' + str(post['id']), _fields='content'))
                doc = BeautifulSoup(payload['content']['rendered'], 'html.parser')
                pages = [image for n in doc.select('img:not(.alignleft)') if (image := picture(n, ROOT))]
                if not pages:
                    raise SourceError('Manga Omega не предоставил страницы выпуска.')
        return self.reader_result(summary, url, chapters, pages)


SOURCES = (MangaOmega('2894342535414560681', 'en'), MangaOmega('8289860289735224810', 'es'))
