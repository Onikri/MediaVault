"""Standalone source catalogues backed by public HTML and reader endpoints."""

import ast
import base64
import json
import re
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_raw_adapters import get as raw_get
from manga_second_batch_profiles import IDENTITIES
from manga_series_port import Archive, Cards, Meta, SeriesPort, label_number, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


MANGA = rf'/manga/({SEGMENT})/?'
CHAPTER = rf'/manga/({SEGMENT})/{SEGMENT}/?'
SOURCES = []


class HTML(SeriesPort):
    def __init__(self, key, cards, meta, archive, reader, *, title=MANGA, chapter=CHAPTER, interval=.35):
        super().__init__(IDENTITIES[key], title, chapter, interval=interval)
        self.cards, self.meta, self.archive_spec, self.reader = cards, meta, archive, reader

    def chapters(self, http, doc, url):
        return self.list_chapters(http, doc, url, self.archive_spec)

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return [picture(node, final, ('data-original', 'data-src', 'data-image')) for node in doc.select(self.reader)]

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)


class MangaPill(HTML):
    def __init__(self):
        super().__init__('mangapill', Cards('.grid > div:not([class])', 'a[href^="/manga/"]',
                                          'div.line-clamp-2', next='a.btn.btn-sm[href*="page="]'),
                         Meta('h1, h2', 'div.container > div:first-child > div:first-child > img',
                              'div.container > div:first-child > div:last-child > div:nth-child(2) > p',
                              genres='a[href*="genre="]'),
                         Archive('#chapters > div > a[href]', anchor=''), 'picture img[data-src]',
                         title=rf'/manga/({SEGMENT})(?:/{SEGMENT})?/?',
                         chapter=rf'/chapters/({SEGMENT})(?:/{SEGMENT})+/?')

    def title_key(self, url):
        slug = super().title_key(url)
        return slug.split('-', 1)[0] if slug[:1].isdigit() else slug

    def chapter_key(self, url):
        return super().chapter_key(url).split('-', 1)[0]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        spec = self.cards
        if query or tag:
            url = query_url(self.ROOT + '/search', page=page, q=query, **({'genre': tag[:120]} if tag else {}))
        else:
            if page != 1:
                return [], False
            if sort == 'updated':
                url = self.ROOT + '/chapters'
            else:
                url = self.ROOT + '/'
                spec = Cards('div:has(> h4:-soup-contains("Trending")) > .grid > div:not([class])',
                             self.cards.link, self.cards.title, next='')
        return self.card_rows(*self.document(http, url), spec)


class MangaKatana(HTML):
    def __init__(self):
        super().__init__('mangakatana', Cards('#book_list > div.item', 'div.text > h3 > a',
                                            next='a.next.page-numbers'),
                         Meta('h1.heading', 'div.media div.cover img', '.summary > p', '.alt_name', '.genres > a',
                              author='.author', status='.value.status'),
                         Archive('tr:has(.chapter)', date='.update_time', date_pattern='%b-%d-%Y'), 'img[data-src]')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'search': query, 'search_by': 'book_name'} if query else {'filter': 1, 'include': tag} if tag else {}
        path = f'/manga/page/{page}' if sort == 'popular' and not args else f'/page/{page}'
        return self.card_rows(*self.document(http, query_url(self.ROOT + path, **args)), self.cards)

    def pages(self, http, url):
        for server in ('', 'mk', '3'):
            target = query_url(url, sv=server) if server else url
            try:
                doc, final = self.page_document(http, target)
            except SourceError as error:
                if type(error) is not SourceError or str(error) != 'Источник вернул HTTP 404.':
                    raise
                continue
            for script in doc.select('script'):
                text = script.string or ''
                marker = re.search(r'''data-src['"],\s*([A-Za-z_]\w*)''', text)
                if not marker:
                    continue
                token = re.search(rf'\bvar\s+{re.escape(marker[1])}\s*=\s*(\[[^\[;]*?\])', text)
                if token:
                    try:
                        raw = ast.literal_eval(token[1])
                    except (ValueError, SyntaxError):
                        continue
                    pages = [image_url(value, final) for value in raw]
                    if pages and all(pages):
                        return pages
        return []


class RussianHTML(HTML):
    def __init__(self, key):
        buff = key == 'mangabuff'
        cards = Cards('.cards .cards__item', 'a[href]', '.cards__name') if buff else Cards('.manga-card', 'a[href]', title_attr='title')
        meta = (Meta('h1, .manga__name, .manga-mobile__name', '.manga__img img, img.manga-mobile__image',
                     '.manga__description', '.manga__name-alt > span, .manga-mobile__name-alt > span',
                     '.manga__middle-links a:not(:last-child), .manga-mobile__info a:not(:last-child)', '.tags > .tags__item')
                if buff else Meta('div.card header .text-base span, h1', 'div.card img.w-full', '.manga-description',
                                  genres='span:-soup-contains("Жанр:") a', status='span:-soup-contains("Статус:")'))
        archive = (Archive('a.chapters__item', anchor='', date='.chapters__add-date', date_pattern='%d.%m.%Y') if buff
                   else Archive('.chapter-item', title='span.chapter-title', date='span.chapter-date', date_pattern='%d.%m.%Y'))
        super().__init__(key, cards, meta, archive, '.reader__pages img' if buff else 'img.page-image',
                         chapter=rf'/manga/({SEGMENT})(?:/{SEGMENT})+/?|/(?:chapter|chapters)/({SEGMENT})(?:/{SEGMENT})*/?')
        self.buff = buff

    def is_chapter(self, url):
        return super().is_chapter(url) and not urlsplit(url).path.rstrip('/').endswith('/chaptersList')

    def chapter_key(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return next((value for value in match.groups() if value), '') if match else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            args = {'q': query, 'page': page}
            if self.buff:
                args['type'] = 'manga'
            url = query_url(self.ROOT + '/search', **args)
        else:
            args = {'page': page}
            if self.buff:
                args['sort'] = 'updated_at' if sort == 'updated' else 'real_views'
            else:
                args['sortBy'] = '-last_chapter_at' if sort == 'updated' else 'popular'
            if tag:
                kind, _, identity = tag.partition(':')
                if not identity.isdecimal() or kind not in {'genres', 'tags'} or not self.buff and kind != 'genres':
                    raise SourceError('Некорректный фильтр каталога.')
                args[kind + '[]' if self.buff else kind] = identity if self.buff else '[' + identity + ']'
            url = query_url(self.ROOT + '/manga', **args)
        nxt = '.pagination a[aria-label*="Вперёд"]:not([aria-disabled=true]), ul li:-soup-contains("Вперёд") > a, .pagination__button a:-soup-contains("Вперёд")'
        spec = (Cards('article.card', 'a.card-about', 'div.post-description p.card-title, a > h2.entry-title', next=nxt)
                if query and not self.buff else Cards(self.cards.rows, self.cards.link, self.cards.title,
                                                       title_attr=self.cards.title_attr, next=nxt))
        return self.card_rows(*self.document(http, url), spec)

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/manga/')
        result = []
        for kind, cat in (('genres', 'genre'), ('tags', 'tag')):
            for node in doc.select(f'select[name="{kind}[]"] option[value], select[name={kind}] option[value]'):
                if node['value'].isdigit() and node_text(node):
                    result.append({'label': node_text(node), 'sourceId': f'{kind}:{node["value"]}', 'category': cat})
        return result

    def saved_chapter_matches(self, target, title):
        return super().saved_chapter_matches(target, title) or self.confirm_archive_membership(target, title)

    def chapters(self, http, doc, url):
        if self.buff:
            series = doc.select_one('.manga[data-id]')
            if doc.select_one('.load-chapters-trigger') and series:
                token = doc.select_one('meta[name*=csrf-token][content]')
                if token is None:
                    home, _ = self.document(http, self.ROOT + '/')
                    token = home.select_one('meta[name*=csrf-token][content]')
                if token is None:
                    raise SourceError('MangaBuff не предоставил токен публичной формы глав.')
                raw, _, _ = http.document(self.ROOT + '/chapters/load', method='POST', action='native-series-form',
                                          headers={'Referer': url, 'X-CSRF-TOKEN': token['content']}, data={'manga_id': series['data-id']})
                try:
                    part = json.loads(raw)['content']
                except (ValueError, KeyError, TypeError):
                    raise SourceError('MangaBuff не предоставил дополнительные главы.') from None
                doc = BeautifulSoup(str(doc) + part, 'html.parser')
            return super().chapters(http, doc, url)
        sub, _ = self.document(http, query_url(url, tab='chapters'))
        if 'Главы удалены по требованию правообладателя' in node_text(sub):
            raise SourceAccessError('Оглавление недоступно на стороне источника.')
        endpoint = url.rstrip('/') + '/chaptersList'
        first, _ = self.document(http, endpoint)
        pages = [int(v) for node in first.select('li.page-item') if (v := node_text(node)).isdecimal()]
        last = max(pages, default=1)
        rows = {}
        for page in range(1, min(last, 80) + 1):
            part = first if page == 1 else self.document(http, query_url(endpoint, page=page))[0]
            result, _ = self.list_chapters(http, part, url, self.archive_spec)
            rows.update((entry['url'], entry) for entry in result)
        return self.order(rows), last > 80


class RawBaka(HTML):
    def __init__(self):
        super().__init__('rawbaka', Cards('div.manga-grid article.manga-card, article.search-result-card',
                                        'h2 a, h3 a', cover='a.cover img', next='a.next.page-numbers'),
                         Meta('section.manga-hero h1.manga-title', 'section.manga-hero .cover img',
                              'section.manga-hero .manga-summary', status='section.manga-hero .status-pill'),
                         Archive('div.chapter-list div.chapter-row', date='time'), 'div.reader-images img',
                         chapter=rf'/manga/({SEGMENT})/{SEGMENT}/?|/chapter/({SEGMENT})/?')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        extra = f'page/{page}/' if page > 1 else ''
        if query:
            url = query_url(self.ROOT + '/' + extra, s=query, post_type='manga')
        elif sort == 'updated':
            url = query_url(self.ROOT + '/', latest_page=page)
        else:
            url = self.ROOT + '/manga/' + extra
        return self.card_rows(*self.document(http, url), self.cards)

    def saved_chapter_matches(self, target, title):
        return super().saved_chapter_matches(target, title) or self.confirm_archive_membership(target, title)


class TCB(HTML):
    def __init__(self):
        super().__init__('tcbscans', Cards('div.bg-card', 'a[href].text-white', next=''),
                         Meta('div.order-1 h1', 'div.order-1 img', 'div.order-1 p'),
                         Archive('div.grid a[href*="/chapters/"]', anchor='', title='div.font-bold:not(.flex)'),
                         'picture img, .image-container img', title=rf'/mangas/({SEGMENT})(?:/{SEGMENT})?/?',
                         chapter=rf'/chapters/({SEGMENT})(?:/{SEGMENT})+/?')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1 or tag:
            return [], False
        cards, _ = self.card_rows(*self.document(http, self.ROOT + '/projects'), self.cards)
        return [row for row in cards if query.casefold() in row['title'].casefold()], False

    def saved_chapter_matches(self, target, title):
        return self.confirm_archive_membership(target, title)


class MangaRw(HTML):
    def __init__(self):
        super().__init__('mangarw', Cards('a[href^="/manga/"]', '', title_attr='title'),
                         Meta('h1', 'img[src*=covers]', 'div.description, p.synopsis', genres='a[href*=genre]'),
                         Archive('option'), 'img[src*=mangabuzz], img[data-src*=mangabuzz]',
                         title=rf'/manga/{SEGMENT}/(\d+)/?', chapter=r'/(read)', interval=1/3)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        path = '/browse' if query or sort == 'updated' else '/'
        url = query_url(self.ROOT + path, page=page, **({'search': query} if query else {}))
        doc, final = self.document(http, url)
        spec = Cards(self.cards.rows, '', title_attr='title', next=f'a[href*="page={page+1}"]')
        for a in doc.select(self.cards.rows):
            a['title'] = a.get('title') or node_text(a)
        return self.card_rows(doc, final, spec)

    def chapters(self, http, _doc, url):
        endpoint = query_url(self.ROOT + '/api/v1/chapters', id=self.title_key(url))
        raw, final, _ = http.document(endpoint, headers={'Referer': url}, action='native-series-html-api')
        if final != endpoint:
            raise SourceError('Manga Rw перенаправил запрос оглавления.')
        rows = {}
        for node in BeautifulSoup(raw, 'html.parser').select('option[value]'):
            value, name = node['value'], node_text(node)
            if value.isdecimal() and name:
                link = query_url(self.ROOT + '/read', id=value)
                rows[link] = self.chapter(link, name, label_number(name, re.compile(r'第(\d+(?:\.\d+)?)話')))
        return self.order(rows), False

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'id').isdecimal()

    def saved_chapter_matches(self, target, title):
        return self.confirm_archive_membership(target, title)

    def chapter_identity(self, url):
        return (super().chapter_identity(url), param(url, 'id'))

    def pages(self, http, url):
        return list(dict.fromkeys(super().pages(http, url)))


class SenManga(SeriesPort):
    def __init__(self):
        super().__init__(IDENTITIES['senmanga'], MANGA, rf'/manga/({SEGMENT})/chapter-({SEGMENT})/?')

    def item(self, raw, slug):
        title = raw.get('title') or slug
        aliases = re.split(r'\s*[;|]\s*', raw.get('alt_name') or '')
        return self.record(self.ROOT + '/manga/' + slug, title, raw.get('cover'), aliases=aliases,
                           description=raw.get('description') or '', status=raw.get('status') or '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page}
        if query:
            args['s'] = query
        if tag:
            return [], False
        latest = sort == 'updated' and not query
        if latest and page > 1:
            return [], False
        if not query:
            args['order'] = 'Popular'
        raw = raw_get(self.ROOT + '/api/home' if latest else query_url(self.ROOT + '/api/directory', **args), http)
        rows = [self.item(entry, entry['slug']) for entry in raw.get('series', [])
                if isinstance(entry.get('slug'), str) and re.fullmatch(SEGMENT, entry['slug'])]
        return rows, type(raw.get('totalPages')) is int and page < raw['totalPages']

    def details(self, http, url):
        slug = self.title_key(self.canonical(url))
        if not slug:
            raise SourceError('Некорректный адрес Sen Manga.')
        return self.item(raw_get(self.ROOT + '/api/manga/' + slug, http), slug)

    def inspect(self, value, http):
        url = self.canonical(value)
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        slug = match[1] if match else self.title_key(url)
        if not slug:
            raise SourceError('Некорректная ссылка Sen Manga.')
        info = raw_get(self.ROOT + '/api/manga/' + slug, http)
        row = self.item(info, slug)
        rows = {}
        for entry in info.get('chapterList') or ():
            part = str(entry.get('url') or '')
            if not re.fullmatch(SEGMENT, part) or match and match[2] != part:
                continue
            link = self.ROOT + f'/manga/{slug}/chapter-{part}/'
            rows[link] = self.chapter(link, entry.get('title') or part, number(part),
                                      release_date(str(entry.get('datetime') or '')[:10], '%Y-%m-%d'))
        if match and not rows:
            raise SourceError('Глава отсутствует в публичном оглавлении Sen Manga.')
        pages = []
        if match:
            data = raw_get(self.ROOT + '/api/read/' + slug + '/' + match[2], http)
            pages = [image_url(path, url) for path in data.get('pages', ())]
            if not pages or not all(pages):
                raise SourceError('Sen Manga не предоставил открытые страницы.')
        return self.reader_result(row, url, self.order(rows), pages)

    def saved_chapter(self, row, root, title):
        value = row.get('realUrl') or row.get('url')
        if isinstance(value, str) and re.fullmatch(rf'{SEGMENT}/{SEGMENT}', value):
            slug, part = value.split('/')
            return self.ROOT + f'/manga/{slug}/chapter-{part}/'
        return super().saved_chapter(row, root, title)


class Toonkor(HTML):
    def __init__(self):
        super().__init__('toonkor', Cards('.section-item-inner', '.section-item-title a', '.section-item-title h3', next=''),
                         Meta('table.bt_view1 td.bt_title', '.bt_thumb img', 'td.bt_over', author='td.bt_label span.bt_data'),
                         Archive('table.web_list tr'), '', title=rf'/({SEGMENT})/?', chapter=rf'/({SEGMENT})/?')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1 or tag:
            return [], False
        url = self.ROOT + '/' + quote('웹툰') + '/' + quote('연재')
        if query:
            url = query_url(self.ROOT + '/bbs/search.php', sfl='wr_subject||wr_content', stx=query)
        elif sort != 'updated':
            url = query_url(url, fil='인기')
        return self.card_rows(*self.document(http, url), self.cards)

    def chapters(self, http, doc, url):
        output = {}
        chapter_number = re.compile(r'(\d+(?:\.\d+)?)\s*(?:화|회)')
        for tr in doc.select('table.web_list tr:has(td.content__title)'):
            cell = tr.select_one('td.content__title[data-role]')
            target = self.site_link(cell['data-role'], url) if cell else ''
            if not self.is_chapter(target):
                continue
            name = node_text(cell)
            output[target] = self.chapter(target, name, label_number(name, chapter_number),
                                          release_date(node_text(tr.select_one('td.episode__index')), '%Y-%m-%d'))
        return self.order(output), False

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка Toonkor.')
        doc, final = self.document(http, url)
        enc = re.search(r'''\btoon_img\s*=\s*['"]([A-Za-z0-9+/=\s]+)['"]''', str(doc))
        if enc:
            try:
                text = base64.b64decode(re.sub(r'\s+', '', enc[1]), validate=True).decode()
            except (ValueError, UnicodeError):
                raise SourceError('Toonkor изменил формат указателя страниц.') from None
            pages = [image_url(node['src'], final) for node in BeautifulSoup(text, 'html.parser').select('img[src]')]
            if not pages or not all(pages):
                raise SourceError('Toonkor не предоставил открытые изображения.')
            name = node_text(doc.select_one('h1, .view-title, title'))
            return self.reader_result(self.record(url, name or unquote(self.title_key(url))), url,
                                      [self.chapter(url, name, 0)], pages)
        chapters, _ = self.chapters(http, doc, final)
        return self.reader_result(self.metadata(doc, final, self.meta), url, chapters, [])

    def saved_chapter_matches(self, target, title):
        return self.confirm_archive_membership(target, title)


SOURCES = (MangaPill(), MangaKatana(), RussianHTML('mangapoisk'), RussianHTML('mangabuff'),
           SenManga(), MangaRw(), Toonkor(), RawBaka(), TCB())
