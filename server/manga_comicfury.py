"""Comic Fury public profiles, infinite-scroll archives and custom layouts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import image_from, node_text
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from manga_xcomic_fury_profiles import FURY
from source_parser import SourceAccessError, SourceError, public_url


ROOT = 'https://comicfury.com'
SLUG = r'[A-Za-z0-9][A-Za-z0-9-]{0,79}'
NUM = r'[1-9][0-9]{0,12}'
TITLE_PATH = re.compile(rf'/read/({SLUG})/archive/?')
ARCHIVE_PATH = re.compile(rf'/read/({SLUG})/archive(?:/chapter/{NUM})?/?')
CHAPTER_PATH = re.compile(rf'/read/({SLUG})/comics/({NUM})(?:/{SLUG})?/?')
CUSTOM_HOST = re.compile(rf'({SLUG})\.(webcomic\.ws|thecomicseries\.com|thewebcomic\.com)')
CUSTOM_CHAPTER = re.compile(rf'/comics/({NUM})(?:/{SLUG})?/?')
CUSTOM_ARCHIVE = '/archive/comics'
TOKEN = re.compile(r'[A-Za-z0-9+=/_.-]{1,512}')
NEXT = 'span.vfpagecurrent + a.vfpage[href]'
MAX_ARCHIVE_PAGES = 60
MAX_EPISODES = 6000


def warning_form(url, data):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not isinstance(data, dict) or data.keys() != {'token', 'proceed'}
            or data.get('proceed') != 'View Webcomic' or not isinstance(data.get('token'), str)
            or not TOKEN.fullmatch(data['token'])):
        return False
    if parts.netloc == 'comicfury.com':
        return bool(ARCHIVE_PATH.fullmatch(parts.path) or CHAPTER_PATH.fullmatch(parts.path)
                    or parts.path == '/comicprofile.php' and title_slug(url))
    return bool(CUSTOM_HOST.fullmatch(parts.netloc) and
                (CUSTOM_CHAPTER.fullmatch(parts.path) or parts.path.rstrip('/') == CUSTOM_ARCHIVE))


def link(value, base=ROOT + '/'):
    if not isinstance(value, str) or not value:
        return ''
    try:
        target = urljoin(base, value)
        parts = urlsplit(target)
        if parts.netloc != 'comicfury.com' and not CUSTOM_HOST.fullmatch(parts.netloc):
            return ''
        return public_url(target, resolve_dns=False)
    except (ValueError, SourceError):
        return ''


def title_slug(value):
    parts = urlsplit(value)
    if parts.netloc != 'comicfury.com':
        match = CUSTOM_HOST.fullmatch(parts.netloc)
        return match[1] if match else ''
    if match := ARCHIVE_PATH.fullmatch(parts.path):
        return match[1]
    if parts.path == '/comicprofile.php':
        try:
            ids = parse_qs(parts.query, max_num_fields=5).get('url', [])
        except ValueError:
            return ''
        return ids[0] if len(ids) == 1 and re.fullmatch(SLUG, ids[0]) else ''
    return ''


def clean_date(raw):
    value = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b|,', '', raw, flags=re.I)
    for form in ('%d %B %Y %I:%M %p', '%d %b %Y %I:%M %p', '%d %B %Y', '%d %b %Y',
                 '%B %d %Y', '%b %d %Y', '%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, form).date().isoformat()
        except ValueError:
            pass
    return ''


def document(http, value):
    url = link(value)
    if not url:
        raise SourceError('Некорректный маршрут Comic Fury.')
    origin = 'https://' + urlsplit(url).netloc
    headers = {'Referer': origin + '/', 'Origin': origin}
    html, final, _ = http.document(url, headers=headers)
    if not link(final):
        raise SourceError('Comic Fury перенаправил запрос на другой сайт.')
    doc = BeautifulSoup(html, 'html.parser')
    token = doc.select_one('input[name=token][value]')
    if ((doc.title is not None and 'Content Warning' in node_text(doc.title))
            and doc.select_one('input[name=proceed][value="View Webcomic"]')):
        if not token or not warning_form(final, {'token': token['value'], 'proceed': 'View Webcomic'}):
            raise SourceAccessError('Comic Fury требует подтверждение предупреждения.')
        origin = 'https://' + urlsplit(final).netloc
        html, final, _ = http.document(final, method='POST', data={'token': token['value'], 'proceed': 'View Webcomic'},
                                       headers={'Origin': origin, 'Referer': final}, action='comicfury-warning')
        doc = BeautifulSoup(html, 'html.parser')
        if doc.select_one('input[name=proceed][value="View Webcomic"]') or not link(final):
            raise SourceAccessError('Comic Fury не принял подтверждение предупреждения.')
    return doc, final


def chapter_address(value):
    parts = urlsplit(value)
    match = CHAPTER_PATH.fullmatch(parts.path)
    if parts.netloc == 'comicfury.com' and match:
        return match[1], match[2], ''
    host, chapter = CUSTOM_HOST.fullmatch(parts.netloc), CUSTOM_CHAPTER.fullmatch(parts.path)
    if host and chapter:
        return host[1], chapter[1], host[2]
    return None


class ComicFury:
    ROOT = ROOT
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, language, name):
        self.SOURCE_ID, self.LANGUAGE, self.NAME = sid, language, name
        self.locale = 'notext' if name.endswith('(No Text)') else 'pt' if language == 'pt-BR' else language

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + '/', value))
            target = link(raw)
            if selected not in (None, self.SOURCE_ID) or not target:
                return ''
            parts = urlsplit(target)
            if custom := CUSTOM_HOST.fullmatch(parts.netloc):
                chapter = chapter_address(target)
                if chapter:
                    return self.chapter_url(*chapter)
                if parts.path.rstrip('/') in ('', CUSTOM_ARCHIVE, '/archive'):
                    return ROOT + '/read/' + custom[1] + '/archive'
                return ''
            return target
        except ValueError:
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def chapter_url(self, slug, identity, layout=''):
        return ROOT + f'/read/{slug}/comics/{identity}' + ('?layout=' + layout if layout else '')

    def row(self, slug, name, cover):
        url = self.reader_url(ROOT + '/read/' + slug + '/archive')
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug.lower()}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'url': url, 'sourceUrl': url, 'kind': 'manga', 'format': 'comic', 'language': self.LANGUAGE,
                'title': name, 'aliases': unique([name]), 'cover': cover, 'genres': [], 'tags': [],
                'description': '', 'sourceOnly': True, 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога Comic Fury.')
        query = query.strip()[:160]
        args = {'query': query, 'page': page, 'language': self.locale,
                'sort': 0 if query or tag else 2 if sort == 'updated' else 1,
                'completed': 1, 'lastupdate': 0, 'fv': 2, 'fn': 2, 'fl': 2, 'fs': 2}
        if tag:
            args['tags'] = tag[:160]
        doc, final = document(http, ROOT + '/search.php?' + urlencode(args))
        if urlsplit(final).netloc != 'comicfury.com':
            raise SourceError('Comic Fury сменил сервер каталога.')
        result = {}
        for row in doc.select('div.webcomic-result'):
            a = row.select_one('div.webcomic-result-avatar a[href]')
            title = row.select_one('div.webcomic-result-title')
            slug = title_slug(link(a['href'], final)) if a else ''
            name = (title.get('title') or node_text(title)).strip() if title else ''
            if slug and name:
                result.setdefault(slug.lower(), self.row(slug, name, image_from(a.select_one('img'), final)))
        return list(result.values()), bool(result and doc.select_one('div.search-next-page'))

    def vocabulary(self, http):
        return []

    def work(self, http, slug):
        doc, final = document(http, ROOT + '/comicprofile.php?' + urlencode({'url': slug}))
        if title_slug(final).lower() != slug.lower():
            raise SourceError('Comic Fury вернул другой тайтл.')
        head = doc.select_one('.username-and-title')
        title = node_text(doc.select_one('.username-and-title .authorname, h1'))
        og = doc.select_one('meta[property="og:title"][content]')
        if og:
            title = og['content']
        if not title and doc.title:
            title = re.split(r' - Webcomic profile| [|-] Comic Fury', node_text(doc.title), maxsplit=1)[0]
        cover = image_from(doc.select_one('.comic-avatar img, .webcomic-result-avatar img, img[alt="Webcomic Icon"]'), final)
        row = self.row(slug, title or slug, cover)
        tags = doc.select_one('div.description-tags')
        row['tags'] = unique(node_text(child) for child in (tags.find_all(recursive=False) if tags else []))
        row['genres'] = unique(node_text(a) for item in doc.select('div.authorinfo')
                               if 'genre' in node_text(item).casefold() for a in item.select('a'))
        row['authors'] = unique(node_text(a) for a in doc.select('a.authorname'))
        description = (''.join(tags.parent.find_all(string=True, recursive=False)).strip() if tags and tags.parent else '')
        row['description'] = (description or node_text(head.select_one('em') if head else None))[:12000]
        return row

    def details(self, http, value):
        slug = title_slug(self.site_link(value))
        if not slug:
            raise SourceError('Некорректная ссылка на комикс Comic Fury.')
        return self.work(http, slug)

    def collect(self, http, doc, url, slug, group=''):
        results, seen = [], {url}
        for _ in range(MAX_ARCHIVE_PAGES):
            for anchor in doc.select('a[href]:has(.archive-comic)'):
                found = chapter_address(link(anchor['href'], url))
                if not found or found[0].lower() != slug.lower():
                    continue
                _, identity, layout = found
                name = node_text(anchor.select_one('.archive-comic-title'))
                date = clean_date(node_text(anchor.select_one('.archive-comic-date')))
                results.append((self.chapter_url(slug, identity, layout), ' — '.join(filter(None, (group, name))), date))
            nxt = doc.select_one(NEXT)
            if not nxt:
                return results, False
            next_url = link(nxt['href'], url)
            if title_slug(next_url).lower() != slug.lower() or next_url in seen:
                raise SourceError('Comic Fury вернул некорректную пагинацию архива.')
            seen.add(next_url)
            doc, url = document(http, next_url)
        return results, True

    def chapters(self, http, slug):
        archive = ROOT + '/read/' + slug + '/archive'
        doc, final = document(http, archive)
        if title_slug(final).lower() != slug.lower():
            raise SourceError('Comic Fury вернул архив другого комикса.')
        sections = {}
        for anchor in doc.select('a[href]:has(.archive-chapter)'):
            url = link(anchor['href'], final)
            if title_slug(url).lower() == slug.lower() and url != final:
                sections[url] = node_text(anchor.select_one('.archive-chapter-title')) or node_text(anchor)

        def collect_section(entry):
            url, name = entry
            worker = http.fork()
            try:
                section, target = document(worker, url)
                if title_slug(target).lower() != slug.lower():
                    raise SourceError('Comic Fury вернул чужой раздел архива.')
                return self.collect(worker, section, target, slug, name)
            finally:
                worker.close()

        rows, truncated = [], False
        if sections:
            with ThreadPoolExecutor(max_workers=min(4, len(sections))) as pool:
                for entries, more in pool.map(collect_section, list(sections.items())[:MAX_ARCHIVE_PAGES]):
                    rows.extend(entries)
                    truncated |= more
            truncated |= len(sections) > MAX_ARCHIVE_PAGES
        else:
            rows, truncated = self.collect(http, doc, final, slug)
        if not rows:
            custom = f'https://{slug.lower()}.webcomic.ws' + CUSTOM_ARCHIVE
            doc, final = document(http, custom)
            if title_slug(final).lower() != slug.lower():
                raise SourceError('Comic Fury подменил архив авторской читалки.')
            for entry in doc.select('div.archivecomic, div.nl-archivecomic'):
                anchor = entry.select_one('a[href]')
                found = chapter_address(link(anchor['href'], final)) if anchor else None
                if not found or found[0].lower() != slug.lower():
                    continue
                _, identity, layout = found
                previous = entry.parent.find_previous_sibling() if entry.parent else None
                group = node_text(previous.select_one('h3')) if previous else ''
                name = ' — '.join(filter(None, (group, node_text(anchor))))
                date = clean_date(node_text(entry.select_one('.comicposttime, .nl-archivecomicposttime')))
                rows.append((self.chapter_url(slug, identity, layout), name, date))
        distinct = {url: (title, date) for url, title, date in rows}
        episodes = [{'url': self.reader_url(url), 'title': title or f'Страница {i+1}', 'number': i, 'season': 1,
                     'language': self.LANGUAGE, 'publishedAt': date}
                    for i, (url, (title, date)) in enumerate(distinct.items()) if i < MAX_EPISODES]
        return list(reversed(episodes)), truncated or len(distinct) > MAX_EPISODES

    def chapter_pages(self, http, slug, identity, layout):
        value = f'https://{slug.lower()}.{layout}/comics/{identity}' if layout else self.chapter_url(slug, identity)
        doc, final = document(http, value)
        found = chapter_address(final)
        if not found or found[0].lower() != slug.lower() or found[1] != identity:
            raise SourceError('Comic Fury вернул другую главу.')
        nodes = doc.select('div.is--comic-page div.is--image-segment div img') or doc.select('#comicimage')
        urls = [image_from(node, final) for node in nodes]
        if not 1 <= len(urls) <= 500 or not all(urls):
            raise SourceError('Comic Fury не предоставил полный список страниц.')
        name = node_text(doc.select_one('h1, .is--comic-title')) or 'Страница'
        notes = node_text(doc.select_one('div.is--author-notes div.is--comment-content'))
        return name, urls, notes

    def inspect(self, value, http):
        target = self.site_link(value)
        split = urlsplit(target)
        title, chapter = TITLE_PATH.fullmatch(split.path), CHAPTER_PATH.fullmatch(split.path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку Comic Fury.')
        slug = (title or chapter)[1]
        row = self.work(http, slug)
        pages, notes, truncated = [], '', False
        if chapter:
            layout = parse_qs(split.query).get('layout', [''])[0]
            if layout and not CUSTOM_HOST.fullmatch(slug + '.' + layout):
                raise SourceError('Comic Fury вернул неизвестный адрес авторской читалки.')
            name, pages, notes = self.chapter_pages(http, slug, chapter[2], layout)
            episodes = [{'url': self.reader_url(target), 'title': name, 'number': 0, 'season': 1, 'language': self.LANGUAGE}]
        else:
            episodes, truncated = self.chapters(http, slug)
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages, 'authorNotes': notes,
                'available': bool(episodes), 'truncated': truncated, 'dubs': [], 'releases': [], 'translations': [],
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else []}

    def saved_title_url(self, value):
        slug = title_slug(value)
        return ROOT + '/read/' + slug + '/archive' if slug else ''

    def saved_chapter_url(self, value, _slug, root):
        return self.site_link(value, root)

    def saved_chapter_matches(self, chapter, title):
        return CHAPTER_PATH.fullmatch(urlsplit(chapter).path)[1].lower() == title_slug(title).lower()


SOURCES = tuple(ComicFury(*profile) for profile in FURY)
