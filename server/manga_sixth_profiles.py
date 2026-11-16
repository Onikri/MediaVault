"""Native catalogue and chapter routes based on the pinned Keiyoushi extensions."""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, SERIES, SLUG
from manga_direct_payloads import JsonSeries, items, strings
from manga_madara import SEGMENT, image_url, node_text
from manga_raw_adapters import RAW_API
from manga_series_port import Archive, Cards, MAX_CHAPTERS, MAX_PAGES, Meta, number
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ID = r'[1-9]\d{0,13}'
DECIMAL = r'\d{1,9}(?:[-.]\d{1,4})?'
DESU = 'desu.uno'
RAW = 'api.mangarw.com'
CLUB = 'webtoonclub.com'


def public_api(host, path, query):
    if host not in {DESU, RAW, CLUB}:
        return False
    fields = parse_qsl(query)
    args = dict(fields)
    if len(fields) != len(args) or any(not 1 <= len(value) <= 160 for value in args.values()):
        return False
    if host == DESU:
        if path == '/api/manga/catalog/':
            return ({'page', 'limit', 'order_by'} <= set(args) <= {'page', 'limit', 'order_by', 'search', 'genres'}
                    and bool(re.fullmatch(ID, args['page'])) and args['limit'] == '20'
                    and args['order_by'] in {'popular', 'updated'}
                    and ('genres' not in args or bool(re.fullmatch(ID, args['genres']))))
        return not query and bool(re.fullmatch(rf'/api/manga/{ID}/(?:chapters(?:/{ID})?)?', path))
    if host == RAW:
        if path == '/api/v1/browse/':
            return (set(args) == {'page', 'limit', 'sort'} and bool(re.fullmatch(ID, args['page']))
                    and args['limit'] == '24' and args['sort'] in {'views_month', 'latest'})
        if path == '/api/v1/search/':
            return set(args) == {'keyword'}
        if re.fullmatch(rf'/api/v1/manga/{ID}/chapters', path):
            return args == {'order': 'desc'}
        return not query and bool(re.fullmatch(rf'/api/v1/(?:manga|chapter)/{ID}', path))
    return not query and bool(re.fullmatch(rf'/api/comics/{ID}/chapters', path))


def _local_parent(value, root, path):
    key = param(value, 'mv_title')
    return root + path + key if re.fullmatch(ID, key) else ''


def _date(value):
    if type(value) is int and 0 < value <= 4_102_444_800:
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    return value[:10] if isinstance(value, str) and re.match(r'\d{4}-\d{2}-\d{2}', value) else ''


def _labels(rows):
    return [row['name'] for row in rows or () if isinstance(row, dict) and isinstance(row.get('name'), str)]


class KaliScans(DirectCatalogue):
    def __init__(self, identity):
        cards = Cards('div.book-item', 'h3 a[href]', cover='.thumb img', image_attrs=('data-src',),
                      next='.paginator a.active ~ a.btn')
        chapter = rf'/series/{SLUG}/{DECIMAL}/?'
        self.archive = Archive('#chapter-list li', 'a[href]', '.chapter-title')
        super().__init__(identity, Layout(
            SERIES, chapter, cards,
            Meta('.book-info .name h1', '.book-info #cover img', '.summary .content', '.book-info .name h2',
                 '.book-info .meta p:has(strong:-soup-contains("Genres")) a',
                 author='.book-info .meta p:has(strong:-soup-contains("Authors")) span',
                 status='.book-info .meta p:has(strong:-soup-contains("Status")) span'),
            self.archive, '#chapter-images img',
            Browse('/popular', (('page', '{page}'),)),
            Browse('/search', (('q', '{query}'), ('status', 'all'), ('sort', 'updated_at'), ('page', '{page}'))),
            Browse('/latest', (('page', '{page}'),)),
            Browse('/search', (('genre[]', '{tag}'), ('status', 'all'), ('sort', 'updated_at'), ('page', '{page}'))),
            title_path='/series/'))

    def chapters(self, http, doc, final):
        chapter, _ = self.list_chapters(http, doc, final, self.archive)
        rows = {}
        for entry in chapter:
            value = self.site_link(entry['url'])
            if self.saved_chapter_matches(value, final):
                entry['number'] = number(urlsplit(value).path.strip('/').split('/')[-1].replace('-', '.'))
                rows[value] = entry
        return self.order(rows), False

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.chapter_key(target) == self.title_key(title))

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return self.ROOT + '/series/' + key if re.fullmatch(SEGMENT, key) else ''

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if self.is_chapter(value):
            return value
        key = urlsplit(value).path.strip('/')
        target = self.ROOT + '/series/' + key
        return target if self.is_chapter(target) else ''

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/search')
        rows = []
        for node in doc.select('#search-form-large label:has(input[name="genre[]"])'):
            value = node.select_one('input')['value']
            label = node_text(node.select_one('.radio__label'))
            if value and label:
                rows.append({'label': label, 'sourceId': value, 'category': 'genre'})
        return rows


class Mangahub(DirectCatalogue):
    def __init__(self, identity):
        cards = Cards('div.item-grid', 'a.fw-medium', cover='img.item-grid-image',
                      next='.pagination .page-item:last-child a')
        self.archive = Archive('.detail-items .detail-item', 'div.align-items-center > a',
                               date='div.text-muted', date_pattern='%d.%m.%Y')
        super().__init__(identity, Layout(
            rf'/title/{SLUG}/?', rf'/title/{SLUG}/(?:[^/?#]+/)*{SEGMENT}/?', cards,
            Meta('.detail-panel h1', 'img.cover-detail', '.markdown-style.text-expandable-content',
                 genres='.tags a[href*="genres-"]', tags='.tags a:not([href*="genres-"])',
                 author='.attr-name:-soup-contains("Автор", "Сценарист") + .attr-value a',
                 status='.attr-name:-soup-contains("Томов") + .attr-value'),
            self.archive, 'img.reader-viewer-img',
            Browse('/explore/sort-is-rating', (('page', '{page}'),)),
            Browse('/search/title', (('query', '{query}'), ('page', '{page}'))),
            Browse('/explore/sort-is-update', (('page', '{page}'),)),
            Browse('/explore/{tag}/sort-is-rating', (('page', '{page}'),)),
            title_path='/title/'))

    def is_chapter(self, url):
        return super().is_chapter(url) and not urlsplit(url).path.rstrip('/').endswith('/chapters')

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        for keys in ('genres', 'tags'):
            row[keys] = [label.removeprefix('#').strip() for label in row[keys]]
        return row

    def chapters(self, http, doc, final):
        translator = ', '.join(node_text(node) for node in doc.select('.attr-name:-soup-contains("Переводчик") + .attr-value a'))
        archive, url = self.document(http, final.rstrip('/') + '/chapters')
        rows, more = self.list_chapters(http, archive, url, self.archive)
        for row in rows:
            row['translator'] = translator
        return rows, more


class MangaRaw(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/manga/({ID})/?', rf'/chapter/({ID})/?', legacy_hosts=('mangarw.com',), interval=.5)

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/manga/' + key if re.fullmatch(ID, key) else ''

    def title_for(self, value):
        return _local_parent(value, self.ROOT, '/manga/')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        key = self.chapter_key(target) or urlsplit(target).path.strip('/')
        if re.fullmatch(ID, key) and self.title_key(title):
            return query_url(self.ROOT + '/chapter/' + key, mv_title=self.title_key(title))
        return ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title)

    def entry(self, row):
        identity = str(row.get('id') or '') if isinstance(row, dict) else ''
        title = row.get('title') if identity else ''
        if not re.fullmatch(ID, identity) or not isinstance(title, str) or not title:
            return None
        target = self.ROOT + '/manga/' + identity
        return self.record(target, title, image_url(row.get('image'), target), aliases=re.split(r'[|;]', row.get('alternative') or ''),
                           description=row.get('description') or '', genres=_labels(row.get('genres')),
                           tags=_labels(row.get('tags')), status=row.get('status') or '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query and page != 1:
            return [], False
        endpoint = query_url(RAW_API + '/search/', keyword=query) if query else query_url(
            RAW_API + '/browse/', page=page, limit=24, sort='latest' if sort == 'updated' else 'views_month')
        data = self.json(http, endpoint)
        return [entry for row in items(data, 'data') if (entry := self.entry(row))], bool(
            (data.get('pagination') or {}).get('hasMore'))

    def series(self, http, url):
        identity = self.title_key(url)
        endpoint = RAW_API + '/manga/' + identity
        entry = self.entry(self.json(http, endpoint, url).get('data'))
        if not entry or self.title_key(self.site_link(entry['url'])) != identity:
            raise SourceError('MangaRaw не подтвердил карточку тайтла.')
        chapters = self.json(http, query_url(endpoint + '/chapters', order='desc'), url)
        rows = {}
        for row in items(chapters, 'data'):
            key = str(row.get('id') or '') if isinstance(row, dict) else ''
            if re.fullmatch(ID, key):
                target = query_url(self.ROOT + '/chapter/' + key, mv_title=identity)
                rows[target] = self.chapter(target, row.get('title') or '', number(row.get('index')), _date(row.get('createdAt')))
        return entry, self.order(rows)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            pages = self.pages(http, url)
            if not pages:
                raise SourceError('MangaRaw не предоставил страницы главы.')
            row = self.record(url, 'Глава ' + self.chapter_key(url))
            return self.reader_result(row, url, [self.chapter(url, n=0)], pages)
        return super().inspect(url, http)

    def pages(self, http, url):
        data = self.json(http, RAW_API + '/chapter/' + self.chapter_key(url), url).get('data') or {}
        base = data.get('storageUrl') or ''
        results = []
        for block in data.get('content') or ():
            kind, rows = block.get('type'), block.get('data')
            if kind == 'selfhosted' and isinstance(rows, dict):
                first, last, template = rows.get('from'), rows.get('to'), rows.get('url')
                if (type(first) is not int or type(last) is not int or not 0 <= first <= last <= 100000
                        or last - first >= MAX_PAGES or not isinstance(template, str) or '{page}' not in template):
                    raise SourceError('MangaRaw изменил шаблон изображений.')
                results.extend(image_url(base + template.replace('{page}', str(i)), url) for i in range(first, last + 1))
            elif kind in {'hotlink', 'external'} and isinstance(rows, list):
                prefix = base if kind == 'external' else ''
                results.extend(image_url(prefix + value, url) for value in rows if isinstance(value, str))
            else:
                raise SourceError('MangaRaw изменил список страниц.')
            if len(results) > MAX_PAGES:
                raise SourceError('MangaRaw вернул слишком много страниц.')
        return results


class Desu(JsonSeries):
    API = 'https://' + DESU + '/api/manga/'

    def __init__(self, identity):
        super().__init__(identity, rf'/manga/({ID})/?', rf'/manga/({ID})/(?:chapters?/)?({ID})/?', interval=2)

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/manga/' + key if re.fullmatch(ID, key) else ''

    def title_for(self, url):
        return self.ROOT + '/manga/' + self.chapter_key(url)

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.group(1, 2) if match else ('', '')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        key = urlsplit(target).path.strip('/')
        if re.fullmatch(ID, key) and self.title_key(title):
            return title.rstrip('/') + '/chapter/' + key
        return ''

    def entry(self, data):
        key = str(data.get('id') or '') if isinstance(data, dict) else ''
        title = (data.get('russian') or data.get('name')) if key else ''
        if not re.fullmatch(ID, key) or not isinstance(title, str) or not title:
            return None
        url = self.ROOT + '/manga/' + key
        row = self.record(url, title, image_url((data.get('cover') or {}).get('preview'), url),
                          aliases=[data.get('name') or '', *strings(data.get('synonyms'))],
                          description=data.get('description') or '', genres=_labels(data.get('genres')),
                          authors=_labels(data.get('authors')), status=data.get('trans_status') or data.get('status') or '')
        row['format'] = {'manga': 'manga', 'manhwa': 'manhwa', 'manhua': 'manhua', 'comics': 'comic',
                         'one_shot': 'oneshot'}.get(data.get('kind'), 'manga')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'page': page, 'limit': 20, 'order_by': 'updated' if sort == 'updated' else 'popular'}
        if query:
            args['search'] = query
        if re.fullmatch(ID, tag):
            args['genres'] = tag
        data = self.json(http, query_url(self.API + 'catalog/', **args))
        paging = data.get('pagination') or {}
        return [entry for row in items(data, 'mangas') if (entry := self.entry(row))], (number(paging.get('last_page')) or 0) > page

    def series(self, http, url):
        key = self.title_key(url)
        row = self.entry(self.json(http, self.API + key + '/', url).get('manga'))
        if not row or self.title_key(self.site_link(row['url'])) != key:
            raise SourceError('Desu не подтвердил карточку тайтла.')
        data = self.json(http, self.API + key + '/chapters', url)
        rows = {}
        for chapter in items(data, 'chapters'):
            cid = str(chapter.get('id') or '') if isinstance(chapter, dict) else ''
            if not re.fullmatch(ID, cid) or chapter.get('is_readable') is False:
                continue
            target = url.rstrip('/') + '/chapter/' + cid
            label = chapter.get('title') or f'Глава {chapter.get("number", cid)}'
            volume = number(chapter.get('volume'))
            rows[target] = self.chapter(target, label, number(chapter.get('number')), _date(chapter.get('publish_date')),
                                        int(volume) if volume and 1 <= volume <= 10000 else 1)
        return row, self.order(rows)

    def pages(self, http, url):
        key, cid = self.chapter_identity(url)
        data = self.json(http, f'{self.API}{key}/chapters/{cid}', url)
        if not isinstance(data.get('chapter'), dict):
            raise SourceAccessError('Desu не выдал открытую версию главы.')
        return [image_url(row.get('url'), url) for row in items(data['chapter'], 'pages') if isinstance(row, dict)]


class WebtoonClub(JsonSeries):
    cards = Cards('a[href^="/webtoon/"]:has(img[data-cover])', '', 'h3', 'img[data-cover]',
                  next='a[aria-label="Go to next page"]')

    def __init__(self, identity):
        super().__init__(identity, rf'/webtoon/{SLUG}/?', rf'/webtoon/{SLUG}/chapter/{DECIMAL}/?', interval=.35)

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/webtoon/' + key if re.fullmatch(SEGMENT, key) else ''

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if self.is_chapter(value):
            return value
        target = self.ROOT + '/webtoon/' + urlsplit(value).path.strip('/')
        return target if self.is_chapter(target) else ''

    def title_for(self, url):
        return self.ROOT + '/webtoon/' + self.chapter_key(url)

    def record(self, url, title, cover='', **metadata):
        row = super().record(url, title, cover, **metadata)
        row.update(format='webtoon', readingMode='scroll')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'sort': 'latest' if sort == 'updated' else 'popular'}
        if query:
            args['search'] = query
        if re.fullmatch(SEGMENT, tag):
            args['genres'] = tag
        if page > 1:
            args['page'] = page
        return self.card_rows(*self.document(http, query_url(self.ROOT + '/webtoons', **args)), self.cards)

    def vocabulary(self, http):
        doc, final = self.document(http, self.ROOT + '/genres')
        return [{'label': node_text(node), 'sourceId': urlsplit(self.site_link(node['href'], final)).path.rsplit('/', 1)[-1],
                 'category': 'genre'} for node in doc.select('a[href^="/genre/"]:has(span[title])') if node_text(node)]

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        key = doc.select_one('[data-comic-id]')
        identity = key['data-comic-id'] if key else ''
        label = node_text(doc.select_one('h1'))
        if not label or not re.fullmatch(ID, identity):
            raise SourceError('WebtoonClub не предоставил карточку или номер тайтла.')
        book = {}
        for script in doc.select('script[type="application/ld+json"]'):
            try:
                book = next((node for node in dictionaries(json.loads(script.string or '')) if node.get('@type') == 'Book'), {})
            except (ValueError, RecursionError):
                continue
            if book:
                break
        row = self.record(final, label, image_url(book.get('image'), final), aliases=strings(book.get('alternateName')),
                          description=node_text(doc.select_one('p.whitespace-pre-line')), genres=strings(book.get('genre')),
                          authors=_labels(book.get('author')), status=node_text(doc.select_one('dt:-soup-contains-own("Status") + dd')))
        data = self.json(http, f'{self.ROOT}/api/comics/{identity}/chapters', final)
        rows = {}
        for chapter in items(data, 'chapters'):
            key = str(chapter.get('slug') or '').removeprefix('chapter-') if isinstance(chapter, dict) else ''
            if not re.fullmatch(DECIMAL, key):
                continue
            target = final.rstrip('/') + '/chapter/' + key
            label = f'Chapter {key}'
            if isinstance(chapter.get('title'), str) and chapter['title'].strip():
                label += ': ' + chapter['title']
            rows[target] = self.chapter(target, label, number(chapter.get('chapterNumber')), _date(chapter.get('date')))
        return row, self.order(rows)[:MAX_CHAPTERS]

    def pages(self, http, url):
        raw, final, _ = http.document(url, headers={'Referer': self.title_for(url)})
        if self.chapter_identity(final) != self.chapter_identity(url):
            raise SourceError('WebtoonClub подменил главу.')
        models = flight_models(flight_stream(raw))
        entries = None
        for model in models.values():
            for node in dictionaries(model):
                if {'comicId', 'images'} <= node.keys():
                    entries = resolve_fields(node['images'], models, [50000])
                    if isinstance(entries, list):
                        break
            if isinstance(entries, list):
                break
        if not isinstance(entries, list):
            raise SourceAccessError('WebtoonClub не выдал открытые страницы главы.')
        images = []
        for index, row in enumerate(entries):
            name = row.get('filename') if isinstance(row, dict) else None
            if not isinstance(name, str) or not re.fullmatch(rf'{SEGMENT}(?:/{SEGMENT}){{0,5}}', name):
                raise SourceError('WebtoonClub вернул некорректный адрес страницы.')
            order = row.get('sortOrder')
            images.append((order if type(order) is int else index, index, self.ROOT + '/uploads/' + name))
        return [value for _, _, value in sorted(images)]


SOURCES = (
    KaliScans(('1879005209022234038', 'KaliScans.org (unoriginal)', 'en', 'https://kaliscans.org', True)),
    Mangahub(('8601336865408732240', 'Mangahub', 'ru', 'https://mangahub.ru', True)),
    MangaRaw(('7355525645759373300', 'MangaRaw', 'ja', 'https://mangaraw.co.uk', True)),
    Desu(('6684416167758830305', 'Desu', 'ru', 'https://desu.uno', True)),
    WebtoonClub(('5827665338810887442', 'WebtoonClub', 'en', 'https://webtoonclub.com', True)),
)
