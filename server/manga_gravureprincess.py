"""Idol. gravureprincess .date Blogger galleries (keiyoushi ``src/ja/idolgravureprincessdate``).

The blog's public JSON feed lists posts; every post is one gallery whose
pages are the full-size images linked from the post body.
"""

import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import image_url
from manga_ninth_routes import register_api
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://idol.gravureprincess.date'
POST = r'/((?:19|20)[0-9]{2}/[0-9]{2}/[^/]{1,300}\.html)'
LIMIT = 25


def public_api(host, path, query):
    if host != 'idol.gravureprincess.date' or path != '/feeds/posts/default':
        return False
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=5, strict_parsing=True)
    except ValueError:
        return False
    args = dict(fields)
    return (len(args) == len(fields) and set(args) <= {'alt', 'max-results', 'start-index', 'q'} and args.get('alt') == 'json'
            and args.get('max-results') == str(LIMIT) and bool(re.fullmatch(r'[1-9][0-9]{0,5}', args.get('start-index', '')))
            and len(args.get('q', '')) <= 200)


register_api(public_api)


def text(value):
    return value.get('$t', '') if isinstance(value, dict) and isinstance(value.get('$t'), str) else ''


class GravurePrincess(JsonSeries):
    def __init__(self):
        super().__init__(('5414342435310010512', 'Idol. gravureprincess .date', 'ja', ROOT, True), POST, POST, interval=.3)

    def is_title(self, url):
        return super().is_title(url) and not param(url, 'mv_read')

    def is_chapter(self, url):
        return bool(self.TITLE_PATH.fullmatch(urlsplit(url).path)) and param(url, 'mv_read') == '1'

    def chapter_identity(self, url):
        return urlsplit(url).path

    def title_for(self, url):
        return self.ROOT + urlsplit(url).path

    def saved_title_url(self, url):
        if isinstance(url, str) and url.startswith('/'):
            url = url.split('#', 1)[0]
        return self.canonical(url)

    def saved_chapter(self, row, root, title):
        return query_url(title, mv_read='1') if self.is_title(title) else ''

    def saved_chapter_matches(self, target, title):
        return self.title_key(target) == self.title_key(title)

    def entry(self, item):
        link = next((l.get('href') for l in item.get('link') or [] if isinstance(l, dict) and l.get('rel') == 'alternate'), '')
        url = self.canonical(link)
        title = text(item.get('title'))
        if not self.is_title(url) or not title:
            return None
        body = BeautifulSoup(text(item.get('content')), 'html.parser')
        cover = body.select_one('img[src]')
        tags = [c['term'] for c in item.get('category') or [] if isinstance(c, dict) and isinstance(c.get('term'), str)]
        row = self.record(url, title.strip(), image_url(cover['src'], ROOT) if cover else '', tags=tags, status='completed')
        row['format'] = 'photobook'
        row['adult'] = True
        row['publishedAt'] = text(item.get('published'))[:10]
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'alt': 'json', 'max-results': str(LIMIT), 'start-index': str(LIMIT * (page - 1) + 1)}
        search = (f'label:"{tag}" ' if tag else '') + query
        if search.strip():
            args['q'] = search.strip()[:200]
        data = self.json(http, query_url(ROOT + '/feeds/posts/default', **args))
        entries = ((data.get('feed') or {}).get('entry') if isinstance(data, dict) else None) or []
        rows = [row for row in map(self.entry, entries) if row]
        for row in rows:
            row.pop('publishedAt', None)
        return rows, len(entries) == LIMIT

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        title = doc.select_one('h3.post-title, h1.post-title, meta[property="og:title"]')
        name = (title.get('content') if title and title.name == 'meta' else title.get_text(' ', strip=True) if title else '')
        if not name:
            raise SourceError('Галерея не найдена.')
        image = doc.select_one('meta[property="og:image"][content]')
        tags = [a.get_text(strip=True) for a in doc.select('.post-labels a, a[rel=tag]')]
        row = self.record(final, name.strip(), image_url(image['content'], final) if image else '', tags=tags, status='completed')
        row['format'] = 'photobook'
        row['adult'] = True
        date = doc.select_one('abbr.published[title], time[datetime]')
        published = (date.get('title') or date.get('datetime') or '')[:10] if date else ''
        return row, [self.chapter(query_url(final, mv_read='1'), 'Gallery', 1.0, published)]

    def pages(self, http, url):
        doc, final = self.document(http, self.ROOT + urlsplit(url).path)
        return [link for a in doc.select('div.post-body a[href]:has(> img)') if (link := image_url(a['href'], final))]


SOURCES = (GravurePrincess(),)
