"""Public WordPress Madara catalogues, including the AJAX chapter variants."""

import base64
from calendar import monthrange
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import threading
import time
import unicodedata
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from manga_madara_profiles import ENABLED, PROFILES
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import PublicHttp, SourceAccessError, SourceError, SourceTemporaryError, public_url


SEGMENT = r'(?!(?:\.|%2[eE]){1,2}(?:/|$))(?:[\w.~+-]|%(?!2[fF]|5[cC]|[01][0-9a-fA-F])[0-9a-fA-F]{2}){1,240}'
ID = re.compile(r'[1-9]\d{0,11}')
NUM = r'(\d{1,4}(?:[.,]\d{1,3})?)(?!\d)'
CHAPTER_NUMBER = re.compile(r'(?:chapter|chap\.?|ch\.?|глава|cap[ií]tulo)[\s_\-#:]*' + NUM, re.I)
VOLUME_NUMBER = re.compile(r'(?:volume|vol\.?|том|tomo)[\s_\-#:]*([1-9]\d{0,2})(?!\d)', re.I)
PAGE_WRAP = '.page-break, li.blocks-gallery-item, .reading-content .text-left:not(:has(.blocks-gallery-item))'
SELECTORS = {
    'cards': '.page-item-detail, .manga__item, .c-tabs-item__content',
    'card_link': '.post-title a[href]', 'card_cover': 'img',
    'next': 'div.nav-previous, a.nextpostslink, #navigation-ajax',
    'title': '.post-title h3, .post-title h1, #manga-title > h1',
    'cover': '.summary_image img', 'genres': '.genres-content a', 'tags': '.tags-content a',
    'authors': '.author-content > a, .manga-authors > a', 'artists': '.artist-content > a',
    'description': '.description-summary .summary__content, .summary_content .manga-excerpt, .summary_content .post-content_item > h5 + div',
    'chapters': 'li.wp-manga-chapter', 'chapter_link': 'a[href]', 'chapter_name': '',
    'chapter_date': '.chapter-release-date', 'page_images': '',
}
FORM = '/wp-admin/admin-ajax.php'
CATALOGUE_FORM = {
    'action': 'madara_load_more', 'template': 'madara-core/content/content-archive',
    'vars[paged]': '1', 'vars[template]': 'archive', 'vars[posts_per_page]': '25',
    'vars[post_type]': 'wp-manga', 'vars[post_status]': 'publish',
    'vars[manga_archives_item_layout]': 'big_thumbnail',
}
MANGA_ONLY = {'vars[meta_query][0][key]': '_wp_manga_chapter_type',
              'vars[meta_query][0][value]': 'manga'}
GENRE = {'vars[tax_query][0][taxonomy]': 'wp-manga-genre',
         'vars[tax_query][0][field]': 'slug'}


def node_text(node):
    return node.get_text(' ', strip=True) if node else ''


def genre_slug(value):
    return isinstance(value, str) and bool(re.fullmatch(SEGMENT, value))


def image_url(value, page):
    if not isinstance(value, str) or not value.strip():
        return ''
    try:
        url = urljoin(page, value.strip())
        parsed = urlsplit(url)
        # WordPress installations can retain old HTTP URLs for local uploads.
        if (parsed.scheme == 'http' and parsed.netloc == urlsplit(page).netloc
                and parsed.path.startswith('/wp-content/uploads/')):
            url = urlunsplit(parsed._replace(scheme='https'))
        return public_url(url, resolve_dns=False)
    except (SourceError, ValueError):
        return ''


def image_from(node, page):
    if not node:
        return ''
    for name in ('data-src', 'data-lazy-src', 'data-lzl-src', 'data-cfsrc', 'data-manga-src'):
        if url := image_url(node.get(name), page):
            return url
    candidates = []
    for value in node.get('srcset', '').split(','):
        item = value.strip().split()
        if item and (url := image_url(item[0], page)):
            weight = item[1][:-1] if len(item) == 2 and re.fullmatch(r'\d+(?:\.\d+)?[wx]', item[1]) else '0'
            candidates.append((float(weight), url))
    return max(candidates)[1] if candidates else image_url(node.get('src'), page)


def public_reader_images(node):
    """Decode only the payload and nonce already supplied by the public reader."""
    text = node.string or node.get_text()
    source = node.get('src', '')
    try:
        if source.startswith('data:text/javascript;base64,'):
            text = base64.b64decode(source.split(',', 1)[1], validate=True).decode()
        nonce = re.search(r"""\bwpmangaprotectornonce\s*=\s*'([^'\r\n]{1,200})'""", text)
        payload = re.search(r"""\bchapter_data\s*=\s*'(\{[^'\r\n]+\})'""", text)
        if not nonce or not payload:
            raise ValueError
        data = json.loads(payload[1])
        salt = bytes.fromhex(data['s'])
        if len(salt) != 8:
            raise ValueError
        ciphertext = base64.b64decode(data['ct'], validate=True)
        previous = b''
        blocks = []
        for _ in range(3):
            previous = hashlib.md5(previous + nonce[1].encode() + salt, usedforsecurity=False).digest()
            blocks.append(previous)
        key_material = b''.join(blocks)
        decryptor = Cipher(algorithms.AES(key_material[:32]), modes.CBC(key_material[32:])).decryptor()
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(decryptor.update(ciphertext) + decryptor.finalize()) + unpadder.finalize()
        result = json.loads(plain)
        return json.loads(result) if isinstance(result, str) else result
    except (KeyError, TypeError, ValueError) as error:
        raise SourceError('Madara изменил формат изображений открытой главы.') from error


def release_date(value, template):
    now = datetime.now(timezone.utc)
    label = value.strip().lower()
    if label == 'today' or label == 'yesterday':
        return (now.date() - timedelta(days=label == 'yesterday')).isoformat()
    if match := re.fullmatch(r'(\d{1,4})\s+(day|week|hour|minute|second)s?\s+ago', label):
        unit = match[2] + 's'
        return (now - timedelta(**{unit: int(match[1])})).date().isoformat()
    if match := re.fullmatch(r'(\d{1,3})\s+(month|year)s?\s+ago', label):
        count = int(match[1]) * (12 if match[2] == 'year' else 1)
        year, month = divmod(12 * now.year + now.month - 1 - count, 12)
        day = min(now.day, monthrange(year, month + 1)[1])
        return now.replace(year=year, month=month + 1, day=day).date().isoformat()
    for date_format in (template, '%Y-%m-%d'):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    return ''


class OriginPace:
    def __init__(self):
        self.lock = threading.Lock()
        self.interval = 0.0
        self.next_request = 0.0

    def wait(self, deadline):
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            scheduled = max(now, self.next_request)
            if deadline is not None and scheduled >= deadline:
                raise SourceTemporaryError('Исчерпан бюджет ожидания запроса к источнику.')
            self.next_request = scheduled + self.interval
        if scheduled > now:
            time.sleep(scheduled - now)


class Madara:
    def __init__(self, sid, name, root, adult, *, html=False, chapter_mode='page', section='manga',
                 genre_section='manga-genre', manga_only=True, uses_post_id=True, date_format='%B %d, %Y',
                 language='en', selectors=None, ajax_template=CATALOGUE_FORM['template'],
                 metadata_interval=0, thumbnail_original=False, alt_names=True,
                 scoped_urls=False, raw_marker=None, origin=None, chapter_volumes=False):
        self.SOURCE_ID = sid
        self.NAME = name
        self.ROOT = root
        self.IS_NSFW = adult
        self.LANGUAGE = language
        self.html = html
        self.chapter_mode = chapter_mode
        self.section = section
        self.genre_section = genre_section
        self.manga_only = manga_only
        self.uses_post_id = uses_post_id
        self.date_format = date_format
        self.selectors = {**SELECTORS, **(selectors or {})}
        self.ajax_template = ajax_template
        self.thumbnail_original = thumbnail_original
        self.alt_names = alt_names
        self.scoped_urls = scoped_urls
        self.raw_marker = raw_marker
        self.origin = origin if origin is not None else OriginPace()
        self.origin.interval = max(self.origin.interval, metadata_interval)
        self.chapter_cache = OrderedDict() if raw_marker and language != 'all' else None
        self.chapter_lock = threading.Lock() if self.chapter_cache is not None else None
        self.host = urlsplit(root).hostname
        self.TITLE_PATH = re.compile(rf'/{section}/({SEGMENT})/?')
        chapter_path = rf'(?:tomo-[1-9]\d{{0,2}}/)?{SEGMENT}' if chapter_volumes else SEGMENT
        self.CHAPTER_PATH = re.compile(rf'/{section}/({SEGMENT})/({chapter_path})/?')

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, candidate = split_reader_url(urljoin(base or self.ROOT + '/', value))
            if selected is not None and (not self.scoped_urls or selected != self.SOURCE_ID):
                return ''
            parsed = urlsplit(candidate)
            if parsed.scheme not in {'http', 'https'} or parsed.netloc != self.host:
                return ''
            return public_url(urlunsplit(parsed._replace(scheme='https')), resolve_dns=False)
        except (SourceError, ValueError):
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID) if self.scoped_urls else value

    def saved_chapter_url(self, value, title, root):
        if isinstance(value, str) and re.fullmatch(SEGMENT, value):
            value = f'/{self.section}/{title}/{value}/'
        return self.site_link(value, root)

    def saved_title_url(self, value):
        target = self.site_link(value)
        if self.TITLE_PATH.fullmatch(urlsplit(target).path):
            return target
        if not self.legacy_post_id(target):
            return ''
        http = PublicHttp(timeout=(3, 6))
        try:
            return self.title(http, target)[1]
        finally:
            http.close()

    def legacy_post_id(self, url):
        if not self.uses_post_id:
            return ''
        parsed = urlsplit(url)
        if not parsed.query and ID.fullmatch(parsed.path.lstrip('/')):
            return parsed.path.lstrip('/')
        query = parse_qs(parsed.query)
        values = query.get('p', [])
        return values[0] if parsed.path == '/' and set(query) == {'p'} and len(values) == 1 and ID.fullmatch(values[0]) else ''

    def soup(self, http, url, *, data=None, referer=None):
        self.origin.wait(getattr(http, 'deadline', None))
        headers = {'Referer': referer or self.ROOT + '/'}
        options = {'method': 'POST', 'data': data, 'action': 'madara-read'} if data is not None else {}
        raw, final, _ = http.document(url, headers=headers, **options)
        if not self.site_link(final):
            raise SourceError('Madara перенаправил на другой источник.')
        from manga_sources import guard
        document = BeautifulSoup(raw, 'html.parser')
        guard(document)
        return document, final

    def catalogue_data(self, page, query, sort, tag):
        data = {**CATALOGUE_FORM, 'template': self.ajax_template, 'page': str(page - 1)}
        if self.manga_only:
            data.update(MANGA_ONLY)
        if query:
            data['vars[s]'] = query[:160]
        elif not tag:
            data.update({'vars[orderby]': 'meta_value_num', 'vars[order]': 'DESC',
                         'vars[meta_key]': '_latest_update' if sort == 'updated' else '_wp_manga_views'})
        if tag:
            data.update(GENRE)
            data['vars[tax_query][0][terms][0]'] = tag
        return data

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if not isinstance(page, int) or not 1 <= page <= 2000 or (tag and not genre_slug(tag)):
            raise SourceError('Некорректные параметры каталога Madara.')
        if self.html:
            if query and not tag and page > 1 and not self.html_search_paginates():
                return [], False
            path, params = self.html_request(http, page, query, sort, tag)
            if not path:
                return [], False
            target = self.ROOT + path + ('?' + urlencode(params) if params else '')
            soup, final = self.soup(http, target)
            if urlsplit(final).path.rstrip('/') != path.rstrip('/'):
                raise SourceError('Madara перенаправил на другую страницу каталога.')
        else:
            soup, final = self.soup(http, self.ROOT + FORM, data=self.catalogue_data(page, query, sort, tag))
        rows = self.archive_rows(soup, final)
        more = (self.html_has_more(soup, query, tag) if self.html else len(rows) == 25)
        return rows, more

    def html_request(self, http, page, query, sort, tag):
        path = f'/{self.genre_section}/{tag}/' if tag else '/' if query else f'/{self.section}/'
        path += f'page/{page}/' if page > 1 else ''
        params = {'s': query, 'post_type': 'wp-manga'} if query else {'m_orderby': 'latest' if sort == 'updated' else 'views'}
        return path, params

    def html_has_more(self, soup, query, tag):
        return (not query or tag or self.html_search_paginates()) and bool(soup.select_one(self.selectors['next']))

    def html_search_paginates(self):
        return not self.uses_post_id

    def archive_rows(self, soup, final):
        found = {}
        for card in soup.select(self.selectors['cards']):
            link = card.select_one(self.selectors['card_link'])
            target = self.site_link(link.get('href'), final) if link else ''
            slug = self.TITLE_PATH.fullmatch(urlsplit(target).path)
            title = node_text(link)
            if slug and title:
                found[slug[1]] = self.row(target, title, self.thumbnail(card.select_one(self.selectors['card_cover']), final))
        return list(found.values())

    def thumbnail(self, node, url):
        image = image_from(node, url)
        if self.thumbnail_original and image:
            parsed = urlsplit(image)
            path = re.sub(r'-\d+x\d+(?=\.[a-zA-Z]+$)', '', parsed.path)
            return urlunsplit(parsed._replace(path=path))
        return image

    def vocabulary(self, http):
        soup, final = self.soup(http, self.ROOT + f'/{self.section}/')
        values = {}
        for node in soup.select('.genres a[href], .genres-content a[href]'):
            target = self.site_link(node['href'], final)
            pattern = rf'/{self.genre_section}/({SEGMENT})/?'
            match = re.fullmatch(pattern, urlsplit(target).path)
            for counter in node.select('.count'):
                counter.decompose()
            if match and (label := node_text(node)):
                values[match[1]] = {'label': label, 'sourceId': match[1], 'category': 'genre'}
        return list(values.values())

    def legacy_term_label(self, label):
        return re.sub(r'\s+\(\d+\)$', '', label)

    def row(self, url, title, cover):
        from manga_sources import title_aliases
        slug = self.TITLE_PATH.fullmatch(urlsplit(url).path)[1]
        reader = self.reader_url(url)
        return {
            'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
            'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': reader,
            'url': reader, 'kind': 'manga', 'language': self.LANGUAGE, 'title': title[:500],
            'aliases': title_aliases(title), 'cover': cover, 'sourceOnly': True, 'ids': {},
        }

    def metadata(self, soup, url):
        title = node_text(soup.select_one(self.selectors['title']))
        if not title:
            raise SourceError('Madara не предоставил карточку произведения.')
        result = self.row(url, title, self.thumbnail(soup.select_one(self.selectors['cover']), url))
        for field in ('genres', 'tags', 'authors', 'artists'):
            result[field] = unique(node_text(node) for node in soup.select(self.selectors[field])) if self.selectors[field] else []
        description = soup.select_one(self.selectors['description'])
        result['description'] = ('\n\n'.join(node_text(p) for p in description.select('p')) or node_text(description))[:12000] if description else ''
        for item in soup.select('.post-content_item'):
            label = node_text(item.select_one('.summary-heading, h5')).casefold()
            value = node_text(item.select_one('.summary-content'))
            if self.alt_names and label in {'alternative', 'alternative names', 'alt names', 'alternative name', 'other names'}:
                aliases = [v.strip() for v in re.split(r'\s*;\s*|\s+[/|]\s+', value) if v.strip()]
                result['aliases'] = unique([*result['aliases'], *aliases])
            elif label == 'status':
                result['status'] = value
            elif label == 'type':
                result['format'] = value.casefold() if value.casefold() in {'manga', 'manhwa', 'manhua', 'webtoon'} else ''
        if status := self.selectors.get('status'):
            result['status'] = node_text(soup.select_one(status))
        return result

    def title(self, http, value):
        target = self.site_link(value)
        expected = self.TITLE_PATH.fullmatch(urlsplit(target).path)
        post_id = self.legacy_post_id(target)
        if not (expected or post_id):
            raise SourceError('Некорректная ссылка на тайтл Madara.')
        soup, final = self.soup(http, self.ROOT + '/?p=' + post_id if post_id else target)
        latest = self.TITLE_PATH.fullmatch(urlsplit(final).path)
        holder = soup.select_one('[id^="manga-chapters-holder"][data-id]') if post_id else None
        if (not latest or expected and unquote(latest[1]) != unquote(expected[1])
                or holder is not None and holder['data-id'] != post_id):
            raise SourceError('Madara перенаправил карточку на другое произведение.')
        return soup, final, latest[1]

    def details(self, http, value):
        soup, final, _ = self.title(http, value)
        return self.metadata(soup, final)

    def chapter_rows(self, soup, url, slug, found):
        for node in soup.select(self.selectors['chapters']):
            anchor = node if node.name == 'a' and node.has_attr('href') else node.select_one(self.selectors['chapter_link'])
            chapter_url = self.site_link(anchor.get('href'), url) if anchor else ''
            path = urlsplit(chapter_url).path
            match = self.CHAPTER_PATH.fullmatch(path)
            if not match or unquote(match[1]) != unquote(slug) or path.rstrip('/') in found:
                continue
            label = node_text(node.select_one(self.selectors['chapter_name'])) if self.selectors['chapter_name'] else node_text(anchor)
            if self.chapter_cache is not None:
                raw = 'raw' in node_text(node).casefold() if self.raw_marker == 'contains' else label.endswith(' raw')
                if raw != (self.LANGUAGE == 'ko'):
                    continue
            num = CHAPTER_NUMBER.search(label) or CHAPTER_NUMBER.search(unquote(match[2]))
            volume = VOLUME_NUMBER.search(label) or VOLUME_NUMBER.search(unquote(match[2]))
            date_node = node.select_one(self.selectors['chapter_date'])
            date_image = date_node.select_one('img[alt]') if date_node else None
            date_link = date_node.select_one('a[title]') if date_node else None
            date = date_image['alt'] if date_image else date_link['title'] if date_link else node_text(date_node)
            found[path.rstrip('/')] = {
                'url': self.reader_url(chapter_url), 'title': label or unquote(match[2]), 'language': self.LANGUAGE,
                'number': float(num[1].replace(',', '.')) if num else None,
                'season': int(volume[1]) if volume else 1, 'translator': '',
                'publishedAt': release_date(date, self.date_format),
            }

    def chapters(self, http, soup, url, slug):
        found = {}
        truncated = False
        if self.chapter_mode == 'page':
            self.chapter_rows(soup, url, slug, found)
        else:
            ajax_url = self.ROOT + f'/{self.section}/{slug}/ajax/chapters/'
            if self.chapter_mode == 'admin':
                holder = soup.select_one('[id^="manga-chapters-holder"][data-id]')
                post_id = holder.get('data-id', '') if holder else ''
                if not ID.fullmatch(post_id):
                    raise SourceError('Madara не предоставил ID списка глав.')
                fragment, _ = self.soup(http, self.ROOT + FORM, data={'action': 'manga_get_chapters', 'manga': post_id}, referer=url)
                self.chapter_rows(fragment, url, slug, found)
            elif self.chapter_mode == 'manga':
                fragment, _ = self.soup(http, ajax_url, data={}, referer=url)
                self.chapter_rows(fragment, url, slug, found)
            else:
                for page in range(1, 101):
                    try:
                        fragment, _ = self.soup(http, ajax_url + '?t=' + str(page), data={}, referer=url)
                    except SourceError as error:
                        if type(error) is SourceError and str(error) == 'Источник вернул HTTP 404.' and page > 1:
                            break
                        raise
                    previous = len(found)
                    self.chapter_rows(fragment, url, slug, found)
                    if len(found) == previous:
                        break
                else:
                    truncated = True
        rows = list(found.values())
        for position, row in enumerate(rows):
            if row['number'] is None:
                row['number'] = len(rows) - position
        if self.chapter_cache is not None and not truncated:
            with self.chapter_lock:
                self.chapter_cache[unquote(slug)] = (time.monotonic() + 180, {
                    unquote(urlsplit(row['url']).path.rstrip('/')): row for row in rows
                })
                self.chapter_cache.move_to_end(unquote(slug))
                if len(self.chapter_cache) > 32:
                    self.chapter_cache.popitem(last=False)
        return sorted(rows, key=lambda row: (row['season'], row['number'])), truncated

    def chapter_in_variant(self, http, slug, path):
        key = unquote(slug)
        chapter_path = unquote(path.rstrip('/'))
        with self.chapter_lock:
            cached = self.chapter_cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1].get(chapter_path)
        soup, title, identity = self.title(http, f'{self.ROOT}/{self.section}/{slug}/')
        chapters, _ = self.chapters(http, soup, title, identity)
        return next((row for row in chapters if unquote(urlsplit(row['url']).path.rstrip('/')) == chapter_path), None)

    def pages(self, http, value, expected):
        soup, final = self.soup(http, value)
        if urlsplit(final).path.rstrip('/') != expected.rstrip('/'):
            raise SourceError('Madara перенаправил на другую главу.')
        if soup.select_one('#single-pager'):
            url = self.ROOT + expected + '?style=list'
            soup, final = self.soup(http, url)
            if urlsplit(final).path.rstrip('/') != expected.rstrip('/'):
                raise SourceError('Madara перенаправил список страниц на другую главу.')
        if protected := soup.select_one('#chapter-protector-data'):
            if soup.select_one('.paywall, .purchase-required, .chapter-locked, form.login'):
                raise SourceAccessError('Глава требует доступ у источника.')
            sources = public_reader_images(protected)
            if not isinstance(sources, list):
                raise SourceError('Madara вернул неверный список изображений.')
            pages = [image_url(value, final) for value in sources]
        else:
            selector = self.selectors['page_images']
            nodes = soup.select(selector) if selector else (wrapper.select_one('img') for wrapper in soup.select(PAGE_WRAP))
            # Gallery containers can be nested, while page order is the HTML order.
            images = {id(node): node for node in nodes if node}
            pages = [image_from(node, final) for node in images.values()]
        if not pages or len(pages) > 500 or not all(pages):
            raise SourceError('Madara не предоставил полный список страниц открытой главы.')
        return pages, final

    def inspect(self, value, http):
        value = self.site_link(value)
        path = urlsplit(value).path
        chapter = self.CHAPTER_PATH.fullmatch(path)
        if chapter:
            slug, chapter_slug = chapter.groups()
            selected = self.chapter_in_variant(http, slug, path) if self.chapter_cache is not None else None
            if self.chapter_cache is not None and selected is None:
                raise SourceError('У источника нет этой главы в выбранном языковом варианте.')
            pages, final = self.pages(http, value, path)
            number = CHAPTER_NUMBER.search(unquote(chapter_slug))
            volume = VOLUME_NUMBER.search(unquote(chapter_slug))
            entry = {'url': self.reader_url(final), 'title': unquote(chapter_slug), 'language': self.LANGUAGE,
                     'number': float(number[1].replace(',', '.')) if number else 0,
                     'season': int(volume[1]) if volume else 1, 'translator': ''}
            result = self.row(self.ROOT + f'/{self.section}/{slug}/', unquote(slug), '')
            episodes, truncated = [{**entry, **(selected or {}), 'url': self.reader_url(final)}], False
        else:
            soup, final, slug = self.title(http, value)
            result = self.metadata(soup, final)
            episodes, truncated = self.chapters(http, soup, final, slug)
            if not episodes and soup.select_one('.chapter-locked, .paywall, .purchase-required'):
                raise SourceAccessError('Список глав требует доступ у источника.')
            pages = []
        return {**result, 'url': self.reader_url(final), 'episodes': episodes, 'pages': pages, 'truncated': truncated,
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({x['season'] for x in episodes})],
                'dubs': [], 'releases': [], 'translations': [], 'available': bool(episodes)}


class AquaManga(Madara):
    def html_request(self, http, page, query, sort, tag):
        path = f'/{self.section}/' + (f'page/{page}/' if page > 1 else '')
        params = {'m_orderby': 'latest' if sort == 'updated' else 'views'}
        if query:
            params['search'] = query
        if tag:
            params['genre'] = tag
        return path, params

    def vocabulary(self, http):
        soup, final = self.soup(http, self.ROOT + f'/{self.section}/')
        options = {}
        for anchor in soup.select('.aqua-genre-pills a.aqua-filter-pill[href]'):
            url = self.site_link(anchor['href'], final)
            genre = parse_qs(urlsplit(url).query).get('genre', [''])[0]
            label = node_text(anchor)
            if genre_slug(genre) and label:
                options[genre] = {'label': label, 'sourceId': genre, 'category': 'genre'}
        return list(options.values())


class ManhwaRaw(Madara):
    def html_request(self, http, page, query, sort, tag):
        if not query or tag:
            return super().html_request(http, page, query, sort, tag)
        normalized = unicodedata.normalize('NFD', query.strip().lower())
        slug = re.sub(r'[^a-z0-9]+', '-', ''.join(c for c in normalized if not unicodedata.combining(c))).strip('-')
        if not slug:
            return '', {}
        home, _ = self.soup(http, self.ROOT + '/')
        field = home.select_one('input[name="mbk_token"]')
        token = field.get('value', '') if field else ''
        if not re.fullmatch(r'[A-Za-z0-9_-]{4,160}', token):
            raise SourceError('Manhwa Raw не предоставил публичный параметр поиска.')
        return f'/search/{token}/{slug}/' + (f'page/{page}/' if page > 1 else ''), {}

    def html_search_paginates(self):
        return True


class MangaHe(Madara):
    def pages(self, http, value, expected):
        pages, final = super().pages(http, value, expected)
        if pages[0].endswith('/1-000001.jpg'):
            pages = pages[1:]
        if not pages:
            raise SourceError('MangaHe вернул только служебное изображение.')
        return pages, final


VARIANTS = {'standard': Madara, 'aqua': AquaManga, 'raw': ManhwaRaw, 'mangahe': MangaHe}
PROFILE_COUNTS = Counter(urlsplit(identity[2]).hostname for identity, _ in PROFILES)
ORIGINS = {host: OriginPace() for host in PROFILE_COUNTS}
SOURCES = tuple(VARIANTS[options.get('variant', 'standard')](
    *identity, scoped_urls=PROFILE_COUNTS[urlsplit(identity[2]).hostname] > 1,
    origin=ORIGINS[urlsplit(identity[2]).hostname], **{k: v for k, v in options.items() if k != 'variant'}
) for identity, options in PROFILES)
ACTIVE_SOURCES = tuple(source for source in SOURCES if source.SOURCE_ID in ENABLED)
SOURCE_HOSTS = {source.host: source for source in SOURCES}


def ajax_form(url, data, referer):
    """The public transport may only send forms this pinned adapter generates."""
    parsed = urlsplit(url)
    source = SOURCE_HOSTS.get(parsed.netloc)
    if parsed.scheme != 'https' or not source or not isinstance(data, dict):
        return False
    if parsed.path == FORM and not parsed.query:
        if source.chapter_mode == 'admin' and data.keys() == {'action', 'manga'}:
            chapter_path = urlsplit(source.site_link(referer)).path
            return data['action'] == 'manga_get_chapters' and bool(ID.fullmatch(str(data['manga']))) and bool(source.TITLE_PATH.fullmatch(chapter_path))
        page = data.get('page', '')
        query = data.get('vars[s]', '')
        tag = data.get('vars[tax_query][0][terms][0]', '')
        if source.html or not isinstance(page, str) or not re.fullmatch(r'\d{1,4}', page) or int(page) >= 2000:
            return False
        if not isinstance(query, str) or len(query) > 160 or (tag and not genre_slug(tag)):
            return False
        sort = 'updated' if data.get('vars[meta_key]') == '_latest_update' else 'popular'
        return data == source.catalogue_data(int(page) + 1, query, sort, tag)
    chapter_path = urlsplit(source.site_link(referer)).path.rstrip('/')
    if data or not source.TITLE_PATH.fullmatch(chapter_path) or parsed.path != chapter_path + '/ajax/chapters/':
        return False
    if source.chapter_mode == 'manga':
        return not parsed.query
    return source.chapter_mode == 'paged' and bool(re.fullmatch(r't=(?:[1-9]\d?|100)', parsed.query))
