"""UniComics bilingual sitemap and deferred image reader."""

import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, node_text
from manga_series_port import Cards, Meta, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceError, public_url

ROOT = 'https://unicomics.ru'
TITLE = rf'/comics/(?:series|online|issues)/({SEGMENT})/?'
READER = rf'/comics/(?:read|reader|online|issues)/({SEGMENT}(?:/{SEGMENT}){{0,4}})/?'
PAGINATOR = re.compile(r"""new Paginator\(['"].*?['"],\s*(\d+),\s*\d+,\s*\d+,\s*['"](.*?)['"]\)""")
IMAGE = 'img.image_online, img#b_image, img#image'
MARK = 'mv_unicomics_page'


def deferred(value):
    parts = urlsplit(value)
    if parts.netloc != 'unicomics.ru' or not re.fullmatch(READER, parts.path):
        raise SourceError('Некорректная страница UniComics.')
    return public_url(value, resolve_dns=False)


def lazy_image(http, url):
    raw, final, _ = http.document(deferred(url))
    if deferred(final).rstrip('/') != url.rstrip('/'):
        raise SourceError('UniComics перенаправил на другую страницу комикса.')
    image = picture(BeautifulSoup(raw, 'html.parser').select_one(IMAGE), final)
    if not image:
        raise SourceError('UniComics не предоставил изображение страницы.')
    return image


class UniComics(SeriesPort):
    cards = Cards('.comics-grid .comic-card', '.comic-title-link, a', '.comic-title-ru, .comic-title-en',
                  '.comic-image-link img, img', next='select.mobilePageSelector option[selected] ~ option')
    events = Cards('.events-grid .event-card, .list_events', 'a[href]', '.comic-title-ru, .event-title')
    meta = Meta('.series-main h1, .issue-info h1, .series-main h2',
                '.cover-series img, .cover-series-mobile img, .issue-cover img',
                '.series-description', '.series-main h2')

    def __init__(self):
        super().__init__(('6859623422196397486', 'UniComics', 'ru', ROOT, False), TITLE, READER, interval=.35)

    def is_title(self, url):
        return super().is_title(url) and param(url, 'mv_unicomics_read') != '1'

    def title_for(self, url):
        title = param(url, 'mv_unicomics_parent')
        kind = param(url, 'mv_unicomics_kind')
        return ROOT + f'/comics/{kind}/{title}' if kind in {'series', 'online', 'issues'} and re.fullmatch(SEGMENT, title) else ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and (self.title_key(self.title_for(target)) == self.title_key(title)
                                                 or self.confirm_archive_membership(target, title)))

    def search(self, http, query):
        tokens = re.findall(r'[^\W_]+', query.casefold())
        if not tokens:
            return []
        doc, final = self.document(http, ROOT + '/map')
        rows = {}
        for anchor in doc.select('a[href^="/comics/series/"]'):
            url = self.site_link(anchor['href'], final)
            title = node_text(anchor)
            if url and title and self.is_title(url) and all(token in (title + ' ' + url).casefold() for token in tokens):
                rows.setdefault(self.title_key(url), self.record(url, title))
        return list(rows.values())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            return (self.search(http, query) if page == 1 else []), False
        if tag == 'events':
            return self.card_rows(*self.document(http, ROOT + '/comics/events'), self.events) if page == 1 else ([], False)
        route = 'online' if sort == 'updated' else 'series'
        if re.fullmatch(SEGMENT, tag):
            route = 'publishers/' + tag
        return self.card_rows(*self.document(http, ROOT + f'/comics/{route}/page/{page}'), self.cards)

    def vocabulary(self, http):
        doc, _ = self.document(http, ROOT + '/comics/publishers')
        rows = [{'key': 'events', 'label': 'События', 'kind': 'category'}]
        for anchor in doc.select('.publishers-card > a:first-child[href]'):
            key = urlsplit(anchor['href']).path.rstrip('/').rsplit('/', 1)[-1]
            if re.fullmatch(SEGMENT, key):
                rows.append({'key': key, 'label': node_text(anchor), 'kind': 'publisher'})
        return rows

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        labels = doc.select('.issue-info-grid .issue-info-label, .series-info-grid .label')
        values = doc.select('.issue-info-grid .issue-info-value, .series-info-grid .value')
        info = {node_text(k).rstrip(':'): node_text(v) for k, v in zip(labels, values)}
        row.update(format='comic', authors=[info['Издательство']] if info.get('Издательство') else [])
        return row

    def chapters(self, http, doc, final):
        kind, key = urlsplit(final).path.strip('/').split('/')[1:3]
        pager = [url for n in doc.select('select.mobilePageSelector option[value]')
                 if (url := self.site_link(n['value'], final)) and url != final]
        issue = doc.select_one('.issue-info-grid')
        rows = {}
        for current in [doc, *(self.document(http, url)[0] for url in dict.fromkeys(pager[:79]) if not issue)]:
            cards = [current] if issue else current.select('.comics-grid .comic-card')
            for card in cards:
                anchor = card.select_one('.btn-read-online-issues, .buttons-grid a:-soup-contains("Читать"), .comic-title-link')
                url = self.site_link(anchor.get('href', ''), final) if anchor else (final if issue else '')
                if not self.is_chapter(url):
                    continue
                title = node_text(card.select_one('.comic-title-ru')) or node_text(card.select_one('.comic-title-en, .issue-info h1'))
                match = re.search(r'№\s*(\d+(?:\.\d+)?)', title)
                target = query_url(url, mv_unicomics_read=1, mv_unicomics_parent=key, mv_unicomics_kind=kind)
                rows[target] = self.chapter(target, title, number(match[1]) if match else None)
        return self.order(rows), len(pager) > 79

    def pages(self, http, url):
        origin = urlsplit(url)
        params = dict((k, v) for k, v in parse_qsl(origin.query)
                      if not k.startswith('mv_unicomics_'))
        target = query_url(url.split('?', 1)[0], **params)
        doc, final = self.document(http, deferred(target))
        routes = [self.site_link(n['value'], final) for n in doc.select('select.mobilePageSelector option[value]')]
        if not routes and (match := PAGINATOR.search(str(doc))):
            routes = [self.site_link(match[2] + str(i), final) for i in range(1, min(int(match[1]), 1000) + 1)]
        if not routes:
            first = picture(doc.select_one(IMAGE), final)
            return [first] if first else []
        return [deferred(route) + '#' + MARK for route in dict.fromkeys(filter(None, routes))]


SOURCES = (UniComics(),)
