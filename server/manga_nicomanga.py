"""Nicomanga public listings and compact embedded reader payloads."""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries, strings
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Cards, number
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://nicomanga.com'
SERIES = r'/manga\d{1,9}/[a-fA-F\d]{8,32}'
TITLE = rf'({SERIES})\.html/?'
CHAPTER = rf'({SERIES})/(chapter-{SEGMENT})\.html/?'
OBFUSCATION = b'NicoMangaX2'
AGO = {'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400,
       'week': 604800, 'month': 2592000, 'year': 31536000}


def unpack(html):
    for marker in re.finditer(r'[0-9a-z]+:T[0-9a-f]+,', html):
        start = next((i for i in range(marker.end(), min(marker.end() + 600, len(html)))
                      if 19968 <= ord(html[i]) <= 20223), -1)
        if start < 0:
            continue
        end = html.find('</script>', start)
        if end < 0:
            continue
        raw = bytes(((ord(c) - 19968) ^ OBFUSCATION[i % len(OBFUSCATION)]) & 255
                    for i, c in enumerate(html[start:end]))
        try:
            data, _ = json.JSONDecoder().raw_decode(raw.decode('utf-8', errors='replace').lstrip())
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get('manga'), dict):
            return data
    raise SourceError('Nicomanga не передал данные читалки.')


def relative_date(value):
    found = re.search(r'(\d{1,7})\s+(second|minute|hour|day|week|month|year)s?\s+ago', str(value or ''))
    if not found:
        return ''
    seconds = int(found[1]) * AGO[found[2]]
    if seconds > 200 * AGO['year']:
        return ''
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).date().isoformat()


class Nicomanga(JsonSeries):
    cards = Cards('.manga-grid .manga-card', 'a.manga-title', 'a.manga-title', 'img.manga-img',
                  next='.custom-pagination .page-link.next:not(.disabled)')

    def __init__(self):
        super().__init__(('5680590515266301834', 'Nicomanga', 'ja', ROOT, True),
                         TITLE, CHAPTER, hosts=('www.nicomanga.com',), interval=.5)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + key + '.html' if key else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        params = {'p': page}
        if re.fullmatch(r'\d{1,8}', tag):
            params.update(g=tag, gm=1)
        if not query:
            params['pr'] = 'new' if sort == 'updated' else 'popular'
        opts = {'n': query} if query else {}
        doc, final = self.document(http, query_url(ROOT + '/manga-list.html', **params, **opts))
        rows, more = self.card_rows(doc, final, self.cards)
        if query and page == 1 and not rows:
            doc, final = self.document(http, query_url(ROOT + '/manga-list.html', **params, a=query))
            rows, more = self.card_rows(doc, final, self.cards)
        return rows, more

    def vocabulary(self, http):
        doc, final = self.document(http, ROOT + '/manga-list.html')
        return [{'key': tag, 'label': label, 'kind': 'genre'} for node in doc.select('a.genre-tag[href]')
                if re.fullmatch(r'\d{1,8}', tag := param(node['href'], 'g')) and (label := node_text(node))]

    def payload(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'})
        if not self.canonical(final) or urlsplit(url).path.rstrip('/') != urlsplit(final).path.rstrip('/'):
            raise SourceError('Nicomanga перенаправил на другую страницу.')
        return unpack(raw)

    def series(self, http, url):
        obj = self.payload(http, url)
        manga = obj['manga']
        if not isinstance(title := manga.get('n'), str) or not title.strip():
            raise SourceError('Nicomanga не предоставил название.')
        description = BeautifulSoup(str(manga.get('description') or ''), 'html.parser').get_text('\n', strip=True)
        authors = labels(manga.get('authors_list'))
        if isinstance(manga.get('artists'), str) and manga['artists'].strip():
            authors.append(manga['artists'])
        status = str(manga.get('status_text') or '').casefold()
        row = self.record(url, title, image_url(manga.get('c'), url), description='' if description.casefold() == 'updating' else description,
                          authors=authors, aliases=[manga.get('other_name') or ''],
                          genres=labels(manga.get('genres_list')),
                          status={'on going': 'ongoing', 'ongoing': 'ongoing', 'completed': 'completed'}.get(status, ''))
        episodes = {}
        for entry in dict_rows(obj.get('chapters_list')):
            target = self.site_link(entry.get('ur'), url)
            if not self.is_chapter(target) or not self.saved_chapter_matches(target, url):
                continue
            n = number(entry.get('chapter'))
            title = entry.get('n') or (f'Chapter {n:g}' if n is not None else '')
            episodes[target] = self.chapter(target, title, n, relative_date(entry.get('t')))
        return row, self.order(episodes)

    def pages(self, http, url):
        return [page for raw in strings(self.payload(http, url).get('images')) if (page := image_url(raw, url))]


def dict_rows(value):
    return (item for item in value if isinstance(item, dict)) if isinstance(value, list) else ()


def labels(value):
    return [item['n'] for item in dict_rows(value) if isinstance(item.get('n'), str) and item['n']]


SOURCES = (Nicomanga(),)
