"""Public NovelCool and Niadd archives, with independent profiles per language."""

from collections import OrderedDict
import re
from threading import Lock
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import SLUG
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_CHAPTERS, MAX_PAGES, Meta, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError, public_url


SERIES = rf'/(?:manga|original)/{SLUG}\.html'
NOVELCOOL = rf'/novel/{SLUG}\.html'
CHAPTER = rf'/chapter/{SEGMENT}/([0-9]{{1,14}})(?:-\d{{1,7}}(?:-\d{{1,7}})?)?(?:\.html|/)?'
CHAPTER_LABEL = re.compile(r'^(\d{1,6})\s*[-–]\s*(\d{1,9}(?:[.,]\d{1,4})?)(?:\s|$)')
JS_LOCATION = re.compile(r"""\b(?:window\.location\.href|document\.location)\s*=\s*['"]([^'"]+)['"]""")
IMAGE_ARRAY = re.compile(r'\ball_imgs_url\s*:\s*\[([^\]]*)\]', re.S)
IMAGE = re.compile(r"""['"]((?:https?:)?//[^'"]+)['"]""")
ADVERTISEMENT = re.compile(r'/go/rds/[^/?#]{1,400}(?:/[^/?#]{1,160}){0,5}/?')
PARTNER_RULE = re.compile(r'/(?:[\w.-]{1,150}/){0,6}[\w.-]{1,240}/?')
JUMPS = OrderedDict()
JUMP_LOCK = Lock()


def chapter_params(url):
    return urlsplit(url).path, dict(parse_qsl(urlsplit(url).query))


def without_local(url):
    return urlunsplit(urlsplit(url)._replace(query='', fragment=''))


def number_fields(label, default):
    match = CHAPTER_LABEL.search(label)
    return (number(match[2]), max(1, int(match[1]))) if match else (default, 1)


def image_script(raw, referer):
    match = IMAGE_ARRAY.search(raw.replace(r'\/', '/'))
    if not match:
        return []
    return list(dict.fromkeys(value for item in IMAGE.finditer(match[1]) if (value := image_url(item[1], referer))))


def html(http, url, referer=None):
    from manga_sources import guard

    raw, final, headers = http.document(url, headers={'Referer': referer} if referer else None)
    doc = BeautifulSoup(raw, 'html.parser')
    guard(doc)
    cookie_header = next((value for key, value in headers.items() if key.lower() == 'set-cookie'), '')
    if 'niadd_bad_user_2=' in cookie_header or re.fullmatch(r'404(?:\s+not\s+found)?', node_text(doc.title), re.I):
        raise SourceAccessError('Источник ограничивает доступ к этому сетевому маршруту.')
    return raw, final, doc


def published_link(value, parent):
    value = public_url(urljoin(parent, value), resolve_dns=False)
    if not PARTNER_RULE.fullmatch(urlsplit(value).path):
        raise SourceError('Источник изменил адрес публичной читалки.')
    return value


class LinkedChapters(SeriesPort):
    def chapter_identity(self, url):
        return self.chapter_key(url)

    def title_for(self, url):
        value = param(url, 'mv_title')
        return self.ROOT + value if self.TITLE_PATH.fullmatch(value) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target) and self.is_title(title):
            return query_url(without_local(target), mv_title=urlsplit(title).path)
        return ''

    def saved_chapter_matches(self, target, title):
        parent = self.title_for(target)
        return bool(self.is_chapter(target) and parent and self.title_key(parent) == self.title_key(title))

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        _, final, doc = html(http, url)
        final = self.site_link(final)
        if not final:
            raise SourceError('Источник перенаправил запрос на другой язык.')
        return doc, final


class NovelCool(LinkedChapters):
    cards = Cards('.book-list .book-item:not(:has(.book-type-novel))', 'a[href]', '.book-pic', 'img',
                  title_attr='title', next='div.page-nav a div.next', image_attrs=('lazy_url', 'data-src'))
    meta = Meta('h1.bookinfo-title', '.bookinfo-pic-img', 'div.bk-summary-txt',
                genres='.bk-cates .bk-cate-item a[title]', author='.bookinfo-author > a', status='.bk-cate-type1 a')

    def __init__(self, identity):
        super().__init__(identity, NOVELCOOL, CHAPTER, interval=1)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or tag:
            args = {'name': query, 'page': page}
            if re.fullmatch(r'[0-9]{1,12}', tag):
                args['category_id'] = ',' + tag
            target = query_url(self.ROOT + '/search', **args)
        elif page == 1:
            target = self.ROOT + ('/category/latest.html' if sort == 'updated' else '/category/new_list.html')
        else:
            return [], False
        return self.card_rows(*self.document(http, target), self.cards)

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/search/')
        return [{'label': node['title'], 'sourceId': node['cate_id'], 'category': 'genre'}
                for node in doc.select('.category-list .category-id-item[title][cate_id]')
                if re.fullmatch(r'[0-9]{1,12}', node['cate_id'])]

    def chapters(self, http, doc, final):
        rows = {}
        for node in doc.select('.chapter-item-list a[href], .chp-item > a[href]'):
            target = self.site_link(node['href'], final)
            if not self.is_chapter(target):
                continue
            target = query_url(without_local(target), mv_title=urlsplit(final).path)
            label = node.get('title') or node_text(node.select_one('.chapter-item-title')) or node_text(node)
            date = release_date(node_text(node.select_one('.chapter-item-time')), '%b %d, %Y')
            n, volume = number_fields(label, number(self.chapter_key(target)))
            rows[self.chapter_key(target)] = self.chapter(target, label, n, date, volume)
        return self.order(rows)[:MAX_CHAPTERS], len(rows) > MAX_CHAPTERS

    def pages(self, http, url):
        visible = without_local(url)
        raw, final, doc = html(http, visible)
        if redirect := JS_LOCATION.search(raw):
            raw, final, doc = html(http, published_link(redirect[1], final), final)
        if node := doc.select_one('a.vision-button[href]'):
            raw, final, doc = html(http, published_link(node['href'], final), final)
            if redirect := JS_LOCATION.search(raw):
                raw, final, doc = html(http, published_link(redirect[1], final), final)
        if pages := image_script(raw, final):
            return pages
        reader = []
        parsed = urlsplit(final)
        picks = list(dict.fromkeys(urljoin(final, node['value']) for node in doc.select('select.sl-page option[value]')))
        if len(picks) > MAX_PAGES:
            raise SourceError('Слишком много страниц в главе NovelCool.')
        if picks:
            for target in picks:
                parts = urlsplit(target)
                if parts.netloc != parsed.netloc or not PARTNER_RULE.fullmatch(parts.path):
                    raise SourceError('Источник добавил адрес с другого сервера в список страниц.')
                if parts.path.startswith('/chapter/') and self.chapter_key(target) != self.chapter_key(url):
                    continue
                if target == final:
                    chapter_url, chapter_doc = final, doc
                else:
                    _, chapter_url, chapter_doc = html(http, target, final)
                    if urlsplit(chapter_url).netloc != parsed.netloc:
                        raise SourceError('Источник перенаправил страницу на другой сервер.')
                reader.extend(picture(node, chapter_url, ('data-src', 'lazy_url'))
                              for node in chapter_doc.select('img.mangaread-manga-pic, img.manga_pic'))
        else:
            reader.extend(picture(node, final, ('data-src', 'lazy_url'))
                          for node in doc.select('img.mangaread-manga-pic, img.manga_pic'))
        return list(dict.fromkeys(page for page in reader if page))


class Niadd(LinkedChapters):
    cards = Cards('div.manga-item', 'a[href]', 'div.manga-name', 'div.manga-img img', next='a.next')
    meta = Meta('h1.book-headline-name', 'div.bookside-img img', 'section.detail-synopsis:not(:has(a))',
                aliases='div.bookside-general-cell:not(:has(a, [itemprop]))',
                genres='div.bookside-general-cell [itemprop=genre]', author='div.bookside-bookinfo a[href*="author="]',
                status='span.book-status')

    def __init__(self, identity):
        hosts = ('niadd.com',) if identity[2] == 'en' else ()
        super().__init__(identity, SERIES, CHAPTER, hosts=hosts, interval=.35)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or tag:
            args = {'name': query, 'page': f'{page}.html'}
            if re.fullmatch(r'[0-9]{1,12}', tag):
                args['category_id'] = tag
            target = query_url(self.ROOT + '/search/', **args)
        elif page == 1:
            target = self.ROOT + ('/list/New-Update.html' if sort == 'updated' else '/list/Hot-Manga.html')
        else:
            return [], False
        return self.card_rows(*self.document(http, target), self.cards)

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/search/?type=high')
        rows = []
        for node in doc.select('li.genre-item a[onclick*="clickGenre"]'):
            value = re.search(r"""['"](\d{1,12})['"]""", node['onclick'])
            if value and node_text(node):
                rows.append({'label': node_text(node), 'sourceId': value[1], 'category': 'genre'})
        return rows

    def chapters(self, http, doc, final):
        archive, ref = self.document(http, without_local(final).removesuffix('.html') + '/chapters.html')
        if not archive.select_one('ul.chapter-list'):
            raise SourceError('Niadd не предоставил оглавление.')
        rows = {}
        for node in archive.select('ul.chapter-list a.hover-underline[href*="/chapter/"]'):
            target = self.site_link(node['href'], ref)
            if not self.is_chapter(target):
                continue
            target = query_url(without_local(target), mv_title=urlsplit(final).path)
            label = node_text(node.select_one('span.chp-title'))
            date = release_date(node_text(node.select_one('span.chp-time')), '%b %d, %Y')
            n, volume = number_fields(label, None)
            rows[self.chapter_key(target)] = self.chapter(target, label, n, date, volume)
        return self.order(rows)[:MAX_CHAPTERS], len(rows) > MAX_CHAPTERS

    def jump(self, http, title='', *, refresh=False):
        with JUMP_LOCK:
            cached = JUMPS.get(self.SOURCE_ID)
        if cached and cached[0] > monotonic() and not refresh:
            return cached[1]
        if not self.is_title(title):
            latest, recent = self.document(http, self.ROOT + '/list/New-Update.html')
            title = next((link for node in latest.select('div.manga-item a[href]') if
                          self.is_title(link := self.site_link(node['href'], recent))), '')
        if not title:
            raise SourceError('Niadd не предоставил открытый тайтл для определения читалки.')
        doc, final = self.title_document(http, title)
        ad = doc.select_one('a[href*="/go/rds/"]')
        target = self.site_link(ad['href'], final) if ad else ''
        if not ADVERTISEMENT.fullmatch(urlsplit(target).path):
            raise SourceError('Niadd не предоставил маршрут читалки для этого языка.')
        raw, final, _ = html(http, target, final)
        match = JS_LOCATION.search(raw)
        if not match:
            raise SourceError('Niadd изменил маршрут читалки.')
        jump = published_link(match[1], final)
        with JUMP_LOCK:
            JUMPS[self.SOURCE_ID] = (monotonic() + 900, jump)
            while len(JUMPS) > 32:
                JUMPS.popitem(last=False)
        return jump

    def pages(self, http, url):
        cid = self.chapter_key(url)
        title = self.title_for(url)
        for refresh in (False, True):
            jump = self.jump(http, title, refresh=refresh)
            parts = urlsplit(jump)
            args = dict(parse_qsl(parts.query))
            args['cid'] = cid
            if urlsplit(title).path.startswith('/original/'):
                args['type'] = 'ogniadd'
            target = urlunsplit(parts._replace(query=urlencode(args)))
            raw, final, _ = html(http, target, without_local(url))
            pages = image_script(raw, final)
            if pages:
                return pages
        raise SourceError('Niadd не предоставил изображения выбранной главы.')


SOURCES = (
    *(Niadd((sid, 'Niadd', language, f'https://{host}.niadd.com', True)) for sid, language, host in (
        ('7623485147777438032', 'pt-BR', 'br'), ('6237269852978906906', 'en', 'www'),
        ('1369970040009723082', 'es', 'es'), ('8223107200339513324', 'it', 'it'),
        ('1044418267385230402', 'ru', 'ru'), ('3358885026101433827', 'de', 'de'),
        ('2892666872128744723', 'fr', 'fr'),
    )),
    *(NovelCool((sid, 'NovelCool', language, f'https://{host}.novelcool.com', True)) for sid, language, host in (
        ('7570101320206504111', 'en', 'www'), ('438359803442833644', 'es', 'es'),
        ('4806085996472938237', 'de', 'de'), ('2000643041937250352', 'ru', 'ru'),
        ('1430309870605719983', 'it', 'it'), ('2431307934077353736', 'pt-BR', 'br'),
        ('1619259951234748770', 'fr', 'fr'),
    )),
)
