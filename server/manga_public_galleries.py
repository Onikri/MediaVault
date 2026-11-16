"""Standalone gallery catalogues with public HTML and WordPress routes."""

import json
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit, urlunsplit

from manga_direct_articles import ARTICLE, Article
from manga_direct_catalogues import Browse, DirectCatalogue, Layout, SLUG
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, Meta, picture
from manga_source_tags import unique
from manga_webcomics import param, query_url
from source_parser import SourceError


POSTS = '/wp-json/wp/v2/posts'
TERMS = '/wp-json/wp/v2/categories'
POPULAR = '/wp-json/wordpress-popular-posts/v1/popular-posts'
FSI = {'fsicomics.com', 'es.fsicomics.com', 'de.fsicomics.com', 'fr.fsicomics.com', 'it.fsicomics.com'}
COSPLAY = {'cosplaytele.com', 'www.cosplaytele.com'}
EVERIA = 'everia.club'
SIZE = 20
KEY = r'[1-9]\d{0,13}'
PAGER = 'a[rel=next], a.next.page-number'
GALLERY = rf'/g/({KEY})/?'
FSI_FIELDS = 'title,link,categories,_embedded,_links.wp:featuredmedia'


def public_api(host, path, query):
    args = parse_qs(query)
    if host == EVERIA:
        if path == POSTS:
            return ({'page', 'per_page', '_embed'} <= set(args) <= {'page', 'per_page', '_embed', 'search', 'categories', 'tags'}
                    and args['per_page'] == ['20'] and args['_embed'] == ['wp:featuredmedia']
                    and len(args['page']) == 1 and bool(re.fullmatch(KEY, args['page'][0]))
                    and all(len(v) == 1 and 1 <= len(v[0]) <= 160 for v in args.values()))
        return (path == TERMS and query == 'per_page=100&hide_empty=true'
                or path == '/wp-json/wp/v2/tags' and query == 'per_page=100&hide_empty=true&orderby=count&order=desc')
    if host not in FSI | COSPLAY or not all(len(v) == 1 and len(v[0]) <= 180 for v in args.values()):
        return False
    if path == POPULAR:
        required = {'limit', 'offset', 'range', 'embed', '_embed', '_fields'}
        return (required <= set(args) <= required | {'order_by'} and args['limit'] == ['20']
                and bool(re.fullmatch(r'\d{1,6}', args['offset'][0])) and args['embed'] == ['true']
                and args['_embed'] == ['wp:featuredmedia']
                and args['range'] == (['last30days'] if host in FSI else ['last7days'])
                and args.get('order_by', ['views']) == ['views']
                and args['_fields'] == [FSI_FIELDS if host in FSI else FSI_FIELDS.replace('categories,', '')])
    if host not in FSI:
        return False
    if path == POSTS:
        return (set(args) <= {'page', 'per_page', '_embed', '_fields', 'search', 'tags', 'categories', 'orderby'}
                and args.get('per_page') == ['20'] and args.get('_embed') == ['wp:featuredmedia']
                and args.get('_fields') == [FSI_FIELDS] and len(args.get('page', [])) == 1
                and bool(re.fullmatch(KEY, args['page'][0])))
    if path == TERMS:
        return (set(args) == {'per_page', 'page', '_fields'} and args['per_page'] == ['100']
                and args['_fields'] == ['id,parent,name,slug'] and bool(re.fullmatch(KEY, args['page'][0])))
    return (path == '/wp-json/wp/v2/tags' and set(args) == {'search', 'per_page', '_fields'}
            and args['per_page'] == ['100'] and args['_fields'] == ['id,name,slug'])


class WordPressGallery(Article):
    def __init__(self, identity):
        self.fsi = urlsplit(identity[3]).hostname in FSI
        self.package = 'fsicomics' if self.fsi else 'cosplaytele'
        layout = Layout(
            ARTICLE, ARTICLE, Cards('main div.box', 'h5 a[href]', next=PAGER),
            Meta('h1.s-title' if self.fsi else '.entry-title', '.entry-content img',
                 '.entry-content > p.wp-block-paragraph', tags='a[rel=tag]' if self.fsi else '#main a[href*="/tag/"]',
                 genres='#main a[href*="/category/"]' if not self.fsi else ''),
            Archive(''), '.entry-content .wp-block-gallery img' if self.fsi else '.gallery-item img',
            Browse('/page/{page}/'), Browse('/page/{page}/', (('s', '{query}'),)),
            title_path='/', tag_index='/explore-categories/', tag_anchor='#main a[href*="/category/"]',
        )
        DirectCatalogue.__init__(self, identity, layout)

    def is_title(self, url):
        return urlsplit(url).path.strip('/') not in {'page', 'genre', 'tag', 'category', 'explore-categories', 'search'} and super().is_title(url)

    def get_json(self, http, path, **args):
        target = query_url(self.ROOT + path, **args)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, headers = http.document(target, headers={'Referer': self.ROOT + '/'}, action='native-series-json')
        if final != target:
            raise SourceError('Источник перенаправил запрос публичного каталога.')
        try:
            result = json.loads(raw)
            if not isinstance(result, list):
                raise ValueError('Not a list')
            return result, int(headers.get('X-WP-TotalPages', 0))
        except (ValueError, TypeError):
            raise SourceError('Источник изменил формат каталога WordPress.') from None

    def post_records(self, posts):
        rows = []
        for post in posts:
            if not isinstance(post, dict) or self.LANGUAGE == 'en' and self.fsi and 320 in (post.get('categories') or []):
                continue
            url = self.site_link(post.get('link'))
            title = unescape((post.get('title') or {}).get('rendered') or '')
            if not self.is_title(url) or not title:
                continue
            media = (post.get('_embedded') or {}).get('wp:featuredmedia') or []
            cover = media[0].get('source_url') if media and isinstance(media[0], dict) else ''
            rows.append(self.record(url, title, image_url(cover, url)))
        return rows

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        fields = FSI_FIELDS if self.fsi else FSI_FIELDS.replace('categories,', '')
        if not query and not tag and sort == 'popular':
            options = {'limit': SIZE, 'offset': (page - int(self.fsi)) * SIZE, 'range': 'last30days' if self.fsi else 'last7days',
                       'embed': 'true', '_embed': 'wp:featuredmedia', '_fields': fields}
            if self.fsi:
                options['order_by'] = 'views'
            posts, _ = self.get_json(http, POPULAR, **options)
            return self.post_records(posts), len(posts) >= SIZE
        if not self.fsi:
            if tag and not re.fullmatch(rf'(?:category|tag)/{SEGMENT}', tag):
                raise SourceError('Некорректная метка каталога.')
            url = self.ROOT + (f'/{tag}' if tag else '') + f'/page/{page}/'
            return self.card_rows(*self.document(http, query_url(url, s=query) if query else url), self.layout.cards)
        options = {'page': page, 'per_page': SIZE, '_embed': 'wp:featuredmedia', '_fields': fields}
        if query:
            options['search'] = query
        if tag.startswith('category:') and re.fullmatch(KEY, tag[9:]):
            options['categories'] = tag[9:]
        elif tag:
            terms, _ = self.get_json(http, '/wp-json/wp/v2/tags', search=tag[:120], per_page=100, _fields='id,name,slug')
            match = next((row for row in terms if isinstance(row, dict) and any(
                str(row.get(key) or '').casefold() == tag.casefold() for key in ('slug', 'name'))), None)
            if not match or not re.fullmatch(KEY, str(match.get('id'))):
                return [], False
            options['tags'] = match['id']
        posts, pages = self.get_json(http, POSTS, **options)
        return self.post_records(posts), page < pages if pages else len(posts) >= SIZE

    def vocabulary(self, http):
        if not self.fsi:
            doc, _ = self.document(http, self.ROOT + '/explore-categories/')
            result = {}
            for node in doc.select('#main a[href]'):
                url = self.site_link(node['href'], self.ROOT)
                path, label = urlsplit(url).path.strip('/'), node_text(node)
                if label and re.fullmatch(rf'(?:category|tag)/{SEGMENT}', path):
                    result[path] = {'label': label, 'sourceId': path, 'category': 'tag' if path.startswith('tag/') else 'genre'}
            return list(result.values())
        result = []
        for page in range(1, 25):
            rows, pages = self.get_json(http, TERMS, per_page=100, page=page, _fields='id,parent,name,slug')
            parent = 318 if self.LANGUAGE == 'en' else 0
            result.extend({'label': unescape(row['name']), 'sourceId': 'category:' + str(row['id']), 'category': 'genre'}
                          for row in rows if isinstance(row, dict) and row.get('parent') == parent
                          and re.fullmatch(KEY, str(row.get('id'))) and isinstance(row.get('name'), str))
            if page >= pages:
                break
        return result

    def article_pages(self, http, doc, final):
        rows = [picture(node, final, ('data-src',)) for node in doc.select(self.layout.reader)]
        if self.fsi:
            rows = [re.sub(r'-scaled(?=\.[a-zA-Z]+(?:\?|$))', '', row) for row in rows]
        return list(dict.fromkeys(filter(None, rows)))


class ThreeHentai(Article):
    LANGUAGE_NAMES = {'en': 'english', 'ja': 'japanese', 'ko': 'korean', 'zh': 'chinese', 'es': 'spanish',
                      'pt': 'portuguese', 'id': 'indonesian', 'jv': 'javanese', 'tl': 'tagalog', 'vi': 'vietnamese',
                      'th': 'thai', 'my': 'burmese', 'tr': 'turkish', 'ru': 'russian', 'uk': 'ukrainian',
                      'pl': 'polish', 'de': 'german', 'it': 'italian', 'fr': 'french', 'nl': 'dutch',
                      'cs': 'czech', 'hu': 'hungarian', 'bg': 'bulgarian', 'is': 'icelandic', 'la': 'latin', 'ar': 'arabic'}

    def __init__(self, identity):
        self.package = 'hentai3'
        path = rf'/d/({KEY})/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('a[href*="/d/"]:has(div.title)', '', 'div.title', next='a[rel=next]'),
            Meta('h1', 'main img, img', tags='a[href*="/tags/"], a[href*="/characters/"], a[href*="/series/"]',
                 author='a[href*="/groups/"], a[href*="/artists/"]'),
            Archive(''), 'img[src]:not([class], [src*="thumb"], [src*="cover"])', Browse('/search'), title_path='/d/',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        lang = self.LANGUAGE_NAMES.get(self.LANGUAGE, '')
        options = {'sort': 'popular'} if sort == 'popular' and not query else {}
        if lang and not query and not tag:
            endpoint = self.ROOT + f'/language/{lang}/' + (str(page) if page > 1 else '')
        else:
            clauses = [query or 'pages:>0']
            if lang:
                clauses.append('language:' + lang)
            if tag:
                clauses.append("tag:'" + tag.replace("'", '')[:120] + "'")
            endpoint = self.ROOT + '/search'
            options.update(q=' '.join(clauses), page=page)
        return self.card_rows(*self.document(http, query_url(endpoint, **options)), self.layout.cards)

    def article_pages(self, http, doc, final):
        rows = [picture(node, final) for node in doc.select(self.layout.reader)]
        return list(dict.fromkeys(re.sub(r't(?=\.(?:jpg|jpeg|png|webp)(?:\?|$))', '', row) for row in rows if row))


class MyHentaiGallery(Article):
    def __init__(self, identity):
        self.package = 'myhentaigallery'
        path = rf'/(?:gallery/thumbnails|g|a)/({KEY})/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('div.comic-inner', 'a[href]', 'h2', next='li.next'),
            Meta('div.comic-header h1', '.comic-listing .comic-inner img',
                 genres='div.comic-header div:-soup-contains-own("categories") a',
                 tags='div.comic-header div:-soup-contains-own("parodies") a',
                 author='div.comic-header div:-soup-contains-own("artists") a'),
            Archive(''), 'div.comic-thumb img[src]', Browse('/views/{page}'),
            Browse('/search/{page}', (('query', '{query}'),)), Browse('/gpage/{page}'),
            Browse('/g/category/{tag}/{page}'), title_path='/g/',
        ))

    def article_pages(self, http, doc, final):
        return [picture(node, final).replace('/thumbnail/', '/original/') for node in doc.select(self.layout.reader)]


class MissKon(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            ARTICLE, rf'/{SLUG}/({KEY})/?',
            Cards('article.item-list', '.post-box-title a[href]', '.post-box-title', next='.current + a'),
            Meta('article > .post-inner .post-title', '.post-thumbnail img', tags='.post-tag > a'),
            Archive(''), 'div.post-inner > div.entry > p > img[data-src]', Browse('/top3/', one_page=True),
            Browse('/page/{page}/', (('s', '{query}'),)), Browse('/page/{page}'),
            Browse('/tag/{tag}/', one_page=True), title_path='/', suffix='/',
        ))

    def chapters(self, http, doc, url):
        options = [int(value) for anchor in doc.select('.page-link a.post-page-numbers')
                   if re.fullmatch(r'\d{1,4}', value := node_text(anchor))]
        count = min(max(options, default=1), 500)
        return [self.chapter(f'{url.rstrip("/")}/{page}', f'Page {page}', page) for page in range(1, count + 1)], False


class EveriaGallery(WordPressGallery):
    def __init__(self, identity):
        self.fsi = False
        self.package = 'everiaclub'
        path = rf'/(\d{{4}}/\d{{2}}/\d{{2}}/{SEGMENT}|{SEGMENT})/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('.wli_popular_posts-class li', 'h3 > a[href]', 'h3'),
            Meta('.entry-title', '.entry-content img', '.entry-title', tags='.post-tags > a'),
            Archive(''), '.entry-content img', Browse('/'), title_path='/',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if sort == 'popular' and not (query or tag):
            if page != 1:
                return [], False
            return self.card_rows(*self.document(http, self.ROOT + '/'), self.layout.cards)
        args = {'page': page, 'per_page': SIZE, '_embed': 'wp:featuredmedia'}
        if query:
            args['search'] = query
        if tag:
            name, _, key = tag.partition(':')
            if name not in {'category', 'tag'} or not re.fullmatch(KEY, key):
                raise SourceError('Некорректная метка каталога.')
            args['categories' if name == 'category' else 'tags'] = key
        rows, total = self.get_json(http, POSTS, **args)
        return self.post_records(rows), page < total if total else len(rows) >= SIZE

    def vocabulary(self, http):
        results = []
        for category, path, options in (('genre', TERMS, {}), ('tag', '/wp-json/wp/v2/tags', {'orderby': 'count', 'order': 'desc'})):
            rows, _ = self.get_json(http, path, per_page=100, hide_empty='true', **options)
            results.extend({'label': unescape(row['name']), 'sourceId': ('category' if category == 'genre' else 'tag')
                            + ':' + str(row['id']), 'category': category} for row in rows if isinstance(row, dict)
                           and isinstance(row.get('name'), str) and re.fullmatch(KEY, str(row.get('id'))))
        return results

    def article_pages(self, http, doc, final):
        base = urlsplit(final).path.rstrip('/')
        links = {1: final}
        for anchor in doc.select('.page-links a.post-page-numbers[href]'):
            target = self.site_link(anchor['href'], final)
            path = urlsplit(target).path
            match = re.fullmatch(re.escape(base) + r'/([1-9]\d{0,2})/?', path)
            idx = match[1] if match else param(target, 'page') if path.rstrip('/') == base else ''
            if re.fullmatch(r'[1-9]\d{0,2}', idx):
                links.setdefault(int(idx), target)
        pages = []
        for _, url in sorted(links.items()):
            section, base = (doc, final) if url == final else self.document(http, url)
            pages.extend(picture(img, base, ('data-lazy-src', 'data-src'))
                         for img in section.select('.entry-content img:not(noscript img)'))
        return list(dict.fromkeys(filter(None, pages)))


class Hennojin(DirectCatalogue):
    def __init__(self, identity):
        self.nonce_page = '/home'
        series = rf'/((?:(?!home/|tags/|tag/|category/|search/|artists/|group/){SEGMENT}/){{0,4}}{SEGMENT})/?'
        super().__init__(identity, Layout(
            series, series,
            Cards('.grid-items .layer-content', '.title_link > a[href]', next='.paginate .next'),
            Meta('h1, .manga-title', '.manga-thumbnail > img', '.manga-subtitle + p + p',
                 tags='.tags-list a[href*="/parody/"], .tags-list a[href*="/tags/"], .tags-list a[href*="/character/"]',
                 author='.tags-list a[href*="/group/"], .tags-list a[href*="/artist/"]'),
            Archive(''), '.slideshow-container > img', Browse('/home/page/{page}'),
        ))

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'view') == 'multi'

    def is_title(self, url):
        return super().is_title(url) and not self.is_chapter(url) and urlsplit(url).path.rstrip('/') != self.nonce_page

    def title_for(self, url):
        from manga_direct_payloads import segment
        slug = param(url, 'mv_parent')
        if slug and slug.startswith('/') and all(segment(part) for part in slug.strip('/').split('/')):
            return self.ROOT + slug
        return ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        suffix = '/' if self.LANGUAGE == 'ja' else ''
        url = f'{self.ROOT}/home/page/{page}{suffix}'
        args = {'archive': 'raw'} if self.LANGUAGE == 'ja' else {}
        filter_text = query or tag[:120]
        if filter_text:
            doc, _ = self.document(http, self.ROOT + self.nonce_page)
            input = doc.select_one('input#_wpnonce[value]')
            nonce = input['value'] if input else ''
            if not re.fullmatch(r'[A-Za-z0-9_-]{6,100}', nonce):
                raise SourceError('Источник не предоставил параметры поиска.')
            args.update(keyword=filter_text, _wpnonce=nonce)
        return self.card_rows(*self.document(http, query_url(url, **args) if args else url), self.layout.cards)

    def chapters(self, http, doc, url):
        rows = {}
        for anchor in doc.select('a[href]:-soup-contains("Read Online")'):
            target = self.site_link(anchor['href'], url)
            if target:
                target = query_url(target, view='multi', mv_parent=urlsplit(url).path)
                if self.is_chapter(target):
                    rows[target] = self.chapter(target, 'Глава', 1)
        return list(rows.values()), False

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        return query_url(target, view='multi', mv_parent=urlsplit(title).path) if target and self.is_title(title) else ''

    def saved_chapter_matches(self, target, title):
        return self.title_key(title) == self.title_key(self.title_for(target))

    def pages(self, http, url):
        from urllib.parse import parse_qsl, urlencode
        parts = urlsplit(url)
        wire = urlunsplit(parts._replace(query=urlencode([(key, val) for key, val in parse_qsl(parts.query)
                                                         if key != 'mv_parent'])))
        doc, final = self.document(http, wire)
        if urlsplit(final).path.rstrip('/') != parts.path.rstrip('/'):
            raise SourceError('Источник перенаправил запрос на другую галерею.')
        return [picture(node, final) for node in doc.select(self.layout.reader)]
