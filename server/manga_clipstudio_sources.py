"""Public FireCross and Comic Festa publisher catalogues."""

from datetime import datetime, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_clipstudio import endpoint, viewer_pages
from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort, number
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

FIRECROSS = 'https://firecross.jp'
COMICFESTA = 'https://comic.iowl.jp'
ID = r'[1-9]\d{0,12}'
FIRE_TITLE = rf'/ebook/series/({SEGMENT})/?'
FIRE_CHAPTER = rf'/ebook/series/({SEGMENT})/episode/({ID})/?'
COMIC_TITLE = rf'/titles/({ID})/?'
READ_MODES = ('free_download', 'trial_download', 'sample_download', 'sample_page_download', 'download')
COMIC_CHAPTER = rf'/volumes/({ID})/({"|".join(READ_MODES)})/?'
FORM_TOKEN = re.compile(r'[a-zA-Z0-9/+_=-]{16,160}')
LABELS = {'1': 'HJ文庫', '2': 'HJノベルス', '3': 'コミックファイア', '4': 'HJコミックス'}


def firecross_route(url, method, data, action, referer):
    parts = urlsplit(url)
    if parts.netloc != 'firecross.jp':
        return False
    if action == 'firecross-guest-title':
        values = parse_qsl(parts.query)
        return (method == 'GET' and data is None and bool(re.fullmatch(FIRE_TITLE, parts.path))
                and all(key == 'sort' and value == 'latest' or key == 'page' and bool(re.fullmatch(r'[1-9]\d{0,2}', value))
                        for key, value in values) and len({key for key, _ in values}) == len(values))
    return (method == 'POST' and parts.path == '/api/reader' and not parts.query
            and firecross_route(referer, 'GET', None, 'firecross-guest-title', '')
            and isinstance(data, dict) and set(data) == {'_token', 'ebook_id'}
            and isinstance(data['_token'], str) and FORM_TOKEN.fullmatch(data['_token'])
            and isinstance(data['ebook_id'], str) and re.fullmatch(ID, data['ebook_id']))


def public_api(host, path, query):
    return host == 'firecross.jp' and path == '/api/reader' and not query


def comicfesta_rsc(host, path, query):
    return host == 'comic.iowl.jp' and path == '/sales_rankings/monthly_general' and query in ('page=1', 'page=2')


def comicfesta_document(url):
    parts = urlsplit(url)
    return (parts.netloc == 'comic.iowl.jp' and
            (parts.path in ('/titles', '/titles/') or bool(re.fullmatch(COMIC_TITLE, parts.path))
             or not parts.query and bool(re.fullmatch(COMIC_CHAPTER, parts.path))))


def flight_item(raw, fields, condition=None):
    # Whole Flight rows also carry references for UI hydration. Resolve the fields used by the
    # adapter to avoid walking references that point back to their component model.
    models = flight_models(flight_stream(raw))
    for model in models.values():
        for item in dictionaries(model):
            if not set(fields) <= item.keys() or condition and not condition(item):
                continue
            try:
                return resolve_fields({key: item[key] for key in fields}, models, [60000])
            except SourceError:
                continue
    return {}


def doc_title_raw(http, url, referer, action):
    raw, final, _ = http.document(url, headers={'Referer': referer}, action=action)
    return raw, BeautifulSoup(raw, 'html.parser'), final


class FireCross(JsonSeries):
    cards = Cards('ul.seriesList li.seriesList_item', 'a.seriesList_itemTitle', cover='img.series-list-img',
                  next='a.pagination-btn--next')
    results = Cards('ul.seriesList#search-result li.seriesList_item', 'a.btn-search-result[href*="/ebook/series/"]',
                    'a.seriesList_itemTitle', 'img.series-list-img', next='a.pagination-btn--next')
    meta = Meta('h1.ebook-series-title', 'img.ebook-series-img', 'p.ebook-series-synopsis',
                genres='div.book-genre a', author='ul.ebook-series-author li')

    def __init__(self):
        super().__init__(('6276622162610581454', 'FireCross', 'ja', FIRECROSS, False),
                         FIRE_TITLE, FIRE_CHAPTER, interval=.45)

    def title_for(self, url):
        key = self.chapter_key(url)
        return FIRECROSS + '/ebook/series/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        if self.is_title(url):
            return url
        return FIRECROSS + '/ebook/series/' + key if re.fullmatch(SEGMENT, key) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        key = urlsplit(url).path.strip('/')
        return title.rstrip('/') + '/episode/' + key if self.is_title(title) and re.fullmatch(ID, key) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        search = bool(query or tag in LABELS)
        if search:
            args = {'q': query, 't': '1', 'distribution_episode': '1', 'page': page}
            if tag in LABELS:
                args['label[]'] = tag
            url = query_url(FIRECROSS + '/search', **args)
        else:
            url = query_url(FIRECROSS + '/ebook/comics', page=page, sort=1)
        return self.card_rows(*self.document(http, url), self.results if search else self.cards)

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'category'} for key, label in LABELS.items()]

    def series_page(self, http, title, page):
        self.origin.wait(getattr(http, 'deadline', None))
        target = query_url(title, sort='latest', page=page if page > 1 else [])
        _, doc, final = doc_title_raw(http, target, FIRECROSS + '/', 'firecross-guest-title')
        if not self.is_title(final) or self.title_key(title) != self.title_key(final):
            raise SourceError('FireCross перенаправил на другой тайтл.')
        return doc, final

    def episodes(self, http, title):
        doc, final = self.series_page(http, title, 1)
        total = max((int(value) for a in doc.select('.ebookSeries_paginationLinks a[href]')
                     if re.fullmatch(r'[1-9]\d{0,2}', value := param(a['href'], 'page'))), default=1)
        docs = ((doc, final) if page == 1 else self.series_page(http, title, page) for page in range(1, min(total, 80) + 1))
        return doc, docs

    def series(self, http, url):
        base = FIRECROSS + '/ebook/series/' + self.title_key(url)
        summary, documents = self.episodes(http, base)
        row = self.metadata(summary, base, self.meta)
        result = {}
        for doc, _ in documents:
            for item in doc.select('div.shop-item--episode[data-id]'):
                cid = item['data-id']
                if not re.fullmatch(ID, cid):
                    continue
                name = node_text(item.select_one('span.shop-item-info-name'))
                raw = node_text(item.select_one('span.shop-item-info-release')).split('公開：')[-1].strip()
                locked = item.select_one('form[data-api="reader"] input[name="_token"]') is None
                target = base + '/episode/' + cid
                result[target] = self.chapter(target, ('🔒 ' if locked else '') + name,
                                              date=release_date(raw, '%Y/%m/%d'))
        return row, self.order(result)

    def pages(self, http, url):
        title = self.title_for(url)
        cid = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        _, documents = self.episodes(http, title)
        for doc, final in documents:
            row = doc.select_one(f'div.shop-item--episode[data-id="{cid}"]')
            if row is None:
                continue
            node = row.select_one('form[data-api="reader"] input[name="_token"][value]')
            if not node or not FORM_TOKEN.fullmatch(node['value']):
                break
            data = {'_token': node['value'], 'ebook_id': cid}
            raw, _, _ = http.document(FIRECROSS + '/api/reader', headers={'Referer': final},
                                      data=data, method='POST', action='firecross-guest-reader')
            try:
                viewer = json.loads(raw).get('redirect')
            except (ValueError, AttributeError):
                viewer = None
            if not isinstance(viewer, str) or not viewer:
                raise SourceAccessError('FireCross не передал открытую читалку.')
            address = endpoint(viewer, final)
            _, page, landed = doc_title_raw(http, address, final, None)
            return viewer_pages(http, landed, url, page)
        raise SourceAccessError('FireCross ограничивает доступ к этому выпуску.')


def active_fair(value):
    if not isinstance(value, dict) or not isinstance(end := value.get('endAt'), str) or not end:
        return False
    try:
        stamp = datetime.fromisoformat(end)
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)) > datetime.now(timezone.utc)
    except ValueError:
        return True


class ComicFesta(JsonSeries):
    cards = Cards('div.list-detail-box', '.list-left-box a[href]', 'div.title-box', 'img')
    meta = Meta("h1[class*='titleName']", "img[class*='thumbnail']", "div[class*='description']",
                genres="[class*='outlineTag'] a", author="a[href*='/authors/']")

    def __init__(self):
        super().__init__(('8029218690220992872', 'Comic Festa', 'ja', COMICFESTA, True),
                         COMIC_TITLE, COMIC_CHAPTER, interval=.45)

    def title_for(self, url):
        key = param(url, 'mv_cf_title')
        return COMICFESTA + '/titles/' + key if self.is_chapter(url) and re.fullmatch(ID, key) else ''

    def chapter_identity(self, url):
        found = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return found[1] if found else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return COMICFESTA + '/titles/' + key if re.fullmatch(ID, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if not self.is_chapter(url):
            url = self.site_link('/volumes/' + urlsplit(url).path.strip('/'))
        return query_url(url, mv_cf_title=self.title_key(title)) if self.is_chapter(url) and self.is_title(title) else ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_title(title) and self.title_for(target) == title.rstrip('/'))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        self.origin.wait(getattr(http, 'deadline', None))
        if not query and sort != 'updated':
            if page > 2:
                return [], False
            target = query_url(COMICFESTA + '/sales_rankings/monthly_general', page=page)
            raw, final, _ = http.document(target, headers={'Referer': COMICFESTA + '/'}, action='native-series-rsc')
            if final != target:
                raise SourceError('Comic Festa перенаправил рейтинг.')
            titles = flight_item(raw, ('titles',)).get('titles') or []
            rows = []
            for entry in titles:
                if isinstance(entry, dict) and re.fullmatch(ID, key := str(entry.get('id') or '')) and entry.get('name'):
                    url = COMICFESTA + '/titles/' + key
                    rows.append(self.record(url, entry['name'], image_url(entry.get('thumbnailPath'), url)))
            return rows, bool(rows and page < 2)
        target = query_url(COMICFESTA + '/titles', page=page, **(
            {'search_form[keyword]': query, 'search': query, 'commit': 'search'} if query
            else {'sort': 'release', 'search_form[other_item][]': 'new'}))
        _, doc, final = doc_title_raw(http, target, COMICFESTA + '/', 'comicfesta-document')
        if urlsplit(final).netloc != 'comic.iowl.jp':
            raise SourceError('Comic Festa перенаправил каталог.')
        return self.card_rows(doc, final, self.cards)

    def series(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, doc, final = doc_title_raw(http, url, COMICFESTA + '/', 'comicfesta-document')
        title_id = self.title_key(url)
        if urlsplit(final).netloc != 'comic.iowl.jp' or self.title_key(final) != title_id:
            raise SourceError('Comic Festa перенаправил на другой тайтл.')
        row = self.metadata(doc, final, self.meta)
        status = node_text(doc.select_one('[class*="latest-package-num-display"]'))
        row['status'] = 'completed' if '完結' in status else 'ongoing'
        obj = flight_item(raw, ('packages', 'titleId'), lambda item: str(item['titleId']) == title_id)
        samples = {}
        for anchor in doc.select('a[href*="/volumes/"]'):
            target = self.site_link(anchor['href'], final)
            found = self.CHAPTER_PATH.fullmatch(urlsplit(target).path)
            if found and found[2].startswith('sample'):
                samples[found[1]] = found[2]
        result = {}
        for entry in obj.get('packages') or []:
            if not isinstance(entry, dict) or not re.fullmatch(ID, key := str(entry.get('id') or '')):
                continue
            fair = entry.get('fairInfo') or {}
            mode = ('free_download' if entry.get('point') == 0 or active_fair(fair.get('free')) else
                    'trial_download' if active_fair(fair.get('trial')) else samples.get(key, 'download'))
            n = number(entry.get('number'))
            label = str(entry.get('name') or (f'{n:g}巻' if n is not None else ''))
            if mode == 'download':
                label = '🔒 ' + label
            if mode.startswith('sample') or mode == 'trial_download':
                label = label + ' · Фрагмент'
            target = query_url(COMICFESTA + f'/volumes/{key}/{mode}', mv_cf_title=title_id)
            result[target] = self.chapter(target, label, n)
        listed = {self.chapter_identity(target) for target in result}
        for key, mode in samples.items():
            if key not in listed:
                target = query_url(COMICFESTA + f'/volumes/{key}/{mode}', mv_cf_title=title_id)
                result[target] = self.chapter(target, 'Ознакомительный фрагмент', 0)
        return row, self.order(result)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        if match[2] == 'download':
            raise SourceAccessError('Comic Festa требует покупку выпуска.')
        target = COMICFESTA + urlsplit(url).path
        _, doc, final = doc_title_raw(http, target, self.title_for(url) or COMICFESTA + '/', 'comicfesta-document')
        if urlsplit(final).path.startswith(('/entry', '/error')):
            raise SourceAccessError('Comic Festa не предоставил открытую читалку.')
        return viewer_pages(http, final, url, doc)


SOURCES = (FireCross(), ComicFesta())
