"""OSOSEDKI public album catalogue and ordered image URLs."""

import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import node_text
from manga_series_port import Meta, SeriesPort, picture
from manga_speedbinb import remember
from manga_toon11 import ToonMirrorPage
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://ososedki.com'
HOSTS = ('ososedki.com', 'www.ososedki.com')
ALBUM_ID = r'(-?\d{1,17})_(\d{1,17})'
TITLE = r'/photos/(' + ALBUM_ID + r')/?'
FILTERS = {'model', 'cosplay', 'fandom', 'top', 'search'}


def public_api(host, path, query):
    if host not in HOSTS or path != '/api/albums':
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(args) != len(pairs) or not re.fullmatch(r'[1-9]\d{0,3}', args.get('page', '')):
        return False
    return set(args) == {'page'} or (set(args) == {'type', 'value', 'page'} and args['type'] in FILTERS
                                    and len(args['value']) <= 160 and (args['type'] != 'top' or args['value'] == '1'))


def page_number(url):
    token = urlsplit(url).path.rsplit('/', 1)[-1].split('.', 1)[0]
    return int(token) if re.fullmatch(r'\d{1,8}', token) else 10**10


class Ososedki(SeriesPort):
    meta = Meta('h1', 'img.gallery-img', '', '', '', 'a[href^="/model/"], a[href^="/cosplay/"], a[href^="/fandom/"]',
                'a[href^="/model/"], a[href^="/cosplay/"]')

    def __init__(self):
        super().__init__(('703138310497011533', 'OSOSEDKI', 'all', ROOT, True),
                         TITLE, TITLE, hosts=HOSTS[1:], interval=.35)

    def is_title(self, url):
        return super().is_title(url) and param(url, 'mv_oso_gallery') != '1'

    def title_for(self, url):
        identity = self.title_key(url)
        return ROOT + '/photos/' + identity if identity else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = self.title_key(url) or urlsplit(url).path.strip('/')
        return ROOT + '/photos/' + key if re.fullmatch(ALBUM_ID, key) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return query_url(ROOT + '/photos/' + key, mv_oso_gallery=1) if re.fullmatch(ALBUM_ID, key) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page}
        kind, _, value = tag.partition(':')
        if query:
            args.update(type='search', value=query)
        elif kind in {'model', 'cosplay', 'fandom'} and value:
            args.update(type=kind, value=value[:160])
        elif sort == 'popular':
            args.update(type='top', value='1')
        payload = self.json(http, query_url(ROOT + '/api/albums', **args))
        raw = payload.get('html')
        if not isinstance(raw, str):
            raise SourceError('OSOSEDKI изменил формат каталога.')
        doc = BeautifulSoup(raw, 'html.parser')
        result = []
        for node in doc.select('article.gallery-item:has(a.gallery-link)'):
            link = self.site_link(node.select_one('a.gallery-link[href]')['href'], ROOT)
            image = node.select_one('img.gallery-img')
            name = node_text(node.select_one('h3')) or (image.get('alt', '').split(' nude.', 1)[0].strip() if image else '')
            if self.is_title(link) and name:
                result.append(self.record(link, name, picture(image, ROOT, ('data-src',)),
                                          authors=[node_text(node.select_one('span.badge:not(.bg-dark)'))], status='completed'))
        return result, payload.get('hasMore') is True

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        title = [node_text(doc.select_one(f'a[href^="/{category}/"]')) for category in ('model', 'cosplay', 'fandom')]
        identity = re.fullmatch(ALBUM_ID, self.title_key(url))
        row.update(title=' - '.join(filter(None, title)) or row['title'], status='completed', format='gallery')
        if identity:
            row['cover'] = f'{ROOT}/images/albums/{identity[1]}/{identity[2]}.webp'
        return row

    def chapters(self, http, doc, final):
        match = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})"', str(doc))
        return [self.chapter(query_url(self.title_for(final), mv_oso_gallery=1), 'Gallery', 1, date=match[1] if match else '')], False

    def pages(self, http, url):
        doc, final = self.page_document(http, self.title_for(url))
        urls = set()
        for anchor in doc.select('#photos a[href]'):
            target = self.site_link(anchor['href'], final)
            parts = urlsplit(target)
            if parts.path.startswith('/images/'):
                urls.add(target)
        refs = []
        for target in sorted(urls, key=lambda url: (page_number(url), url)):
            parts = urlsplit(target)
            fallback = urlunsplit(parts._replace(path=parts.path.replace('/images/a/1280/', '/images/a/604/', 1))) if (
                parts.path.startswith('/images/a/1280/')) else ''
            refs.append((target, ToonMirrorPage(fallback)))
        return remember(refs, final)


SOURCES = (Ososedki(),)
