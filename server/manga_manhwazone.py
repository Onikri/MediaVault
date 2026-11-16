"""ManhwaZone's Livewire chapter list and public image reader."""

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT
from manga_series_port import Cards, Meta, SeriesPort, picture
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceError

HOST = 'manhwazone.com'
ROOT = 'https://' + HOST
HOSTS = {HOST, 'www.' + HOST}
TITLE = rf'/series/({SEGMENT})/?'
CHAPTER = rf'/(?:series|chapter|read|reader)/({SEGMENT}(?:/{SEGMENT}){{0,3}})/?'
READ_ACTION = 'manhwazone-livewire'


def livewire_form(url, body, referer):
    parts = urlsplit(url)
    parent = urlsplit(referer)
    if (parts.netloc not in HOSTS or parts.path != '/livewire/update' or parts.query or
            parent.netloc != parts.netloc or not re.fullmatch(TITLE, parent.path) or
            not isinstance(body, bytes) or len(body) > 512_000):
        return False
    try:
        data = json.loads(body)
        if set(data) != {'_token', 'components'} or not re.fullmatch(r'[A-Za-z0-9+/=_-]{16,128}', data['_token']):
            return False
        [component] = data['components']
        if (set(component) != {'snapshot', 'updates', 'calls'} or component['updates'] != {}
                or component['calls'] != [{'path': '', 'method': 'bootLoad', 'params': []}]):
            return False
        snap = json.loads(component['snapshot'])
        return isinstance(snap.get('data'), dict) and isinstance(snap.get('memo'), dict) and bool(
            re.fullmatch(r'[a-f\d]{64}', snap.get('checksum', ''), re.I))
    except (ValueError, AttributeError, TypeError, KeyError):
        return False


class ManhwaZonePage:
    """The image CDN only accepts the public image without a site Referer."""


class ManhwaZone(SeriesPort):
    cards = Cards('article.group', 'a[href]', '.min-w-0 > a.font-semibold', 'img', next='a[rel=next], nav a:-soup-contains("›")')
    meta = Meta('h1.page-title', 'img[class*="aspect-[7/10]"], figure.relative img', 'p.page-subtitle', '',
                'a.badge-genre', '', '', 'span.badge-sm')

    def __init__(self):
        super().__init__(('618830122769950563', 'ManhwaZone', 'en', ROOT, True),
                         TITLE, CHAPTER, hosts=('www.' + HOST,), interval=.35)

    def is_chapter(self, url):
        return super().is_chapter(url) and not self.is_title(url)

    def title_for(self, url):
        slug = param(url, 'mv_mhz_title')
        return ROOT + '/series/' + slug if re.fullmatch(SEGMENT, slug) else ''

    def saved_chapter_matches(self, target, title):
        bound = self.title_for(target)
        return bool(self.is_chapter(target) and (self.title_key(bound) == self.title_key(title)
                                                if bound else self.confirm_archive_membership(target, title)))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'sortBy': 'latest' if sort == 'updated' else 'popularity', 'page': page}
        if query:
            args['keyword'] = query
        if re.fullmatch(r'[a-zA-Z0-9-]{1,80}', tag):
            args['genres'] = tag
        rows, more = self.card_rows(*self.document(http, query_url(ROOT + '/series', **args)), self.cards)
        return rows, more or len(rows) >= 24

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        for script in doc.select('script[type="application/ld+json"]'):
            try:
                obj = json.loads(script.string or '')
            except ValueError:
                continue
            if isinstance(obj, dict):
                authors = obj.get('author', [])
                if isinstance(authors, dict):
                    authors = [authors]
                row['authors'] = [name for author in authors if isinstance(author, dict)
                                  and isinstance(name := author.get('name'), str) and name.lower() != 'unknown']
                break
        return row

    def title_document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, action='manhwazone-document')
        if not self.is_title(final) or self.title_key(final) != self.title_key(url):
            raise SourceError('ManhwaZone перенаправил на другой тайтл.')
        return BeautifulSoup(raw, 'html.parser'), final

    def chapters(self, http, doc, final):
        wire = doc.select_one(r'div[wire\:snapshot][wire\:id][wire\:init="bootLoad"]')
        token = doc.select_one('meta[name="csrf-token"][content]')
        if not wire or not token:
            return [], False
        target = 'https://' + urlsplit(final).netloc + '/livewire/update'
        payload = {'_token': token['content'], 'components': [{'snapshot': wire['wire:snapshot'], 'updates': {},
                  'calls': [{'path': '', 'method': 'bootLoad', 'params': []}]}]}
        raw, location, _ = http.document(target, headers={'Referer': final}, method='POST',
                                         data=json.dumps(payload, separators=(',', ':')).encode(), action=READ_ACTION)
        if location != target:
            raise SourceError('ManhwaZone перенаправил запрос оглавления.')
        results = json.loads(raw).get('components') or []
        if not results:
            return [], False
        updated = json.loads(results[0]['snapshot'])
        chapters = (updated.get('data') or {}).get('chapters') or []
        entries = {}
        for record in chapters[0] if chapters else []:
            item = record[0] if isinstance(record, list) and record else None
            target = self.site_link(item.get('web_url'), final) if isinstance(item, dict) else ''
            if self.is_chapter(target):
                url = query_url(target, mv_mhz_title=self.title_key(final))
                entries[url] = self.chapter(url, str(item.get('name') or 'Chapter'), date=str(item.get('published') or '')[:10])
        return self.order(entries), False

    def pages(self, http, url):
        target = query_url(url, mv_mhz_title=[])
        doc, final = self.page_document(http, target)
        images = [(src, ManhwaZonePage()) for node in doc.select('img.lazy-image[data-src]')
                  if (src := picture(node, final, ('data-src',)))]
        return remember(images, final)


SOURCES = (ManhwaZone(),)
