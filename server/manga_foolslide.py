"""FoOlSlide catalogues and reader payloads used by the Keiyoushi extension."""

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString

from manga_madara import CHAPTER_NUMBER, SEGMENT, VOLUME_NUMBER, image_from, image_url, node_text, release_date
from manga_source_tags import from_html, unique
from source_parser import SourceError, public_url


TITLE_PATH = re.compile(rf'/series/({SEGMENT})/?')
CHAPTER_PATH = re.compile(rf'/read/({SEGMENT})(?:/{SEGMENT}){{1,8}}/?')
PAGES = re.compile(r'\bvar\s+pages\s*=\s*(?=\[)')
TOC = 'div.group div.element, div.list div.element'


def chapter_date(value):
    value = value.partition(', ')[2] if re.match(r'^[A-Za-z ]+, ', value) else value
    lowered = value.casefold()
    if lowered.startswith(('today', 'yesterday', 'tomorrow')):
        days = 1 if lowered.startswith('tomorrow') else -1 if lowered.startswith('yesterday') else 0
        return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()
    ordinal = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', value).replace(',', '')
    if re.fullmatch(r'\d{1,2} [A-Za-z]+', ordinal):
        ordinal += ' ' + str(datetime.now(timezone.utc).year)
    return (release_date(ordinal, '%d %B %Y') or release_date(value, '%Y.%m.%d')
            or release_date(re.sub(r'\b(wk|hr|min|sec|yr)(s?)\b',
                                   lambda m: {'wk': 'week', 'hr': 'hour', 'min': 'minute',
                                              'sec': 'second', 'yr': 'year'}[m[1]] + m[2], lowered), '%Y.%m.%d'))


class FoolSlide:
    LANGUAGE = 'en'
    IS_NSFW = False
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH

    def __init__(self, sid, name, root):
        self.SOURCE_ID, self.NAME, self.ROOT = sid, name, root
        self.host = urlsplit(root).netloc

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            parts = urlsplit(urljoin(base or self.ROOT + '/', value))
            if parts.netloc == self.host and parts.scheme == 'https':
                return public_url(self.ROOT + parts.path, resolve_dns=False)
        except (SourceError, ValueError):
            pass
        return ''

    def document(self, http, target, form=None):
        target = self.site_link(target)
        if not target:
            raise SourceError('Некорректный адрес FoOlSlide.')
        options = {'method': 'POST', 'data': form} if form else {}
        html, final, _ = http.document(target, headers={'Origin': self.ROOT, 'Referer': self.ROOT + '/'}, **options)
        final = self.site_link(final)
        if not final:
            raise SourceError('FoOlSlide перенаправил запрос на другой домен.')
        return BeautifulSoup(html, 'html.parser'), final

    def row(self, slug, title, cover=''):
        target = self.ROOT + '/series/' + slug + '/'
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'url': target, 'sourceUrl': target, 'sourceOnly': True, 'kind': 'manga',
                'title': title, 'aliases': [title], 'cover': cover, 'language': self.LANGUAGE,
                'genres': [], 'tags': [], 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or tag:
            raise SourceError('Некорректные параметры каталога FoOlSlide.')
        query = query.strip()[:160]
        if query:
            if page != 1:
                return [], False
            doc, final = self.document(http, '/search/', {'search': query})
        else:
            section = 'latest' if sort == 'updated' else 'directory'
            doc, final = self.document(http, f'/{section}/{page}/')
        results = {}
        for group in doc.select('div.group'):
            link = group.select_one('a[title][href]')
            match = TITLE_PATH.fullmatch(urlsplit(self.site_link(link['href'], final)).path) if link else None
            title = node_text(link)
            if match and title:
                cover = image_from(group.select_one('img'), final).replace('/thumb_', '/')
                results.setdefault(match[1], self.row(match[1], title, cover))
        return list(results.values()), bool(not query and results and doc.select_one('div.next'))

    def vocabulary(self, http):
        return []

    def details(self, http, value):
        link = self.site_link(value)
        match = TITLE_PATH.fullmatch(urlsplit(link).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл FoOlSlide.')
        return self.work(http, match[1])[0]

    def work(self, http, slug):
        doc, final = self.document(http, '/series/' + slug + '/', {'adult': 'true'})
        match = TITLE_PATH.fullmatch(urlsplit(final).path)
        if not match or match[1] != slug:
            raise SourceError('FoOlSlide вернул другой тайтл.')
        info = {}
        headings = {'author': 'authors', 'autore': 'authors', 'artist': 'artists',
                    'synopsis': 'description', 'description': 'description', 'trama': 'description'}
        for label in doc.select('div.info b'):
            sibling = label.next_sibling
            value = str(sibling).strip().lstrip(':').strip() if isinstance(sibling, NavigableString) else ''
            if value:
                for key, field in headings.items():
                    if key in node_text(label).casefold():
                        info.setdefault(field, value)
        title = node_text(doc.select_one('.title h1, .title h2, div.title, h1, .tbtitle')) or slug.replace('_', ' ')
        cover = image_from(doc.select_one('div.thumbnail img, table.thumb img'), final)
        return {**self.row(slug, title, cover), **from_html(doc), 'description': info.get('description', '')[:12000],
                'authors': unique([info.get('authors')]), 'artists': unique([info.get('artists')])}, doc, final

    def chapters(self, doc, final, slug):
        entries = {}
        for entry in doc.select(TOC):
            link = entry.select_one('a[title][href]')
            target = self.site_link(link['href'], final).rstrip('/') + '/' if link else ''
            chapter = CHAPTER_PATH.fullmatch(urlsplit(target).path)
            if not chapter or chapter[1] != slug:
                continue
            title = node_text(link)
            number = CHAPTER_NUMBER.search(title)
            volume = VOLUME_NUMBER.search(title)
            entries.setdefault(target, {'url': target, 'title': title, 'language': self.LANGUAGE,
                                        'number': float(number[1].replace(',', '.')) if number else 0,
                                        'season': int(volume[1]) if volume else 1,
                                        'publishedAt': chapter_date(node_text(entry.select_one('div.meta_r')))})
        return list(entries.values())

    def pages(self, http, target):
        doc, final = self.document(http, target, {'adult': 'true'})
        if final.rstrip('/') != target.rstrip('/'):
            raise SourceError('FoOlSlide вернул другую главу.')
        for script in doc.find_all('script'):
            match = PAGES.search(script.string or '')
            if not match:
                continue
            try:
                data, _ = json.JSONDecoder().raw_decode(script.string[match.end():])
            except (ValueError, RecursionError):
                break
            if isinstance(data, list) and 1 <= len(data) <= 500:
                found = [image_url(page.get('url'), final) if isinstance(page, dict) else '' for page in data]
                if all(found):
                    return found
        raise SourceError('FoOlSlide не предоставил полный список страниц.')

    def inspect(self, value, http):
        target = self.site_link(value).rstrip('/') + '/'
        path = urlsplit(target).path
        title, chapter = TITLE_PATH.fullmatch(path), CHAPTER_PATH.fullmatch(path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку FoOlSlide.')
        slug = (title or chapter)[1]
        row, doc, final = self.work(http, slug)
        episodes, pages = self.chapters(doc, final, slug), []
        if chapter:
            episodes = [entry for entry in episodes if entry['url'] == target]
            if len(episodes) != 1:
                raise SourceError('Глава отсутствует в оглавлении FoOlSlide.')
            pages = self.pages(http, target)
        return {**row, 'url': target, 'episodes': episodes, 'pages': pages, 'available': bool(episodes),
                'truncated': False, 'dubs': [], 'releases': [], 'translations': [],
                'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({item['season'] for item in episodes})]}

    def saved_chapter_url(self, value, slug, root):
        return self.site_link(value, root)


SOURCES = (
    FoolSlide('4722346859737894698', 'Death Toll Scans', 'https://reader.deathtollscans.net'),
    FoolSlide('3478835885302345699', 'Mangatellers', 'https://reader.mangatellers.gr'),
)
