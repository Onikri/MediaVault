"""Localized SayManhwa catalogue, title pages and public chapters."""

import re
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_global_dbm_profiles import SAY
from manga_madara import OriginPace, SEGMENT, image_from, node_text
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceAccessError, SourceError, public_url


ROOT = 'https://saymanhwa.net'
LANGS = {'pt': 'pt-br', 'zh': 'zh-cn', 'zh-Hans': 'zh-cn', 'zh-Hant': 'zh-tw'}
STATUSES = {
    'ar': ('مستمر', 'مكتمل'), 'de': ('laufend', 'abgeschlossen'), 'es': ('en curso', 'completado'),
    'fil': ('tuloy-tuloy|tuloy tuloy', 'tapos'), 'fr': ('en cours', 'terminé|termine'),
    'id': ('berjalan', 'selesai'), 'ja': ('連載中', '完結'), 'pt-br': ('em andamento', 'concluído|concluido'),
    'th': ('กำลังดำเนิน', 'จบแล้ว'), 'vi': ('đang tiến hành|đang', 'hoàn thành'),
    'zh-cn': ('连载中|連載中', '已完结|已完結|完结|完結'),
    'zh-tw': ('连载中|連載中', '已完结|已完結|完结|完結'),
}
PACE = OriginPace()
PACE.interval = .35


class SayManhwa:
    ROOT = ROOT
    NAME = 'SayManhwa'
    IS_NSFW = False
    scoped_urls = True
    index_sort = 'updated'

    def __init__(self, sid, language):
        self.SOURCE_ID, self.LANGUAGE = sid, language
        self.locale = LANGS.get(language, language)
        prefix = '/' + self.locale
        self.TITLE_PATH = re.compile(rf'{prefix}/series/({SEGMENT})/?')
        self.CHAPTER_PATH = re.compile(rf'{prefix}/series/({SEGMENT})/(chapter-{SEGMENT})/?')

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or ROOT + f'/{self.locale}/', value))
            parts = urlsplit(raw)
            if selected in (None, self.SOURCE_ID) and parts.scheme == 'https' and parts.netloc == 'saymanhwa.net':
                if parts.path == '/' or parts.path.startswith('/' + self.locale + '/'):
                    return public_url(raw, resolve_dns=False)
        except (ValueError, SourceError):
            pass
        return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def document(self, http, url):
        PACE.wait(http.deadline)
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'})
        final = self.site_link(final)
        if not final or urlsplit(url).path.rstrip('/') != urlsplit(final).path.rstrip('/'):
            raise SourceError('SayManhwa перенаправил запрос на другой маршрут.')
        return BeautifulSoup(raw, 'html.parser'), final

    def row(self, link, title, cover):
        slug = self.TITLE_PATH.fullmatch(urlsplit(link).path)[1]
        url = self.reader_url(ROOT + f'/{self.locale}/series/' + slug)
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME, 'sourceOnly': True,
                'url': url, 'sourceUrl': url, 'kind': 'manga', 'language': self.LANGUAGE,
                'title': title, 'aliases': unique([title]), 'cover': cover, 'genres': [], 'tags': [],
                'format': 'manhwa', 'readingMode': 'scroll', 'ids': {}}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or tag and not re.fullmatch(SEGMENT, tag):
            raise SourceError('Некорректные параметры каталога SayManhwa.')
        params = {'page': page} if page > 1 else {}
        if query := query.strip()[:160]:
            params['q'] = query
        if tag:
            params['genre'] = tag
        route = 'series' if query or tag else 'latest' if sort == 'updated' else 'popular'
        url = ROOT + f'/{self.locale}/{route}'
        doc, final = self.document(http, url + ('?' + urlencode(params) if params else ''))
        rows = []
        for item in doc.select('article.series-card'):
            anchor = item.select_one('.series-card-body h2 a[href]')
            title = node_text(anchor)
            link = self.site_link(anchor.get('href'), final) if anchor else ''
            if title and self.TITLE_PATH.fullmatch(urlsplit(link).path):
                rows.append(self.row(link, title, image_from(item.select_one('.series-card-cover img, a img'), final)))
        return rows, bool(rows and doc.select_one('nav.pagination span + a'))

    def vocabulary(self, http):
        doc, _ = self.document(http, ROOT + f'/{self.locale}/series')
        return [{'label': node_text(node), 'sourceId': value, 'category': 'genre'}
                for node in doc.select('select[name=genre] option[value]')
                if re.fullmatch(SEGMENT, (value := node['value'])) and node_text(node)]

    def details(self, http, value):
        title = self.TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not title:
            raise SourceError('Некорректная ссылка на тайтл SayManhwa.')
        return self.work(http, title[1])[0]

    def work(self, http, slug):
        url = ROOT + f'/{self.locale}/series/' + slug
        doc, final = self.document(http, url)
        title = node_text(doc.select_one('h1'))
        if not title:
            raise SourceError('SayManhwa не предоставил название карточки.')
        row = self.row(final, title, image_from(doc.select_one('.series-v72-cover img'), final))
        creators = doc.select('.series-v72-meta-row strong.series-creator-links')
        status = node_text(doc.select_one('.series-v72-meta-pair > div:first-child strong')).casefold()
        ongoing, completed = STATUSES.get(self.locale, ('ongoing', 'completed'))
        row.update(authors=unique(node_text(node) for node in creators[0].select('a')) if creators else [],
                   artists=unique(node_text(node) for node in creators[1].select('a')) if len(creators) > 1 else [],
                   status='ongoing' if any(word in status for word in ongoing.split('|'))
                   else 'completed' if any(word in status for word in completed.split('|')) else '',
                   genres=unique(node_text(node) for node in doc.select('a[href*="/genres/"]')),
                   description=node_text(doc.select_one('.series-seo-context p'))[:12000])
        entries = {}
        for anchor in doc.select('.series-v72-chapter-list > a.series-v72-chapter-row[href]'):
            target = self.site_link(anchor['href'], final)
            match = self.CHAPTER_PATH.fullmatch(urlsplit(target).path)
            if not match or match[1] != slug:
                continue
            number = re.match(r'chapter-(\d{1,5}(?:[.-]\d{1,3})?)(?:$|-)', match[2])
            label = node_text(anchor.select_one('.series-chapter-number-text'))
            date = anchor.select_one('time[datetime]')
            clean = self.reader_url(target.rstrip('/'))
            entries.setdefault(clean, {'url': clean, 'title': label or 'Глава',
                                       'number': float(number[1].replace('-', '.')) if number else 0,
                                       'language': self.LANGUAGE, 'season': 1,
                                       'locked': anchor.select_one('.chapter-mini-lock') is not None,
                                       'publishedAt': date['datetime'][:10] if date else ''})
        return row, list(entries.values())

    def inspect(self, value, http):
        target = self.site_link(value).rstrip('/')
        path = urlsplit(target).path
        title, chapter = self.TITLE_PATH.fullmatch(path), self.CHAPTER_PATH.fullmatch(path)
        if not (title or chapter):
            raise SourceError('Некорректная ссылка на читалку SayManhwa.')
        row, episodes = self.work(http, (title or chapter)[1])
        pages = []
        if chapter:
            episodes = [episode for episode in episodes if episode['url'] == self.reader_url(target)]
            if len(episodes) != 1:
                raise SourceError('Глава отсутствует в оглавлении SayManhwa.')
            if episodes[0]['locked']:
                raise SourceAccessError('SayManhwa ограничивает доступ к главе.')
            doc, final = self.document(http, target)
            pages = [image_from(node, final) for node in doc.select('.reader-pages img')]
            if not 1 <= len(pages) <= 500 or not all(pages):
                raise SourceError('SayManhwa не предоставил полный список страниц.')
        return {**row, 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': any(not item['locked'] for item in episodes), 'truncated': False,
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [], 'translations': [],
                'dubs': [], 'releases': []}

    def saved_chapter_url(self, value, slug, root):
        return self.site_link(value, root).rstrip('/')


SOURCES = tuple(SayManhwa(*profile) for profile in SAY)
