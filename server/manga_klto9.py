"""Klto9 HTML archives and public .lst/.iog chapter routes."""

import base64
import binascii
import re
import secrets
import string
from urllib.parse import parse_qsl, urlsplit

from manga_direct_catalogues import SLUG
from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Cards, MAX_PAGES, Meta, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceError


HOST = 'klto9.com'
ROOT = 'https://' + HOST
TITLE = rf'/teap-{SLUG}\.html'
ORDINAL = r'\d{1,9}(?:\.\d{1,5})?'
CHAPTER = rf'/zmqs-{SLUG}-chapter-({ORDINAL})\.html'
MEDIA = r'[A-Za-z0-9_.-]{1,140}'
THUMB = re.compile(r'cover\.php[?,]q?u=([\w-]{1,1500})', re.ASCII)
ALPHABET = string.ascii_letters + string.digits


def suffix(length, ext):
    return '/' + ''.join(secrets.choice(ALPHABET) for _ in range(length)) + ext


def public_api(host, path, query):
    if host != HOST or not re.fullmatch(r'/[A-Za-z0-9]{25}\.lst', path):
        return False
    fields = parse_qsl(query)
    return len(fields) == 1 and fields[0][0] == 'manga' and bool(re.fullmatch(SEGMENT, fields[0][1]))


def cover(value):
    match = THUMB.search(value)
    if not match:
        return value
    try:
        payload = match[1].encode()
        return image_url(base64.urlsafe_b64decode(payload + b'=' * (-len(payload) % 4)).decode(), ROOT)
    except (UnicodeError, binascii.Error):
        return value


class Klto9(JsonSeries):
    cards = Cards('article.manga-update-card', 'h3.update-title a', cover='img.update-cover-img',
                  next='a.pagination-btn[title="Next Page"]')
    meta = Meta('h1.cinema-title', '#btn-manga-bookmark', '#synopsis-content', 'span.alt-value',
                genres='a.cinema-genre-pill', author='a.cinema-meta-link[href^="/manga-author"]',
                status='span.poster-status-chip')

    def __init__(self):
        super().__init__(('3136857802804349121', 'Klto9', 'ja', ROOT, True), TITLE, CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/teap-' + key + '.html' if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_chapter(url):
            return self.title_for(url)
        return url if self.is_title(url) else ''

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.group(1, 2) if match else ('', '')

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        parts = urlsplit(url)
        values = parts.fragment.split('#')
        if (len(values) == 2 and self.title_key(title) == values[0] and re.fullmatch(SEGMENT, values[0])
                and re.fullmatch(ORDINAL, values[1]) and re.fullmatch(MEDIA, parts.path.strip('/'))):
            return query_url(f'{self.ROOT}/zmqs-{values[0]}-chapter-{values[1].removesuffix(".0")}.html', cid=parts.path.strip('/'))
        return ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'listType': 'pagination', 'page': page, 'sort': 'last_update' if sort == 'updated' or query else 'views',
                'sort_type': 'DESC'}
        if query:
            args['title'] = query
        if re.fullmatch(SEGMENT, tag):
            args['include_genres[]'] = tag
        rows, more = self.card_rows(*self.document(http, query_url(self.ROOT + '/manga-list.html', **args)), self.cards)
        for row in rows:
            row['cover'] = cover(row['cover'])
        return rows, more

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/manga-list.html')
        return [{'label': node['data-name'], 'sourceId': node['data-slug'], 'category': 'genre'}
                for node in doc.select('button.filter-genre-pill[data-name][data-slug]') if node['data-name']]

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        thumb = doc.select_one('#btn-manga-bookmark[data-cover]')
        if thumb:
            row['cover'] = cover(image_url(thumb['data-cover'], final))
        key = self.title_key(final)
        target = query_url(self.ROOT + suffix(25, '.lst'), manga=key)
        result = self.json(http, target, final)
        if not isinstance(result, list):
            raise SourceError('Klto9 изменил формат оглавления.')
        chapters = {}
        for entry in result:
            cid = str(entry.get('id') or '') if isinstance(entry, dict) else ''
            chapter_no = str(entry.get('chapter') or '').removesuffix('.0') if cid else ''
            if not re.fullmatch(MEDIA, cid) or not re.fullmatch(ORDINAL, chapter_no) or entry.get('manga', key) != key:
                continue
            target = query_url(f'{self.ROOT}/zmqs-{key}-chapter-{chapter_no}.html', cid=cid)
            label = f'Chapter {chapter_no}' + (f' - {entry["name"]}' if entry.get('name') else '')
            date = str(entry.get('last_update') or '')[:10]
            chapters[target] = self.chapter(target, label, number(chapter_no), date)
        return row, self.order(chapters)

    def pages(self, http, url):
        cid = param(url, 'cid')
        if not re.fullmatch(MEDIA, cid):
            raise SourceError('Klto9 не предоставил ID главы.')
        target = query_url(self.ROOT + suffix(30, '.iog'), cid=cid)
        doc, final = self.document(http, target)
        if final != target:
            raise SourceError('Klto9 перенаправил читалку на другой выпуск.')
        return [picture(node, final, ('data-pagespeed-lazy-src',)) for node in doc.select('img', limit=MAX_PAGES + 1)]


SOURCES = (Klto9(),)
