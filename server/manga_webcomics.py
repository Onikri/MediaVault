"""Native adapters for independent public webcomics and single-series readers."""

from dataclasses import dataclass, field
import json
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import image_from, image_url, node_text, release_date
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import PublicHttp, SourceError, public_url


MAX_ARCHIVE_PAGES = 80
MAX_EPISODES = 10000
MAX_PAGES = 500
PATH = r'/[A-Za-z0-9_%.~/-]+'
NUMBER = r'[0-9]{1,9}(?:[.,][0-9]{1,4})?'


def param(url, name):
    try:
        values = parse_qs(urlsplit(url).query, max_num_fields=16).get(name, ())
    except ValueError:
        return ''
    return values[0] if len(values) == 1 else ''


def numeric(value):
    return float(str(value).replace(',', '.')) if re.fullmatch(NUMBER, str(value)) else None


def query_url(url, **values):
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query.update(values)
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def selected_text(node, selector):
    return node_text(node.select_one(selector)) if selector else node_text(node)


def meta(doc, key):
    node = doc.select_one(f'meta[property="og:{key}"][content]')
    return node['content'].strip() if node else ''


@dataclass(frozen=True)
class Work:
    path: str
    title: str
    cover: str = ''
    description: str = ''
    author: str = ''
    aliases: tuple = ()
    archive: str = ''


@dataclass(frozen=True)
class Archive:
    selector: str
    href: str = 'href'
    title: str = ''
    next_page: str = ''
    reverse: bool = False
    query_key: str = ''
    query_path: str = ''
    prefix: str = ''
    number: str = ''
    date: str = ''
    date_format: str = '%Y-%m-%d'


@dataclass(frozen=True)
class Reader:
    selector: str
    attrs: tuple = ()
    image_hosts: tuple = ()
    exclude_crop: bool = False
    notes: str = ''
    notes_attr: str = ''


@dataclass(frozen=True)
class Profile:
    works: tuple = ()
    archive: Archive | None = None
    reader: Reader | None = None
    title_path: str = ''
    chapter_path: str = PATH
    chapter_query: str = ''
    title_query: str = ''
    hosts: tuple = ()
    enrich: bool = False
    title_selector: str = ''
    cover_selector: str = ''
    description_selector: str = ''
    genres_selector: str = ''
    author_selector: str = ''
    tag_selector: str = ''
    browse: object = None
    chapters: object = None
    pages: object = None
    title_for: object = None
    html_redirect: str = ''
    legacy_title: dict = field(default_factory=dict)
    legacy_chapter_prefix: str = ''


class Webcomic:
    scoped_urls = True

    def __init__(self, identity, profile):
        self.SOURCE_ID, self.NAME, self.LANGUAGE, self.ROOT, self.IS_NSFW = identity
        self.ROOT = self.ROOT.rstrip('/')
        self.profile = profile
        self.hostname = urlsplit(self.ROOT).hostname
        self.reader_hosts = frozenset((self.hostname, *profile.hosts))
        paths = [urlsplit(work.path).path.rstrip('/') for work in profile.works]
        allowed = profile.title_path or '|'.join(re.escape(path) + '/?' if path else '/' for path in paths)
        self.TITLE_PATH = re.compile(f'({allowed})')
        self.CHAPTER_PATH = re.compile(f'({profile.chapter_path})')

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or self.ROOT + '/', value))
            parts = urlsplit(raw)
            if selected not in (None, self.SOURCE_ID) or parts.hostname not in self.reader_hosts:
                return ''
            if parts.scheme not in {'http', 'https'} or parts.username or parts.password or parts.port not in (None, 443):
                return ''
            path = '/' + parts.path.lstrip('/')
            cleaned = public_url(urlunsplit(parts._replace(scheme='https', path=path)), resolve_dns=False)
            return urlunsplit(urlsplit(cleaned)._replace(fragment=parts.fragment))
        except (ValueError, SourceError):
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def title_identity(self, value):
        parts = urlsplit(value)
        try:
            query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True, max_num_fields=16)))
        except ValueError:
            query = parts.query
        suffix = ('?' + query if query else '') + ('#' + parts.fragment if parts.fragment else '')
        return (parts.path.rstrip('/') or '/') + suffix

    def is_title(self, url):
        return bool(self.TITLE_PATH.fullmatch(urlsplit(url).path) and
                    (not self.profile.title_query or param(url, self.profile.title_query)))

    def is_chapter(self, url):
        return bool(self.CHAPTER_PATH.fullmatch(urlsplit(url).path) and
                    (not self.profile.chapter_query or any(param(url, key) for key in self.profile.chapter_query.split('|'))))

    def document(self, http, url):
        if not self.site_link(url):
            raise SourceError('Некорректный адрес архива комикса.')
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        target = self.site_link(final)
        if not target:
            raise SourceError('Архив комикса перенаправил на другой источник.')
        if self.profile.html_redirect and (match := re.search(self.profile.html_redirect, raw)):
            redirect = self.site_link(match[1], target)
            if not redirect or redirect == target:
                raise SourceError('Некорректное перенаправление архива комикса.')
            if param(redirect, 'm') == '1':
                redirect = query_url(redirect, m=0)
            raw, final, _ = http.document(redirect, headers={'Referer': target})
            target = self.site_link(final)
            if not target or re.search(self.profile.html_redirect, raw):
                raise SourceError('Источник не завершил перенаправление архива.')
        return BeautifulSoup(raw, 'html.parser'), target

    def json(self, http, path):
        url = self.ROOT + path
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'}, action='webcomic-json')
        if (urlsplit(final).hostname != self.hostname or urlsplit(final).path != urlsplit(url).path):
            raise SourceError('Источник перенаправил запрос данных на другой маршрут.')
        try:
            return json.loads(raw)
        except ValueError:
            raise SourceError('Источник вернул некорректные данные комикса.') from None

    def work_rows(self, http, page, query, sort, tag):
        if self.profile.browse:
            return self.profile.browse(self, http, page, query, sort, tag)
        return (self.profile.works if page == 1 and not tag else ()), False

    def row(self, work, url, doc=None):
        title, cover, description, authors = work.title, work.cover, work.description, [work.author]
        genres, tags = [], []
        if doc is not None:
            p = self.profile
            found = image_from(doc.select_one(p.cover_selector), url) if p.cover_selector else image_url(meta(doc, 'image'), url)
            cover = found or cover
            description = (selected_text(doc, p.description_selector) if p.description_selector else meta(doc, 'description')) or description
            if p.title_selector:
                title = selected_text(doc, p.title_selector) or title
            if p.author_selector:
                authors.extend(node_text(node) for node in doc.select(p.author_selector))
            if p.genres_selector:
                genres = unique(node_text(node) for node in doc.select(p.genres_selector))
            if p.tag_selector:
                tags = unique(node_text(node) for node in doc.select(p.tag_selector))
        href = self.reader_url(url)
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{self.title_identity(url)}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME, 'kind': 'manga',
                'format': 'comic', 'language': self.LANGUAGE, 'title': title[:500], 'aliases': unique([title, *work.aliases]),
                'url': href, 'sourceUrl': href, 'cover': image_url(cover, url), 'description': description[:12000],
                'genres': genres, 'tags': tags, 'authors': unique(authors), 'sourceOnly': True, 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога комикса.')
        query = query.strip()[:160]
        works, more = self.work_rows(http, page, query, sort, tag)
        rows = {}
        for work in works:
            url = self.site_link(work.path or '/')
            if not url or not self.is_title(url):
                continue
            if not self.profile.browse and query and not any(query.casefold() in name.casefold() for name in (work.title, *work.aliases)):
                continue
            row = self.row(work, url)
            rows[row['id']] = row
        return list(rows.values()), more

    def vocabulary(self, http):
        return []

    def saved_title_url(self, value):
        if not value:
            return ''
        key = self.title_identity(value)
        alias = self.profile.legacy_title.get(key)
        return self.site_link(alias) if alias else value

    def work(self, http, url):
        key = self.title_identity(url)
        works = self.profile.works
        if self.profile.browse:
            works, _ = self.work_rows(http, 1, '', 'popular', '')
        return next((work for work in works if self.title_identity(self.site_link(work.path or '/')) == key), None)

    def details(self, http, value):
        url = self.saved_title_url(self.site_link(value))
        work = self.work(http, url) if self.is_title(url) else None
        if work is None:
            raise SourceError('Архив не содержит этот тайтл.')
        doc = self.document(http, self.site_link(work.archive or url))[0] if self.profile.enrich else None
        return self.row(work, url, doc)

    def archive(self, http, work, url):
        spec = self.profile.archive
        if spec is None:
            raise SourceError('Источник не предоставил оглавление комикса.')
        archive = self.site_link(work.archive or url)
        doc, final = self.document(http, archive)
        return self.archive_rows(http, spec, doc, final)

    def archive_rows(self, http, spec, doc, final):
        rows, visited = [], set()
        more = False
        for _ in range(MAX_ARCHIVE_PAGES):
            visited.add(final)
            for node in doc.select(spec.selector):
                link = node.get(spec.href, '')
                if spec.query_key:
                    link = (spec.query_path or urlsplit(final).path) + '?' + urlencode({spec.query_key: link}) if link else ''
                elif link and spec.prefix:
                    link = spec.prefix + link.lstrip('/')
                target = self.site_link(link, final)
                if not target or not self.is_chapter(target):
                    continue
                title = selected_text(node, spec.title)
                found = re.search(spec.number, target) if spec.number else None
                date = selected_text(node, spec.date) if spec.date else ''
                rows.append((target, title, numeric(found[1]) if found else None, release_date(date, spec.date_format)))
                if len(rows) >= MAX_EPISODES:
                    return rows[::-1] if spec.reverse else rows, True
            nxt = doc.select_one(spec.next_page) if spec.next_page else None
            if not nxt:
                more = False
                break
            more = True
            target = self.site_link(nxt.get('href'), final)
            if not target or target in visited:
                raise SourceError('Источник вернул циклическую пагинацию архива.')
            doc, final = self.document(http, target)
        return rows[::-1] if spec.reverse else rows, more

    def chapter_rows(self, http, work, title):
        load = self.profile.chapters or Webcomic.archive
        rows, truncated = load(self, http, work, title)
        return self.episodes(rows), truncated or len(rows) > MAX_EPISODES

    def episodes(self, rows):
        unique_rows = {}
        for url, name, number, date in rows:
            target = self.site_link(url)
            if target and self.is_chapter(target):
                unique_rows.setdefault(target, (name, number, date))
        return [self.episode(url, name, number if number is not None else index, date)
                for index, (url, (name, number, date)) in enumerate(unique_rows.items(), 1) if index <= MAX_EPISODES]

    def episode(self, target, title, number, date=''):
        return {'url': self.reader_url(target), 'title': title or f'Страница {number}',
                'number': number, 'season': 1, 'language': self.LANGUAGE, 'publishedAt': date}

    def images(self, doc, final):
        spec = self.profile.reader
        images = []
        for node in doc.select(spec.selector):
            if spec.attrs:
                url = next((val for attr in spec.attrs if (val := image_url(node.get(attr), final))), '')
            else:
                url = image_from(node, final)
            if not url:
                continue
            parts = urlsplit(url)
            if spec.exclude_crop and 'cropped-' in parts.path:
                continue
            if spec.image_hosts and not any(parts.hostname == host or parts.hostname.endswith('.' + host)
                                             for host in spec.image_hosts):
                continue
            images.append(url)
        return list(dict.fromkeys(images))

    def pages(self, http, url):
        doc, final = self.document(http, url)
        if not self.is_chapter(final):
            raise SourceError('Источник перенаправил запрос на другую главу.')
        spec = self.profile.reader
        note = doc.select_one(spec.notes) if spec.notes else None
        notes = str(note.get(spec.notes_attr, '')) if note and spec.notes_attr else node_text(note)
        name = selected_text(doc, 'h1, .comic-title')
        return name, self.images(doc, final), notes

    def stored_target(self, value):
        if not isinstance(value, str) or not value:
            return ''
        if self.profile.legacy_chapter_prefix and re.fullmatch(r'[\w.-]{1,200}', value):
            value = self.profile.legacy_chapter_prefix + value
        return self.site_link(value)

    def saved_chapter_url(self, value, _slug, _root):
        return self.stored_target(value)

    def saved_chapter_matches(self, target, title):
        if not self.is_title(title) or not self.is_chapter(target):
            return False
        if len(self.profile.works) == 1 and not self.profile.browse:
            return True
        http = PublicHttp(timeout=(3, 6))
        try:
            work = self.work(http, title)
            if work is None:
                return False
            rows, _ = self.chapter_rows(http, work, title)
            key = self.title_identity(target)
            return any(self.title_identity(self.site_link(row['url'])) == key for row in rows)
        finally:
            http.close()

    def inspect(self, value, http):
        url = self.site_link(value)
        if not url:
            raise SourceError('Некорректная ссылка на комикс.')
        title = self.saved_title_url(url)
        work = self.work(http, title) if self.is_title(title) else None
        pages, notes, truncated = [], '', False
        if work is not None:
            if self.profile.archive and not work.archive and self.profile.enrich:
                doc, final = self.document(http, title)
                row = self.row(work, title, doc)
                raw, truncated = self.archive_rows(http, self.profile.archive, doc, final)
                episodes = self.episodes(raw)
            else:
                row = self.details(http, title) if self.profile.enrich else self.row(work, title)
                episodes, truncated = self.chapter_rows(http, work, title)
        elif self.is_chapter(url):
            if self.profile.title_for:
                title = self.site_link(self.profile.title_for(self, url))
                work = self.work(http, title)
                if work is None:
                    raise SourceError('Источник не предоставил тайтл этой главы.')
            elif len(self.profile.works) == 1 and not self.profile.browse:
                work = self.profile.works[0]
                title = self.site_link(work.path or '/')
            if work is None:
                work = Work(url, self.NAME)
                title = url
            row = self.row(work, title)
            name, pages, notes = (self.profile.pages or Webcomic.pages)(self, http, url)
            if not 1 <= len(pages) <= MAX_PAGES or not all(pages):
                raise SourceError('Источник не предоставил полный список страниц открытой главы.')
            episodes = [self.episode(url, name, 0)]
        else:
            raise SourceError('Архив не содержит этот тайтл или главу.')
        return {**row, 'url': self.reader_url(url), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': truncated, 'authorNotes': notes,
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [],
                'dubs': [], 'releases': [], 'translations': []}


def adapters():
    from manga_webcomic_profiles import PROFILES
    return tuple(Webcomic(identity, profile) for identity, profile in PROFILES)
