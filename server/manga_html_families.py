"""Public MangaBox, MangaReader, FMReader, WPComics and Liliana site profiles."""

import base64
import json
import re
import unicodedata
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Archive, Cards, Meta, SeriesPort, leaf, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceError


BOX = {
    'www.mangabats.com': (), 'www.kakamanga.com': ('www.mangakakalove.com', 'www.katamanga.com'),
    # natomanga.com rotates mirrors: manganami.com, then natumanga.com (Nov 2026).
    'www.natomanga.com': ('www.natumanga.com', 'www.manganami.com', 'www.nelomanga.net', 'www.manganato.gg'),
}
# On 2026-11-19 natomanga/manganami redirect to natumanga.com, a redesigned
# Next.js site the MangaBox markup no longer matches (the extension breaks the
# same way); manganato.gg still serves the MangaBox site. Manganato reads from
# it and rewrites saved links on the other mirrors to it (IDs are path-only).
MANGANATO_HOME = 'www.manganato.gg'
# The same day kakamanga.com started redirecting to the redesigned katamanga.com;
# mangakakalove.com keeps the MangaBox site.
KAKALOT_HOME = 'www.mangakakalove.com'
READER_HOSTS = {'manganow.to', 'jmanga.cloud', 'rawotaku.com'}
FM_HOSTS = {'nihonkuni.com', 'rawinu.com', 'weloma.net', 'love4u.net'}
LILI_HOSTS = {'manhuaplus.org', 'raw1001.net'}
CHAPTER_ID = r'[a-zA-Z0-9_-]{1,100}'
SERIES = rf'/manga/({SEGMENT})/?'
SUBCHAPTER = rf'/manga/({SEGMENT})/{SEGMENT}(?:/all)?/?'
PAGE_ATTRS = ('data-img', 'data-url', 'data-original', 'data-src', 'data-srcset', 'data-aload')


def public_api(host, path, query):
    if host in {h for primary, mirrors in BOX.items() for h in (primary, *mirrors)}:
        return bool(re.fullmatch(rf'/api/manga/{SEGMENT}/chapters', path) and query == 'limit=-1')
    if host == 'manganow.to':
        return bool(re.fullmatch(rf'/ajax/image/list/{CHAPTER_ID}', path) and query == 'mode=vertical')
    if host in READER_HOSTS:
        return bool(path == '/json/chapter' and re.fullmatch(rf'mode=vertical&id={CHAPTER_ID}', query))
    if host in LILI_HOSTS:
        return bool(re.fullmatch(r'/ajax/image/list/chap/[0-9]{1,14}', path) and not query)
    return False


def array(doc, key):
    pattern = re.compile(rf'\b{re.escape(key)}\s*=\s*(\[)')
    for element in doc.select('script'):
        text = element.string or ''
        found = pattern.search(text)
        if found:
            try:
                values, _ = json.JSONDecoder().raw_decode(text[found.start(1):])
            except ValueError:
                continue
            if isinstance(values, list) and all(isinstance(v, str) for v in values):
                return values
    return []


class MangaBox(SeriesPort):
    cards = Cards('.truyen-list .list-truyen-item-wrap, .comic-list .list-comic-item-wrap, '
                  '.panel_story_list .story_item, .list-truyen-item-wrap, .list-comic-item-wrap',
                  'h3 a, .story_name a', next='.group_page a.page_select + a:not(.page_last), '
                  '.group-page a:not([href]) + a:not(.page-last), a[rel=next]')
    meta = Meta('.manga-info-top h1, .panel-story-info h1, h1', 'div.manga-info-pic img, span.info-image img',
                '#noidungm, #panel-story-info-description, #contentBox', '.story-alternative, tr:has(.info-alternative) h2',
                'li:-soup-contains("Genres") a, td:-soup-contains("Genres") + td a',
                author='li:-soup-contains("Author") a, td:-soup-contains("Author") + td a',
                status='li:-soup-contains("Status"), td:-soup-contains("Status") + td')

    def __init__(self, identity, mirrors=(), legacy_hosts=(), *, home_mirror=False):
        super().__init__(identity, SERIES, SUBCHAPTER, hosts=mirrors, legacy_hosts=legacy_hosts, interval=.25)
        self.mirror_hosts = frozenset(mirrors) - {self.hostname} if home_mirror else frozenset()

    def page_headers(self, _url):
        # The image CDN (2xstorage) accepts only the site's origin as Referer,
        # as the extension sends it; a chapter URL gets HTTP 403.
        return {'Referer': self.ROOT + '/'}

    def canonical(self, value):
        target = super().canonical(value)
        parts = urlsplit(target)
        if target and parts.hostname in self.mirror_hosts:
            # A saved link on another mirror reads from the profile's home mirror.
            return self.site_link(urlunsplit(parts._replace(netloc=self.hostname)))
        return target

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and not re.fullmatch(SEGMENT, tag):
            raise SourceError('Некорректный жанр MangaBox.')
        if query:
            text = unicodedata.normalize('NFKD', query.casefold().replace('đ', 'd'))
            slug = re.sub(r'[^\w]+', '_', ''.join(c for c in text if not unicodedata.combining(c))).strip('_')
            if not slug:
                return [], False
            route = '/search/story/' + quote(slug, safe='')
        elif tag:
            route = '/manga-list/' + tag
        else:
            route = '/manga-list/latest-manga' if sort == 'updated' else '/manga-list/hot-manga'
        return self.card_rows(*self.document(http, query_url(self.ROOT + route, page=page)), self.cards)

    def chapters(self, http, _doc, url):
        slug = self.title_key(url)
        base = 'https://' + urlsplit(url).netloc
        data = self.json(http, f'{base}/api/manga/{slug}/chapters?limit=-1', url)
        values = data.get('data', {}).get('chapters') if isinstance(data, dict) and data.get('success') and isinstance(data.get('data'), dict) else None
        if not isinstance(values, list):
            raise SourceError('MangaBox не предоставил список глав.')
        rows = {}
        for item in values[:10000]:
            chapter = item.get('chapter_slug') if isinstance(item, dict) else None
            if isinstance(chapter, str) and re.fullmatch(SEGMENT, chapter):
                href = f'{base}/manga/{slug}/{chapter}'
                rows[href] = self.chapter(href, item.get('chapter_name') or chapter, number(item.get('chapter_num')),
                                          release_date(str(item.get('updated_at') or '')[:10], '%Y-%m-%d'))
        return self.order(rows), len(values) > 10000

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        cdns = array(doc, 'cdns') + array(doc, 'backupImage')
        paths = array(doc, 'chapterImages')
        if paths:
            base = next((value for host in cdns if (value := image_url(host, final))), '')
            return [image_url(base.rstrip('/') + '/' + path.lstrip('/'), final) for path in paths] if base else []
        return [picture(node, final, PAGE_ATTRS) for node in doc.select('.container-chapter-reader > img')]


class MangaReader(SeriesPort):
    cards = Cards('.manga_list-sbs .manga-poster[href]', '', title='img', title_attr='alt',
                  next='ul.pagination > li.active + li a[href]')
    meta = Meta('#ani_detail .manga-name', '#ani_detail img', '#ani_detail .description',
                '#ani_detail .manga-name-or', '#ani_detail .genres > a',
                author='.anisc-info .item:has(.item-head:-soup-contains("Authors", "著者")) a',
                status='.anisc-info .item:has(.item-head:-soup-contains("Status", "地位")) .name')

    def __init__(self, identity):
        super().__init__(identity, rf'/(?:manga|raw-manga)/({SEGMENT})/?', rf'/read/({SEGMENT})(?:/{SEGMENT})+/?', interval=.5)
        self.japanese = self.LANGUAGE == 'ja'

    def title_for(self, url):
        return self.ROOT + ('/raw-manga/' if self.japanese else '/manga/') + self.chapter_key(url)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            path, args = ('/', {'q': query}) if self.japanese else ('/search', {'keyword': query})
        else:
            path, args = '/filter/', {'sort': 'latest-updated' if sort == 'updated' else 'most-viewed'}
            if tag:
                if not re.fullmatch(SEGMENT, tag):
                    raise SourceError('Некорректный жанр MangaReader.')
                args['genre[]' if self.japanese else 'genres'] = tag
        if not self.japanese or page > 1:
            args['page'] = page
        return self.card_rows(*self.document(http, self.ROOT + path + '?' + urlencode(args)), self.cards)

    def chapters(self, http, doc, final):
        section = '#ja-chaps' if self.japanese else '#en-chapters'
        return self.list_chapters(http, doc, final, Archive(section + ' > li.chapter-item', title='.name', fragment='data-id'))

    def saved_chapter_matches(self, target, title):
        return super().saved_chapter_matches(target, title) or self.confirm_archive_membership(target, title)

    def pages(self, http, url):
        parts = urlsplit(url)
        identity = parts.fragment
        real = urlunsplit(parts._replace(fragment=''))
        if not re.fullmatch(CHAPTER_ID, identity):
            doc, real = self.page_document(http, real)
            node = doc.select_one('div[data-reading-id]')
            identity = node.get('data-reading-id', '') if node else ''
        if not re.fullmatch(CHAPTER_ID, identity):
            raise SourceError('MangaReader не предоставил ID читалки.')
        path = '/json/chapter?mode=vertical&id=' + identity if self.japanese else f'/ajax/image/list/{identity}?mode=vertical'
        data = self.json(http, self.ROOT + path, real)
        if not isinstance(data, dict) or not isinstance(data.get('html'), str):
            raise SourceError('MangaReader не предоставил HTML читалки.')
        doc = BeautifulSoup(data['html'], 'html.parser')
        selector = '.container-reader-chapter > .iv-card:not([data-url$="manganow.jpg"])' if not self.japanese else '.container-reader-chapter > div > img'
        return [picture(node, real, PAGE_ATTRS) or picture(node.select_one('img'), real, PAGE_ATTRS)
                for node in doc.select(selector)]


class FMReader(SeriesPort):
    cards = Cards('div.media, .thumb-item-flow', 'h3 a, .series-title a', cover='img, .thumb-wrapper .img-in-ratio',
                  next='.pagination a:-soup-contains("»"):not(.disabled), div.col-lg-9 button.btn-info',
                  image_attrs=('data-original', 'data-src', 'data-bg'))
    meta = Meta('.manga-info h1, .manga-info h3, h1', 'img.thumbnail, .manga-cover img',
                'div.detail .content, div.row ~ div.row:has(h3:first-child) p, .summary-content p',
                'li:-soup-contains("Other names")', 'li a.btn-danger', author='li a.btn-info', status='li a.btn-success')
    listing = Archive('div#list-chapters p, table.table tr, .list-chapters > a', date='time, .chapter-time, .publishedDate', label_attr='title')
    controller = '/app/manga/controllers/'

    def __init__(self, identity):
        super().__init__(identity, rf'/((?:manga|raw)-{SEGMENT}\.html|manga/{SEGMENT}(?:/\d+)?)/?',
                         rf'/((?:manga-|raw-)?{SEGMENT})(?:/{SEGMENT})+(?:\.html)?/?|/((?:chapter|read)-{SEGMENT}\.html)/?',
                         interval=.5)
        self.variant = urlsplit(self.ROOT).hostname

    def is_chapter(self, url):
        return not self.is_title(url) and super().is_chapter(url)

    def chapter_key(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return next((value for value in match.groups() if value), '') if match else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        cards = self.cards
        args = {'page': page, 'sort': 'last_update' if sort == 'updated' else 'views'}
        if query or tag:
            args.update(name=query, genre=tag)
        elif self.variant != 'love4u.net' or sort != 'updated':
            args.update(listType='pagination', sort_type='DESC')
        if self.variant == 'nihonkuni.com':
            args.update({key: args.get(key, '') for key in ('artist', 'author', 'group', 'm_status', 'name', 'genre', 'ungenre', 'magazine')})
            cards = Cards('div.manga-grid div.manga-card', '.manga-title', cover='.manga-cover', next='.page-link.next[href]',
                          image_attrs=('data-original', 'data-src', 'data-bg', 'data-srcset'))
        return self.card_rows(*self.document(http, query_url(self.ROOT + '/manga-list.html', **args)), cards)

    def metadata(self, doc, url, spec):
        if self.variant == 'nihonkuni.com':
            title = doc.select_one('h1.manga-main-title[data-enc]')
            if title:
                try:
                    title.string = base64.b64decode(title['data-enc'], validate=True).decode()
                except (ValueError, UnicodeError):
                    pass
            spec = Meta('h1.manga-main-title', '.manga-cover img, .manga-cover', '.description-text-content, .info-field-value')
        return super().metadata(doc, url, spec)

    def chapters(self, http, doc, final):
        if self.variant == 'weloma.net':
            spec = Archive('div#list-chapters a[href], .list-chapters > a[href], table.table a[href]',
                           anchor='', date='time, .chapter-time', label_attr='title')
        else:
            path = urlsplit(final).path
            if self.variant == 'love4u.net':
                match = re.search(r'(\d+)/', path)
                if not match:
                    raise SourceError('Love4u не предоставил ID тайтла.')
                params = {'mid': match[1]}
            else:
                match = re.search(r'/(?:manga|raw)-([^/]+)\.html', path)
                if not match:
                    raise SourceError('FMReader не предоставил идентификатор тайтла.')
                params = {'slug': match[1]}
            url = query_url(self.ROOT + self.controller + 'cont.Listchapter.php', **params)
            doc, _ = self.document(http, url)
            spec = Archive('.at-series a[href], div#list-chapters a[href], .list-chapters a[href], table.table a[href]',
                           anchor='', title='.chapter-name', date='time, .chapter-time', label_attr='title')
        return self.list_chapters(http, doc, self.ROOT + '/', spec)

    def saved_chapter_matches(self, target, title):
        return self.confirm_archive_membership(target, title)

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        if self.variant in {'rawinu.com', 'love4u.net'}:
            node = doc.select_one('input#chapter[value]')
            identity = node['value'] if node else ''
            if not re.fullmatch(r'\d{1,14}', identity):
                raise SourceError('FMReader не предоставил номер ресурса главы.')
            path = 'cont.imagesChap.php' if self.variant == 'rawinu.com' else 'cont.listImg.php'
            doc, _ = self.document(http, query_url(self.ROOT + self.controller + path, cid=identity))
        nodes = doc.select('img[id^=page]' if self.variant == 'nihonkuni.com' else 'img.chapter-img')
        images = []
        for node in nodes:
            raw = next((node[attr] for attr in (*PAGE_ATTRS, 'src') if node.get(attr)), '')
            if self.variant == 'weloma.net' and raw and '.' not in raw:
                try:
                    raw = base64.b64decode(raw, validate=True).decode()
                except (ValueError, UnicodeError):
                    raw = ''
            images.append(image_url(raw, final))
        return images


class Liliana(SeriesPort):
    cards = Cards('div#main div.grid > div', 'a[href*="/manga/"]', title='h3, h2, .title',
                  next='.blog-pager > span.pagecurrent + span')
    meta = Meta('.a2 header h1', '.a1 > figure img', '#syn-target', genres='.a2 div > a[rel=tag].label',
                author='div.y6x11p i.fas.fa-user + span.dt', status='div.y6x11p i.fas.fa-rss + span.dt')

    def __init__(self, identity):
        super().__init__(identity, SERIES, SUBCHAPTER)

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            url = query_url(f'{self.ROOT}/search/{page}/', keyword=query)
        elif tag:
            url = query_url(f'{self.ROOT}/filter/{page}/', genre=tag)
        elif sort == 'updated':
            url = f'{self.ROOT}/all-manga/{page}/?sort=last_update&status=0'
        else:
            url = f'{self.ROOT}/ranking/week/{page}'
        return self.card_rows(*self.document(http, url), self.cards)

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/filter')
        return [{'label': node_text(span.parent), 'sourceId': span['data-genre'], 'category': 'genre'}
                for span in doc.select('.advanced-genres .advance-item span[data-genre]')]

    def chapters(self, http, doc, url):
        return self.list_chapters(http, doc, url, Archive('ul > li.chapter'))

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        match = re.search(r'\bconst\s+CHAPTER_ID\s*=\s*([0-9]{1,14})\s*;', str(doc))
        if not match:
            raise SourceError('Liliana не предоставил ID главы.')
        data = self.json(http, self.ROOT + '/ajax/image/list/chap/' + match[1], final)
        if not isinstance(data, dict) or not data.get('status') or not isinstance(data.get('html'), str):
            raise SourceError('Liliana не предоставил список страниц.')
        doc = BeautifulSoup(data['html'], 'html.parser')
        indexed = doc.select('div.separator[data-index]')
        nodes = indexed or doc.select('div.separator')
        pages = []
        for i, node in enumerate(nodes):
            a = node.select_one('a[href]')
            link = image_url(a['href'], final) if a else ''
            if link and not urlsplit(link).path.lower().endswith('.svg') and 'loading_comments' not in link.lower():
                index = node.get('data-index', '')
                pages.append((int(index) if index.isdecimal() else i, link))
        return [link for _, link in sorted(pages)] if indexed else [link for _, link in pages]

    def page_headers(self, _url):
        return {}


class WPComics(SeriesPort):
    meta = Meta('#item-detail h1, h1.title-detail, h1', '#item-detail .col-image img', '.detail-content', '.other-name',
                'li.kind p.col-xs-8 a', author='li.author p.col-xs-8', status='li.status p.col-xs-8')
    cards = Cards('div.items .item', 'h3 a', next='a.next-page, a[rel=next]')

    def __init__(self, identity):
        super().__init__(identity, rf'/(?:comic|manga|truyen-tranh)/({SEGMENT})/?',
                         rf'/(?:comic|manga|truyen-tranh)/({SEGMENT})(?:/{SEGMENT})+(?:/all)?/?')
        self.xoxo = self.LANGUAGE == 'en'

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        spec, args = self.cards, {'page': page}
        if query:
            path = '/search-comic' if self.xoxo else '/search/manga'
            args['keyword'] = query
        elif tag:
            if not re.fullmatch(SEGMENT, tag):
                raise SourceError('Некорректный жанр WPComics.')
            path = '/genre/' + tag if self.xoxo else '/search/manga'
            if not self.xoxo:
                args['genre'] = tag
        elif sort == 'updated':
            path = '/comic-update' if self.xoxo else '/'
            if self.xoxo:
                spec = Cards('li.row', 'h3 a', next=spec.next)
        else:
            path = '/hot-comic' if self.xoxo else '/hot'
        if not self.xoxo:
            spec = Cards(spec.rows, spec.link, next='li:nth-last-child(2) a.page-link[href]')
        return self.card_rows(*self.document(http, query_url(self.ROOT + path, **args)), spec)

    def vocabulary(self, http):
        doc, url = self.document(http, self.ROOT + ('/comic-list' if self.xoxo else '/search/manga'))
        found = {}
        for node in doc.select('.genres ul.nav a[href]'):
            link = self.site_link(node['href'], url)
            slug = param(link, 'genre') or urlsplit(link).path.rstrip('/').rsplit('/', 1)[-1]
            if re.fullmatch(SEGMENT, slug) and node_text(node):
                found[slug] = {'label': node_text(node), 'sourceId': slug, 'category': 'genre'}
        return list(found.values())

    def title_for(self, url):
        return self.ROOT + '/' + '/'.join(urlsplit(url).path.strip('/').split('/')[:2])

    def chapters(self, http, doc, final):
        return self.list_chapters(http, doc, final, Archive('div.list-chapter li.row:not(.heading)',
                                  date='div.col-xs-3' if self.xoxo else 'div.col-xs-4',
                                  date_pattern='%m/%d/%Y', next='ul.pagination a[rel=next]' if self.xoxo else ''))

    def pages(self, http, url):
        target = urlunsplit(urlsplit(url)._replace(path=urlsplit(url).path.rstrip('/').removesuffix('/all') + '/all')) if self.xoxo else url
        doc, final = self.page_document(http, target)
        return [picture(node, final, PAGE_ATTRS) for node in doc.select('div.page-chapter > img, li.blocks-gallery-item img')]


SOURCES = (
    MangaBox(('4215511432986138970', 'Mangabat', 'en', 'https://www.mangabats.com', True),
             legacy_hosts=('m.mangabat.com', 'h.mangabat.com', 'readmangabat.com', 'www.mangabat.com')),
    MangaBox(('2528986671771677900', 'Mangakakalot', 'en', 'https://' + KAKALOT_HOME, True),
             ('www.kakamanga.com', *(host for host in BOX['www.kakamanga.com'] if host != KAKALOT_HOME)),
             legacy_hosts=('mangakakalot.com', 'www.mangakakalot.com'), home_mirror=True),
    MangaBox(('1024627298672457456', 'Manganato', 'en', 'https://' + MANGANATO_HOME, True),
             ('www.natomanga.com', *(host for host in BOX['www.natomanga.com'] if host != MANGANATO_HOME)),
             legacy_hosts=('chapmanganato.to', 'manganato.com', 'readmanganato.com'), home_mirror=True),
    MangaReader(('855054225815309342', 'MangaNow', 'en', 'https://manganow.to', True)),
    MangaReader(('6141590427749684419', 'Jmanga', 'ja', 'https://jmanga.cloud', True)),
    MangaReader(('7370546749583817262', 'Raw Otaku', 'ja', 'https://rawotaku.com', True)),
    FMReader(('3811800324362294701', 'NihonKuni', 'ja', 'https://nihonkuni.com', True)),
    FMReader(('7788489411010171607', 'RawINU', 'ja', 'https://rawinu.com', True)),
    FMReader(('7595224096258102519', 'WeLoveManga', 'ja', 'https://weloma.net', True)),
    FMReader(('1647179844716143786', 'Love4u', 'ja', 'https://love4u.net', True)),
    WPComics(('2385956107618754468', 'XOXO Comics', 'en', 'https://xoxocomic.com', False)),
    WPComics(('2238636513447052332', 'Raw18', 'ja', 'https://raw18.rent', True)),
    Liliana(('5075089422240578347', 'ManhuaPlus (Unoriginal)', 'en', 'https://manhuaplus.org', False)),
    Liliana(('3349575794425308347', 'Raw1001', 'ja', 'https://raw1001.net', True)),
)
