"""Direct public catalogue adapters for YSK Comics and Atsumaru."""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import MANGA, CHAPTER, SLUG
from manga_direct_payloads import JsonSeries, items, strings
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_CHAPTERS, Meta, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


YSK = 'www.ysk-comics.com'
YSK_SEARCH = 'api.ysk-comics.com'
ATSU = 'atsu.moe'
MPC = 'mangaplus-creators.jp'
BBATO = 'bato1.com'
ATSU_ID = r'[A-Za-z0-9_-]{1,120}'
INDEX = r'[1-9][0-9]{0,3}'
ATSU_PUBLIC = ('hidden:!=true && isAdult:=false && '
               '(mbContentRating:=[`Safe`,`Suggestive`,`Erotica`] || mbContentRating:!=*) && medium:!=[`Novel`] && views:>0')
ATSU_FILTER = r'(?P<kind>genre|tag):(?P<key>[A-Za-z0-9_-]{1,120})'
TYPESET = 'Manga,Manwha,Manhua,OEL'
CREATOR_GENRES = {'fantasy': 'Fantasy', 'action': 'Action', 'romance': 'Romance', 'horror': 'Horror',
                  'slice_of_life': 'Slice of Life', 'comedy': 'Comedy', 'sports': 'Sports',
                  'sf': 'Sci-Fi', 'mystery': 'Mystery', 'others': 'Others'}


def public_api(host, path, query):
    if host not in {YSK, YSK_SEARCH, ATSU, MPC, BBATO}:
        return False
    fields = parse_qsl(query)
    args = dict(fields)
    if len(fields) != len(args) or any(len(value) > 460 for value in args.values()):
        return False
    if host == YSK_SEARCH:
        return path == '/api/v1/search-comics-home' and set(args) == {'name'} and 3 <= len(args['name']) <= 160
    if host == YSK:
        if path == '/api/home/latest-comics' or re.fullmatch(rf'/api/comic/chapter/{SEGMENT}', path):
            return set(args) == {'page'} and bool(re.fullmatch(INDEX, args['page']))
        return not query and (path == '/api/home/best-comics' or bool(re.fullmatch(
            rf'/api/(?:comic/{SEGMENT}|chapters/images/{SEGMENT})', path)))
    if host == MPC:
        return (path == '/api/titles/recent/' and set(args) == {'page', 'l', 't'}
                and bool(re.fullmatch(INDEX, args['page'])) and args['l'] in {'en', 'es'} and args['t'] == 'episode')
    if host == BBATO:
        return path == '/get-chapter-list' and set(args) == {'slug'} and bool(re.fullmatch(SEGMENT, args['slug']))
    if path in ('/api/home2/popular', '/api/home2/recentlyUpdated'):
        keys = {'offset', 'limit', 'types', 'mediums'} | ({'timeframe'} if path.endswith('/popular') else set())
        return (set(args) == keys and bool(re.fullmatch(r'\d{1,6}', args['offset'])) and args['limit'] == '40'
                and args['types'] == TYPESET and args['mediums'] == 'Comic' and args.get('timeframe', 'daily') == 'daily')
    if path == '/collections/manga/documents/search':
        return (set(args) == {'q', 'filter_by', 'query_by', 'query_by_weights', 'num_typos', 'page', 'per_page'}
                and 1 <= len(args['q']) <= 160 and bool(re.fullmatch(INDEX, args['page'])) and args['per_page'] == '40'
                and args['query_by'] == 'title,englishTitle,otherNames,authors'
                and args['query_by_weights'] == args['num_typos'] == '4,3,2,1'
                and (args['filter_by'] == ATSU_PUBLIC or bool(re.fullmatch(
                    re.escape(ATSU_PUBLIC) + rf' && (?:genre|tag)Ids:=`{ATSU_ID}`', args['filter_by']))))
    if path == '/api/explore/availableFilters':
        return not query
    keys = {'/api/manga/page': {'id'}, '/api/manga/allChapters': {'mangaId'}, '/api/read/chapter': {'mangaId', 'chapterId'}}
    return path in keys and set(args) == keys[path] and all(re.fullmatch(ATSU_ID, value) for value in args.values())


def named(items):
    if not isinstance(items, list):
        return []
    values = [item.get('name') if isinstance(item, dict) else item for item in items]
    return [item for item in values if isinstance(item, str) and item]


class YSKComics(JsonSeries):
    def __init__(self, identity):
        lang = identity[2]
        super().__init__(identity, rf'/{lang}/comic/{SLUG}/?', rf'/{lang}/chapter/{SLUG}/?', interval=.35)

    def title_identity(self, value):
        return urlsplit(value).path.rstrip('/')

    def title_for(self, url):
        value = param(url, 'mv_title')
        return f'{self.ROOT}/{self.LANGUAGE}/comic/{value}' if re.fullmatch(SEGMENT, value) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target) and self.title_key(title):
            return query_url(target, mv_title=self.title_key(title))
        return ''

    def saved_chapter_matches(self, target, title):
        key = self.title_key(title)
        return bool(self.is_chapter(target) and key and self.title_key(self.title_for(target)) == key)

    def json(self, http, url, referer=None):
        self.origin.wait(getattr(http, 'deadline', None))
        self_ref = self.ROOT + f'/{self.LANGUAGE}/'
        raw, final, _ = http.document(url, headers={'Referer': self_ref, 'x-localization': self.LANGUAGE}, action='ysk-json')
        try:
            if final != url:
                raise ValueError('Mismatched endpoint')
            value = json.loads(raw)
            return value['data']
        except (KeyError, TypeError, ValueError, RecursionError):
            raise SourceError('YSK Comics изменил формат ответа.') from None

    def row_for(self, data):
        key = data.get('slug') if isinstance(data, dict) else ''
        title = data.get('full_name') if key else ''
        if not isinstance(key, str) or not re.fullmatch(SEGMENT, key) or not isinstance(title, str) or not title:
            return None
        if data.get('language_code', self.LANGUAGE) != self.LANGUAGE:
            return None
        target = f'{self.ROOT}/{self.LANGUAGE}/comic/{key}'
        writer = data.get('writer')
        authors = named([writer]) if writer else []
        markup = data.get('description') or data.get('descrition') or ''
        desc = BeautifulSoup(markup, 'html.parser').get_text(' ', strip=True) if isinstance(markup, str) else ''
        return self.record(target, title, image_url(data.get('image'), target), description=desc, authors=authors,
                           genres=named(data.get('genres')), status=data.get('status') or '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        more = False
        if query:
            if len(query) < 3 or page != 1:
                return [], False
            rows = self.json(http, query_url('https://' + YSK_SEARCH + '/api/v1/search-comics-home', name=query))
        elif sort == 'updated':
            reply = self.json(http, query_url(self.ROOT + '/api/home/latest-comics', page=page))
            rows = items(reply, 'data_messages')
            more = bool((reply.get('meta') or {}).get('link_next'))
        elif page == 1:
            rows = self.json(http, self.ROOT + '/api/home/best-comics')
        else:
            return [], False
        if not isinstance(rows, list):
            raise SourceError('YSK Comics изменил формат каталога.')
        return [row for entry in rows if (row := self.row_for(entry))], more

    def series(self, http, url):
        key = self.title_key(url)
        data = self.json(http, self.ROOT + '/api/comic/' + key)
        row = self.row_for(data)
        if not row or self.title_key(row['url']) != key:
            raise SourceAccessError('YSK Comics не предоставил тайтл на выбранном языке.')
        entries = {}
        for page in range(1, 121):
            reply = self.json(http, query_url(self.ROOT + '/api/comic/chapter/' + key, page=page))
            for item in items(reply, 'data_messages'):
                slug = item.get('slug') if isinstance(item, dict) else None
                if isinstance(slug, str) and re.fullmatch(SEGMENT, slug):
                    target = query_url(f'{self.ROOT}/{self.LANGUAGE}/chapter/{slug}', mv_title=key)
                    rank = str(item.get('rank') or '')
                    entries[target] = self.chapter(target, '#' + rank if rank else '', number(rank))
            if not (reply.get('meta') or {}).get('link_next'):
                return row, self.order(entries)
        raise SourceError('YSK Comics не предоставил полный список глав.')

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            pages = self.pages(http, url)
            if not pages:
                raise SourceError('YSK Comics не предоставил изображения главы.')
            row = self.record(url, 'Глава ' + self.chapter_key(url))
            return self.reader_result(row, url, [self.chapter(url, n=0)], pages)
        return super().inspect(url, http)

    def pages(self, http, url):
        data = self.json(http, self.ROOT + '/api/chapters/images/' + self.chapter_key(url))
        if not isinstance(data, list):
            raise SourceError('YSK Comics не предоставил изображения главы.')
        return [image_url(item, url) for item in data]


class Atsumaru(JsonSeries):
    def __init__(self):
        super().__init__(('2327480808438768017', 'Atsumaru', 'en', 'https://' + ATSU, True),
                         rf'/manga/({ATSU_ID})/?', rf'/read/({ATSU_ID})/({ATSU_ID})/?', interval=.4)

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/manga/' + key if re.fullmatch(ATSU_ID, key) else ''

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if self.is_chapter(value):
            return value
        target = self.ROOT + '/read/' + urlsplit(value).path.strip('/')
        return target if self.is_chapter(target) and self.chapter_key(target) == self.title_key(title) else ''

    def cover(self, value, page=False):
        if not isinstance(value, str) or not value:
            return ''
        if not value.startswith(('http://', 'https://', '//')):
            value = self.ROOT + '/static/' + value.lstrip('/').removeprefix('static/')
        if page:
            value = re.sub(r'^https?://(?:cdn\.)?', 'https://cdn.', 'https:' + value if value.startswith('//') else value)
        return image_url(value, self.ROOT)

    def entry(self, data):
        key = str(data.get('id') or '') if isinstance(data, dict) else ''
        title = data.get('title') if key else ''
        if not re.fullmatch(ATSU_ID, key) or not isinstance(title, str) or not title:
            return None
        poster = data.get('poster') or data.get('image')
        if isinstance(poster, dict):
            poster = poster.get('largeImage') or poster.get('image')
        row = self.record(self.ROOT + '/manga/' + key, title, self.cover(data.get('largeImage') or poster),
                          aliases=strings(data.get('otherNames')), description=data.get('synopsis') or '',
                          genres=named(data.get('genres')), tags=named(data.get('tags')), authors=named(data.get('authors')),
                          status=data.get('status') or '')
        row['format'] = {'Manwha': 'manhwa', 'Manhwa': 'manhwa', 'Manhua': 'manhua', 'OEL': 'comic'}.get(data.get('type'), 'manga')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or tag:
            clause = ATSU_PUBLIC
            if match := re.fullmatch(ATSU_FILTER, tag):
                clause += f' && {match["kind"]}Ids:=`{match["key"]}`'
            endpoint = query_url(self.ROOT + '/collections/manga/documents/search', q=query or '*', filter_by=clause,
                                 query_by='title,englishTitle,otherNames,authors', query_by_weights='4,3,2,1',
                                 num_typos='4,3,2,1', page=page, per_page=40)
            data = self.json(http, endpoint)
            records = [item.get('document') for item in items(data, 'hits') if isinstance(item, dict)]
            more = (number(data.get('found')) or 0) > page * 40
        else:
            path = 'recentlyUpdated' if sort == 'updated' else 'popular'
            params = {'offset': (page - 1) * 40, 'limit': 40, 'types': TYPESET, 'mediums': 'Comic'}
            if path == 'popular':
                params['timeframe'] = 'daily'
            data = self.json(http, query_url(self.ROOT + '/api/home2/' + path, **params))
            records = items(data, 'items')
            more = len(records) >= 40
        return [row for item in records if (row := self.entry(item))], more

    def vocabulary(self, http):
        data = self.json(http, self.ROOT + '/api/explore/availableFilters')
        return [{'label': row['name'], 'sourceId': f'{kind}:{key}', 'category': kind}
                for kind in ('genre', 'tag') for row in items(data, kind + 's') if isinstance(row, dict)
                and re.fullmatch(ATSU_ID, key := str(row.get('id') or '')) and isinstance(row.get('name'), str)]

    def series(self, http, url):
        key = self.title_key(url)
        data = self.json(http, query_url(self.ROOT + '/api/manga/page', id=key), url).get('mangaPage')
        record = self.entry(data)
        if not record or self.title_key(record['url']) != key:
            raise SourceError('Atsumaru не подтвердил карточку произведения.')
        translators = {entry['id']: entry.get('name', '') for entry in items(data, 'scanlators') if
                       isinstance(entry, dict) and isinstance(entry.get('id'), str)}
        reply = self.json(http, query_url(self.ROOT + '/api/manga/allChapters', mangaId=key), url)
        chapters = {}
        for item in items(reply, 'chapters'):
            cid = str(item.get('id') or '') if isinstance(item, dict) else ''
            if not re.fullmatch(ATSU_ID, cid):
                continue
            target = f'{self.ROOT}/read/{key}/{cid}'
            date = item.get('createdAt')
            if type(date) is int and 0 < date <= 4_102_444_800_000:
                date = datetime.fromtimestamp(date / 1000, tz=timezone.utc).date().isoformat()
            date = date[:10] if isinstance(date, str) else ''
            chapters[target] = self.chapter(target, item.get('title') or '', number(item.get('number')), date,
                                            translator=translators.get(item.get('scanlationMangaId'), ''))
        return record, self.order(chapters)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        target = query_url(self.ROOT + '/api/read/chapter', mangaId=match[1], chapterId=match[2])
        data = self.json(http, target, url).get('readChapter') or {}
        return [self.cover(page.get('image'), page=True) for page in items(data, 'pages') if isinstance(page, dict)]


class MangaPlusCreators(JsonSeries):
    meta = Meta('.book-box div.title', '.book-box div.cover img', '.book-box div.summary',
                genres='.book-box div.genre-area div.tag-genre', author='.book-box div.mod-btn-profile div.name',
                status='.book-box div.book-submit-type')

    def __init__(self, sid, language):
        super().__init__((sid, 'MANGA Plus Creators by SHUEISHA', language, 'https://' + MPC, False),
                         rf'/titles/{SLUG}/?', rf'/episodes/{SLUG}/?', interval=.35)

    def title_for(self, url):
        key = param(url, 'mv_title')
        return self.ROOT + '/titles/' + key if re.fullmatch(SEGMENT, key) else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        path = urlsplit(value).path if isinstance(value, str) and value else ''
        match = re.fullmatch(rf'/(?:mpc/)?titles/{SLUG}/?', path)
        if match and urlsplit(value).hostname == 'medibang.com':
            return self.ROOT + '/titles/' + match[1]
        return ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if not self.is_chapter(url):
            return ''
        return query_url(url.split('?')[0], mv_title=self.title_key(title))

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'mv_title') == self.title_key(title)

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': key, 'category': 'genre'} for key, label in CREATOR_GENRES.items()]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        language = self.LANGUAGE
        rows = {}
        if sort == 'updated' and not query and not tag:
            endpoint = query_url(self.ROOT + '/api/titles/recent/', page=page, l=language, t='episode')
            data = self.json(http, endpoint)
            for row in items(data, 'titles'):
                key = (row.get('latest_episode') or {}).get('title_connect_id') if isinstance(row, dict) else ''
                title = row.get('title') if key else None
                if not isinstance(key, str) or not re.fullmatch(SEGMENT, key) or not isinstance(title, str) or not title:
                    continue
                target = self.ROOT + '/titles/' + key
                author = (row.get('author') or {}).get('name') or ''
                rows[target] = self.record(target, title, image_url(row.get('thumbnail'), target), authors=[author])
            return list(rows.values()), bool(rows) and data.get('status') != 'error'
        if page != 1:
            return [], False
        selector = 'div.item-recent'
        if query:
            target = query_url(self.ROOT + '/keywords', q=query, s='date', lang=language)
            selector = 'div.item-search'
        elif tag in CREATOR_GENRES:
            target = query_url(self.ROOT + '/genres/' + tag, l=language)
        else:
            target = query_url(self.ROOT + '/titles/popular/', p='m', l=language)
        doc, final = self.document(http, target)
        for card in doc.select(selector):
            title = node_text(card.select_one('.title-area .title'))
            cover = picture(card.select_one('.image-area img'), final)
            link = card.select_one('a[href^="/titles/"]')
            url = self.site_link(link['href'], final) if link else ''
            if not url and cover:
                parts = urlsplit(cover).path.strip('/').split('/')
                if len(parts) >= 3 and re.fullmatch(SEGMENT, parts[2]):
                    url = self.ROOT + '/titles/' + parts[2]
            if title and self.is_title(url):
                rows[url] = self.record(url, title, cover)
        return list(rows.values()), False

    def series(self, http, url):
        key = self.title_key(url)
        archive = self.ROOT + '/titles/' + key + '/'
        doc, final = self.title_document(http, query_url(archive, page=1))
        row = self.metadata(doc, final.split('?')[0], self.meta)
        if row['status'] == 'One-shot':
            row.update(status='completed', format='oneshot')
        elif row['status'] == 'Series':
            row['status'] = 'ongoing'
        chapters = {}
        for page in range(1, 121):
            if page != 1:
                doc, final = self.title_document(http, query_url(archive, page=page))
            for node in doc.select('a.mod-item-series[href]'):
                target = self.site_link(node['href'], final)
                if not self.is_chapter(target):
                    continue
                label = node_text(node.select_one('.number'))
                date = release_date(node_text(node.select_one('.first-update')), '%Y-%m-%d')
                target = query_url(target, mv_title=key)
                chapters[target] = self.chapter(target, label, 0 if label == 'One-shot' else number(label.lstrip('#')), date)
            if not doc.select_one('.mod-pagination .next') or len(chapters) >= MAX_CHAPTERS:
                return row, self.order(chapters)[:MAX_CHAPTERS]
        raise SourceError('MANGA Plus Creators не предоставил полное оглавление.')

    def manifest(self, http, url):
        wire = url.split('?')[0]
        doc, final = self.document(http, wire)
        if self.chapter_key(final) != self.chapter_key(wire):
            raise SourceError('MANGA Plus Creators перенаправил на другой выпуск.')
        node = doc.select_one('div[react="viewer"][data-pages]')
        if not node:
            raise SourceAccessError('MANGA Plus Creators не предоставил открытую версию выпуска.')
        try:
            data = json.loads(node['data-pages'])
            title = json.loads(node.get('data-title') or '{}')
            pages = []
            for row in items(data, 'pc'):
                index = row['page_no']
                page = image_url(row['image_url'], final)
                if type(index) is not int or not page:
                    raise ValueError('Invalid page')
                pages.append((index, page))
            return title, [page for _, page in sorted(pages)]
        except (KeyError, TypeError, ValueError, RecursionError):
            raise SourceError('MANGA Plus Creators изменил список страниц.') from None

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            title, pages = self.manifest(http, url)
            key, label = title.get('contents_id'), title.get('title')
            if not isinstance(key, str) or not re.fullmatch(SEGMENT, key) or not isinstance(label, str) or not pages:
                raise SourceError('MANGA Plus Creators не подтвердил выбранный выпуск.')
            row = self.record(self.ROOT + '/titles/' + key, label, image_url(title.get('thumbnail'), url))
            target = query_url(url, mv_title=key)
            return self.reader_result(row, target, [self.chapter(target, n=1)], pages)
        return super().inspect(url, http)

    def pages(self, http, url):
        title, pages = self.manifest(http, url)
        if title.get('contents_id') != param(url, 'mv_title'):
            raise SourceError('MANGA Plus Creators подменил тайтл выпуска.')
        return pages


class Bbato(JsonSeries):
    cards = Cards('.original.card-lg .unit:has(a.poster)', 'a.poster', '.info > a', 'a.poster img',
                  next='.pagination a[rel=next]', image_attrs=('data-src',))
    meta = Meta('h1[itemprop=name]', '.poster img', '.description',
                genres='.meta div:has(span:-soup-contains("Genres")) a',
                author='.meta div:has(span:-soup-contains("Author")) a', status='.info > p')

    def __init__(self):
        super().__init__(('1678128543826757763', 'Bbato', 'en', 'https://' + BBATO, True),
                         MANGA, rf'/read/{SLUG}/{SEGMENT}/?', legacy_hosts=('bbato.com', 'www.bbato.com'), interval=.35)

    def title_for(self, url):
        slug = self.chapter_key(url)
        return self.ROOT + '/manga/' + slug if slug else ''

    def saved_chapter(self, row, root, title):
        link = super().saved_chapter(row, root, title)
        if self.is_chapter(link):
            return link
        slug = urlsplit(link).path.strip('/')
        return self.ROOT + '/read/' + self.title_key(title) + '/' + slug if (
            self.is_title(title) and re.fullmatch(SEGMENT, slug)) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if not query and not tag and sort == 'updated':
            path = '/updated' + (f'/page/{page}' if page > 1 else '')
            url = self.ROOT + path
        else:
            args = {'keyword': query} if query else {'sort': 'views'}
            if page > 1:
                args['page'] = page
            if re.fullmatch(SEGMENT, tag):
                args['genre[]'] = tag
            url = query_url(self.ROOT + '/filter', **args)
        return self.card_rows(*self.document(http, url), self.cards)

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        cover = picture(doc.select_one('.poster img'), final, ('data-src',))
        if cover:
            row['cover'] = cover
        key = self.title_key(final)
        data = self.json(http, query_url(self.ROOT + '/get-chapter-list', slug=key), url)
        chapters = {}
        for entry in items(data, 'data'):
            slug = entry.get('chapter_slug') if isinstance(entry, dict) else None
            if isinstance(slug, str) and re.fullmatch(SEGMENT, slug):
                target = f'{self.ROOT}/read/{key}/{slug}'
                date = entry.get('updated_at') or ''
                chapters[target] = self.chapter(target, entry.get('chapter_name') or '', date=date[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return [picture(node, final, ('data-src',)) for node in doc.select('.pages .page:not(.notice-page) img')]


class Manhwa18Net(JsonSeries):
    def __init__(self):
        super().__init__(('687150405919946955', 'Manhwa18.Net', 'en', 'https://manhwa18.net', True),
                         MANGA, CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/manga/' + key if key else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        key = urlsplit(target).path.strip('/')
        return title.rstrip('/') + '/' + key if self.is_title(title) and re.fullmatch(SEGMENT, key) else ''

    @staticmethod
    def props(doc):
        node = doc.select_one('#app[data-page], div[data-page]')
        if node:
            try:
                data = json.loads(node['data-page'])['props']
                if isinstance(data, dict):
                    return data
            except (KeyError, TypeError, ValueError, RecursionError):
                pass
        raise SourceError('Manhwa18.Net изменил данные страницы.')

    def entry(self, data):
        slug = data.get('slug') if isinstance(data, dict) else None
        name = data.get('name') if isinstance(slug, str) and re.fullmatch(SEGMENT, slug) else None
        if not isinstance(name, str) or not name:
            return None
        target = self.ROOT + '/manga/' + slug
        markup = data.get('pilot') or data.get('description') or ''
        description = BeautifulSoup(markup, 'html.parser').get_text(' ', strip=True) if isinstance(markup, str) else ''
        row = self.record(target, name, image_url(data.get('cover_url') or data.get('thumb_url'), target),
                          description=description, genres=named(data.get('genres')), authors=named(data.get('artists')),
                          status={0: 'ongoing', 1: 'completed', 2: 'completed'}.get(data.get('status_id'), ''))
        row['format'] = 'manhwa'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            target = query_url(self.ROOT + '/tim-kiem', q=query, page=page)
        else:
            target = query_url(self.ROOT + '/manga-list', sort='update' if sort == 'updated' else 'top', page=page)
        props = self.props(self.document(http, target)[0])
        listing = next((props[key] for key in ('paginate', 'popularManga', 'mangas', 'latestManhwaMain')
                        if isinstance(props.get(key), dict)), None)
        if listing is None:
            raise SourceError('Manhwa18.Net не предоставил каталог.')
        return [row for item in items(listing, 'data') if (row := self.entry(item))], bool(listing.get('next_page_url'))

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        data = self.props(doc)
        row = self.entry(data.get('manga'))
        if not row or self.title_key(row['url']) != self.title_key(final):
            raise SourceError('Manhwa18.Net не подтвердил карточку тайтла.')
        chapters = {}
        for item in items(data, 'chapters'):
            slug = item.get('slug') if isinstance(item, dict) else None
            if isinstance(slug, str) and re.fullmatch(SEGMENT, slug):
                target = final.rstrip('/') + '/' + slug
                date = item.get('created_at') or ''
                chapters[target] = self.chapter(target, item.get('name') or '', date=date[:10])
        return row, self.order(chapters)

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        markup = self.props(doc).get('chapterContent')
        if not isinstance(markup, str) or not markup:
            raise SourceAccessError('Manhwa18.Net не предоставил страницы главы.')
        return [picture(node, final, ('data-src', 'data-lazy-src')) for node in
                BeautifulSoup(markup, 'html.parser').select('img')]


SOURCES = (
    YSKComics(('9170389107417152397', 'YSK Comics', 'ar', 'https://' + YSK, False)),
    YSKComics(('177448809266948921', 'YSK Comics', 'en', 'https://' + YSK, False)),
    Atsumaru(),
    MangaPlusCreators('4994699950662723787', 'en'),
    MangaPlusCreators('1894436225000314286', 'es'),
    Bbato(),
    Manhwa18Net(),
)
