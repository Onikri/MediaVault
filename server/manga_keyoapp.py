"""Public Keyoapp catalogues and readers, based on Keiyoushi's Apache-2.0 multisrc."""

import json
import re
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import CHAPTER_NUMBER, SEGMENT, VOLUME_NUMBER, OriginPace, image_url, node_text, release_date
from manga_source_tags import unique
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


SLUG = re.compile(SEGMENT)
GENRE = re.compile(r"[\w '\u2019&+.,/()-]{1,100}")
CSS_IMAGE = re.compile(r'''url\(\s*['"]?([^'"\s)]+)''')
CDN = re.compile(r'realUrl\s*=\s*`[^`]+//([^/]+)')
CDN_SUBSTITUTION = re.compile(r'\$\{[^}]*\}')
GENRE_ARRAY = re.compile(r'''type\s*:\s*["']genre["']\s*,[^{}]{0,512}?\bitems\s*:\s*\[(.*?)\]''', re.S)
GENRE_ENTRY = re.compile(r'''["']?displayName["']?\s*:\s*(["'])(.*?)\1\s*,\s*["']?value["']?\s*:\s*(["'])(.*?)\3''', re.S)
READER_JSON = re.compile(r"""JSON\.parse\('((?:[^'\\]|\\.)+)'\)""")
PAID_V1 = 'img[alt*="Coin"]'
PAID_REDESIGN = PAID_V1 + ', img[src*="star-circle"]'
BASE_FIELDS = {
    'aliases': 'div.font-medium:-soup-contains-own("Alternative titles") ~ div span',
    'genres': 'div:has(>h1) a[href*="genre="]',
    'authors': 'div:has(span:-soup-contains-own("Author")) ~ div',
    'artists': 'div:has(span:-soup-contains-own("Artist")) ~ div',
    'format': 'div:has(span:-soup-contains-own("Type")) ~ div',
    'status': 'div:has(span:-soup-contains-own("Status")) ~ div',
}
REDESIGN_FIELDS = {
    'aliases': 'details[data-testid=series-other-names] li.select-all',
    'genres': 'div:has(>h1) a[href*="/genres/"]',
    'authors': 'dt:-soup-contains-own("Author") + dd',
    'artists': 'dt:-soup-contains-own("Artist") + dd',
    'format': 'a[aria-label=Type]',
    'status': 'a[aria-label=Status]',
}


def novel(card):
    return card.get('data-type', '').casefold() == 'novel' or bool(card.select_one('[data-type=novel i]')) or any(
        node_text(span).casefold() == 'novel' for span in card.select('span')
    )


class Keyoapp:
    def __init__(self, sid, name, root, adult=False, *, layout='original', fields=None,
                 interval=0, query_limit=160, latest_cards='div.grid > div.group'):
        self.SOURCE_ID, self.NAME, self.ROOT, self.IS_NSFW = sid, name, root, adult
        self.LANGUAGE = 'en'
        self.host = urlsplit(root).netloc
        self.layout = layout
        self.query_limit = query_limit
        self.latest_cards = latest_cards
        self.fields = {**(REDESIGN_FIELDS if layout == 'redesign' else BASE_FIELDS), **(fields or {})}
        self.origin = OriginPace()
        self.origin.interval = interval
        self.TITLE_PATH = re.compile(rf'/({SEGMENT})/?' if layout == 'v2' else rf'/series/({SEGMENT})/?')
        chapter_prefix = '' if layout == 'v2' else 'read/' if layout == 'redesign' else 'chapter/'
        self.CHAPTER_PATH = re.compile(rf'/{chapter_prefix}({SEGMENT})/?')

    def site_link(self, value, base=None):
        if isinstance(value, str) and value:
            try:
                url = urljoin(base or self.ROOT, value)
                parts = urlsplit(url)
                if parts.scheme == 'https' and parts.netloc == self.host:
                    return public_url(url, resolve_dns=False)
            except (SourceError, ValueError):
                pass
        return ''

    def request(self, http, path, params=None):
        url = self.ROOT + path + ('?' + urlencode(params) if params else '')
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != path.rstrip('/'):
            raise SourceError('Keyoapp перенаправил запрос на другую страницу.')
        return raw, final

    def document(self, http, path, params=None):
        raw, url = self.request(http, path, params)
        soup = BeautifulSoup(raw, 'html.parser')
        from manga_sources import guard
        guard(soup)
        return soup, url

    def json_html(self, http, params, field):
        raw, final = self.request(http, '/', params)
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('Keyoapp вернул страницу вместо данных AJAX.') from None
        if not isinstance(data, dict) or not isinstance(data.get(field), str):
            raise SourceError('Keyoapp вернул неожиданные данные AJAX.')
        return BeautifulSoup(data[field], 'html.parser'), final, data

    def row(self, label, url, cover=''):
        from manga_sources import title_aliases
        slug = self.TITLE_PATH.fullmatch(urlsplit(url).path)[1]
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
                'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
                'kind': 'manga', 'language': self.LANGUAGE, 'title': label[:500], 'aliases': title_aliases(label),
                'cover': cover, 'sourceOnly': True, 'ids': {}}

    def cover(self, node, url):
        selector = 'img[data-src], img[alt$=" cover"]' if self.layout != 'original' else 'img[data-src], img'
        picture = node.select_one(selector)
        if picture:
            return image_url(picture.get('data-src') or picture.get('src'), url)
        cover = node.select_one('[style*="background-image"]')
        match = CSS_IMAGE.search(cover.get('style', '')) if cover else None
        return image_url(match[1], url) if match else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(tag, str) or (tag and not GENRE.fullmatch(tag)):
            raise SourceError('Некорректные параметры каталога Keyoapp.')
        query = query.strip()[:self.query_limit]
        if self.layout == 'v2':
            return self.catalogue_v2(http, page, query, sort, tag)
        if self.layout == 'redesign':
            return self.catalogue_redesign(http, page, query, sort, tag)
        if page != 1:
            return [], False
        params = {'q': query} if query else {}
        if tag:
            params['genre'] = tag
        updates = sort == 'updated' and not query and not tag
        soup, url = self.document(http, '/latest/' if updates else '/series/', params)
        if updates:
            return self.rows(soup.select(self.latest_cards), url), False
        cards = soup.select('#searched_series_page > button')
        if tag:
            cards = [card for card in cards if tag.casefold() in {name.casefold() for name in self.tags(card)}]
        rows = self.rows(cards, url)
        return [row for row in rows if not query or query.casefold() in row['title'].casefold()], False

    def catalogue_v2(self, http, page, query, sort, tag):
        if sort == 'updated' and not query and not tag:
            soup, url = self.document(http, '/', {'_ajax': 'recent-chapters', 'page': page})
            entries = self.rows(soup.select('article.ru-card'), url)
            more = bool(soup.select_one('button[aria-label="Next recently updated page"]:not([disabled])'))
            return entries, more
        params = {'_ajax': 'search', 'offset': (page - 1) * 20}
        if query:
            params['q'] = query
        elif not tag:
            params['sort'] = 'popular'
        if tag:
            params['tag[]'] = tag
        soup, url, data = self.json_html(http, params, 'html')
        return self.rows(soup.select('a.group[href]'), url), data.get('has_more') is True

    def catalogue_redesign(self, http, page, query, sort, tag):
        if sort == 'updated' and not query and not tag:
            soup, url = self.document(http, '/latest', {'page': page})
            return self.rows(soup.select('div.grid > div.group'), url), bool(soup.select_one('a[href*="?page="]'))
        params = {'page': page} if page > 1 else {}
        if query:
            params['title'] = query
        elif not tag:
            params.update(sort='popular', page=page)
        if tag:
            params['genre'] = tag
        soup, url = self.document(http, '/search', params)
        cards = soup.select(r'main#main-content [wire\:key*="serie"]')
        return self.rows(cards, url), len(cards) >= 20

    @staticmethod
    def tags(card):
        try:
            data = json.loads(card.get('tags', '[]').replace('___', "'"))
        except ValueError:
            return []
        return unique(data) if isinstance(data, list) else []

    def rows(self, cards, url):
        found = {}
        for card in cards:
            if novel(card):
                continue
            anchors = [card] if card.name == 'a' else card.select('a[href]')
            for anchor in anchors:
                target = self.site_link(anchor.get('href'), url)
                path = urlsplit(target).path
                label = (anchor.get('title') or node_text(card.select_one('h2, h3, .ru-title')) or node_text(anchor)).strip()
                if target and label and self.TITLE_PATH.fullmatch(path):
                    found[path.rstrip('/')] = self.row(label, target, self.cover(card, url))
                    break
        return list(found.values())

    def vocabulary(self, http):
        options = {}
        if self.layout == 'v2':
            soup, _ = self.document(http, '/', {'browse': 1})
            for anchor in soup.select('#fsel-genres a[role=option][href]'):
                values = parse_qs(urlsplit(anchor['href']).query).get('tag[]', [])
                if len(values) == 1:
                    options[values[0]] = node_text(anchor) or values[0].capitalize()
        elif self.layout == 'redesign':
            soup, _ = self.document(http, '/search')
            for item in soup.select(r'[wire\:model\.live="genre"] option[value]'):
                options[item['value']] = node_text(item)
        else:
            soup, _ = self.document(http, '/series/')
            for script in soup.find_all('script'):
                if body := GENRE_ARRAY.search(script.string or ''):
                    options.update((match[4], match[2]) for match in GENRE_ENTRY.finditer(body[1]))
                    break
            if not options:
                labels = {}
                for card in soup.select('#searched_series_page > button'):
                    if not novel(card):
                        for label in self.tags(card):
                            labels.setdefault(label.casefold(), label)
                options = {label: label for label in labels.values()}
        return [{'sourceId': value, 'label': label, 'category': 'genre'}
                for value, label in options.items() if label and GENRE.fullmatch(value)]

    def metadata(self, soup, url):
        title = node_text(soup.select_one('h1' if self.layout == 'v2' else 'div.grid > h1, main h1'))
        if not title or self.layout == 'v2' and not soup.select_one('[data-series-uid]'):
            raise SourceError('Keyoapp не предоставил карточку произведения.')
        meta = soup.select_one('meta[property="og:image"]')
        result = self.row(title, url, image_url(meta.get('content'), url) if meta else self.cover(soup, url))
        result['description'] = node_text(soup.select_one('#series-desc, #expand_content p'))[:12000]
        result['tags'] = []
        if self.layout == 'v2':
            result['genres'] = unique(node_text(node) for node in soup.select('a[href*="?browse&tag"]'))
            for key, heading in (('authors', 'Author'), ('artists', 'Artist')):
                node = soup.select_one(f'span.text-xs:-soup-contains-own("{heading}")')
                result[key] = unique([node_text(node.parent.find_next_sibling()) if node else ''])
            result['status'] = node_text(soup.select_one('div.text-xs:-soup-contains-own("Status") + div span.text-sm'))
            if self.SOURCE_ID == '2076371496779298312':
                by = node_text(soup.select_one('p.l2-by')).removeprefix('By ').split(',', 1)
                if by[0]:
                    result['authors'] = unique(by[:1])
                    if len(by) > 1:
                        result['artists'] = unique(by[1:])
                subtitle = node_text(soup.select_one('p.l2-kicker, div.l2-meta span')).casefold()
                result['status'] = next((status for status in ('ongoing', 'completed', 'dropped', 'paused', 'hiatus')
                                         if status in subtitle), result['status'])
            return result
        for key, selector in self.fields.items():
            values = unique(node_text(node) for node in soup.select(selector))
            if key == 'aliases':
                result[key] = unique([*result[key], *(value for value in values if value != 'No alternative titles.')])
            else:
                result[key] = values if key in {'genres', 'authors', 'artists'} else next(iter(values), '').casefold()
        return result

    def details(self, http, value):
        url = self.site_link(value)
        path = urlsplit(url).path
        if not self.TITLE_PATH.fullmatch(path):
            raise SourceError('Некорректная ссылка на тайтл Keyoapp.')
        return self.metadata(*self.document(http, path))

    def chapter(self, url, label, date=''):
        number = CHAPTER_NUMBER.search(label)
        volume = VOLUME_NUMBER.search(label)
        return {'url': url, 'title': label, 'number': float(number[1].replace(',', '.')) if number else None,
                'season': int(volume[1]) if volume else 1, 'language': self.LANGUAGE,
                'translator': '', 'publishedAt': release_date(date, '%b %d, %Y')}

    def chapters(self, http, soup, url, title):
        if self.layout == 'v2':
            soup, _, _ = self.json_html(http, {'_chapters_html': 1, 'series_slug': unquote(title)}, 'rows_html')
            entries = soup.select('a.chapter-row[href]:not([data-ch-locked="1"])')
        else:
            entries = soup.select('#chapters > a, #chapters > div')
        found = {}
        for node in entries:
            if node.select_one(PAID_REDESIGN if self.layout == 'redesign' else PAID_V1):
                continue
            if any(node_text(badge).casefold() == 'upcoming' for badge in node.select('span')):
                continue
            anchor = node if node.has_attr('href') else node.select_one('a[href]')
            target = self.site_link(anchor['href'], url) if anchor else ''
            path = urlsplit(target).path
            label = node.get('data-ch-label') or node_text(node.select_one('.text-sm'))
            if not label or label.casefold() == 'upcoming' or not self.CHAPTER_PATH.fullmatch(path):
                continue
            date = node_text(node.select_one('.ch-date-row span:last-child, .text-xs'))
            found[path.rstrip('/')] = self.chapter(target, label, date)
        rows = list(found.values())
        for index, row in enumerate(rows):
            if row['number'] is None:
                row['number'] = len(rows) - index
        return sorted(rows, key=lambda row: (row['season'], row['number']))

    def pages(self, soup, url):
        if self.layout == 'v2':
            values = [node.get('src') for node in soup.select('#strip-reader img.reader-page')]
        elif self.layout == 'redesign':
            reader = soup.select_one('[x-data^=immersiveReader]')
            match = READER_JSON.search(reader['x-data']) if reader else None
            if not match:
                raise SourceAccessError('Keyoapp не предоставил страницы открытой главы.')
            try:
                data = json.loads(json.loads('"' + match[1] + '"'))
                values = [node['path'] for node in data]
            except (ValueError, TypeError, KeyError):
                raise SourceError('Keyoapp вернул неподдерживаемый список страниц.') from None
        else:
            values = self.original_pages(soup)
        pages = [image_url(value, url) for value in values]
        if not pages or len(pages) > 500 or not all(pages):
            raise SourceError('Keyoapp не предоставил полный список страниц открытой главы.')
        return pages

    def original_pages(self, soup):
        nodes = soup.select('#pages > img')
        ids = [node['uid'] for node in nodes if node.get('uid')]
        if not ids:
            return ['https:' + value.split(':', 1)[-1] if value.startswith('http:') else value for node in nodes
                    if re.match(r'^(?:https?:)?//cdn\d*\.keyoapp\.com/', value := node.get('data-lazy-src') or node.get('data-src') or node.get('src', ''))]
        if any(not all(SLUG.fullmatch(part) for part in ident.split('/')) for ident in ids):
            raise SourceError('Keyoapp вернул некорректный путь страницы.')
        for script in soup.find_all('script'):
            if match := CDN.search(script.string or ''):
                host = CDN_SUBSTITUTION.sub('', match[1])
                if re.fullmatch(r'[a-zA-Z0-9.-]+', host):
                    return ['https://' + host + '/uploads/' + ident for ident in ids]
        return []

    def series_link(self, soup, url):
        if self.layout == 'v2':
            sidebar = soup.select_one('#sidebar-ch-list[data-series-slug]')
            slug = sidebar['data-series-slug'] if sidebar else ''
            return self.ROOT + '/' + slug if SLUG.fullmatch(slug) else ''
        for anchor in soup.select('a[href*="/series/"]'):
            target = self.site_link(anchor['href'], url)
            if self.TITLE_PATH.fullmatch(urlsplit(target).path):
                return target
        return ''

    def saved_chapter_url(self, value, title, root):
        return self.site_link(value, root)

    def saved_chapter_matches(self, target, title):
        http = PublicHttp(timeout=(3, 6))
        try:
            path = urlsplit(title).path
            series = self.TITLE_PATH.fullmatch(path)
            soup, final = self.document(http, path)
            chapter_path = urlsplit(target).path.rstrip('/')
            return bool(series and any(urlsplit(entry['url']).path.rstrip('/') == chapter_path
                                       for entry in self.chapters(http, soup, final, series[1])))
        finally:
            http.close()

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        series = self.TITLE_PATH.fullmatch(path)
        if not (series or self.CHAPTER_PATH.fullmatch(path)):
            raise SourceError('Некорректная ссылка на читалку Keyoapp.')
        soup, url = self.document(http, path)
        if series and (self.layout != 'v2' or soup.select_one('[data-series-uid]')):
            result = self.metadata(soup, url)
            episodes = self.chapters(http, soup, url, series[1])
            pages = []
        else:
            parent = self.series_link(soup, url)
            if not parent:
                raise SourceError('Keyoapp не предоставил ссылку главы на произведение.')
            label = node_text(soup.select_one('h1, title'))
            result = self.row(label or self.TITLE_PATH.fullmatch(urlsplit(parent).path)[1], parent)
            episode = self.chapter(url, label)
            episodes = [{**episode, 'number': episode['number'] or 0}]
            pages = self.pages(soup, url)
        return {**result, 'url': url, 'episodes': episodes, 'pages': pages, 'available': bool(episodes),
                'truncated': False, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({e['season'] for e in episodes})],
                'dubs': [], 'releases': [], 'translations': []}


SOURCES = (
    Keyoapp('734404203508686053', 'Art Lapsa', 'https://artlapsa.com', True, layout='redesign'),
    Keyoapp('2076371496779298312', 'Asmodeus Scans', 'https://asmotoon.com', layout='v2'),
    Keyoapp('8358420357808595754', 'Eris Scans', 'https://erisscans.com', True, fields={
        'aliases': 'div.font-medium:-soup-contains-own("Alternative titles") ~ div span.select-all',
        'status': 'div[alt=Status]', 'authors': 'div[alt=Author]', 'artists': 'div[alt=Artist]',
        'format': 'div[alt="Series Type"]',
    }),
    Keyoapp('8588684547293952127', 'Grim Scans', 'https://grimscans.com'),
    Keyoapp('1145415569668934781', 'Kaizen Scan', 'https://kaizenscan.com', True),
    Keyoapp('2816768640766208312', 'Kewn Scans', 'https://kewnscans.org'),
    Keyoapp('7739452864322240494', 'Kitsune Dawn', 'https://kitsunedawn.com', True, layout='redesign', query_limit=100),
    Keyoapp('4513668905743562887', 'Luna Toons', 'https://lunatoons.net', True, layout='v2'),
    Keyoapp('3314074618469377356', 'MeiToon', 'https://meitoon.org'),
    # mistscans.com lost its DNS; the extension moved to mistscans.org (Nov 2026).
    Keyoapp('80073424419623517', 'Mist Scans', 'https://mistscans.org'),
    Keyoapp('3025454996745441538', 'Nyanu Kafe', 'https://nyanukafe.com', fields={
        'authors': 'div.w-full.flex-wrap > div:nth-child(1) > div:last-child',
        'artists': 'div.w-full.flex-wrap > div:nth-child(2) > div:last-child',
        'format': 'div.w-full.flex-wrap > div:nth-child(3) > div:last-child',
        'status': 'div.w-full.flex-wrap > div:nth-child(4) > div:last-child',
    }),
    Keyoapp('8220771912098311271', 'RitharScans', 'https://ritharscans.com', layout='redesign', query_limit=100),
    Keyoapp('5804710058654490234', 'Siren Scans', 'https://sirenscans.com', layout='v2'),
    Keyoapp('1061713767402958340', 'Genz Toons', 'https://genztoons.org', interval=1 / 3),
    Keyoapp('9063123408669132087', 'TimelessToons', 'https://timelesstoons.org',
            latest_cards='div.grid > div.group.latest-poster'),
    Keyoapp('561830040001881975', 'Writer Scans', 'https://writerscans.com'),
)

ENABLED = {
    '2076371496779298312',  # Asmodeus Scans
    '2816768640766208312',  # Kewn Scans
    '80073424419623517',    # Mist Scans
    '3025454996745441538',  # Nyanu Kafe
    '8220771912098311271',  # RitharScans
    '5804710058654490234',  # Siren Scans
    '1061713767402958340',  # Genz Toons
    '9063123408669132087',  # TimelessToons
    '561830040001881975',   # Writer Scans
}
ACTIVE_SOURCES = tuple(source for source in SOURCES if source.SOURCE_ID in ENABLED)
