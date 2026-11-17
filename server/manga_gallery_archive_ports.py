"""Public single-gallery archives with native chapter URLs."""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from html import unescape
import json
import re
from threading import Lock
from time import time
from urllib.parse import parse_qsl, quote, urlsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import SLUG
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_PAGES, Meta, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


PICS = ('data-original', 'data-src', 'data-lazy-src')
JPAGE = r'[1-9][0-9]{0,3}'
JCAT = r'(?!ajax_)[A-Za-z0-9_-]{1,35}'
JPHOTO = rf'/({JCAT}/{SEGMENT}\.html)'
KING = rf'/{SLUG}/?'
UTILITY = frozenset({'category', 'search', 'page', 'tag', 'feed', 'contact', 'about', 'wp-json'})
CAPTION = re.compile(r'\b(\d{1,4})\s+images?\b', re.I)
ROKU_PATH = rf'/{SLUG}/?'
DOUJINS_PATH = rf'/({SEGMENT}-{JPAGE}(?:/{SEGMENT}){{0,2}})/?'
CURSORS = OrderedDict()
CURSOR_LOCK = Lock()


def public_api(host, path, query):
    pairs = parse_qsl(query)
    values = dict(pairs)
    return (host == 'doujins.com' and path == '/folders' and len(pairs) == 2 and set(values) == {'start', 'end'}
            and all(re.fullmatch(r'[1-9]\d{8,10}', value) for value in values.values())
            and int(values['end']) - int(values['start']) == 3 * 86400)


class SingleGallery(SeriesPort):
    def is_title(self, url):
        return super().is_title(url) and self.title_key(url) not in UTILITY and not param(url, 'mv_gallery')

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'mv_gallery') == '1'

    def title_for(self, url):
        return url.split('?')[0]

    def chapter_identity(self, url):
        return self.title_key(self.title_for(url))

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        key = self.title_key(title)
        if not self.is_title(title) or not target or self.title_key(self.title_for(target)) != key:
            return ''
        return query_url(self.title_for(title), mv_gallery=1)

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.chapter_identity(target) == self.title_key(title))

    def chapters(self, http, doc, final):
        published = doc.select_one('meta[property="article:published_time"][content]')
        date = release_date(published['content'][:10], '%Y-%m-%d') if published else ''
        return [self.chapter(query_url(final, mv_gallery=1), 'Глава', 1, date)], False

    def gallery(self, http, url):
        return self.title_document(http, self.title_for(url))


class KingComix(SingleGallery):
    meta = Meta('h1.singleTitle-h1, h1.widget-title', '.entry-content img', '',
                tags='.caTotal .tagsPost a.taxLink')

    def __init__(self):
        super().__init__(('8953466777316975228', 'KingComiX', 'en', 'https://kingcomix.com', True), KING, KING, interval=.35)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        cover = doc.select_one('meta[property="og:image"][content]')
        author = doc.select_one('meta[name="author"][content]')
        row['cover'] = image_url(cover['content'], url) if cover else row['cover']
        row.update(status='completed', authors=[author['content']] if author else [])
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        section, _, key = tag.partition(':')
        prefix = f'/{section}/{key}' if not query and section in ('category', 'tag') and re.fullmatch(SEGMENT, key) else ''
        path = prefix + (f'/page/{page}/' if page > 1 else '/')
        target = query_url(self.ROOT + path, s=query) if query else self.ROOT + path
        doc, final = self.document(http, target)
        rows = {}
        for node in doc.select('div.entry, article.thumb-block'):
            a = node.select_one('h2.information a[href], a[title][href]')
            href = self.site_link(a.get('href'), final) if a else ''
            if not self.is_title(href):
                continue
            title = node_text(a) or a.get('title')
            if title:
                rows[href] = self.record(href, title, picture(node.select_one('img'), final, ('data-src',)))
        more = any(num.isdecimal() and int(num) > page for el in doc.select('.pagination a') if (num := node_text(el)))
        return list(rows.values()), bool(rows) and more

    def vocabulary(self, http):
        doc, final = self.document(http, self.ROOT + '/')
        terms = {}
        for node in doc.select('a[href*="/category/"], a[href*="/tag/"]'):
            target = self.site_link(node['href'], final)
            label = node_text(node)
            match = re.fullmatch(rf'/(category|tag)/({SEGMENT})/?', urlsplit(target).path)
            if match and label:
                key = ':'.join(match.groups())
                terms[key] = {'label': label, 'sourceId': key, 'category': 'genre' if match[1] == 'category' else 'tag'}
        return list(terms.values())

    def pages(self, http, url):
        doc, final = self.gallery(http, url)
        return [picture(node, final, ('data-src',)) for node in doc.select('.entry-content img')]


class Junmeitu(SingleGallery):
    cards = Cards('.pic-list > ul > li', 'a[href]', 'p', 'img', next='span + a + a')
    meta = Meta('.news-title, .title', '.pictures img, .news-body img', '.news-info, .picture-details, .introduce',
                tags='.relation_tags > a')

    def __init__(self):
        super().__init__(('4721197766605490540', 'Junmeitu', 'all', 'https://meijuntu.com', True),
                         JPHOTO, JPHOTO, interval=.35)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            route = '/search/' + quote(query, safe='')
        elif tag and re.fullmatch(SEGMENT, tag):
            route = f'/tags/{tag}-6'
        else:
            route = '/beauty/index' if sort == 'updated' else '/beauty/hot'
        return self.card_rows(*self.document(http, f'{self.ROOT}{route}-{page}.html'), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row.update(status='completed', cover=picture(doc.select_one(spec.cover), url, PICS) or row['cover'])
        return row

    def vocabulary(self, http):
        doc, final = self.document(http, self.ROOT + '/beauty/index-1.html')
        rows = []
        for node in doc.select('a[href*="/tags/"]'):
            link = self.site_link(node['href'], final)
            match = re.fullmatch(r'/tags/(.+?)-\d+-\d+\.html', urlsplit(link).path)
            name = node_text(node)
            if match and name and re.fullmatch(SEGMENT, match[1]):
                rows.append({'label': name, 'sourceId': match[1], 'category': 'tag'})
        return rows

    def pages(self, http, url):
        doc, final = self.gallery(http, url)
        body = doc.select_one('.news-body')
        if body:
            return [picture(node, final, PICS) for node in body.select('img')]
        count = max((int(val) for node in doc.select('.pages a') if re.fullmatch(JPAGE, val := node_text(node))), default=1)
        if count > MAX_PAGES:
            raise SourceError('Junmeitu вернул слишком много страниц.')
        path = urlsplit(final).path
        category, name = path.strip('/').split('/', 1)
        stem = re.sub(r'-\d+$', '', name.removesuffix('.html'))
        javascript = '\n'.join(node.string or '' for node in doc.select('script'))
        cid = re.search(r'\bpc_cid\s*=\s*(\d{1,12})\b', javascript)
        pid = re.search(r'\bpc_id\s*=\s*(\d{1,12})\b', javascript)
        first = picture(doc.select_one('.pictures img'), final, PICS)
        results = [first] if first else []
        for page in range(2 if first else 1, count + 1):
            if cid and pid:
                target = query_url(f'{self.ROOT}/ajax_{category}/{stem}-{page}.html', ajax=1, catid=cid[1], conid=pid[1])
                raw, response_url, _ = http.document(target, headers={'Referer': final})
                try:
                    html = json.loads(raw)['pic']
                    node = BeautifulSoup(html, 'html.parser').select_one('img')
                except (KeyError, TypeError, ValueError, RecursionError):
                    raise SourceError('Junmeitu изменил данные страницы галереи.') from None
            else:
                suffix = f'-{page}' if page != 1 else ''
                target = f'{self.ROOT}/{category}/{stem}{suffix}.html'
                page_doc, response_url = self.document(http, target)
                node = page_doc.select_one('.pictures img')
            if response_url != target:
                raise SourceError('Junmeitu подменил страницу галереи.')
            results.append(picture(node, response_url, PICS))
        return results


class V2ph(SingleGallery):
    cards = Cards('.albums-list .card:has(a.media-cover)', 'a.media-cover', '.card-body h6 a',
                  '.card-cover img', next='ul.pagination li.page-item a:-soup-contains("Next")')
    latest_cards = Cards('#latest-albums-title ~ .albums-list .card:has(a.media-cover)', 'a.media-cover',
                         '.card-body h6 a', '.card-cover img', next='ul.pagination li.page-item a:-soup-contains("Next")')
    meta = Meta('h1', '', '.album-intro', tags='dl dt:-soup-contains-own("Tags") + dd a',
                author='dl dt:-soup-contains-own("Vendor", "Model") + dd a')

    def __init__(self):
        path = rf'/album/{SLUG}/?'
        super().__init__(('4511819378822109646', 'V2PH', 'all', 'https://www.v2ph.com', True),
                         path, path, hosts=('v2ph.com',), interval=.35)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        spec = self.cards
        args = {'page': page}
        if query:
            path = '/search/'
            args['q'] = query
        else:
            scope, _, key = tag.partition(':')
            if scope in ('category', 'country') and re.fullmatch(SEGMENT, key):
                path = f'/{scope}/{key}'
            elif sort == 'updated':
                path, spec = '/', self.latest_cards
            else:
                path = '/category/best-quality'
        return self.card_rows(*self.document(http, query_url(self.ROOT + path, **args)), spec)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row.update(status='completed', format='photos')
        return row

    def vocabulary(self, http):
        doc, final = self.document(http, self.ROOT + '/')
        rows = {}
        for node in doc.select('a[href*="/category/"], a[href*="/country/"]'):
            match = re.fullmatch(rf'/(category|country)/({SEGMENT})/?', urlsplit(self.site_link(node['href'], final)).path)
            if match and (text := node_text(node)):
                key = ':'.join(match.groups())
                rows[key] = {'label': text, 'sourceId': key, 'category': 'tag'}
        return list(rows.values())

    def chapters(self, http, doc, final):
        date = release_date(node_text(doc.select_one('dl dt:-soup-contains-own("Date") + dd')), '%Y-%m-%d')
        return [self.chapter(query_url(final, mv_gallery=1), 'Gallery', 1, date)], False

    def pages(self, http, url):
        doc, final = self.gallery(http, url)
        value = node_text(doc.select_one('dl dt:-soup-contains-own("Photos") + dd'))
        count = int(value) if re.fullmatch(r'\d{1,4}', value) else 0
        if count > MAX_PAGES:
            raise SourceError('V2PH вернул слишком большую галерею.')
        if count > 20 and doc.select_one('a[href*="/login"], a[href*="/register"]'):
            raise SourceAccessError('V2PH ограничил полный альбом для гостевой сессии.')
        photos = [picture(node, final) for node in doc.select('.photos-list img')]
        for page in range(2, (count + 9) // 10 + 1):
            next_doc, next_url = self.title_document(http, query_url(final, page=page))
            photos.extend(picture(node, next_url) for node in next_doc.select('.photos-list img'))
        images = list(dict.fromkeys(value for value in photos if value))
        if count and len(images) != count:
            raise SourceError('V2PH не предоставил полный альбом.')
        return images


class XAsiat(SingleGallery):
    meta = Meta('.entry-title', '', '', tags='.info-content a[href*="/albums/"]')

    def __init__(self):
        path = rf'/albums/{SLUG}/?'
        super().__init__(('7187893778775685546', 'XAsiat Albums', 'all', 'https://www.xasiat.com', True),
                         path, path, hosts=('xasiat.com',), interval=.35)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        info = doc.select_one('meta[property="og:description"][content]')
        row.update(description=info['content'] if info else '', status='completed', format='photos')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        start = (page - 1) * 12 + 1
        opts = {'mode': 'async', 'function': 'get_block', 'from': start}
        if query:
            route = '/search/search/'
            opts.update(block_id='list_albums_albums_list_search_result', q=query, from_albums=start)
        else:
            route = '/albums/'
            if re.fullmatch(rf'/albums/(?:tags|categories|models)/{SEGMENT}/?', tag):
                route = tag.rstrip('/') + '/'
            else:
                opts['sort_by'] = 'post_date' if sort == 'updated' else 'album_viewed_week'
            opts['block_id'] = 'list_albums_common_albums_list'
        opts['_'] = int(time() * 1000)
        doc, final = self.document(http, query_url(self.ROOT + route, **opts))
        rows = {}
        for node in doc.select('.list-albums .item a[href]'):
            target = self.site_link(node['href'], final)
            if not self.is_title(target):
                continue
            cover = node.select_one('img')
            label = node.get('title') or (cover.get('alt') if cover else '')
            if label:
                rows[target] = self.record(target, label, picture(cover, final, ('data-original',)))
        more = len(rows) >= 12 or bool(doc.select_one(':is(.pagination, .pages, .pager) a:-soup-contains("Next")'))
        return list(rows.values()), bool(rows) and more

    def pages(self, http, url):
        doc, final = self.gallery(http, url)
        return list(dict.fromkeys(target for node in doc.select('a[href*="/get_image/"]') if (
            target := self.site_link(node['href'], final)) and urlsplit(target).path.startswith('/get_image/')))


class Doujins(SingleGallery):
    meta = Meta('.folder-title a:last-child', '', '', tags='.tag-area:first-of-type a', author='.gallery-artist a')

    def __init__(self):
        super().__init__(('3733450486998805728', 'Doujins', 'en', 'https://doujins.com', True),
                         DOUJINS_PATH, DOUJINS_PATH, interval=.35)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            target = query_url(self.ROOT + '/searches', words=query, page=page, sort='')
        elif tag and re.fullmatch(rf'{SEGMENT}-{JPAGE}', tag):
            target = query_url(self.ROOT + '/' + tag, sort='', page=page)
        elif sort == 'updated':
            day = datetime.now(timezone.utc).date() + timedelta(days=1-3 * (page - 1))
            end = int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())
            data = self.json(http, query_url(self.ROOT + '/folders', start=end - 3 * 86400, end=end))
            rows = []
            for item in data.get('folders') or ():
                url = self.site_link(item.get('link')) if isinstance(item, dict) else ''
                label = item.get('name') if url else None
                if self.is_title(url) and isinstance(label, str) and label:
                    artist = item.get('artistList')
                    rows.append(self.record(url, label, image_url(item.get('thumbnail2'), url),
                                            authors=[artist] if isinstance(artist, str) else []))
            return rows, bool(rows)
        elif page == 1:
            target = self.ROOT + '/top/month'
        else:
            return [], False
        doc, final = self.document(http, target)
        rows = {}
        for node in doc.select('div:not(.premium-folder) > .thumbnail-doujin a.gallery-visited-from-favorites[href]'):
            url = self.site_link(node['href'], final)
            label = node_text(node.select_one('div.title .text'))
            thumb = node.select_one('img')
            if self.is_title(url) and label:
                url_img = picture(thumb, final, ('srcset',))
                if not url_img:
                    url_img = picture(thumb, final)
                rows[url] = self.record(url, label, url_img)
        more = bool(doc.select_one('.pagination li.page-item:last-child:not(.disabled):has(a[href])'))
        return list(rows.values()), more

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['status'] = 'completed'
        tags = doc.select_one('.tag-area')
        if tags:
            row['tags'] = [node_text(node) for node in tags.select('a') if node_text(node)]
        return row

    def chapters(self, http, doc, final):
        translator = node_text(doc.select_one('div.folder-message:-soup-contains("Translated")')).partition('by:')[-1].strip()
        text = node_text(doc.select_one('.text-md-right.text-sm-left > .folder-message')).split(' • ')[0]
        date = release_date(re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', text), '%B %d, %Y')
        return [self.chapter(query_url(final, mv_gallery=1), 'Chapter', 1, date, translator=translator)], False

    def pages(self, http, url):
        doc, final = self.gallery(http, url)
        return [image_url(unescape(node['data-file']), final) for node in doc.select('.doujin[data-file]')]


class Roku(SingleGallery):
    meta = Meta('.site-manga-info__info h6', '', '.site-manga-info__info h6:nth-of-type(2)')

    def __init__(self):
        super().__init__(('6773816792833894188', 'Roku Hentai', 'all', 'https://rokuhentai.com', True),
                         ROKU_PATH, ROKU_PATH, interval=.35)

    def is_title(self, url):
        return super().is_title(url) and self.title_key(url) not in {'_search', '_images'}

    def title_for(self, url):
        return self.ROOT + urlsplit(url).path.rstrip('/')

    def title_identity(self, value):
        return super().title_identity(self.title_for(value))

    def image_style(self, node, base):
        match = re.search(r"""url\(['"]([^'"]+)['"]\)""", node.get('style', '')) if node else None
        return image_url(match[1], base) if match else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and re.fullmatch(r'[a-z][a-z0-9_-]{1,20}:[^"\r\n]{1,90}', tag):
            kind, _, term = tag.partition(':')
            query = ' '.join(value for value in (query, f'{kind}:"{term}"') if value)
        scope = (query, page)
        if page == 1:
            url = query_url(self.ROOT + '/', q=query) if query else self.ROOT + '/'
            docs = [self.document(http, url)[0]]
        else:
            with CURSOR_LOCK:
                cursor = CURSORS.get(scope)
            if not cursor:
                return [], False
            params = {'p': cursor}
            if query:
                params['q'] = query
            target = query_url(self.ROOT + '/_search', **params)
            raw, final, _ = http.document(target, headers={'Referer': self.ROOT + '/'})
            if target != final:
                raise SourceError('Roku перенаправил поиск.')
            try:
                snippets = json.loads(raw)['manga-cards']
                docs = [BeautifulSoup(item, 'html.parser') for item in snippets[:200] if isinstance(item, str)]
            except (KeyError, TypeError, ValueError, RecursionError):
                raise SourceError('Roku изменил продолжение каталога.') from None
        rows = {}
        for doc in docs:
            for node in doc.select('.site-popunder-ad-slot[href]'):
                href = self.site_link(node['href'])
                url = href.rsplit('/', 1)[0] if href else ''
                title = node_text(node.select_one('.site-manga-card__title--primary'))
                count = CAPTION.search(node_text(node.select_one('.mdc-typography--caption:last-child')))
                if not self.is_title(url) or not title or not count:
                    continue
                target = url + '#' + count[1] + ',0'
                rows[url] = self.record(target, title, self.image_style(node.select_one('.mdc-card__media'), url))
        if rows:
            last = self.title_key(next(reversed(rows)))
            with CURSOR_LOCK:
                CURSORS[(query, page + 1)] = last
                while len(CURSORS) > 512:
                    CURSORS.popitem(last=False)
        return list(rows.values()), bool(rows)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['cover'] = self.image_style(doc.select_one('.site-manga-info .mdc-card__media'), url) or row['cover']
        for node in doc.select('.mdc-chip'):
            value = node_text(node)
            kind, _, label = value.partition(':')
            if kind.strip() == 'artist' and label.strip():
                row['authors'].append(label.strip())
            elif label:
                row['tags'].append(value)
        row['status'] = 'completed'
        return row

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        path = urlsplit(target).path.rstrip('/')
        if path.endswith('/0') and self.canonical(self.ROOT + path[:-2]).rstrip('/') == self.title_for(title):
            target = self.title_for(title)
        count = urlsplit(title).fragment.partition(',')[0]
        if target and self.title_key(target) == self.title_key(title):
            target = query_url(self.title_for(title), mv_gallery=1)
            return query_url(target, count=count) if re.fullmatch(JPAGE, count) else target
        return ''

    def chapters(self, http, doc, final):
        count = CAPTION.search(node_text(doc.select_one('.site-manga-info')))
        args = {'mv_gallery': 1}
        if count:
            args['count'] = count[1]
        return [self.chapter(query_url(self.title_for(final), **args), 'Chapter', 1)], False

    def inspect(self, value, http):
        target = self.canonical(value)
        if self.is_title(target):
            count = urlsplit(target).fragment.partition(',')[0]
            result = super().inspect(self.title_for(target), http)
            if re.fullmatch(JPAGE, count):
                chapter = self.site_link(result['episodes'][0]['url'])
                result['episodes'][0]['url'] = self.reader_url(query_url(chapter, count=count))
            return result
        return super().inspect(target, http)

    def pages(self, http, url):
        doc, final = self.gallery(http, url)
        match = CAPTION.search(node_text(doc.select_one('.site-manga-info')))
        val = match[1] if match else param(url, 'count')
        if not re.fullmatch(JPAGE, val) or int(val) > MAX_PAGES:
            raise SourceError('Roku не предоставил число страниц.')
        key = self.title_key(final)
        return [f'{self.ROOT}/_images/pages/{key}/{index}.jpg' for index in range(int(val))]


SOURCES = (KingComix(), Junmeitu(), V2ph(), XAsiat(), Doujins(), Roku())
