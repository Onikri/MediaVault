"""Toonz catalogue, chapter JSON and React Flight reader shared by three hosts."""

import re
from urllib.parse import urlsplit

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import number, picture
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceError


PROFILES = (
    ('225310046014902430', 'Toonz', 'en', 'https://toonz.to', False),
    ('3603837449597882885', 'Toonx', 'en', 'https://toonx.to', True),
    ('3627030858599443012', 'LewdManhwa', 'en', 'https://lewdmanhwa.com', True),
)
TYPES = {'toonz.to': ('manhwa', 'manhua', 'manga', 'western'),
         'toonx.to': ('comic', 'adult'), 'lewdmanhwa.com': ('webtoon',)}
COMIC_ID = re.compile(r'comicId["\\]*\s*:\s*(\d{1,18})(?!\d)')
CHAPTERS_API = re.compile(r'/api/comics/[0-9]{1,18}/chapters')


def public_api(host, path, query):
    return host in TYPES and not query and (path == '/api/genres' or bool(CHAPTERS_API.fullmatch(path)))


def chapter_images(raw):
    models = flight_models(flight_stream(raw))
    for model in models.values():
        for row in dictionaries(model):
            if 'images' not in row:
                continue
            entries = resolve_fields(row['images'], models, [60000])
            if isinstance(entries, list) and entries and all(
                    isinstance(item, dict) and isinstance(item.get('filename'), str) for item in entries):
                return entries
    return []


class Toonz(JsonSeries):
    def __init__(self, identity):
        kinds = '|'.join(TYPES[urlsplit(identity[3]).hostname])
        title = rf'(/(?:{kinds})/{SEGMENT})'
        super().__init__(identity, title + '/?', title + rf'/chapter/({SEGMENT})/?', interval=.55)

    def site_link(self, value, base=None):
        target = super().site_link(value, base)
        if not target:
            return ''
        parts = urlsplit(target)
        aliases = {'toonz.to': ('/manhua/', '/manhwa/'), 'toonx.to': ('/comic/', '/adult/')}
        before, after = aliases.get(self.hostname, ('', ''))
        if before and parts.path.startswith(before):
            return target.replace(before, after, 1)
        return target

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + key if key else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        section = 'webtoons' if self.hostname == 'lewdmanhwa.com' else 'comics'
        if query:
            target = query_url(self.ROOT + '/search', q=query, page=page)
        elif not tag or re.fullmatch(SEGMENT, tag):
            target = query_url(self.ROOT + ('/genre/' + tag if tag else '/' + section),
                               sort='latest' if sort == 'updated' else 'popular', page=page)
        else:
            return [], False
        doc, final = self.document(http, target)
        for chunk in doc.select('div[hidden][id^="S:"]'):
            placeholder = doc.find(id='P:' + chunk['id'][2:])
            if placeholder:
                for item in list(chunk.contents):
                    placeholder.insert_before(item.extract())
                placeholder.decompose()
                chunk.decompose()
        rows = {}
        for cover in doc.select('img[data-cover][alt]'):
            ancestor = cover.find_parent('a', href=True)
            if not ancestor:
                ancestor = cover.find_parent(lambda node: node.find('a', href=True, recursive=False))
                ancestor = ancestor.find('a', href=True, recursive=False) if ancestor else None
            url = self.site_link(ancestor.get('href'), final) if ancestor else ''
            if self.is_title(url) and (title := cover.get('alt', '').strip()):
                rows[url] = self.record(url, title, picture(cover, final))
        more = any(param(a['href'], 'page') == str(page + 1) for a in doc.select('a[href]'))
        return list(rows.values()), more

    def vocabulary(self, http):
        data = self.json(http, self.ROOT + '/api/genres')
        return [{'key': slug, 'label': row['name'], 'kind': 'genre'} for row in data
                if isinstance(row, dict) and isinstance(row.get('name'), str)
                and isinstance(slug := row.get('slug'), str) and re.fullmatch(SEGMENT, slug)] if isinstance(data, list) else []

    def series(self, http, url):
        url = self.canonical(url)
        doc, final = self.title_document(http, url)
        title = node_text(doc.select_one('h1'))
        series_id = next((match[1] for script in doc.select('script')
                          if (match := COMIC_ID.search(script.string or ''))), '')
        if not title or not series_id:
            raise SourceError('Источник не предоставил идентификатор тайтла.')
        cover = picture(doc.select_one('img[data-cover], div.group img[src]'), final)
        description = node_text(doc.select_one('div.prose'))
        if not description and (meta := doc.select_one('meta[name="description"][content]')):
            description = meta['content'].strip()
        status = next((node_text(dt.find_next_sibling('dd')) for dt in doc.select('dt')
                       if node_text(dt).casefold() == 'status'), '').casefold()
        row = self.record(final, title, cover, description=description,
                          genres=[node_text(a) for a in doc.select('a[href^="/genre/"]')],
                          authors=[node_text(a) for a in doc.select('a[href^="/author/"]')],
                          status=status if status in {'ongoing', 'completed'} else '')
        data = self.json(http, f'{self.ROOT}/api/comics/{series_id}/chapters', final)
        chapters = data.get('chapters') if isinstance(data, dict) else None
        if not isinstance(chapters, list):
            raise SourceError('Источник изменил формат оглавления.')
        found = {}
        for item in chapters:
            if not isinstance(item, dict) or not isinstance(slug := item.get('slug'), str):
                continue
            slug = slug.removeprefix('chapter-')
            if not re.fullmatch(SEGMENT, slug):
                continue
            ordinal = str(item.get('chapterNumber') or '').removesuffix('.0')
            label = str(item.get('title') or '').strip()
            if not re.match(r'(?i)^(?:chapter\b|ch\.)', label):
                label = ('Chapter ' + (ordinal or slug) + (': ' + label if label else ''))
            target = final.rstrip('/') + '/chapter/' + slug
            found[target] = self.chapter(target, label, number(ordinal), str(item.get('date') or '').partition('T')[0])
        return row, self.order(found)

    def pages(self, http, url):
        raw, final, _ = http.document(url, headers={'Referer': self.title_for(url)})
        if not self.is_chapter(final) or self.chapter_identity(url) != self.chapter_identity(final):
            raise SourceError('Источник перенаправил читалку на другую главу.')
        entries = chapter_images(raw)
        if not entries:
            raw, final, _ = http.document(url, headers={'Referer': self.title_for(url), 'RSC': '1'},
                                         action='toonz-rsc')
            if self.chapter_identity(url) != self.chapter_identity(final):
                raise SourceError('Источник перенаправил данные другой главы.')
            entries = chapter_images(raw)
        pages = []
        for item in entries:
            path = item['filename'].lstrip('/')
            pieces = path.split('/')
            if not all(re.fullmatch(SEGMENT, piece) and piece not in {'.', '..'} for piece in pieces):
                raise SourceError('Некорректный файл страницы.')
            pages.append(image_url('/uploads/' + path, self.ROOT))
        return pages


SOURCES = tuple(Toonz(identity) for identity in PROFILES)


def rsc_route(host, path, query):
    return not query and any(host == item.hostname and item.CHAPTER_PATH.fullmatch(path) for item in SOURCES)
