"""Direct protocols for installed Goda and Monochrome family sources."""

import os
import re
from collections import deque
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, MANGA, SLUG
from manga_direct_payloads import JsonSeries, items, segment
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, MAX_PAGES, Meta, number, picture
from manga_source_tags import unique
from manga_webcomics import param, query_url
from source_parser import SourceError, public_url


UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
VERSION = r'[0-9]{1,10}'
ITEM_ID = r'[A-Za-z0-9_-]{1,80}'
MONOCHROME_SCAN_API = 'https://api.manga.d34d.one'
MONOCHROME_DEMO_API = 'https://api-3qnqyl7llq-lz.a.run.app'


def monochrome_custom_api():
    value = os.getenv('MONOCHROME_CUSTOM_API_URL', '').strip().rstrip('/') or MONOCHROME_DEMO_API
    parts = urlsplit(value)
    if parts.path or parts.query or parts.fragment:
        raise SourceError('Адрес Monochrome Custom должен указывать на корень HTTPS API.')
    return public_url(value, resolve_dns=False, allow_api=True).rstrip('/')


class Monochrome(JsonSeries):
    def __init__(self, identity, custom=False):
        super().__init__(identity, rf'/manga/({UUID})/?', rf'/chapters/({UUID})/?', interval=.35)
        self.custom = custom

    @property
    def api(self):
        return monochrome_custom_api() if self.custom else MONOCHROME_SCAN_API

    def title_url(self, manga):
        return self.ROOT + '/manga/' + manga

    def title_for(self, url):
        return self.title_url(param(url, 'manga'))

    def chapter_identity(self, url):
        return self.chapter_key(url), param(url, 'manga')

    def saved_title_url(self, url):
        value = self.canonical(url)
        identity = urlsplit(value).path.strip('/')
        return self.title_url(identity) if re.fullmatch(UUID, identity) else value

    def saved_chapter(self, row, root, title):
        raw = row.get('realUrl') or row.get('url') or ''
        value = self.canonical(raw)
        manga = self.title_key(title)
        if self.is_chapter(value):
            selected = param(value, 'manga')
            return query_url(value, manga=manga) if selected in ('', manga) else ''
        combined = re.fullmatch(rf'/?({UUID})/({UUID})\|{VERSION}\|[0-9]{{1,4}}', raw)
        if combined and combined[1] == manga:
            return query_url(self.ROOT + '/chapters/' + combined[2], manga=manga)
        return ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'manga') == self.title_key(title)

    def record_manga(self, row):
        key, title = row.get('id'), row.get('title')
        if not isinstance(key, str) or not re.fullmatch(UUID, key) or not isinstance(title, str) or not title:
            raise SourceError('Monochrome изменил формат карточки тайтла.')
        version = str(row.get('version', ''))
        cover = f'{self.api}/media/{key}/cover.jpg?version={version}' if re.fullmatch(VERSION, version) else ''
        status = {'ongoing': 'ongoing', 'hiatus': 'hiatus', 'completed': 'completed', 'cancelled': 'cancelled'}
        return self.record(self.title_url(key), title, cover, description=str(row.get('description') or ''),
                           authors=[value for value in (row.get('author'), row.get('artist')) if isinstance(value, str)],
                           status=status.get(row.get('status'), ''))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        data = self.json(http, query_url(self.api + '/manga', limit=10, offset=(page - 1) * 10, title=query))
        rows = data.get('results') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise SourceError('Monochrome изменил формат каталога.')
        total = number(data.get('total')) or 0
        return [self.record_manga(row) for row in rows if isinstance(row, dict)], total > (page - 1) * 10 + len(rows)

    def series(self, http, url):
        manga = self.title_key(url)
        path = self.api + '/manga/' + manga
        info = self.json(http, path)
        if not isinstance(info, dict) or info.get('id') != manga:
            raise SourceError('Monochrome вернул другой тайтл.')
        rows = {}
        for row in self.chapters_from_api(http, path):
            identity, n = row.get('id'), number(row.get('number'))
            if not isinstance(identity, str) or not re.fullmatch(UUID, identity) or n is None:
                continue
            chapter = query_url(self.ROOT + '/chapters/' + identity, manga=manga)
            label = f'Chapter {n:g}'
            if row.get('name'):
                label += ' - ' + str(row['name'])
            vol = str(row.get('volume', ''))
            rows[chapter] = self.chapter(chapter, label, n, str(row.get('uploadTime') or '')[:10],
                                         int(vol) if re.fullmatch(r'[1-9]\d{0,5}', vol) else 1,
                                         str(row.get('scanGroup') or ''))
        return self.record_manga(info), self.order(rows)

    def chapters_from_api(self, http, path):
        rows = self.json(http, path + '/chapters')
        if not isinstance(rows, list):
            raise SourceError('Monochrome изменил формат оглавления.')
        return [row for row in rows if isinstance(row, dict)]

    def pages(self, http, url):
        manga, chapter = param(url, 'manga'), self.chapter_key(url)
        rows = self.chapters_from_api(http, self.api + '/manga/' + manga)
        selected = next((row for row in rows if row.get('id') == chapter), {})
        version, length = str(selected.get('version', '')), selected.get('length')
        if not re.fullmatch(VERSION, version) or type(length) is not int or not 1 <= length <= 1500:
            return []
        root = self.api + f'/media/{manga}/{chapter}/'
        return [f'{root}{idx}.jpg?version={version}' for idx in range(1, length + 1)]


class Goda(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            MANGA, rf'/manga/{SLUG}(?:/{SEGMENT})?/?',
            Cards('.container > .cardlist .pb-2 a', '', 'h3', next='a[aria-label="NEXT"] button'),
            Meta('main h1', 'main img.object-cover'), Archive(''), '#chapcontent > div > img',
            Browse('/hots/page/{page}'), Browse('/s/{query}', (('page', '{page}'),)),
            Browse('/newss/page/{page}'),
        ))

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(rf'{ITEM_ID}/{ITEM_ID}', urlsplit(url).fragment))

    def is_title(self, url):
        return super().is_title(url) and not self.is_chapter(url)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        h1 = doc.select_one('main h1')
        fields = h1.parent.parent.find_all(recursive=False)
        if len(fields) >= 5 and fields[4].name == 'p':
            row['description'] = node_text(fields[4])
            row['authors'] = unique(node_text(item).removesuffix(' ,') for item in fields[1].find_all(recursive=False)[1:])
            row['genres'] = unique(node_text(item).removesuffix(' ,') for item in fields[2].find_all(recursive=False)[1:])
            row['tags'] = unique(node_text(item).lstrip('#') for item in fields[3].find_all(recursive=False))
        own_title = ' '.join(h1.find_all(string=True, recursive=False)).strip()
        if own_title:
            row['title'] = own_title
            row['aliases'] = [own_title]
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        rows, more = super().catalogue(http, page, query=query, sort=sort, tag=tag)
        for row in rows:
            src = param(row['cover'], 'url')
            if src:
                row['cover'] = image_url(src, self.ROOT)
        return rows, more

    def chapters(self, http, doc, url):
        node = doc.select_one('#mangachapters[data-mid]')
        mid = node.get('data-mid', '') if node else ''
        if not re.fullmatch(ITEM_ID, mid):
            raise SourceError('Goda не предоставил идентификатор тайтла.')
        outline = self.fragment(http, query_url(self.ROOT + '/manga/get', mid=mid, mode='all'), url)
        rows = {}
        for item in outline.select('.chapteritem a[data-cs][href]'):
            cid = item['data-cs']
            target = self.site_link(item['href'], url)
            if not target or not re.fullmatch(ITEM_ID, cid):
                continue
            target = urlunsplit(urlsplit(target)._replace(fragment=f'{mid}/{cid}'))
            if self.is_chapter(target):
                rows[target] = self.chapter(target, item.get('data-ct') or node_text(item))
        return self.order(rows), False

    def fragment(self, http, url, referer):
        self.origin.wait(getattr(http, 'deadline', None))
        body, final, _ = http.document(url, headers={'Referer': referer}, action='native-series-html-api')
        if final != url:
            raise SourceError('Goda перенаправил запрос читалки.')
        return BeautifulSoup(body, 'html.parser')

    def pages(self, http, url):
        mid, cid = urlsplit(url).fragment.split('/')
        doc = self.fragment(http, query_url(self.ROOT + '/chapter/getcontent', m=mid, c=cid), url)
        return [picture(node, url, ('data-src',)) for node in doc.select(self.layout.reader)]

    def saved_chapter(self, row, root, title):
        for value in (row.get('realUrl'), row.get('url')):
            target = self.site_link(value, root.rstrip('/') + '/manga/')
            if self.is_chapter(target):
                return target
        return ''

    def saved_chapter_matches(self, target, title):
        return self.confirm_archive_membership(target, title)

    def chapter_identity(self, url):
        return super().chapter_identity(url), urlsplit(url).fragment


class CosplayGallery(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            rf'/image/{SLUG}/?', rf'/story/{SLUG}/?',
            Cards('div.image-list-item:has(a[href*="/image/"])', 'a[href*="/image/"]',
                  '.image-list-item-title', next='div.wp-pagenavi > a[rel=next]'),
            Meta('h1, title', '#detail img', tags='#detail_tag a[href*="/tag/"]'), Archive(''),
            'amp-img[src*=upload]:not(.related-thumbnail)',
            Browse('/ranking/page/{page}/'), Browse('/search/keyword/{query}/page/{page}/'), Browse('/search/page/{page}/'),
            Browse('/tag/{tag}/page/{page}/'), title_path='/image/', suffix='/',
            tag_index='/ranking-tag/', tag_anchor='#tags a[href*="/tag/"]',
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        layout = self.layout
        route = layout.search if query else layout.browse_tag if tag else layout.latest if sort == 'updated' else layout.popular
        doc, final = self.document(http, route.url(self.ROOT, page, query, tag))
        cards = layout.cards if doc.select_one('div.image-list-item') else Cards(
            '#entry_list > li > a[href*="/image/"]', '', 'span:not(.posted)', next='a.paginator_page[rel=next]')
        return self.card_rows(doc, final, cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        title = doc.select_one('meta[property="og:title"][content]')
        if title:
            row['title'] = title['content'].rsplit(' - ', 1)[0]
            row['aliases'] = [row['title']]
        row['status'] = 'completed'
        return row

    def chapters(self, http, doc, url):
        target = f'{self.ROOT}/story/{self.title_key(url)}/'
        return [self.chapter(target, 'Галерея', 1)], False


class EroMuse(DirectCatalogue):
    def __init__(self, identity):
        self.erofus = identity[1] == 'Erofus'
        self.root_path = '/comics/' if self.erofus else '/porn/album/'
        path = self.root_path + rf'({SEGMENT}(?:/{SEGMENT}){{0,8}})/?'
        self.album = 'a.a-click:has(img)' if self.erofus else 'a.c-tile:has(img):not(:has(.members-only))'
        self.reader_selector = 'a.a-click[href*="/pic/"] img' if self.erofus else 'a.c-tile[href*="/porn/picture/"] img'
        super().__init__(identity, Layout(
            path, path, Cards(self.album, ''), Meta('title', self.album + ' img', tags='div.album-tag-container a',
                                                    author='div.top-menu-breadcrumb li:nth-child(2), div.navigation-breadcrumb li:nth-child(3)'),
            Archive(''), self.reader_selector, Browse(self.root_path), title_path=self.root_path,
        ))

    def is_chapter(self, url):
        return super().is_chapter(url) and param(url, 'mv_album') == '1'

    def title_for(self, url):
        return urlunsplit(urlsplit(url)._replace(query='', fragment=''))

    def stored_target(self, value):
        return self.canonical(value)

    def saved_title_url(self, value):
        return self.title_for(self.canonical(value))

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        return query_url(self.title_for(target), mv_album=1) if self.is_title(target) else ''

    def saved_chapter_matches(self, target, title):
        selected, work = self.title_key(target), self.title_key(title)
        return bool(selected and work and (selected == work or selected.startswith(work + '/')))

    def links(self, doc, final):
        for node in doc.select(self.album):
            link = self.site_link(node.get('href'), final)
            if self.is_title(link):
                yield self.title_for(link), node

    def paging(self, doc, final):
        anchor = doc.select_one('.pagination span.current + span a')
        if not anchor:
            return ''
        target = self.site_link(anchor.get('href'), final)
        if target and target != final:
            return target
        n = node_text(anchor)
        if not re.fullmatch(r'\d{1,4}', n):
            return ''
        if param(final, 'page'):
            return query_url(final, page=n)
        path = re.sub(r'/\d+/?$', '', urlsplit(final).path.rstrip('/'))
        return urlunsplit(urlsplit(final)._replace(path=path + '/' + n))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if self.erofus:
            path = '/' if query else self.root_path + 'various-authors'
            ordering = 'recent' if sort == 'updated' else 'viewed'
            url = query_url(self.ROOT + path, page=page, sort=ordering, **({'search': query} if query else {}))
        else:
            path = '/search' if query else self.root_path + 'Various-Authors'
            ordering = {'sort': 'date'} if sort == 'updated' else {}
            url = query_url(self.ROOT + path, page=page, **({'q': query} if query else {}), **ordering)
        doc, final = self.document(http, url)
        rows = {}
        for target, node in self.links(doc, final):
            key = self.title_key(target)
            title = node_text(node)
            if not title:
                continue
            if key.count('/') == 0 and not query:
                detail, actual = self.document(http, query_url(target, **ordering))
                for comic, card in self.links(detail, actual):
                    if self.title_key(comic).startswith(key + '/') and (text := node_text(card)):
                        rows[comic] = self.record(comic, text, picture(card.select_one('img'), actual))
            elif key.count('/') > 0:
                rows[target] = self.record(target, title, picture(node.select_one('img'), final))
        return list(rows.values()), bool(self.paging(doc, final))

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['title'] = row['title'].split(' | ', 1)[0]
        row['aliases'] = [row['title']]
        return row

    def scan(self, http, url, doc, final, descend):
        result, seen, queue = {}, set(), deque([(url, doc, final)])
        root = self.title_key(url)
        while queue and len(seen) < 100:
            target, doc, final = queue.popleft()
            if target in seen:
                continue
            seen.add(target)
            if doc is None:
                doc, final = self.document(http, target)
            linked = [(child, node_text(node)) for child, node in self.links(doc, final)
                      if self.title_key(child).startswith(root + '/')]
            if descend:
                for node in doc.select(self.reader_selector):
                    value = picture(node, final, ('data-src',))
                    if value:
                        current, replacement = ('/thumb/', '/medium/') if self.erofus else ('/th/', '/fl/')
                        result[value.replace(current, replacement, 1)] = ''
                queue.extend((child, None, None) for child, _ in linked if child not in seen)
            else:
                result.update(linked)
                if target == url and doc.select_one(self.reader_selector):
                    result[self.title_for(target)] = 'Глава'
            if (more := self.paging(doc, final)) and self.title_key(more).startswith(root) and more not in seen:
                queue.appendleft((more, None, None))
            if len(result) >= MAX_PAGES:
                break
        return result, bool(queue)

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            return super().inspect(value, http)
        title = self.title_for(url)
        doc, final = self.title_document(http, title)
        pages, more = self.scan(http, title, doc, final, True)
        if not pages or more:
            raise SourceError('Источник не предоставил полный список страниц.')
        return self.reader_result(self.metadata(doc, final, self.meta), url,
                                  [self.chapter(url, 'Глава', 1)], list(pages))

    def chapters(self, http, doc, url):
        rows, more = self.scan(http, url, doc, url, False)
        return [self.chapter(query_url(target, mv_album=1), label, i)
                for i, (target, label) in enumerate(rows.items(), 1)], more


class PizzaReader(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/comics/{SLUG}/?', rf'/read/{SLUG}/{SEGMENT}/{SEGMENT}/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/comics/' + self.chapter_key(url)

    def record_comic(self, data, target):
        title = data.get('title')
        if not isinstance(title, str) or not title:
            raise SourceError('PizzaReader не предоставил название тайтла.')
        genres = [label.get('name') for label in data.get('genres') or [] if isinstance(label, dict)]
        authors = [name for name in (data.get('author'), data.get('artist')) if isinstance(name, str)]
        return self.record(target, title, image_url(data.get('thumbnail'), self.ROOT), description=data.get('description') or '',
                           genres=genres, authors=authors, status=data.get('status') or '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        root = self.ROOT + '/api'
        if query:
            term = segment(query)
            if not term:
                return [], False
            url = root + '/search/' + term
        else:
            url = root + '/comics'
        rows = items(self.json(http, url), 'comics')
        records = {}
        recent = sorted((row for row in rows if isinstance(row, dict) and isinstance(row.get('last_chapter'), dict)),
                        key=lambda row: str(row['last_chapter'].get('published_on') or ''), reverse=True)[:10]
        for item in recent if sort == 'updated' and not query else rows:
            if isinstance(item, dict) and self.is_title(target := self.site_link(item.get('url'))):
                records[target] = self.record_comic(item, target)
        return list(records.values()), False

    def series(self, http, url):
        data = self.json(http, self.ROOT + '/api/comics/' + self.title_key(url), url)
        comic = data.get('comic') if isinstance(data, dict) else None
        if not isinstance(comic, dict):
            raise SourceError('PizzaReader не предоставил карточку тайтла.')
        result = {}
        for row in items(comic, 'chapters'):
            if not isinstance(row, dict):
                continue
            target = self.site_link(row.get('url'))
            if not self.is_chapter(target) or self.chapter_key(target) != self.title_key(url):
                continue
            n = number(row.get('chapter'))
            sub = row.get('subchapter')
            if n is not None and type(sub) is int and 0 < sub < 10000:
                n += float(f'0.{sub}')
            teams = [team['name'] for team in row.get('teams') or [] if isinstance(team, dict) and isinstance(team.get('name'), str)]
            result[target] = self.chapter(target, row.get('full_title') or '', n,
                                          str(row.get('published_on') or '')[:10], translator=' & '.join(teams))
        return self.record_comic(comic, url), self.order(result)

    def pages(self, http, url):
        data = self.json(http, self.ROOT + '/api' + urlsplit(url).path, url)
        chapter = data.get('chapter') if isinstance(data, dict) else None
        return [image_url(page, url) for page in items(chapter, 'pages')]


def public_api(host, path, query):
    if host == 'hni-scantrad.net':
        return not query and bool(re.fullmatch(rf'/api/(?:comics(?:/{SEGMENT})?|search/{SEGMENT}|read/{SEGMENT}/{SEGMENT}/{SEGMENT})/?', path))
    if host == 'manhuascans.org':
        args = parse_qs(query)
        if path == '/manga/get':
            return set(args) == {'mid', 'mode'} and args['mode'] == ['all'] and len(args['mid']) == 1 and bool(
                re.fullmatch(ITEM_ID, args['mid'][0]))
        if path == '/chapter/getcontent':
            return set(args) == {'m', 'c'} and all(len(values) == 1 and re.fullmatch(ITEM_ID, values[0]) for values in args.values())
        return False
    if host != urlsplit(MONOCHROME_SCAN_API).hostname:
        try:
            if host != urlsplit(monochrome_custom_api()).hostname:
                return False
        except (ValueError, SourceError):
            return False
    if path == '/manga':
        args = parse_qs(query, keep_blank_values=True)
        return (set(args) == {'title', 'offset', 'limit'} and args['limit'] == ['10'] and
                len(args['offset']) == len(args['title']) == 1 and
                bool(re.fullmatch(r'\d{1,5}', args['offset'][0])) and len(args['title'][0]) <= 160)
    if re.fullmatch(rf'/manga/{UUID}(?:/chapters)?', path):
        return not query
    return bool(re.fullmatch(rf'/media/{UUID}/(?:cover|{UUID}/[1-9]\d{{0,3}})\.jpg', path) and
                re.fullmatch(rf'version={VERSION}', query))
