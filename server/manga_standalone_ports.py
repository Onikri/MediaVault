"""Public HTML series and reader manifests from pinned standalone extensions."""

import base64
import binascii
import json
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_articles import Article
from manga_direct_catalogues import Browse, CHAPTER, DirectCatalogue, JoomlaGallery, Layout, MANGA, SLUG, query
from manga_direct_payloads import JsonSeries, items, segment
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, MAX_PAGES, Meta, number, picture
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceError


class DokiRaw(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            MANGA, CHAPTER, Cards('div[class*="manga-item_item"]', 'a[href*="/manga/"]', 'h3', next=''),
            Meta('div[class*="manga-detail_boxInfo"] h1', 'img[src*=cover]', 'div.work-break p:last-of-type',
                 genres='tr:-soup-contains("ジャンル") a[href*=genre]'),
            Archive('a:has(div[class*="manga-detail_chapter"])', anchor='', title='div[class*="manga-detail_chapter"] span:first-of-type'),
            'div.page-chapter img', Browse('/hot', (('page', '{page}'),)),
            query('/search/manga', 'keyword'),
            Browse('/search/manga', (('status', '-1'), ('sort', '15'), ('page', '{page}'))),
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or tag:
            root = self.ROOT + '/search/manga'
            args = {'page': page}
            if query:
                args['keyword'] = query
            if tag:
                args['genre'] = tag[:120]
            url = query_url(root, **args)
        else:
            route = self.layout.latest if sort == 'updated' else self.layout.popular
            url = route.url(self.ROOT, page, query, tag)
        rows, _ = self.card_rows(*self.document(http, url), self.layout.cards)
        return rows, len(rows) == (20 if query or tag or sort == 'updated' else 36)

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return [picture(node, final, ('data-cdn', 'data-original')) for node in doc.select(self.layout.reader)]


class HentaiHere(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/(?:doujinshi|original|imageset)/{SLUG}/?', rf'/(?:read|doujinshi|original|imageset|m)/{SLUG}(?:/{SEGMENT})*/?',
            Cards('article.card[data-card]', 'a[href]', 'h3', next='a[rel=next]'),
            Meta('h1#book-title', '', tags='ul[aria-label="Tags"] a',
                 author='dl[aria-label="Details"] dt:-soup-contains("Artist") + dd, dl[aria-label="Details"] dt:-soup-contains("Author") + dd',
                 status='dl[aria-label="Details"] dt:-soup-contains("Status") + dd'),
            Archive(''), '', Browse('/browse/newest/page-{page}', first_path='/browse/newest'),
            query('/search', 'q'), Browse('/browse/newest/page-{page}'), title_path='/doujinshi/',
        ))

    def canonical(self, value):
        target = super().canonical(value)
        if match := re.fullmatch(r'/m/(\d{1,15})/?', urlsplit(target).path):
            return f'{self.ROOT}/doujinshi/{match[1]}'
        return target

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_title(url) and urlsplit(url).query:
            pages = self.pages(http, url)
            if not 1 <= len(pages) <= MAX_PAGES or not all(pages):
                raise SourceError('Источник не предоставил полный список страниц.')
            title = url.split('?', 1)[0]
            row = self.details(http, title)
            return self.reader_result(row, url, [self.chapter(url)], pages)
        return super().inspect(value, http)

    def chapters(self, http, doc, url):
        rows = {}
        for item in doc.select('#preview-chapter option[data-read]'):
            target = self.site_link(item['data-read'], url)
            if self.is_chapter(target) and target != url:
                name = node_text(item).removesuffix('(latest)').strip()
                rows[target] = self.chapter(target, name)
        return self.order(rows), False

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        script = doc.select_one('script[data-reader-data]')
        if not script:
            return []
        try:
            images = json.loads(script.string)['images']
        except (TypeError, ValueError, KeyError):
            raise SourceError('Источник изменил формат страниц читалки.') from None
        return [image_url(value, final) for value in images] if isinstance(images, list) else []


class MangaTown(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            MANGA, CHAPTER,
            Cards('li:has(a.manga_cover)', 'p.title a',
                  next='div.next-page a.next:not([href^=javascript]), .page-nav a:-soup-contains("next"):not([href^=javascript])'),
            Meta('div.article_content h1', 'div.detail_info img', 'span#show',
                 genres='div.article_content li:has(b:-soup-contains("genre")) a',
                 author='div.article_content li:has(b:-soup-contains("author"),b:-soup-contains("artist")) a',
                 status='div.article_content li:has(b:-soup-contains("status"))'),
            Archive('ul.chapter_list li:has(a[href])', date='span.time', date_pattern='%b %d,%Y'),
            'div#viewer img', Browse('/directory/0-0-0-0-0-0/{page}.htm'), query('/search', 'name'),
            Browse('/latest/{page}.htm'),
        ))

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        entries = doc.select('select#top_chapter_list ~ div.page_select option[value]:not(:-soup-contains("featured"))')
        if not entries:
            return [picture(node, final) for node in doc.select(self.layout.reader)]
        base = urlsplit(final).path.rstrip('/')
        results = []
        for item in entries:
            target = self.site_link(item['value'], final)
            if not target or not (urlsplit(target).path.rstrip('/') == base or urlsplit(target).path.startswith(base + '/')):
                raise SourceError('Читалка вернула страницу другой главы.')
            page, resolved = (doc, final) if target == final else self.document(http, target)
            if self.chapter_key(resolved) != self.chapter_key(url):
                raise SourceError('Читалка перенаправила запрос на другой тайтл.')
            results.append(picture(page.select_one(self.layout.reader), resolved))
            if len(results) > MAX_PAGES:
                raise SourceError('Превышен лимит страниц главы.')
        return results


class HentaiKun(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            MANGA, rf'/(?:manga|read|chapter)/{SLUG}(?:/{SEGMENT})+/?',
            Cards('table.table-striped tr:not(.danger):has(td a)', 'td:first-child a', next='ul.pagination li[aria-label=Next]'),
            Meta('div.single_title h1', '', genres='h2:has(strong:-soup-contains("Category")) a',
                 tags='div.desc a[href*="/tag/"] span.label-danger', author='h2:has(strong:-soup-contains("Artist")) a'),
            Archive('tr:has(a.readchap)', anchor='a.readchap', date='td:last-child h6', date_pattern='%d-%m-%Y'), '',
            Browse('/manga/manga-list/most-viewed/{page}/', first_path='/manga/manga-list/most-viewed/'),
            Browse('/manga/search/title/{query}/{page}/', first_path='/manga/search/title/{query}/'),
            Browse('/manga/manga-list/last-updated/{page}/', first_path='/manga/manga-list/last-updated/'),
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        route = self.layout.search if query else self.layout.latest if sort == 'updated' else self.layout.popular
        doc, final = self.document(http, route.url(self.ROOT, page, query, tag))
        if not doc.select_one('table.table-striped'):
            return self.card_rows(doc, final, Cards('div.thumbnail[id^="galary-"]', 'div.overlay a',
                                                    cover='img.img-responsive', next=self.layout.cards.next))
        rows = {}
        for node in doc.select(self.layout.cards.rows):
            anchor = node.select_one(self.layout.cards.link)
            target = self.site_link(anchor.get('href'), final) if anchor else ''
            if not self.is_title(target):
                continue
            image = BeautifulSoup(anchor.get('title', ''), 'html.parser').select_one('img')
            item = self.record(target, node_text(anchor), picture(image, final))
            rows[item['id']] = item
        return list(rows.values()), bool(doc.select_one(self.layout.cards.next))

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        for script in doc.select('script'):
            if match := re.search(r'\bvar\s+jsondata\s*=\s*(\[[^;]+\])', script.string or ''):
                try:
                    pages = json.loads(match[1])
                except ValueError:
                    raise SourceError('Источник изменил формат списка страниц.') from None
                return [image_url(value, final) for value in pages] if isinstance(pages, list) else []
        return []


class KuraManga(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/{SLUG}/?', rf'/{SLUG}/{SEGMENT}/?',
            Cards('section:has(h2:-soup-contains("Popular")) a.sp-card', '', '.sp-cap h3', next=''),
            Meta('h1.manga-title', '', '.summary-inner, .mp-synopsis', genres='.genre-list a.genre-chip',
                 author='.mp-cred:has(.mp-cred-k:-soup-contains("Author"), .mp-cred-k:-soup-contains("Story"),'
                        ' .mp-cred-k:-soup-contains("Art")) .mp-cred-v',
                 status='.mp-status, .meta-grid div:-soup-contains("Status:")'),
            Archive('.chapter-list .chapter-item:has(a[href])', date='time', date_pattern='%b %d, %Y'),
            '#chapterImages img', Browse('/', one_page=True),
            latest=Browse('/', (('page', '{page}'),), Cards('.update-list .update-row', 'a.update-series-link', next='a[data-lu-next]:not(.is-disabled)')),
            title_path='/',
        ))

    def is_title(self, value):
        return super().is_title(value) and self.title_key(value) not in {'search', 'assets', 'api', 'login', 'register'}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if not (query or tag):
            return super().catalogue(http, page, sort=sort)
        args = {'ajax': 1, 'page': page, **({'name': query} if query else {}), **({'genre': tag[:120]} if tag else {})}
        data = self.json(http, query_url(self.ROOT + '/search', **args))
        rows = {}
        for item in items(data, 'data'):
            if not isinstance(item, dict) or not (slug := segment(item.get('normalized_title'))) or not isinstance(item.get('title'), str):
                continue
            url = self.ROOT + '/' + slug
            if self.is_title(url):
                rows[slug] = self.record(url, item['title'], image_url(item.get('thumb') or item.get('cover_image_url'), url))
        return list(rows.values()), len(rows) == 18 and (not number(data.get('total')) or page * 18 < number(data['total']))


class Gensura(Article):
    def __init__(self, identity):
        spec = rf'/manga/{SLUG}/?'
        self.package = 'gensura'
        DirectCatalogue.__init__(self, identity, Layout(
            spec, spec, Cards('a[href^="/manga/"]:has(h2)', '', 'h2', next='a[href*=page]:not(:-soup-contains("1"))'),
            Meta('h1.font-semibold', 'img[src*=thumbnail].w-96', 'tr:-soup-contains("page")', 'h2.text-lg.font-medium',
                 'a[href*="/categories/"]', 'a[href*="/tags/"]', 'a[href*="/authors/"], a[href*="/circles/"]'),
            Archive(''), 'img[src*=images]:not([src*=thumbnail]).w-full, img[data-src*=images]',
            Browse('/advanced-search/'), title_path='/manga/',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'search': 1, 'type': 0, 'sort': 0 if query else 2 if sort == 'updated' else 1, 'page': page}
        if query:
            args['name'] = query
        if tag:
            if not segment(tag):
                raise SourceError('Некорректная метка каталога.')
            args['include_tags'] = tag
        url = query_url(self.ROOT + '/advanced-search/', **args)
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'}, action='native-series-html-api')
        if final != url:
            raise SourceError('Источник перенаправил поиск.')
        doc = BeautifulSoup(raw, 'html.parser')
        rows, _ = self.card_rows(doc, final, self.layout.cards)
        return rows, any(not node_text(node) and self.site_link(node.get('href'), final) for node in doc.select('a[href*=page]'))

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/advanced-search/')
        return [{'label': node_text(node), 'sourceId': node['data-value'], 'category': 'tag'}
                for node in doc.select('li[onclick="updateTag(this)"][data-value]')
                if segment(node['data-value']) and node_text(node)]

    def article_pages(self, http, doc, final):
        result = []
        for value in super().article_pages(http, doc, final):
            parts = urlsplit(value)
            result.append(urlunsplit(parts._replace(path=re.sub(r'-t(?=\.)', '', parts.path))))
        return result


class Comivex(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/(?:manga|series)/{SLUG}/?', rf'/(?:manga|series|chapter|read)/{SLUG}(?:/{SEGMENT})+/?',
            Cards('article.manga-card', 'a.card-cover', '.card-title a', next=''),
            Meta('.md-title', '.md-cover-wrap img.md-cover', '#synopsis',
                 genres='.md-genres a.md-genre-pill', author='.md-author span', status='.md-status'),
            Archive('.ch-list .ch-item', anchor='a.ch-link', title='.ch-num'), '#chapter-images .page-wrapper img',
            Browse('/explore/'),
            latest=Browse('/latest/', cards=Cards('article.u-card', 'a.u-card__title', cover='img.u-card__img', next=''), one_page=True),
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if sort == 'updated' and not (query or tag):
            return super().catalogue(http, page, sort=sort)
        args = {'sort_by': 'Views', 'results': page, 'ajax': 1}
        if query:
            args['search'] = query
        if tag:
            args['genre_included'] = tag[:120]
        rows, _ = self.card_rows(*self.document(http, query_url(self.ROOT + '/explore/', **args)), self.layout.cards)
        return rows, bool(rows)


class KumaRaw(DirectCatalogue):
    def __init__(self, identity):
        cards = Cards('div.recoment_box div.story_item', '.mg_name a', next='.pagination a[rel=next]')
        super().__init__(identity, Layout(
            MANGA, CHAPTER, cards, Meta('h1', '.detail_avatar img', '.detail_reviewContent',
                                        '.info_label:-soup-contains("ほかの名前") + .info_value',
                                        '.detail_listInfo a[href*="/genres/"]',
                                        author='.info_label:-soup-contains("著者") + .info_value'),
            Archive('div.chapter_box div.item', anchor='a.chapter_num', date='p.chapter_info:nth-of-type(2)', date_pattern='%Y-%m-%d'),
            '', Browse('/', cards=Cards('div#top_day div.story_item, div#top_month div.story_item, div#top_all div.story_item',
                                        '.mg_name a', next=''), one_page=True),
            Browse('/mangas', (('search', '{query}'),), one_page=True), Browse('/latest/{page}', first_path='/'),
            reader_source='manga18',
        ))


class ManhwaLike(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/(?:manga|manhwa)/{SLUG}/?', rf'/(?:manga|manhwa|read)/{SLUG}(?:/{SEGMENT})+/?',
            Cards('ul.list-hot div.visual', 'a[href]', 'h3.title a', next=''),
            Meta('h1', 'div.fixed-img img', 'div.summary-block p.about',
                 genres='div.categories a', author='div.author a', status='small:-soup-contains("Status") + strong'),
            Archive('ul.chapter-list li:has(a[href])', date='.time', date_pattern='%B %d, %Y'),
            '.chapter-content .page-chapter img',
            Browse('/', one_page=True),
            latest=Browse('/', cards=Cards('ul.slick_item div.visual', 'a[href]', 'h3.title a', next=''), one_page=True),
        ))
        self.results = Cards('ul.normal li:has(img[alt]), ul li:has(> a img[alt])', 'a[href]', 'img[alt]',
                             next='ul.pagination li:last-child a', title_attr='alt')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page != 1:
                return [], False
            target = self.ROOT + '/search/html/1'
            raw, final, _ = http.document(target, method='POST', action='native-series-form',
                                          data={'keyword': query}, headers={'Referer': self.ROOT + '/'})
            if target != final:
                raise SourceError('Поиск перенаправил запрос на другой маршрут.')
            rows, _ = self.card_rows(BeautifulSoup(raw, 'html.parser'), final, self.results)
            return rows, False
        if tag:
            if not segment(tag):
                raise SourceError('Некорректный жанр каталога.')
            return self.card_rows(*self.document(http, query_url(self.ROOT + '/' + segment(tag), page=page)),
                                  self.results)
        return super().catalogue(http, page, sort=sort)


class HachiRaw(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            MANGA, CHAPTER, Cards('div.ng-scope > div.top-15', 'a.ng-binding.SeriesName', cover='img.img-fluid',
                                 next='ul.pagination li:-soup-contains("→")'),
            Meta('div.BoxBody > div.row h1', 'div.BoxBody > div.row img.img-fluid', 'div.BoxBody > div.row div.Content',
                 genres='li.list-group-item:-soup-contains("ジャンル") a', author='li.list-group-item:-soup-contains("著者")'),
            Archive('a.ChapterLink', anchor='', title='span:first-child', date='span.float-right', date_pattern='%Y-%m-%d'),
            '#TopPage img', Browse('/list-manga/{page}', (('order_by', 'views'),), first_path='/list-manga'),
            Browse('/list-manga/{page}', (('search', '{query}'),), first_path='/list-manga'),
            Browse('/list-manga/{page}', (('order_by', 'lastest'),), first_path='/list-manga'),
            Browse('/manga-list/{tag}/{page}', first_path='/manga-list/{tag}'),
            tag_index='/list-manga', tag_anchor='#TypeShow a[href]',
        ))

    @staticmethod
    def repair_cover(row):
        row['cover'] = row['cover'].replace('https://i0.wp.com/cdn.kumaraw.com/', 'https://cdn.hachiraw.net/', 1)
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        rows, more = super().catalogue(http, page, query=query, sort=sort, tag=tag)
        return [self.repair_cover(row) for row in rows], more

    def metadata(self, doc, url, spec):
        return self.repair_cover(super().metadata(doc, url, spec))


class HentaiSco(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/hentai/{SLUG}/?', rf'/hentai/{SLUG}/{SEGMENT}/?',
            Cards('article.cover-card', 'a[href]', 'h3', next='nav.pager a[rel=next]'),
            Meta('article[data-manga-id] h1', 'article[data-manga-id] .cover-frame img', '[data-read-more-body] p, h1 + p',
                 genres='article[data-manga-id] a[href^="/genre/"]', tags='article[data-manga-id] a[href^="/tag/"]',
                 author='dt:-soup-contains("Author") + dd a, dt:-soup-contains("Artist") + dd a', status='article[data-manga-id] p:has(+ h1)'),
            Archive('ol[data-chapter-list] > li > a', anchor='', title='span'), '[data-reader-pages] img.reader-page',
            Browse('/hentai-list/page/{page}/', (('m_orderby', 'views'),), first_path='/hentai-list/'),
            query('/search/', 'q'), Browse('/hentai-list/page/{page}/', first_path='/hentai-list/'),
            Browse('/genre/{tag}/page/{page}/', first_path='/genre/{tag}/'),
            title_path='/hentai/', tag_index='/hentai-list/', tag_anchor='section[aria-labelledby=browse-genres] a',
        ))

    def saved_title_url(self, url):
        value = self.canonical(url)
        slug = urlsplit(value).path.strip('/')
        return self.ROOT + '/hentai/' + slug + '/' if re.fullmatch(SEGMENT, slug) else value

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if self.is_chapter(value):
            return value
        parts = urlsplit(value).path.strip('/').split('/')
        if len(parts) == 2 and parts[0] == self.title_key(title) and re.fullmatch(SEGMENT, parts[1]):
            return self.ROOT + '/hentai/' + '/'.join(parts) + '/'
        if len(parts) == 1 and re.fullmatch(SEGMENT, parts[0]) and self.is_title(title):
            return title.rstrip('/') + '/' + parts[0] + '/'
        return ''


class Hentara(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/manhwa/{SLUG}/?', rf'/manhwa/{SLUG}/chapter-(\d{{1,9}})/?', interval=.5)

    def title_for(self, url):
        return self.ROOT + '/manhwa/' + self.chapter_key(url)

    def from_comic(self, data):
        slug, title = segment(data.get('slug')), data.get('title')
        if not slug or not isinstance(title, str) or not title:
            raise SourceError('Источник не предоставил корректную карточку тайтла.')
        url = f'{self.ROOT}/manhwa/{slug}'
        record = self.record(url, title, image_url(data.get('thumbnail_url'), url), description=data.get('description') or '',
                             genres=[g.get('name') for g in data.get('genres') or [] if isinstance(g, dict)])
        record['format'] = 'manhwa'
        return record

    def comics(self, http):
        return [row for row in items(self.json(http, self.ROOT + '/r2-data/index.json'), 'comics') if isinstance(row, dict)]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        rows = sorted(self.comics(http), key=(lambda row: str(row.get('latest_episode_date') or '')) if sort == 'updated'
                      else (lambda row: number(row.get('view_count')) or 0), reverse=True)
        entries = [self.from_comic(row) for row in rows if query in str(row.get('title') or '').casefold()]
        return [row for row in entries if not tag or any(tag.casefold() == name.casefold() for name in row['genres'])], False

    def vocabulary(self, http):
        names = {g['name'] for row in self.comics(http) for g in row.get('genres') or []
                 if isinstance(g, dict) and isinstance(g.get('name'), str) and g['name']}
        return [{'label': label, 'sourceId': label, 'category': 'genre'} for label in sorted(names)]

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.json(http, f'{self.ROOT}/r2-data/comics/{slug}.json', url)
        row = data.get('comic') if isinstance(data, dict) else None
        if not isinstance(row, dict) or segment(row.get('slug')) != slug:
            raise SourceError('Источник вернул другой тайтл.')
        episodes = {}
        for item in items(data, 'episodes'):
            if not isinstance(item, dict) or type(n := item.get('episode_number')) is not int or not 0 <= n < 10**9:
                continue
            path = f'{self.ROOT}/manhwa/{slug}/chapter-{n}'
            label = f'Chapter {n}'
            if item.get('title'):
                label += ' - ' + str(item['title'])
            episodes[path] = self.chapter(path, label, n, str(item.get('created_at') or '')[:10])
        return self.from_comic(row), self.order(episodes)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        data = self.json(http, f'{self.ROOT}/r2-data/episodes/{match[1]}/{match[2]}.json', url)
        rows = sorted((row for row in items(data, 'pages') if isinstance(row, dict)),
                      key=lambda row: number(row.get('page_number')) or 0)
        return [image_url(row.get('image_url'), url) for row in rows]


class HentaiKisu(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/g/{SLUG}/?', rf'/read/{SLUG}/?',
            Cards('div.book-list a[href]', '', 'div.book-description p', 'img.lozad', ''),
            Meta('div#info h1', 'div#cover img', tags='div.tag-container:-soup-contains("Categories:") span.tags a.tag',
                 author='div.tag-container:-soup-contains("Artist:") span.tags, div.tag-container:-soup-contains("Group:") span.tags'),
            Archive(''), '', Browse('/backend/infinite.index.php'), Browse('/search', (('s', '{query}'),), one_page=True), title_path='/g/',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            return super().catalogue(http, page, query=query, sort=sort, tag=tag)
        data = self.json(http, query_url(self.ROOT + '/backend/infinite.index.php', p=page))
        if not isinstance(data, list):
            raise SourceError('Источник изменил формат каталога.')
        rows = {}
        for item in data:
            if isinstance(item, dict) and (key := segment(item.get('id'))) and item.get('title'):
                url = f'{self.ROOT}/g/{key}'
                rows[key] = self.record(url, str(item['title']), image_url(item.get('img'), url))
        return list(rows.values()), bool(rows)

    def chapters(self, http, doc, url):
        chapter = f'{self.ROOT}/read/{self.title_key(url)}'
        return [self.chapter(chapter, 'Глава', 1)], False

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        return self.ROOT + '/read/' + self.title_key(value) if self.is_title(value) else value

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        for script in doc.select('script'):
            if match := re.search(r"\bla\s*=\s*'([A-Za-z0-9+/=]+)'", script.string or ''):
                try:
                    raw = base64.b64decode(match[1], validate=True).decode()
                except (UnicodeError, binascii.Error):
                    raise SourceError('Источник изменил формат списка страниц.') from None
                return [image_url(value, final) for value in raw.split(',')]
        return []


class MyAdultComics(Article):
    def __init__(self, identity):
        self.package = 'myadultcomics'
        DirectCatalogue.__init__(self, identity, Layout(
            r'(/read\.php)', r'(/read\.php)',
            Cards('td.list_container', 'p.text_container > a', cover='img.fon_pic_img', next='td.tbl_page a:-soup-contains(">>")'),
            Meta('h1#TOP', '', tags='p.text_info_book:-soup-contains("Tags:") a', author='p.text_info_book:-soup-contains("Artists:") a'),
            Archive(''), '', Browse('/index.php', (('page', '{page}'),)),
            Browse('/index.php', (('name', '{query}'), ('search', 'yes'), ('page', '{page}'))),
            title_path='/',
        ))

    def is_title(self, url):
        return super().is_title(url) and bool(re.fullmatch(r'\d{1,15}', param(url, 'i')))

    def is_chapter(self, url):
        return super().is_chapter(url) and self.is_title(url)

    def title_key(self, url):
        return param(url, 'i')

    def chapter_key(self, url):
        return self.title_key(url)

    def title_for(self, url):
        return query_url(self.ROOT + '/read.php', i=param(url, 'i')) if self.is_title(url) else ''

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        paths = self.article_pages(None, doc, url)
        if paths and not row['cover']:
            parts = urlsplit(paths[0]).path.rsplit('/', 2)
            if len(parts) == 3 and '.' in parts[-1]:
                row['cover'] = image_url(f'/poster/{parts[-2]}.{parts[-1].rsplit(".", 1)[1]}', url)
        return row

    def article_pages(self, http, doc, final):
        for script in doc.select('script'):
            raw = script.string or ''
            if 'let template' in raw:
                return [image_url('/' + path, final) for path in re.findall(r"""src=["'](books/[^"']+)["']""", raw)
                        if '..' not in path.split('/')]
        return []


class EggComics(Article):
    def __init__(self, identity):
        self.package = 'eggporncomics'
        path = rf'/(?:comic/)?{SLUG}/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('div.preview:has(div.name)', 'a:has(img)', next='ul.ne-pe li.next:not(.disabled)'),
            Meta('div.info h1, h1, title', 'div.grid div.image img', 'div.links',
                 tags='div.links a[href*="/comics-tag/"]'),
            Archive(''), 'div.grid div.image img',
            Browse('/category/1/anime-comics', (('page', '{page}'),)),
            Browse('/search/{query}', (('page', '{page}'),)), Browse('/latest-comics', (('page', '{page}'),)),
            title_path='/',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = re.sub(r"[\s']", '-', self.catalogue_params(page, query, tag))
        if tag and not query and segment(tag):
            url = query_url(self.ROOT + '/comics-tag/' + segment(tag), page=page)
            return self.card_rows(*self.document(http, url), self.layout.cards)
        return super().catalogue(http, page, query=query, sort=sort)

    def article_pages(self, http, doc, final):
        return [value.replace('thumb300_', '') for value in super().article_pages(http, doc, final)]

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['cover'] = row['cover'].replace('thumb300_', '')
        return row


class Mitaku(Article):
    def __init__(self, identity):
        self.package = 'mitaku'
        path = rf'/((?:{SEGMENT}/){{0,3}}{SEGMENT})/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('div.article-container article', 'a[href]', 'h1,h2,h3', next='div.wp-pagenavi a.page.larger'),
            Meta('article h1', 'article img', genres='article span.cat-links a', tags='article span.tag-links a'),
            Archive(''), 'a.msacwl-img-link', Browse('/category/ero-cosplay/page/{page}'),
            Browse('/page/{page}', (('s', '{query}'),)), browse_tag=Browse('/tag/{tag}/page/{page}'), title_path='/',
        ))

    def is_title(self, url):
        path = urlsplit(url).path.lstrip('/').split('/', 1)[0]
        return path not in {'category', 'tag', 'author', 'page', 'wp-json', 'wp-admin', 'wp-content'} and super().is_title(url)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        route = self.layout.search if query else self.layout.browse_tag if tag else self.layout.popular
        doc, final = self.document(http, route.url(self.ROOT, page, query, tag))
        if query and self.is_title(final) and doc.select_one('article h1'):
            return [self.metadata(doc, final, self.meta)], False
        return self.card_rows(doc, final, self.layout.cards)

    def article_pages(self, http, doc, final):
        return [image_url(value, final) for node in doc.select(self.layout.reader)
                if (value := node.get('data-mfp-src') or node.get('href'))]


class EveriaUnoriginal(Article):
    def __init__(self, identity):
        self.package = 'everiaclubcom'
        path = rf'/{SLUG}(?:/{SEGMENT})?/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('.mainleft .leftp > a', '', 'img', next='li:has(span.current) + li > a', title_attr='title'),
            Meta('.mainleft h1, h1, title', '.mainleft img', tags='div.end span:-soup-contains("Tags:") ~ a > p.tags'),
            Archive(''), '.mainleft img',
            Browse('/', cards=Cards('.mainright li a:has(img)', '', 'img', next='', title_attr='title'), one_page=True),
            query('/search/', 'keyword'), Browse('/', (('page', '{page}'),)), Browse('/tags/{tag}/{page}'), title_path='/',
        ))


class BuonDua(JoomlaGallery):
    def __init__(self, identity):
        super().__init__(identity, 'xiutaku')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if tag and not query:
            self.catalogue_params(page, query, tag)
            if not segment(tag):
                raise SourceError('Некорректный тег каталога.')
            url = f'{self.ROOT}/tag/{segment(tag)}&start={(page - 1) * 20}'
            return self.card_rows(*self.document(http, url), self.layout.cards)
        return super().catalogue(http, page, query=query, sort=sort)

    def chapters(self, http, doc, url):
        last = doc.select('nav.pagination:first-of-type a.pagination-next[href]')
        total = param(self.site_link(last[-1]['href'], url), 'page') if last else '1'
        total = min(int(total), 1500) if re.fullmatch(r'[1-9]\d{0,3}', total) else 1
        return [self.chapter(query_url(url, page=n), f'Page {n}', n) for n in range(1, total + 1)], False


class Manhwa18(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/(?:manga|manhwa|truyen-tranh)/{SLUG}/?', rf'/(?:manga|manhwa|truyen-tranh|doc-truyen)/{SLUG}(?:/{SEGMENT})+/?',
            Cards('.thumb-item-flow', 'a[href]', '.series-title a', '.lazy-bg, .img-in-ratio', '.pagination_wrap a.next',
                  image_attrs=('data-bg',)),
            Meta('.series-name a, .au-bento h1, .au-crumb a:last-child', '.series-cover .img-in-ratio', '.summary-content',
                 genres='.info-item:has(.info-name:-soup-contains("Genre")) .info-value a',
                 author='.info-item:has(.info-name:-soup-contains("Author")) .info-value, .fantrans-value a',
                 status='.info-item:has(.info-name:-soup-contains("Status")) .info-value'),
            Archive('div.au-chgrid a.au-chtile, ul.list-chapters > a', anchor='', label_attr='data-name'),
            '#chapter-content img.lazy', Browse('/tim-kiem', (('sort', 'top'), ('page', '{page}'))),
            Browse('/tim-kiem', (('q', '{query}'), ('sort', 'update'), ('page', '{page}'))),
            Browse('/tim-kiem', (('sort', 'update'), ('page', '{page}'))),
            Browse('/tim-kiem', (('sort', 'update'), ('accept_genres', '{tag}'), ('page', '{page}'))),
        ))


class HentaiReadIO(DirectCatalogue):
    def __init__(self, identity):
        cards = Cards('div.card:has(.jtip)', '.title-manga a', cover='img.card-img-top',
                      next='ul.pagination li.page-item a.page-link:-soup-contains("»")')
        super().__init__(identity, Layout(
            rf'/{SLUG}/?', rf'/{SLUG}/{SEGMENT}(?:/{SEGMENT})?/?', cards,
            Meta('h1.title-detail', '.col-image img', '#summary_shortened', genres='.kind p.col-8 a',
                 author='.author p.col-8', status='.status p.col-8'),
            Archive('ul#list_chapter_id_detail li.wp-manga-chapter, ul.version-chap li.wp-manga-chapter', date='.chapter-release-date i'),
            '.page-chapter img', Browse('/'), title_path='/',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'act': 'search', 'f[status]': 'all', 'f[sortby]': 'lastest-chap' if query or sort == 'updated' else 'top-manga',
                'pageNum': page}
        if query:
            args['f[keyword]'] = query
        if tag:
            args['f[genres]'] = tag[:120]
        return self.card_rows(*self.document(http, query_url(self.ROOT + '/', **args)), self.layout.cards)


class OnlyBest(Article):
    def __init__(self, identity):
        self.package = 'onlythebesthentai'
        path = rf'/{SLUG}/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('article.post', '.blog-entry-title a, .entry-title a',
                              cover='.nv-post-thumbnail-wrap img', next='a.next.page-numbers'),
            Meta('h1.manga-title', '.manga-box .manga-img img', '.manga-info p',
                 tags='.manga-tags-container:has(.manga-tags-label:-soup-contains("Tags")) .tag-button',
                 author='.manga-tags-container:has(.manga-tags-label:-soup-contains("Artist")) .tag-button'),
            Archive(''), '.manga-gallery-wrapper figure.wp-block-image img',
            Browse('/page/{page}/', first_path='/'), Browse('/', (('s', '{query}'), ('paged', '{page}'))),
            browse_tag=Browse('/tag/{tag}/page/{page}/', first_path='/tag/{tag}/'), title_path='/',
        ))

    def clean_title(self, title):
        return re.sub(r'\s*\[\d+]\s*$', '', title).strip()

    def article_pages(self, http, doc, final):
        pages = []
        for image in doc.select(self.layout.reader):
            candidates = []
            for entry in image.get('srcset', '').split(','):
                fields = entry.split()
                if len(fields) == 2 and re.fullmatch(r'\d{1,6}w', fields[1]):
                    candidates.append((int(fields[1][:-1]), image_url(fields[0], final)))
            pages.append(max(candidates)[1] if candidates else picture(image, final, ('data-src',)))
        return pages


class MangaGeko(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/(?:manga|reader|novel)/{SLUG}/?', rf'/(?:manga|reader|novel|chapter)/{SLUG}/(?!all-chapters/?$){SEGMENT}(?:/{SEGMENT})?/?',
            Cards('.comic-card', 'a[href]', '.comic-card__title a', '.comic-card__cover img', ''),
            Meta('.novel-header h1, .novel-title', '.cover img', '.description', '.alternative-title',
                 '.categories a[href*=genre]', author='.author a', status='.header-stats strong'),
            Archive('ul.chapter-list > li', title='.chapter-title, .chapter-number'),
            '#chapter-reader img', Browse('/browse-comics/data/'),
            Browse('/search/', (('search', '{query}'), ('results', '{page}')),
                   Cards('.novel-item', 'a[href]', '.novel-title', '.novel-cover img', 'nav.paging a:-soup-contains("Next")')),
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query and not tag:
            return super().catalogue(http, page, query=query, sort=sort)
        args = {'page': page, 'sort': 'latest' if sort == 'updated' else 'popular_all_time', 'safe_mode': 0}
        if tag:
            args['include_genres'] = tag[:120]
        if query:
            args['q'] = query
        url = query_url(self.ROOT + '/browse-comics/data/', **args)
        data = self.json(http, url)
        if not isinstance(data, dict) or not isinstance(data.get('html'), str):
            raise SourceError('Источник изменил формат выдачи.')
        rows, _ = self.card_rows(BeautifulSoup(data['html'], 'html.parser'), url, self.layout.cards)
        return rows, page < (number(data.get('num_pages')) or 0)

    def chapters(self, http, doc, url):
        archive = url.rstrip('/') + '/all-chapters/'
        return self.list_chapters(http, *self.document(http, archive), self.layout.archive)

    def pages(self, http, url):
        return [value for value in super().pages(http, url) if 'credits-mgeko.png' not in value]


class HentaiTnT(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/(?:manga|comic)/{SLUG}/?', rf'/(?:manga|comic|read)/{SLUG}(?:/{SEGMENT})+/?',
            Cards('.comic-card a[href]', '', title_attr='title', next='a[title=Next]'),
            Meta('h1, meta[property="og:title"]', '.comic-cover img, .cover img', '#synopsisText',
                 genres='.genre-item', author='i[title=Artists] + span a', status='span:has(i[title=Status])'),
            Archive('.comic-card:not(:has(.fa-crown))', label_attr='title'), '.page-image',
            Browse('/recommended/page/{page}', first_path='/recommended'),
            Browse('/page/{page}', (('s', '{query}'),), first_path='/'),
            Browse('/latest-updates/page/{page}', first_path='/latest-updates'),
            Browse('/genre/{tag}/page/{page}', first_path='/genre/{tag}'),
        ))

    def chapters(self, http, doc, url):
        node = doc.select_one('#post_manga_id[value]')
        if not node or not re.fullmatch(r'\d{1,15}', node['value']):
            raise SourceError('Источник не предоставил ID оглавления.')
        endpoint = self.ROOT + '/wp-admin/admin-ajax.php'
        data = {'action': 'baka_ajax', 'type': 'load_chapters_paginated', 'parent_id': node['value'],
                'per_page': '10000', 'order': 'newest_first'}
        raw, final, _ = http.document(endpoint, method='POST', action='native-series-form',
                                       headers={'Referer': url}, data=data)
        if endpoint != final:
            raise SourceError('Источник перенаправил запрос оглавления.')
        try:
            template = json.loads(raw)['data']['html']
        except (ValueError, KeyError, TypeError):
            raise SourceError('Источник изменил формат оглавления.') from None
        if not isinstance(template, str):
            raise SourceError('Источник вернул некорректное оглавление.')
        return self.list_chapters(http, BeautifulSoup(template, 'html.parser'), url, self.layout.archive)


class BaoBua(Article):
    def __init__(self, identity):
        self.package = 'baobua'
        path = rf'/((?:{SEGMENT}/){{0,2}}{SEGMENT})/?'
        DirectCatalogue.__init__(self, identity, Layout(
            path, path, Cards('.thcovering-video', 'a.denomination', cover='img.xld', next='a.page-numbers.next'),
            Meta('h2.box-mt-output, h1', 'div.contentme a[href^="/img.html"] img', tags='.it-categories a'),
            Archive(''), 'div.contentme a[href^="/img.html"] img',
            Browse('/page/{page}/', first_path='/'), query('/search', 'q'), title_path='/',
        ))

    def clean_title(self, title):
        return re.sub(r' \| Page \d+/\d+$', '', title.removeprefix('BaoBua.Net: '))

    def article_pages(self, http, doc, final):
        pages, seen = [], set()
        while final not in seen and len(seen) < 80:
            seen.add(final)
            pages.extend(picture(node, final) for node in doc.select(self.layout.reader))
            if len(pages) > MAX_PAGES:
                break
            link = doc.select_one('a.page-numbers[href]:-soup-contains("Next")')
            if not link:
                return pages
            target = self.site_link(link['href'], final)
            if not target:
                break
            doc, final = self.document(http, target)
        raise SourceError('Источник не предоставил полный список галереи.')


class HentaiRead(DirectCatalogue):
    def __init__(self, identity):
        path = rf'/hentai/{SLUG}/?'
        super().__init__(identity, Layout(
            path, path, Cards('.manga-item', 'a.manga-item__link', next='a[rel=next]',
                              image_attrs=('data-src', 'data-lazy-src', 'data-cfsrc')),
            Meta('div.manga-titles h1, h1', '', aliases='.manga-titles h2', tags='a[href*="/tag/"] span:first-of-type',
                 author='a[href*="/circle/"] span:first-of-type, a[href*="/artist/"] span:first-of-type'),
            Archive(''), '', Browse('/hentai/page/{page}/', (('sortby', 'views'),), first_path='/hentai/'),
            Browse('/page/{page}', (('s', '{query}'), ('title-type', 'contains'))),
            Browse('/hentai/page/{page}/', (('sortby', 'new'),), first_path='/hentai/'), title_path='/hentai/',
        ))

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'mv_hr') == '1'

    def title_for(self, url):
        return self.ROOT + '/hentai/' + self.chapter_key(url) + '/'

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and not query:
            if not segment(tag):
                raise SourceError('Некорректный тег каталога.')
            url = self.ROOT + '/tag/' + segment(tag) + '/' + (f'page/{page}/' if page > 1 else '')
            return self.card_rows(*self.document(http, url), self.layout.cards)
        return super().catalogue(http, page, query=query, sort=sort)

    def chapters(self, http, doc, url):
        found = {}
        for item in doc.select('div.collection-listing > div div.manga-item'):
            link = item.select_one('a.manga-item__link[href]')
            value = self.site_link(link['href'], url) if link else ''
            if not self.is_title(value):
                continue
            target = query_url(value, mv_hr=1)
            found[target] = self.chapter(target, node_text(link), number(node_text(item.select_one('div.collection-badge'))))
        if not found:
            target = query_url(url, mv_hr=1)
            found[target] = self.chapter(target, 'Глава', 1)
        return self.order(found), False

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            return super().inspect(value, http)
        pages = self.pages(http, url)
        if not 1 <= len(pages) <= MAX_PAGES or not all(pages):
            raise SourceError('Источник не предоставил полный список страниц.')
        return self.reader_result(self.details(http, self.title_for(url)), url, [self.chapter(url)], pages)

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        return query_url(value, mv_hr=1) if self.is_title(value) else ''

    def pages(self, http, url):
        reader = self.title_for(url) + 'english/p/1/'
        doc, final = self.document(http, reader)
        if urlsplit(final).path.rstrip('/') != urlsplit(reader).path.rstrip('/'):
            raise SourceError('Читалка перенаправила запрос на другой выпуск.')
        extra = doc.select_one('#single-chapter-js-extra')
        script = doc.select_one('#single-chapter-js-before')
        if not extra or not script:
            return []
        base = re.search(r'=\s*(\{[^;]+\})', extra.string or '')
        encoded = re.search(r'["\'](ey[A-Za-z0-9+/=]+)["\']', script.string or '')
        if not base or not encoded:
            return []
        try:
            directory = json.loads(base[1])['baseUrl'].rstrip('/') + '/'
            manifest = json.loads(base64.b64decode(encoded[1], validate=True))['data']['chapter']['images']
        except (ValueError, AttributeError, KeyError, TypeError, binascii.Error):
            raise SourceError('Читалка изменила формат списка страниц.') from None
        return [image_url(row.get('src'), directory) if isinstance(row, dict) else '' for row in manifest] if isinstance(manifest, list) else []


class ManhuaTop(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/manhua/{SLUG}/?', rf'/manhua/{SLUG}/{SEGMENT}/?', Cards('', ''),
            Meta('h1#manga-title', '.detail-cover img', '.rich-content.synopsis', 'p.alternative-title',
                 '.genre-chips a', '.tags-chips a', status='.detail-stats .status-badge'),
            Archive(''), '', Browse('/series/'), title_path='/manhua/', suffix='/',
        ))

    def api(self, http, method, path=None, **args):
        if path:
            args['path'] = path
        return self.json(http, query_url(self.ROOT + '/api/' + method, **args))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query and (len(query) < 2 or not segment(query)):
            return [], False
        if query:
            path = f'/search/{segment(query)}/'
        else:
            path = '/series/' + (f'page/{page}/' if page > 1 else '')
        args = {'sort': 'latest_update' if sort == 'updated' else 'trending-week'}
        if query and page > 1:
            args['page'] = page
        if tag:
            if not re.fullmatch(r'\d{1,14}', tag):
                raise SourceError('Некорректный жанр каталога.')
            args['genre'] = tag
        data = self.api(http, 'discovery', query_url(path, **args))
        rows = {}
        for item in items(data, 'items'):
            if isinstance(item, dict) and self.is_title(target := self.site_link(item.get('path'))) and isinstance(item.get('title'), str):
                rows[target] = self.record(target, item['title'], image_url(item.get('thumbnail'), target), status=item.get('status') or '')
        return list(rows.values()), data.get('hasMore') is True

    def chapters(self, http, doc, url):
        key = self.title_key(url)
        root = urlsplit(url).path.rstrip('/') + '/'
        rows = {}
        for page in range(1, 81):
            data = self.api(http, 'reader', query_url(root, tab='chapters', chapter_page=page), resource='chapters')
            for chapter in items(data, 'items'):
                if not isinstance(chapter, dict):
                    continue
                target = self.site_link(chapter.get('path'), url)
                if self.is_chapter(target) and self.chapter_key(target) == key:
                    title = ' - '.join(str(chapter[name]) for name in ('title', 'extra') if chapter.get(name))
                    rows[target] = self.chapter(target, title, date=str(chapter.get('date') or '')[:10])
            if page * 30 >= (number(data.get('total')) or 0):
                return self.order(rows), False
        return self.order(rows), True

    def pages(self, http, url):
        data = self.api(http, 'reader', urlsplit(url).path, resource='content')
        return [image_url(row.get('url'), url) if isinstance(row, dict) else '' for row in items(data, 'images')]

    def vocabulary(self, http):
        rows = {}
        for page in range(1, 41):
            data = self.api(http, 'genres', page=page)
            for row in items(data, 'terms'):
                if isinstance(row, dict) and isinstance(row.get('name'), str) and (number(row.get('count')) or 0) > 0:
                    key = str(row.get('id', ''))
                    if re.fullmatch(r'\d{1,14}', key):
                        rows[key] = {'label': row['name'], 'sourceId': key, 'category': 'genre'}
            if data.get('hasMore') is not True:
                break
        return list(rows.values())


class PornhwaDB(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            r'/series/(\d{1,14})/?', rf'/(?:series|read)/(\d{{1,14}})(?:/{SEGMENT})+/?',
            Cards('article.cover-card:has(h3.cover-title a)', 'h3.cover-title a',
                  next='nav.pagination a.pagination-step:-soup-contains("Next")'),
            Meta('section.series-main h1#series-title', 'section.series-main .series-cover img', 'section.series-main .synopsis > p',
                 'section.series-main dt:-soup-contains("Also known as") + dd',
                 'section.series-main ul[aria-label="Genres"] a', author='section.series-main p.credits a',
                 status='section.series-main dt:-soup-contains("Status") + dd'),
            Archive('ol.chapter-list > li:has(a[data-edition])', anchor='a[data-edition]', title='.chapter-title', number_attr='data-number',
                    next='.chapter-results nav.pagination a.pagination-step:-soup-contains("Next")'),
            '', Browse('/browse', (('sort', 'read'), ('page', '{page}'))), query('/browse', 'q'),
            Browse('/browse', (('page', '{page}'),)), Browse('/browse', (('g', '{tag}'), ('page', '{page}'))),
            title_path='/series/',
        ))

    def document(self, http, url):
        doc, final = super().document(http, url)
        for template in doc.select('template[id^="P:"]'):
            segment_id = 'S:' + template['id'].split(':', 1)[1]
            part = doc.find(id=segment_id)
            if part:
                for node in list(part.contents):
                    template.insert_before(node.extract())
                part.decompose()
                template.decompose()
        return doc, final

    def chapters(self, http, doc, url):
        editions = {url: doc}
        for node in doc.select('.edition-switch a[href]:not([aria-current])'):
            target = self.site_link(node['href'], url)
            if target and self.title_key(target) == self.title_key(url) and target not in editions:
                editions[target] = self.title_document(http, target)[0]
        rows, truncated = {}, False
        for target, page in editions.items():
            entries, partial = self.list_chapters(http, page, target, self.layout.archive)
            for entry in entries:
                rows[entry['url']] = entry
            truncated |= partial
        return self.order(rows), truncated

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        models = flight_models(flight_stream(str(doc)))
        for model in models.values():
            for item in dictionaries(model):
                if {'edition', 'pages'} <= item.keys():
                    rows = resolve_fields(item['pages'], models, [50000])
                    if not isinstance(rows, list):
                        continue
                    records = sorted((row for row in rows if isinstance(row, dict)),
                                     key=lambda row: number(row.get('ordinal')) or 0)
                    return [image_url(row.get('url'), final) for row in records]
        return []


class MyHentaiComics(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/gallery/(?!show/|category/|artist/|group/)({SEGMENT}(?:/{SEGMENT})?)/?',
            r'/gallery/show/(\d{1,14})/\d{1,4}/?',
            Cards('li.item:not(.image-block) .comic-inner a[href]', '', 'h2.comic-name', next='li.next a'),
            Meta('div.comic-description h1', 'div.comic-cover img', 'div.comic-description',
                 genres='div.comic-description a[href*="/gallery/category/"]',
                 author='div.comic-description a[href*="/gallery/artist/"], div.comic-description a[href*="/gallery/group/"]'),
            Archive(''), '', Browse('/views/{page}'), Browse('/search/{page}', (('query', '{query}'),)),
            Browse('/gallery/{page}'), Browse('/gallery/category/{tag}/{page}'), title_path='/gallery/',
        ))

    def chapters(self, http, doc, url):
        link = doc.select_one('div.comic-cover a[href]')
        target = self.site_link(link['href'], url) if link else ''
        if not self.is_chapter(target):
            return [], False
        chapter = f'{self.ROOT}/gallery/show/{self.chapter_key(target)}/1'
        return [self.chapter(chapter, 'Глава', 1)], False

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        image = picture(doc.select_one('ul.gallery-slide li img'), final)
        path = urlsplit(image)
        if not image or not re.search(r'/\d{3}\.[A-Za-z0-9]{2,5}$', path.path):
            return []
        chapter = self.chapter_key(url)
        count = 1
        for link in doc.select('ul li a[href*="/gallery/show/"]'):
            target = self.site_link(link['href'], final)
            if self.chapter_key(target) == chapter:
                n = int(urlsplit(target).path.rstrip('/').rsplit('/', 1)[-1])
                count = max(count, n)
        if count > MAX_PAGES:
            raise SourceError('Превышен лимит страниц галереи.')
        return [urlunsplit(path._replace(path=re.sub(r'\d{3}(?=\.[A-Za-z0-9]+$)', f'{n:03d}', path.path)))
                for n in range(1, count + 1)]

    def title_for(self, url):
        return ''

    def saved_chapter_matches(self, target, title):
        return self.confirm_archive_membership(target, title)


def public_api(host, path, query):
    args = parse_qs(query)
    if host == 'kuramanga.com' and path == '/search':
        return (set(args) <= {'ajax', 'page', 'name', 'genre'} and args.get('ajax') == ['1']
                and len(args.get('page', [])) == 1 and bool(re.fullmatch(r'\d{1,4}', args['page'][0]))
                and all(len(value) == 1 and len(value[0]) <= 160 for value in args.values()))
    if host == 'gensura.net' and path == '/advanced-search/':
        return (set(args) <= {'search', 'type', 'sort', 'page', 'name', 'include_tags'} and args.get('search') == ['1']
                and args.get('sort') in (['0'], ['1'], ['2']) and args.get('type') == ['0']
                and len(args.get('page', [])) == 1 and bool(re.fullmatch(r'\d{1,4}', args['page'][0]))
                and all(len(value) == 1 and len(value[0]) <= 160 for value in args.values()))
    if host == 'hentaikisu.com' and path == '/backend/infinite.index.php':
        return bool(re.fullmatch(r'p=[1-9]\d{0,3}', query))
    if host == 'hentara.com':
        return not query and bool(re.fullmatch(rf'/r2-data/(?:index|comics/{SEGMENT}|episodes/{SEGMENT}/\d{{1,9}})\.json', path))
    if host == 'www.mgeko.cc' and path == '/browse-comics/data/':
        return (set(args) <= {'page', 'sort', 'safe_mode', 'include_genres', 'q'} and args.get('safe_mode') == ['0']
                and args.get('sort') in (['latest'], ['popular_all_time']) and len(args.get('page', [])) == 1
                and bool(re.fullmatch(r'\d{1,4}', args['page'][0]))
                and all(len(value) == 1 and len(value[0]) <= 160 for value in args.values()))
    if host == 'manhuatop.org':
        if path == '/api/genres':
            return bool(re.fullmatch(r'page=[1-9]\d{0,3}', query))
        values = args.get('path', [])
        if len(values) != 1 or not values[0].startswith('/') or len(values[0]) > 1100:
            return False
        target = urlsplit(values[0])
        if target.netloc or target.scheme or target.fragment:
            return False
        if path == '/api/discovery':
            params = parse_qs(target.query)
            return (set(args) == {'path'} and bool(re.fullmatch(rf'/series/(?:page/\d{{1,4}}/)?|/search/{SEGMENT}/', target.path)) and
                    set(params) <= {'page', 'sort', 'genre'} and params.get('sort') in (['trending-week'], ['latest_update']) and
                    all(len(part) == 1 and re.fullmatch(r'\d{1,14}', part[0])
                        for key, part in params.items() if key != 'sort'))
        if path == '/api/reader' and set(args) == {'resource', 'path'}:
            if args['resource'] == ['chapters']:
                return bool(re.fullmatch(rf'/manhua/{SEGMENT}/?', target.path) and
                            re.fullmatch(r'tab=chapters&chapter_page=\d{1,4}', target.query))
            if args['resource'] == ['content']:
                return not target.query and bool(re.fullmatch(rf'/manhua/{SEGMENT}/{SEGMENT}/?', target.path))
    return False


def public_form(url, data):
    if not isinstance(data, dict):
        return False
    if url == 'https://manhwalike.com/search/html/1':
        return set(data) == {'keyword'} and isinstance(data['keyword'], str) and 1 <= len(data['keyword']) <= 160
    if url == 'https://hentaitnt.net/wp-admin/admin-ajax.php':
        return (set(data) == {'action', 'type', 'parent_id', 'per_page', 'order'} and data['action'] == 'baka_ajax'
                and data['type'] == 'load_chapters_paginated' and data['per_page'] == '10000' and data['order'] == 'newest_first'
                and isinstance(data['parent_id'], str) and bool(re.fullmatch(r'\d{1,15}', data['parent_id'])))
    return False
