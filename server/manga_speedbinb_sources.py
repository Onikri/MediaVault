"""Public catalogues for the Japanese SpeedBinb extensions in Keiyoushi."""

import json
import re
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_CHAPTERS, Meta, SeriesPort, number, picture
from manga_speedbinb import CID, chapter_pages, reader_pages, reader_url
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ID = r'[0-9]{1,15}'
DATA_ID = r'[A-Za-z0-9_.~-]{1,160}'
TAG_ID = r'(?:genre|category|label|tag_id|category_id):[0-9]{1,12}'
HTML_INSERT = re.compile(r"""insertAdjacentHTML\(\s*['"]\w+['"],\s*("(?:[^"\\]|\\.)*")""")


def public_api(host, path, query):
    if host != 'kirapo.jp' or path != '/api/title-list':
        return False
    pairs = parse_qsl(query)
    values = dict(pairs)
    return (len(values) == len(pairs) and 1 <= len(values.get('read_at', '')) <= 64
            and set(values) <= {'read_at', 'word', 'label', 'genre', 'category'}
            and all(len(value) <= 160 for value in values.values()))


def without_local(url):
    parts = urlsplit(url)
    pairs = [(name, value) for name, value in parse_qsl(parts.query) if name != 'mv_title']
    return query_url(urlunsplit(parts._replace(query='', fragment='')), **dict(pairs))


def terms(doc, selector, field, category='genre'):
    result = {}
    for node in doc.select(selector):
        key = param(node.get('href', ''), field)
        label = node_text(node)
        if label and key.isdecimal() and len(key) <= 12:
            result[key] = {'label': label, 'sourceId': f'{field}:{key}', 'category': category}
    return list(result.values())


class SpeedCatalogue(SeriesPort):
    def document(self, http, url, *, xhr=False):
        from manga_sources import guard

        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'},
                                      action='speedbinb-xhr' if xhr else 'speedbinb-site')
        final = self.site_link(final)
        if not final:
            raise SourceError('Источник перенаправил на неизвестный сайт.')
        if xhr:
            try:
                raw = ''.join(json.loads(item[1]) for item in HTML_INSERT.finditer(raw))
            except (ValueError, RecursionError):
                raise SourceError('Источник изменил формат списка глав.') from None
        doc = BeautifulSoup(raw, 'html.parser')
        guard(doc)
        return doc, final

    def chapter_identity(self, url):
        return urlsplit(url).path.rstrip('/'), param(url, 'cid')

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return reader_pages(http, doc, final)

    def saved_chapter_matches(self, target, title):
        parent = self.title_for(target)
        return bool(parent and self.title_key(parent) == self.title_key(title))

    def details(self, http, url):
        url = self.saved_title_url(url)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на карточку источника.')
        return self.metadata(*self.title_document(http, url), self.meta)


class BookLive(SpeedCatalogue):
    cards = Cards('ul.search_item_list > li.item', 'h3.title_ellipsis a', cover='div.picture img',
                  next='.bl-pager li.page_nav_next:not(.page_stop)')
    meta = Meta('#breadcrumb .book_title', '#product_detail_area .product_image img', '#product_summary .product_description',
                genres='#product_field a[href*="/g_ids/"]', tags='#product_tag_area .tags_list a',
                author='#product_detail_area dl.author a', status='ul.product_topic li')

    def __init__(self, identity):
        super().__init__(identity, rf'/product/index/title_id/({ID})(?:/vol_no/{ID})?/?', r'(/bviewer/?)', interval=.35)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'sort': 't3' if query else 't2' if sort == 'updated' else 't1', 'page_no': page}
        if query:
            args['keyword'] = query
        if re.fullmatch(ID, tag):
            args['g_ids'] = tag
        rows, more = self.card_rows(*self.document(http, query_url(self.ROOT + '/search/keyword', **args)), self.cards)
        return [self.large_cover(row) for row in rows], more

    @staticmethod
    def large_cover(row):
        if row['cover']:
            row['cover'] = image_url(urljoin(row['cover'], 'X.jpg'), row['cover'])
        return row

    def metadata(self, doc, url, spec):
        return self.large_cover(super().metadata(doc, url, spec))

    def saved_title_url(self, value):
        value = self.canonical(value)
        key = self.title_key(value) or urlsplit(value).path.strip('/')
        return self.ROOT + '/product/index/title_id/' + key if re.fullmatch(ID, key) else ''

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(rf'{ID}_{ID}', param(url, 'cid')))

    def title_for(self, url):
        cid = param(url, 'cid')
        return self.saved_title_url('/' + cid.split('_', 1)[0]) if self.is_chapter(url) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        match = self.TITLE_PATH.fullmatch(urlsplit(target).path)
        volume = urlsplit(target).path.strip('/').rsplit('/', 1)[-1]
        if (match and '/vol_no/' in target and match[1] == self.title_key(title)) or re.fullmatch(ID, urlsplit(target).path.strip('/')):
            return query_url(self.ROOT + '/bviewer/', cid=f'{self.title_key(title)}_{volume}')
        return ''

    def chapters(self, http, doc, final):
        if doc.select_one('#product_detail_area .category-label--l, #product_detail_area .category-label--b'):
            return [], False
        rows = {}
        for node in doc.select('div.series_list_area li.item') or doc.select('#product_detail_area'):
            viewer = node.select_one('a.bl-bviewer[data-title][data-vol]')
            free = node.select_one('a.bl-free_reading[href*="/title_id/"]')
            if node.select_one('a.reservation_action') or not (viewer or free):
                continue
            if viewer:
                cid = f'{viewer["data-title"]}_{viewer["data-vol"]}'
            else:
                path = urlsplit(free['href']).path
                match = re.fullmatch(rf'/product/index/title_id/({ID})/vol_no/({ID})/?', path)
                cid = f'{match[1]}_{match[2]}' if match else ''
            if not re.fullmatch(rf'{ID}_{ID}', cid):
                continue
            target = query_url(self.ROOT + '/bviewer/', cid=cid)
            vol = int(cid.split('_')[1])
            label = node_text(node.select_one('h3 a, h1')) or f'第{vol}巻'
            if node.select_one('a.bl-cart') and not free:
                label = '試し読み · ' + label
            rows[target] = self.chapter(target, label, vol, season=vol or 1)
        return self.order(rows), False

    def pages(self, http, url):
        return chapter_pages(http, self.ROOT + '/bib-api/bibGetCntntInfo', param(url, 'cid'), url)


class Cmoa(SpeedCatalogue):
    normal = Cards('li.search_result_box', 'div.search_result_box_left a.title',
                   'div.search_result_box_right_sec1 a.title', 'div.search_result_box_left img', next='li.next:not(.nopage)')
    latest = Cards('ul.title_list li.title_wrap', 'div.thum_box a', 'div.text_box p.title_name',
                   'div.thum_box img', next='div.pageSlider div.swiper-slide.selected + div.swiper-slide')
    meta = Meta('section.brCramb a[href^="/title/"]', 'div.thumBox img', '#comic_description > p',
                genres='div.category_line_f_r_l.genre_detail a', tags='a.comic_mark_thum',
                author='div.title_details_author_name a', status='div.volume')

    def __init__(self, identity):
        super().__init__(identity, rf'/title/({ID})/?', rf'/reader/browserviewer/content_id/({DATA_ID})/?', interval=.35)

    def saved_title_url(self, value):
        value = self.canonical(value)
        key = self.title_key(value) or urlsplit(value).path.strip('/')
        return self.ROOT + '/title/' + key if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        key = self.chapter_key(target) or urlsplit(target).path.strip('/')
        if re.fullmatch(DATA_ID, key):
            return query_url(self.ROOT + f'/reader/browserviewer/content_id/{key}/', mv_title=self.title_key(title))
        return ''

    def title_for(self, url):
        title = param(url, 'mv_title')
        return self.ROOT + '/title/' + title if re.fullmatch(ID, title) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or tag:
            args = {'page': page}
            if query:
                args['word'] = query
            if re.fullmatch(ID, tag):
                args['genre_id'] = tag
            url, spec = query_url(self.ROOT + '/search/result', **args), self.normal
        elif sort == 'updated':
            url, spec = query_url(self.ROOT + '/newrelease/', page=page), self.latest
        elif page == 1:
            url, spec = self.ROOT + '/search/purpose/ranking/all?period=daily&daily=all', self.normal
        else:
            return [], False
        return self.card_rows(*self.document(http, url), spec)

    def title_document(self, http, url):
        return super().title_document(http, query_url(url, page=1, order='down'))

    def chapters(self, http, doc, final):
        rows = {}
        title = self.title_key(final)
        pages = max((int(node_text(node)) for node in doc.select('div.pagination li a') if node_text(node).isdecimal()), default=1)
        for page in range(1, min(pages, 80) + 1):
            if page != 1:
                doc, _ = self.document(http, query_url(final.split('?')[0], page=page, order='down'))
            for node in doc.select('ul.title_vol_vox_vols li'):
                if not node.select_one('div.GA_free, div.title_vol_btn_box_w a[href*="browserviewer"]'):
                    continue
                cover = node.select_one('div.thum_box img[src]')
                cid = urlsplit(cover['src']).path.rsplit('/', 1)[-1].split('.', 1)[0] if cover else ''
                if not re.fullmatch(DATA_ID, cid):
                    continue
                target = query_url(self.ROOT + f'/reader/browserviewer/content_id/{cid}/', mv_title=title)
                n = number(cid.rsplit('_', 1)[-1])
                rows[target] = self.chapter(target, node_text(node.select_one('h3.title_details_title_name_h2 a')), n,
                                            season=int(n) if n and 1 <= n <= 10000 else 1)
        return self.order(rows)[:MAX_CHAPTERS], pages > 80 or len(rows) > MAX_CHAPTERS

    def pages(self, http, url):
        doc, final = self.document(http, without_local(url))
        if '/bib/reader' in urlsplit(final).path:
            raise SourceAccessError('Читалка источника не предоставляет страницы этого издания.')
        return reader_pages(http, doc, final)


class Kiraboshi(SpeedCatalogue):
    cards = Cards('#titles-container a:has(img), .content-container .grid-group .w-auto a:has(img)', '',
                  'img', 'img', title_attr='alt')
    meta = Meta('main h2', 'meta[property="og:image"]', '#plot + div',
                genres='div.pt-5 a.button-gray', author='a[href*="/authors/"]')

    def __init__(self, identity):
        title = rf'(/(?:pt/)?{SEGMENT}/{SEGMENT})/?'
        super().__init__(identity, title, rf'(/pt/{SEGMENT}/{SEGMENT})/{SEGMENT}/viewer/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + (param(url, 'mv_title') or self.chapter_key(url))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        args = {'word': query} if query else {}
        if not query and re.fullmatch(TAG_ID, tag):
            field, value = tag.split(':')
            if field in {'genre', 'category', 'label'}:
                args[field] = value
        base = self.ROOT + ('/search' if query else '/titles')
        doc, final = self.document(http, query_url(base, **args))
        rows, _ = self.card_rows(doc, final, self.cards)
        extra = doc.select_one('#more_titles_button[data-read-at]')
        if extra:
            data = self.json(http, query_url(self.ROOT + '/api/title-list', read_at=extra['data-read-at'], **args), final)
            if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                raise SourceError('Источник изменил список тайтлов.')
            for item in data['data']:
                url = self.site_link(item.get('url'), final) if isinstance(item, dict) else ''
                if self.is_title(url) and isinstance(item.get('name'), str):
                    rows.append(self.record(url, item['name'], image_url(item.get('thumbnail'), final)))
        return list({row['id']: row for row in rows}.values()), False

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/titles')
        return [row for field in ('genre', 'label', 'category') for row in terms(
            doc, f'a[href*="{field}="]', field, 'genre' if field == 'genre' else 'tag')]

    def chapters(self, http, doc, final):
        rows = {}
        for node in doc.select('.episodes-container .episode-item:not(:-soup-contains("未公開話")) a[href], .header-side a.episode-read[href]'):
            target = self.site_link(node['href'], final)
            if not self.is_chapter(target):
                continue
            slug = urlsplit(target).path.rstrip('/').split('/')[-2]
            label = node_text(node.select_one('.episode-item-left') or node.parent.select_one('.episode-item-left'))
            if not label:
                label = node_text(doc.select_one('.latest-episode-title')) or node_text(node)
            date = node_text(doc.select_one('.last-update')).split('更新')[0].strip()
            rows[target] = self.chapter(target, label, number(slug), release_date(date, '%Y年%m月%d日'))
        return self.order(rows), False


class Gaugau(SpeedCatalogue):
    cards = Cards('.works__grid .list__box', 'h4 a', cover='.thumbnail .img-books',
                  next='ol.pagination li.next a:not([href="#"])')
    meta = Meta('.mbOff h1', '.list__box .thumbnail .img-books', 'p.mbOff',
                tags='.list__text .tag__item', author='.list__text span a')

    def __init__(self, identity):
        super().__init__(identity, rf'/list/work/({SEGMENT})(?:/episodes)?/?',
                         rf'/list/work/({SEGMENT})/episodes/{SEGMENT}/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/list/work/' + self.chapter_key(url)

    def title_document(self, http, url):
        target = self.ROOT + '/list/work/' + self.title_key(url) + '/episodes'
        return super().title_document(http, target)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        slug = urlsplit(target).path.strip('/')
        return self.ROOT + '/list/work/' + self.title_key(title) + '/episodes/' + slug if re.fullmatch(SEGMENT, slug) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page}
        if query:
            path = '/list/search-result'
            args['word'] = query
        elif tag and len(tag) <= 160 and '/' not in tag and tag not in ('.', '..'):
            path = '/list/tag/' + quote(tag, safe='')
        else:
            path = '/list/works'
        return self.card_rows(*self.document(http, query_url(self.ROOT + path, **args)), self.cards)

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/list/works')
        return [{'label': node_text(node), 'sourceId': unquote(urlsplit(node['href']).path.split('/')[3]), 'category': 'tag'}
                for node in doc.select('a[href^="/list/tag/"]') if node_text(node)]

    def chapters(self, http, doc, final):
        rows = {}
        for node in doc.select('#episodes .episode__grid:not(:has(.episode__button-app, .episode__button-complete)) a[href]'):
            target = self.site_link(node['href'], final)
            if not self.saved_chapter_matches(target, final) or not self.is_chapter(target):
                continue
            label = node_text(node.select_one('.episode__num'))
            subtitle = node_text(node.select_one('.episode__title'))
            match = re.search(r'(\d+)(?:\D+(\d+))?', label)
            n = int(match[1]) + int(match[2] or 0) / 10 if match else None
            rows[target] = self.chapter(target, f'{label}「{subtitle}」' if subtitle else label, n)
        return self.order(rows), False


class Ohta(SpeedCatalogue):
    cards = Cards('.bnrList ul li a[href]', '', '.title', '.pic img')
    meta = Meta('[itemprop=name]', '', '', author='[itemprop=author]')

    def __init__(self, identity):
        title = rf'(/(?!list/?$)(?!contents/){SEGMENT}(?:/{SEGMENT}){{0,3}})/?'
        super().__init__(identity, title, rf'/contents/({DATA_ID})/?', hosts=('www.yondemill.jp',), interval=.35)

    def is_title(self, url):
        return urlsplit(url).hostname == self.hostname and super().is_title(url)

    def is_chapter(self, url):
        return urlsplit(url).hostname == 'www.yondemill.jp' and super().is_chapter(url)

    def title_for(self, url):
        path = param(url, 'mv_title')
        return self.ROOT + path if self.TITLE_PATH.fullmatch(path) else ''

    def ch_url(self, key, title):
        return query_url('https://www.yondemill.jp/contents/' + key, view=1, u0=1, mv_title=urlsplit(title).path)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        key = self.chapter_key(target) or urlsplit(target).path.strip('/')
        return self.ch_url(key, title) if re.fullmatch(DATA_ID, key) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1 or tag:
            return [], False
        rows, _ = self.card_rows(*self.document(http, self.ROOT + '/list/'), self.cards)
        return [row for row in rows if query in row['title'].casefold()], False

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        node = doc.select_one('.contentHeader[style]')
        style = re.search(r'background-image\s*:\s*url\(([^)]+)\)', node['style']) if node else None
        if style:
            row['cover'] = image_url(style[1].strip("""' "\t"""), url)
        section = doc.select_one('h3.titleBoader:-soup-contains("作品について") + dl')
        if section:
            paragraphs = []
            for item in section.find_next_siblings():
                if item.name != 'p':
                    break
                paragraphs.append(node_text(item))
            row['description'] = '\n'.join(paragraphs)[:12000]
        return row

    def chapters(self, http, doc, final):
        rows = {}
        for node in (doc.select('.backnumberList a[onclick*="openBook"]') or doc.select('.headBtnList a[onclick*="openBook"]')):
            key = re.search(rf"""openBook\(['"]({DATA_ID})['"]\)""", node['onclick'])
            if key:
                target = self.ch_url(key[1], final)
                label = node_text(node.select_one('div.title') or node)
                words = node_text(node.select_one('dt.number')).split()
                rows[target] = self.chapter(target, label, number(words[0]) if words else None)
        return self.order(rows), False

    def pages(self, http, url):
        raw, final, _ = http.document(without_local(url), headers={'Referer': self.ROOT + '/'}, action='speedbinb-site')
        match = re.search(r"""location\.href\s*=\s*['"]([^'"\\]+)['"]""", raw)
        if not match:
            raise SourceAccessError('Yondemill не открыл главу.')
        target = reader_url(urljoin(final, match[1]))
        html, final, _ = http.document(target, headers={'Referer': final}, action='speedbinb-site')
        return reader_pages(http, BeautifulSoup(html, 'html.parser'), final)


class Yomonga(SpeedCatalogue):
    index_sort = 'popular'
    cards = Cards('div.book-box4', 'a[href]', 'div.book-box4-title', 'img.book-box4-thumbnail',
                  next='.paging-next.paging-click')
    meta = Meta('.intr-title', '.intr-thumbnail', '.intr-text > .intr-desc', tags='.tag-wrapper .tag', author='.intr-writer')

    def __init__(self, identity):
        super().__init__(identity, rf'/titles/({SEGMENT})/?', rf'/titles/({SEGMENT})/?', interval=.35)

    def is_title(self, url):
        return super().is_title(url) and not param(url, 'cid')

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(CID.fullmatch(param(url, 'cid')))

    def title_for(self, url):
        return self.ROOT + '/titles/' + self.chapter_key(url) + '/'

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        cid = param(target, 'cid') or urlsplit(target).path.strip('/')
        return query_url(title.split('?')[0], episode=cid, cid=cid) if CID.fullmatch(cid) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page_num': page}
        if query:
            args['search_word'] = query
        elif re.fullmatch(r'(?:tag_id|category_id):[0-9]{1,12}', tag):
            field, key = tag.split(':')
            args[field] = key
        return self.card_rows(*self.document(http, query_url(self.ROOT + '/titles/', **args)), self.cards)

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/titles/')
        return [row for field in ('tag_id', 'category_id') for row in terms(doc, f'a[href*="{field}="]', field, 'tag')]

    def chapters(self, http, doc, final):
        rows = {}
        for node in doc.select('.episode-list[data-episode_no]'):
            link = node.select_one('a.button-type1[href]')
            cid = param(link['href'], 'cid') if link else ''
            if CID.fullmatch(cid):
                target = query_url(final.split('?')[0], episode=cid, cid=cid)
                rows[target] = self.chapter(target, node_text(node.select_one('.episode-name')), number(node['data-episode_no']))
        return self.order(rows), False

    def pages(self, http, url):
        return chapter_pages(http, self.ROOT + '/binb/sws/apis/bibGetCntntInfo.php', param(url, 'cid'), url)


class Yanmaga(SpeedCatalogue):
    index_sort = 'updated'
    rank_cards = Cards('[data-tab-name] a.mod-ranking-v2-link', '', '.mod-ranking-v2-title', 'img')
    banner_cards = Cards('a.banner-link', '', '.text-wrapper h2', '.img-bg-wrapper',
                         image_attrs=('data-bg',), next='ul.pagination > li.page-item > a.page-next')
    meta = Meta('.detailv2-outline-title', '.detailv2-thumbnail-image img', '.detailv2-description',
                tags='.detailv2-tag .ga-tag', author='.detailv2-outline-author-item a')

    def __init__(self, identity, gravure=False):
        self.gravure = gravure
        self.section = 'gravures/books' if gravure else 'comics'
        title = rf'/{self.section}/({SEGMENT})/?'
        super().__init__(identity, title, rf'/{self.section}/({SEGMENT})/{SEGMENT}/?', interval=.35)
        if gravure:
            self.meta = Meta('.detail-header-title', '.detail-header-image img', '', tags='.ga-tag')
        self.search_cards = Cards(f'main a[href^="/{self.section}/"]:has(img)', '', 'p', 'img', next='main a[rel=next]')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            args = {'q': query}
            if self.gravure:
                args.update(tab='gravures', sub='book')
            if page != 1:
                args['page'] = page
            return self.card_rows(*self.document(http, query_url(self.ROOT + '/search', **args)), self.search_cards)
        if sort == 'updated':
            route = self.section if self.gravure else 'comics/series'
            target = query_url(f'{self.ROOT}/{route}/newer/more', offset=(page - 1) * 12)
            doc, final = self.document(http, target, xhr=True)
            rows, _ = self.card_rows(doc, final, self.banner_cards)
            return rows, len(doc.select(self.banner_cards.rows)) == 12
        if self.gravure:
            url = query_url(self.ROOT + '/gravures/series', page=page)
            return self.card_rows(*self.document(http, url), self.banner_cards)
        if page == 1:
            return self.card_rows(*self.document(http, self.ROOT + '/ranking?ranking-index=0'), self.rank_cards)
        return [], False

    def title_for(self, url):
        return f'{self.ROOT}/{self.section}/{self.chapter_key(url)}'

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        key = urlsplit(target).path.strip('/')
        return title.rstrip('/') + '/' + key if re.fullmatch(SEGMENT, key) else ''

    def chapters(self, http, doc, final):
        rows, offset = {}, 0
        endpoint = final.split('?')[0].rstrip('/') + ('/more' if self.gravure else '/episodes')
        for _ in range(70):
            result, _ = self.document(http, query_url(endpoint, offset=offset), xhr=True)
            entries = result.select('li.mod-episode-item')
            for node in entries:
                link = node.select_one('a.mod-episode-link[href]')
                if not link or 'js-modal' in node.get('class', []) or node.select_one('.mod-episode-price:not(:has(.mod-episode-point--free))'):
                    continue
                target = self.site_link(link['href'], final)
                if not self.is_chapter(target) or not self.saved_chapter_matches(target, final):
                    continue
                label = node_text(node.select_one('.mod-episode-title'))
                date = release_date(node_text(node.select_one('.mod-episode-date')), '%Y/%m/%d')
                rows[target] = self.chapter(target, label, date=date)
            if len(entries) < 150:
                return self.order(rows), False
            offset += len(entries)
        return self.order(rows)[:MAX_CHAPTERS], True

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        if doc.select_one('.ga-rental-modal-sign-up, .ga-modal-open'):
            raise SourceAccessError('Глава доступна на условиях источника.')
        return reader_pages(http, doc, final)


SOURCES = (
    BookLive(('7845281380500415137', 'BookLive', 'ja', 'https://booklive.jp', True)),
    Cmoa(('1222039348961733003', "C'moA", 'ja', 'https://www.cmoa.jp', True)),
    Kiraboshi(('7760875295931980663', 'Kiraboshi', 'ja', 'https://kirapo.jp', True)),
    Gaugau(('9220365500598403749', 'がうがうモンスター＋', 'ja', 'https://gaugau.futabanet.jp', False)),
    Ohta(('1056568527385317039', 'Ohta Web Comic', 'ja', 'https://webcomic.ohtabooks.com', True)),
    Yanmaga(('2126618372106431410', 'ヤンマガ（マンガ）', 'ja', 'https://yanmaga.jp', True)),
    Yanmaga(('2227240489801599645', 'ヤンマガ（グラビア）', 'ja', 'https://yanmaga.jp', True), gravure=True),
    Yomonga(('7561635982432447429', 'Yomonga', 'ja', 'https://www.yomonga.com', False)),
)
