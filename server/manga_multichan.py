"""Direct adapters for the Keiyoushi MultiChan layouts (Apache-2.0)."""

import re
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_hentaichan import HOSTS as HEN_MIRRORS, number, parse_pages, series_title
from manga_madara import OriginPace, image_url, node_text, release_date
from manga_multichan_terms import TERMS
from manga_source_tags import unique
from source_parser import SourceError, public_url


NAME = r'[1-9][0-9]{0,11}(?:-[^/?#\\]{1,250})?\.html'
TITLE_PATH = re.compile(rf'/manga/({NAME})')
CHAPTER_PATH = re.compile(rf'/(?:online|manga)/({NAME})')
RELATED_PATH = re.compile(rf'/related/({NAME})')
NEXT = 'a:-soup-contains("Вперед", "Вперёд")'


def path_of(value):
    return urlsplit(value).path


class MultiChan:
    LANGUAGE = 'ru'
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    index_sort = 'updated'

    def __init__(self, sid, name, root, adult, *, hen=False, aliases=()):
        self.SOURCE_ID, self.NAME, self.ROOT, self.IS_NSFW = sid, name, root, adult
        host = urlsplit(root).netloc
        self.hosts = HEN_MIRRORS if hen else frozenset({host, *aliases})
        self.hen = hen
        self.pace = OriginPace()
        self.pace.interval = 0.5

    def site_link(self, value, base=None):
        if isinstance(value, str) and value:
            try:
                target = urljoin(base or self.ROOT, value)
                parts = urlsplit(target)
                if parts.scheme in {'http', 'https'} and parts.netloc in self.hosts:
                    return public_url(urlunsplit(parts._replace(scheme='https')), resolve_dns=False)
            except (SourceError, ValueError):
                pass
        return ''

    def document(self, http, target, *, paths=None):
        from manga_sources import guard

        self.pace.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(target, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or path_of(final).rstrip('/') not in (paths or {path_of(target).rstrip('/')}):
            raise SourceError('MultiChan перенаправил запрос на другую страницу.')
        soup = BeautifulSoup(raw, 'html.parser')
        guard(soup)
        return raw, soup, final

    def row(self, url, label, cover=''):
        from manga_sources import title_aliases

        slug = TITLE_PATH.fullmatch(path_of(url))[1]
        ref = urlunsplit(urlsplit(url)._replace(query=''))
        alias = series_title(label) if self.hen else None
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID,
                'url': ref, 'sourceURL': ref, 'sourceUrl': ref, 'providerName': self.NAME,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'title': label[:500],
                'aliases': unique([*title_aliases(label), alias]), 'sourceOnly': True, 'ids': {},
                'kind': 'manga', 'language': self.LANGUAGE, 'cover': cover}

    def list_target(self, page, query, sort, tag):
        cursor = 20 * (page - 1)
        if query:
            return self.ROOT + '/?' + urlencode({'do': 'search', 'subaction': 'search', 'story': query, 'search_start': page})
        if tag:
            if tag not in TERMS[self.SOURCE_ID]:
                raise SourceError('MultiChan не распознал тег источника.')
            escaped = quote(tag, safe='')
            if self.hen:
                return f'{self.ROOT}/tags/{escaped}&sort=manga&n=favdesc?offset={cursor}'
            return f'{self.ROOT}/tags/{escaped}?offset={cursor}&status='
        if sort == 'updated':
            path = '/manga/newest' if self.hen else '/manga/new'
        else:
            path = '/mostfavorites'
        return self.ROOT + path + '?' + urlencode({'offset': cursor})

    def image(self, source, base):
        value = image_url(source, base)
        if value and self.hen:
            value = re.sub(r'manganew_thumbs[^/]*/manga', 'showfull_retina/manga', value)
            value = value.replace('_' + (urlsplit(base).hostname or ''), '_hentaichan.ru')
        return image_url(value, base)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога MultiChan.')
        _, soup, final = self.document(http, self.list_target(page, query.strip()[:160], sort, tag))
        rows = {}
        for card in soup.select('.content_row'):
            if query and self.hen and card.select_one('div.item:-soup-contains-own("Тип")'):
                continue
            anchor = card.select_one('h2 > a[href], a.title_link[href]')
            if not anchor:
                continue
            target = self.site_link(anchor.get('href'), final)
            label = (card.get('title') or node_text(anchor)).strip()
            if not TITLE_PATH.fullmatch(path_of(target)) or not label:
                continue
            img = card.select_one('img')
            cover = self.image(img.get('data-src') or img.get('src'), final) if img else ''
            rows.setdefault(path_of(target), self.row(target, label, cover))
        more = soup.select_one(NEXT) or query and soup.select_one('a:-soup-contains("Далее")')
        return list(rows.values()), bool(more)

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': slug, 'category': 'tag'} for slug, label in TERMS[self.SOURCE_ID].items()]

    def metadata(self, soup, final):
        label = node_text(soup.title).split(' »', 1)[0] or node_text(soup.select_one('a.title_top_a, h1'))
        if not label:
            raise SourceError('MultiChan не предоставил название произведения.')
        img = soup.select_one('img#cover')
        row = self.row(final, label, self.image(img.get('src'), final) if img else '')
        info = soup.select_one('#info_wrap')
        authors = info.select('tr:-soup-contains("Автор") .item2, div:-soup-contains("Автор") > .item2') if info else []
        kind = info.select_one('tr:-soup-contains("Тип") a, div:-soup-contains("Тип") a') if info else None
        desc = soup.select_one('#description')
        direct_text = desc.find(string=True, recursive=False) if desc else ''
        stamp = node_text(info).casefold()
        status = 'completed' if 'перевод завершен' in stamp else 'ongoing' if 'перевод продолжается' in stamp else ''
        row.update(authors=unique(node_text(author) for author in authors),
                   tags=unique(node_text(tag) for tag in soup.select('.sidetags ul a:last-child')),
                   genres=[], format=node_text(kind).casefold(), status=status,
                   description=str(direct_text or '').strip()[:12000])
        return row

    def details(self, http, value):
        target = self.site_link(value)
        if not TITLE_PATH.fullmatch(path_of(target)):
            raise SourceError('Некорректная ссылка на тайтл MultiChan.')
        _, soup, final = self.document(http, target)
        return self.metadata(soup, final)

    def episode(self, value, label, date=''):
        match = CHAPTER_PATH.fullmatch(path_of(value))
        if not match:
            return None
        target = urlunsplit(urlsplit(value)._replace(path='/online/' + match[1], query=''))
        return {'url': target, 'title': label or 'Глава', 'number': number(label),
                'season': 1, 'language': self.LANGUAGE, 'translator': '',
                'publishedAt': release_date(date, '%Y-%m-%d')}

    def entries(self, search, final, selector):
        for container in search.select(selector):
            anchor = container.select_one('h2 a[href], a[href]')
            if anchor and (entry := self.episode(self.site_link(anchor['href'], final),
                                                  anchor.get('title') or node_text(anchor),
                                                  node_text(container.select_one('.date')))):
                yield entry

    def hen_chapters(self, http, card, final, label):
        item = TITLE_PATH.fullmatch(path_of(final))[1]
        primary = self.episode(final, label)
        cover = card.select_one('img#cover')
        if cover and '/manganew_thumbs_blur/' in (cover.get('src') or ''):
            primary['number'] = 1
            return [primary], False
        related = urlunsplit(urlsplit(final)._replace(path='/related/' + item, query=''))
        target, seen, rows = related, set(), []
        while target and target not in seen and len(seen) < 25:
            seen.add(target)
            try:
                _, part, current = self.document(http, target, paths={path_of(related), path_of(final)})
            except SourceError as error:
                if not rows and len(seen) == 1 and 'HTTP 404' in str(error):
                    primary['number'] = 1
                    return [primary], False
                raise
            heading = node_text(part.select_one('#right > div:nth-child(4)'))
            if path_of(current) == path_of(final) or ' похожий на ' in heading:
                break
            rows.extend(self.entries(part, current, '.related, .related_info'))
            anchor = part.select_one(f'#pagination_related {NEXT}[href]')
            candidate = self.site_link(anchor.get('href'), current) if anchor else ''
            parts = urlsplit(candidate)
            target = candidate if RELATED_PATH.fullmatch(parts.path) and parts.path == path_of(related) and re.fullmatch(r'offset=[0-9]{1,6}', parts.query) else ''
        return (list(reversed(rows)) if rows else [primary]), bool(target and target not in seen)

    def inspect(self, value, http):
        target = self.site_link(value)
        path = path_of(target)
        title, chapter = TITLE_PATH.fullmatch(path), CHAPTER_PATH.fullmatch(path)
        pages, truncated = [], False
        if title:
            _, soup, final = self.document(http, target)
            row = self.metadata(soup, final)
            if self.hen:
                episodes, truncated = self.hen_chapters(http, soup, final, row['title'])
            else:
                episodes = list(self.entries(soup, final, 'table.table_cha tr'))
        elif chapter:
            raw, soup, final = self.document(http, target)
            label = node_text(soup.select_one('a.title_top_a, .reader-title, h1')) or node_text(soup.title).split(' »', 1)[0]
            if not label:
                raise SourceError('MultiChan не указал название главы.')
            parent = urlunsplit(urlsplit(final)._replace(path='/manga/' + chapter[1], query=''))
            row = self.row(parent, label)
            episodes = [self.episode(final, label)]
            pages = parse_pages(raw, final)
            if not pages:
                raise SourceError('MultiChan не предоставил страницы открытой главы.')
        else:
            raise SourceError('Некорректная ссылка на читалку MultiChan.')
        deduped = {item['url']: item for item in episodes}
        for i, entry in enumerate(deduped.values(), 1):
            if entry['number'] is None:
                entry['number'] = i
        ordered = sorted(deduped.values(), key=lambda item: item['number'])
        return {**row, 'url': final, 'episodes': ordered, 'pages': pages, 'available': bool(ordered),
                'truncated': truncated, 'seasons': [{'number': 1, 'name': 'Том 1'}] if ordered else [],
                'dubs': [], 'releases': [], 'translations': []}

    def saved_chapter_url(self, value, _slug, root):
        url = self.site_link(value, root)
        item = self.episode(url, '')
        return item['url'] if item else ''

    def saved_chapter_matches(self, target, title):
        # The bridge selects the chapter by its index from this exact stored title.
        return bool(CHAPTER_PATH.fullmatch(path_of(target)) and TITLE_PATH.fullmatch(path_of(title)))


SOURCES = (
    MultiChan('5504588601186153612', 'HenChan', 'https://xxl.hentaichan.live', True, hen=True),
    MultiChan('7', 'MangaChan', 'https://im.manga-chan.me', False, aliases=('manga-chan.me', 'mangachan.me')),
    MultiChan('2466512768990363955', 'YaoiChan', 'https://yaoi-chan.me', True),
)
