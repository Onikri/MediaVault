"""Digital Comic Museum catalogue and its per-page public preview."""

import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_madara import node_text
from manga_series_port import Cards, MAX_PAGES, Meta, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceError, public_url


HOSTS = ('digitalcomicmuseum.com', 'www.digitalcomicmuseum.com', 'ftp.digitalcomicmuseum.com',
         'fb.digitalcomicmuseum.com', 'hope.digitalcomicmuseum.com', 'mobile.digitalcomicmuseum.com')
ROOT = 'https://' + HOSTS[0]
SEARCH = ROOT + '/index.php?ACT=dosearch'
PREVIEW = '/preview/index.php'
MARK = 'mv_dcm_page'
ID = r'[1-9]\d{0,8}'


def public_search(url, fields):
    return url == SEARCH and set(fields) == {'terms'} and isinstance(fields['terms'], str) and 1 <= len(fields['terms']) <= 160


def preview(value, marked=False):
    parts = urlsplit(value)
    args = parse_qsl(parts.query)
    fields = dict(args)
    if (parts.hostname not in HOSTS or parts.path != PREVIEW or len(args) != len(fields) or
            set(fields) - {'did', 'page'} or not re.fullmatch(ID, fields.get('did', '')) or
            ('page' in fields and not re.fullmatch(ID, fields['page'])) or
            (marked and parts.fragment != MARK)):
        return ''
    return public_url(value, resolve_dns=False)


def lazy_image(http, target):
    raw, final, _ = http.document(target)
    if (not preview(final) or param(final, 'did') != param(target, 'did')
            or (param(final, 'page') or '1') != (param(target, 'page') or '1')):
        raise SourceError('Digital Comic Museum подменил страницу выпуска.')
    doc = BeautifulSoup(raw, 'html.parser')
    image = picture(doc.select_one('img.reader-page-image'), final)
    if not image or urlsplit(image).hostname not in HOSTS:
        raise SourceError('Digital Comic Museum не предоставил изображение страницы.')
    return image


class ComicMuseum(SeriesPort):
    cards = Cards('tbody > .mainrow', 'a[href]', cover='img', next='img[alt=Next]')
    search_cards = Cards('#search-results tbody > tr', 'td > a[href]', cover='img')
    meta = Meta('.tableborder #catname', '.tableborder table img', '.tableborder:has(#catname:-soup-contains-own("Description")) table')

    def __init__(self):
        super().__init__(('1057298314437889941', 'Digital Comic Museum', 'en', ROOT, False),
                         r'(/index\.php)', r'(/preview/index\.php)', hosts=HOSTS[1:], interval=.35)

    def title_key(self, url):
        return param(url, 'dlid') or param(url, 'did')

    def is_title(self, url):
        return super().is_title(url) and bool(re.fullmatch(ID, self.title_key(url)))

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(preview(url))

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_chapter(target):
            return self.title_for(target)
        return target if self.is_title(target) else ''

    def title_for(self, url):
        return query_url(ROOT + '/index.php', dlid=self.title_key(url))

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(target) == self.title_key(title))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page != 1:
                return [], False
            raw, final, _ = http.document(SEARCH, method='POST', data={'terms': query}, action='dcm-search')
            if self.site_link(final) != SEARCH:
                raise SourceError('Digital Comic Museum перенаправил поиск.')
            return self.card_rows(BeautifulSoup(raw, 'html.parser'), final, self.search_cards)[0], False
        path = query_url(ROOT + '/stats.php', ACT='latest' if sort == 'updated' else 'topdl', start=f'{page-1}00', limit=100)
        return self.card_rows(*self.document(http, path), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row.update(status='completed', format='comic')
        return row

    def chapters(self, http, doc, final):
        title = self.title_key(final)
        targets = [node for node in doc.select('.tableborder .tablefooter a[href]') if
                   (url := self.site_link(node['href'], final)) and self.saved_chapter_matches(url, final)]
        if targets:
            url = self.site_link(targets[0]['href'], final)
        else:
            url = query_url(ROOT + PREVIEW, did=title)
        label = node_text(doc.select_one('.tableborder #catname'))
        return [self.chapter(url, label or 'Comic', 1)], False

    def pages(self, http, url):
        if not preview(url):
            raise SourceError('Некорректная ссылка на выпуск Digital Comic Museum.')
        doc, final = self.document(http, url)
        if not preview(final) or self.title_key(final) != self.title_key(url):
            raise SourceError('Digital Comic Museum подменил выпуск.')
        result = {}
        for node in doc.select('.reader-page-list a.reader-page-link[href]'):
            target = self.site_link(node['href'], final)
            if self.saved_chapter_matches(target, self.title_for(final)):
                result[target] = target + '#' + MARK
        if result:
            return list(result.values())[:MAX_PAGES + 1]
        first = picture(doc.select_one('img.reader-page-image'), final)
        return [first] if first else []


SOURCES = (ComicMuseum(),)
