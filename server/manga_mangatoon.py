"""MangaToon localized catalogues and free episodes from the publisher's HTML."""

import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_global_dbm_profiles import TOON
from manga_madara import OriginPace, SEGMENT, image_from, node_text
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceAccessError, SourceError, public_url


ROOT = 'https://mangatoon.mobi'
HOST = 'mangatoon.mobi'
ID = r'[1-9][0-9]{0,13}'
IDENTITY = re.compile(ID)
LANGS = {'zh': 'cn', 'pt-BR': 'pt'}
MIRRORS = {'fr': 'fr.mangatoon.mobi', 'vi': 'mangatooncom.vn'}
EPISODES = re.compile(r"""\bdata\s*=\s*JSON\.parse\(\s*'((?:\\.|[^'\\])*)'\s*\)""")
JS_ESCAPE = re.compile(r'\\(?:u([0-9A-Fa-f]{4})|x([0-9A-Fa-f]{2})|([^\n\r]))')
POSTER = re.compile(r'(\.jpg)-poster.*\d+$', re.I)
ONGOING = {'连载', 'on going', 'sedang berlangsung', 'tiếp tục cập nhật', 'en proceso', 'atualizando', 'เซเรียล', 'en cours', '連載中'}
COMPLETED = {'完结', 'completed', 'tamat', 'đã full', 'terminada', 'concluído', 'จบ', 'fin'}
PACE = OriginPace()
PACE.interval = 1


def unescape(match):
    if code := match[1] or match[2]:
        return chr(int(code, 16))
    char = match[3]
    return {'n': '\n', 'r': '\r', 't': '\t'}.get(char, char)


def episode_data(doc):
    for script in doc.find_all('script'):
        if match := EPISODES.search(script.string or ''):
            try:
                rows = json.loads(JS_ESCAPE.sub(unescape, match[1]))
            except (ValueError, RecursionError):
                raise SourceError('MangaToon изменил формат списка глав.') from None
            if isinstance(rows, list) and all(isinstance(item, dict) for item in rows):
                return rows
    raise SourceError('MangaToon не предоставил список глав.')


class MangaToon:
    ROOT = ROOT
    NAME = 'MangaToon (Limited)'
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, language):
        self.SOURCE_ID, self.LANGUAGE = sid, language
        self.locale = LANGS.get(language, language)
        self.TITLE_PATH = re.compile(rf'/{self.locale}/((?:detail/{ID})|{SEGMENT})/?')
        self.CHAPTER_PATH = re.compile(rf'/{self.locale}/watch/({ID})/({ID})/?')
        self.hosts = {HOST, 'www.' + HOST, MIRRORS.get(language, HOST)}

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            source, raw = split_reader_url(urljoin(base or ROOT + '/' + self.locale + '/', value))
            url = urlsplit(raw)
            if source not in (None, self.SOURCE_ID) or url.scheme != 'https' or url.netloc not in self.hosts:
                return ''
            path = url.path
            if url.netloc == MIRRORS.get(self.LANGUAGE) and not path.startswith('/' + self.locale + '/'):
                path = '/' + self.locale + path
            if path == '/' or path.startswith('/' + self.locale + '/'):
                return public_url(urlunsplit(url._replace(netloc=HOST, path=path)), resolve_dns=False)
        except (ValueError, SourceError):
            pass
        return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def title_url(self, identity):
        return ROOT + f'/{self.locale}/detail/{identity}'

    def title_id(self, value):
        url = urlsplit(self.site_link(value))
        title = self.TITLE_PATH.fullmatch(url.path)
        if not title:
            return ''
        if title[1].startswith('detail/'):
            return title[1].split('/')[1]
        try:
            ids = parse_qs(url.query, keep_blank_values=True, max_num_fields=12).get('content_id', [])
        except ValueError:
            return ''
        return ids[0] if len(ids) == 1 and IDENTITY.fullmatch(ids[0]) else ''

    def document(self, http, value):
        PACE.wait(http.deadline)
        raw, final, _ = http.document(value, headers={'Referer': ROOT + '/' + self.locale + '/'})
        target = self.site_link(final)
        if not target:
            raise SourceError('MangaToon перенаправил запрос на другой домен.')
        return BeautifulSoup(raw, 'html.parser'), target, final

    def row(self, identity, title, cover):
        target = self.reader_url(self.title_url(identity))
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{identity}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
                'title': title, 'language': self.LANGUAGE, 'aliases': unique([title]),
                'kind': 'manga', 'format': 'manhua', 'readingMode': 'scroll',
                'url': target, 'sourceUrl': target, 'cover': POSTER.sub(r'\1', cover),
                'genres': [], 'tags': [], 'ids': {}, 'sourceOnly': True}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or tag and not IDENTITY.fullmatch(tag):
            raise SourceError('Некорректные параметры каталога MangaToon.')
        if query := query.strip()[:160]:
            if page != 1:
                return [], False
            path, args = 'search', {'word': query}
            selector, title_css = 'div.comics-result div.recommend-item', 'div.recommend-comics-title'
        else:
            mode = 'tags/' + tag if tag else 'new' if sort == 'updated' else 'comic' if self.LANGUAGE == 'pt-BR' else 'hot'
            path, args = 'genre/' + mode, {'type': 1, 'page': page-1}
            selector, title_css = 'div.genre-content div.items a', 'div.content-title'
        doc, _, final = self.document(http, ROOT + f'/{self.locale}/{path}?' + urlencode(args))
        rows = {}
        for node in doc.select(selector):
            anchor = node if node.name == 'a' else node.select_one('a[href]')
            identity = self.title_id(self.site_link(anchor.get('href'), final)) if anchor else ''
            name = node_text(node.select_one(title_css))
            if identity and name:
                rows.setdefault(identity, self.row(identity, name, image_from(node.select_one('img'), final)))
        return list(rows.values()), bool(rows and not query and doc.select_one('span.next'))

    def vocabulary(self, http):
        doc, _, final = self.document(http, ROOT + f'/{self.locale}/genre/comic?type=1&page=0')
        terms = {}
        for anchor in doc.select('a[href*="/genre/tags/"]'):
            link = self.site_link(anchor['href'], final)
            match = re.fullmatch(rf'/{self.locale}/genre/tags/({ID})/?', urlsplit(link).path)
            label = node_text(anchor)
            if match and label:
                terms.setdefault(match[1], {'sourceId': match[1], 'label': label, 'category': 'tag'})
        return list(terms.values())

    def work(self, http, identity):
        doc, target, final = self.document(http, self.title_url(identity))
        title = node_text(doc.select_one('h1.detail-title, h1'))
        if self.title_id(target) != identity or not title:
            raise SourceError('MangaToon вернул другую карточку.')
        cover = image_from(doc.select_one('div.detail-img img'), final)
        author = node_text(doc.select_one('div.detail-author-name span'))
        status = node_text(doc.select_one('div.detail-status')).lower()
        genres = unique(node_text(doc.select_one('div.detail-tags-info')).split('/'))
        row = self.row(identity, title, '' if 'cartoon-big-images' in cover else cover)
        row.update(tags=genres, authors=unique([author.split(': ', 1)[-1]]),
                   status='ongoing' if status in ONGOING else 'completed' if status in COMPLETED else '',
                   description='\n\n'.join(node_text(p) for p in doc.select('div.detail-description-short p'))[:12000])
        return row, doc

    def details(self, http, value):
        identity = self.title_id(value)
        if not identity:
            raise SourceError('Некорректная ссылка на тайтл MangaToon.')
        return self.work(http, identity)[0]

    def chapter_url(self, title, part):
        return ROOT + f'/{self.locale}/watch/{title}/{part}'

    def chapters(self, doc, title):
        rows = {}
        for item in reversed(episode_data(doc)):
            identity = str(item.get('id', ''))
            number, opened = item.get('weight'), item.get('open_at')
            if item.get('is_fee') in (True, 'true', '1') or not IDENTITY.fullmatch(identity):
                continue
            target = self.reader_url(self.chapter_url(title, identity))
            rows.setdefault(identity, {'url': target, 'title': item.get('title') or 'Глава', 'language': self.LANGUAGE,
                                      'number': number if type(number) in (int, float) and 0 <= number < 100000 else 0,
                                      'season': 1, 'publishedAt': opened[:10] if isinstance(opened, str) else ''})
        return list(rows.values())

    def inspect(self, value, http):
        target = self.site_link(value)
        chapter = self.CHAPTER_PATH.fullmatch(urlsplit(target).path)
        identity = chapter[1] if chapter else self.title_id(target)
        if not identity:
            raise SourceError('Некорректная ссылка на читалку MangaToon.')
        row, doc = self.work(http, identity)
        episodes, pages = self.chapters(doc, identity), []
        if chapter:
            canonical = self.reader_url(self.chapter_url(*chapter.groups()))
            episodes = [item for item in episodes if item['url'] == canonical]
            if len(episodes) != 1:
                raise SourceAccessError('MangaToon не предоставил эту главу для открытого чтения.')
            read, link, final = self.document(http, self.chapter_url(*chapter.groups()))
            if urlsplit(link).path.rstrip('/') != urlsplit(target).path.rstrip('/'):
                raise SourceError('MangaToon вернул другую главу.')
            pages = [image_from(node, final) for node in read.select('div.pictures div img:first-child')]
            if not 1 <= len(pages) <= 500 or not all(pages):
                raise SourceAccessError('MangaToon не предоставил полный список страниц.')
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': False, 'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [],
                'translations': [], 'dubs': [], 'releases': []}

    def saved_title_url(self, value):
        identity = self.title_id(value)
        return self.title_url(identity) if identity else ''

    def saved_chapter_url(self, value, _slug, root):
        return self.site_link(value, root).rstrip('/')

    def saved_chapter_matches(self, chapter, title):
        item = self.CHAPTER_PATH.fullmatch(urlsplit(chapter).path)
        return bool(item and item[1] == self.title_id(title))


SOURCES = tuple(MangaToon(*profile) for profile in TOON)
