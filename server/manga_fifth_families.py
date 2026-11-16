"""Public series and reader routes for Rizz Comic, MurimScan and MMRCMS."""

import json
import re
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, SLUG
from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, Meta, picture
from manga_themesia import MangaThemesia
from manga_webcomics import query_url
from source_parser import PublicHttp, SourceError


RIZZ_ROOT = 'https://rizzfables.com'
RIZZ_GENRES = (
    'Abilities', 'Action', 'Adaptation', 'Adventure', 'Another Chance', 'Apocalypse', 'Based On A Novel',
    'Cheat', 'Comedy', 'Conspiracy', 'Cultivation', 'Demon', 'Demon King', 'Dragon', 'Drama', 'Drop',
    'Dungeon', 'Dungeons', 'Fantasy', 'Game', 'Genius', 'Ghosts', 'Harem', 'Hero', 'Hidden Identity',
    'HighFantasy', 'Historical', 'Horror',
)
RIZZ_TERMS = {str(index): name for index, name in enumerate(RIZZ_GENRES, 2)}


class RizzComic(MangaThemesia):
    def __init__(self, identity):
        source_id, name, lang, root, adult = identity
        super().__init__((source_id, name, root, adult), section='series', interval=1, language=lang,
                         cards='div.bsx a[href]')
        self.reader_selector = 'div#readerarea > img'
        self.chapter_date_format = '%d %b %Y'

    def stable_url(self, url):
        parts = urlsplit(url)
        match = self.TITLE_PATH.fullmatch(parts.path)
        if not match:
            return url
        slug = re.sub(r'^r\d+-', '', match[1])
        return urlunsplit(parts._replace(path=f'/series/{slug}/'))

    def saved_title_url(self, url):
        return self.stable_url(self.site_link(url))

    def row(self, url, label, thumbnail):
        return super().row(self.stable_url(url), label, thumbnail)

    def title_document(self, http, url):
        stored = self.stable_url(url)
        if urlsplit(stored).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            return self.document(http, url)
        doc, final = self.document(http, self.ROOT + '/series')
        for anchor in doc.select(self.cards):
            href = self.site_link(anchor.get('href'), final)
            if href and urlsplit(self.stable_url(href)).path == urlsplit(stored).path:
                return self.document(http, href)
        return self.document(http, url)

    def saved_chapter_matches(self, target, title):
        http = PublicHttp(timeout=(3, 6))
        try:
            soup, final = self.document(http, target)
            parent = self.series_link(soup, final)
        finally:
            http.close()
        return bool(parent and urlsplit(self.stable_url(parent)).path == urlsplit(self.stable_url(title)).path)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(tag, str) or (tag and tag not in RIZZ_TERMS):
            raise SourceError('Некорректные параметры каталога Rizz Comic.')
        if page != 1:
            return [], False
        if query:
            endpoint = self.ROOT + '/Index/live_search'
            fields = {'search_value': query.strip()[:160]}
        else:
            endpoint = self.ROOT + '/Index/filter_series'
            fields = {'StatusValue': 'all', 'TypeValue': 'all', 'OrderValue': 'update' if sort == 'updated' else 'popular'}
            if tag:
                fields['genres_checked[]'] = tag
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(endpoint, method='POST', action='native-series-form',
                                      headers={'Referer': self.ROOT + '/'}, data=fields)
        if final != endpoint:
            raise SourceError('Источник перенаправил запрос поиска.')
        try:
            results = json.loads(raw)
            if not isinstance(results, list):
                raise ValueError('Unexpected result')
        except ValueError:
            raise SourceError('Источник изменил формат поиска.') from None
        rows = []
        for comic in results:
            if not isinstance(comic, dict) or not isinstance(name := comic.get('title'), str):
                continue
            key = str(comic.get('id', ''))
            slug = name.strip().lower().replace('-', ' ').replace("'s", 's').replace("'", '')
            slug = re.sub(r'[^a-z0-9]+', '-', slug).replace('-ll-', 'll-').strip('-')
            if not slug or not re.fullmatch(r'\d{1,18}', key):
                continue
            url = f'{self.ROOT}/series/{slug}/#{key}'
            cover = image_url(comic.get('image_url'), self.ROOT + '/assets/images/')
            row = self.row(url, name, cover)
            ids = str(comic.get('genre_id', '')).split(',')
            row.update(description=comic.get('long_description') or '', status=comic.get('status') or '',
                       format=str(comic.get('type') or '').lower(),
                       genres=[RIZZ_TERMS[value.strip()] for value in ids if value.strip() in RIZZ_TERMS],
                       authors=[value for value in (comic.get('author'), comic.get('serialization')) if value],
                       artists=[comic['artist']] if comic.get('artist') else [])
            rows.append(row)
        return rows, False

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': key, 'category': 'genre'} for key, label in RIZZ_TERMS.items()]


class ReadComicsOnline(DirectCatalogue):
    def __init__(self, identity):
        title = rf'/comic/{SLUG}/?'
        search_cards = Cards('div a:has(img)', '', 'p', next='span a[rel=next]')
        super().__init__(identity, Layout(
            title, rf'/comic/{SLUG}/{SEGMENT}/?',
            Cards('div.comic-list-layout .grid > .group', 'a.block.text-sm.font-semibold', next='nav a[rel=next]'),
            Meta('h1.text-2xl', 'img.w-full.rounded-xl', 'div:has(> div > h3:-soup-contains("Synopsis")) > div > p',
                 genres='dl div:-soup-contains("Genres:") a', author='div:has(> span:-soup-contains("Author:")) > a',
                 status='div.flex.flex-wrap.gap-2 span.rounded-full'),
            Archive('.overflow-hidden.border-ink-600 > a', anchor='', title='.text-brand-400', date='.text-slate-500',
                    date_pattern='%d %b %Y'),
            '#reader-all img',
            Browse('/comic-list', (('sort', 'views'), ('page', '{page}'))),
            Browse('/advanced-search', (('name', '{query}'), ('page', '{page}')), cards=search_cards),
            Browse('/comic-list', (('sort', 'latest'), ('page', '{page}'))),
            Browse('/advanced-search', (('genres[]', '{tag}'), ('page', '{page}')), cards=search_cards),
            title_path='/comic/',
        ))


BLOG_POST = rf'/(\d{{4}}/\d{{2}}/{SEGMENT}\.html)'
BLOG_GENRES = 'dl.flex:-soup-contains("Genre") a[rel=tag]'
BLOG_INCLUSIONS = ('Series', 'Manga', 'Manhwa', 'Manhua', 'Doujinshi', 'Web Novel (JP)', 'Web Novel (KR)', 'Web Novel (CN)')
BLOG_EXCLUSIONS = ('Anime', 'Novel', 'Novela', 'Chapter')


def blog_value(row, key):
    value = row.get(key) or {}
    return str(value.get('$t', '')) if isinstance(value, dict) else ''


def blog_labels(row):
    return [item['term'] for item in row.get('category', []) if isinstance(item, dict) and isinstance(item.get('term'), str)]


class MurimScan(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, BLOG_POST, BLOG_POST, interval=.35, hosts=('murimscans.site',))

    def is_chapter(self, url):
        return super().is_chapter(url) and self.is_title(self.title_for(url)) and bool(urlsplit(url).query)

    def is_title(self, url):
        return super().is_title(url) and not urlsplit(url).query

    def title_for(self, url):
        path = parse_qs(urlsplit(url).query).get('mv_series', [''])[0]
        return self.ROOT + path if re.fullmatch(BLOG_POST, path) else ''

    def entry_link(self, row):
        return next((self.site_link(link.get('href')) for link in row.get('link', [])
                     if isinstance(link, dict) and link.get('rel') == 'alternate'), '')

    def feed(self, http, base, **query):
        url = query_url(base, alt='json', **query)
        reply = self.json(http, url)
        feed = reply.get('feed') if isinstance(reply, dict) else None
        if not isinstance(feed, dict):
            raise SourceError('Источник изменил формат ленты Blogger.')
        return feed

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        terms = '{' + ' '.join(f'label:"{value}"' for value in BLOG_INCLUSIONS) + '}'
        terms += ' ' + ' '.join(f'-label:"{value}"' for value in BLOG_EXCLUSIONS)
        if query:
            terms += ' ' + query
        elif tag:
            terms += ' label:"' + tag.replace('"', '') + '"'
        start = 20 * (page - 1) + 1
        feed = self.feed(http, self.ROOT + '/feeds/posts/default/',
                         **{'q': terms, 'orderby': 'published', 'start-index': start, 'max-results': 21})
        entries = feed.get('entry') or []
        rows = []
        for entry in entries[:20]:
            if not isinstance(entry, dict):
                continue
            url = self.entry_link(entry)
            title = blog_value(entry, 'title')
            if not self.is_title(url) or not title or set(blog_labels(entry)).intersection(BLOG_EXCLUSIONS):
                continue
            thumb = (entry.get('media$thumbnail') or {}).get('url') or ''
            if thumb:
                thumb = re.sub(r'/s[^/]+?-c/', '/w600/', thumb)
                thumb = re.sub(r'=s[^=]+-c$', '=w600', thumb)
            else:
                thumb = picture(BeautifulSoup(blog_value(entry, 'content'), 'html.parser').select_one('img'), url)
            rows.append(self.record(url, title, image_url(thumb, url)))
        return rows, len(entries) > 20

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        root = doc.select_one('main')
        title = node_text(root.select_one('h1, h2')) if root else ''
        if not title:
            raise SourceError('Источник не предоставил карточку тайтла.')
        cover = picture(root.select_one('header img, img'), final)
        genre_nodes = root.select(BLOG_GENRES)
        details = self.record(final, title, cover, description=node_text(root.select_one('[itemprop=description], .entry-content')),
                              genres=[node_text(item) for item in genre_nodes],
                              tags=[node_text(item) for item in root.select('a[rel=tag]') if item not in genre_nodes])
        script = doc.select_one('#clwd > script, #latest > script')
        marker = re.search(r'''(?:clwd\.run\(\s*|label\s*=\s*)["']([^"']+)["']''', script.string or '' if script else '')
        old = doc.select_one('#myUL > script[src]')
        if marker:
            path = '/feeds/posts/default/-/Chapter/' + quote(marker[1], safe='')
        elif old:
            parts = urlsplit(self.site_link(old['src'], final))
            path = parts.path if re.fullmatch(r'/feeds/posts/default/-/(?:[^/]+/){0,3}[^/]+/?', parts.path) else ''
            if not path:
                raise SourceError('Источник опубликовал неизвестный маршрут оглавления.')
        else:
            path = '/feeds/posts/default/-/Chapter/' + quote(title, safe='')
        chapters, start = {}, 1
        for _ in range(100):
            feed = self.feed(http, self.ROOT + path, **{'start-index': start, 'max-results': 150})
            entries = feed.get('entry') or []
            for entry in entries:
                if not isinstance(entry, dict) or 'Chapter' not in blog_labels(entry):
                    continue
                target = self.entry_link(entry)
                label = blog_value(entry, 'title')
                if not target or not re.fullmatch(BLOG_POST, urlsplit(target).path) or not label:
                    continue
                target = query_url(target, mv_series=urlsplit(final).path)
                chapters[target] = self.chapter(target, label, date=blog_value(entry, 'published')[:10])
            total = blog_value(feed, 'openSearch$totalResults')
            start += len(entries)
            if not entries or not total.isdecimal() or start > int(total):
                return details, self.order(chapters)
        raise SourceError('Источник не предоставил полное оглавление.')

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if target and re.fullmatch(BLOG_POST, urlsplit(target).path) and self.is_title(title):
            return query_url(target.split('?')[0], mv_series=urlsplit(title).path)
        return ''

    def saved_chapter_matches(self, target, title):
        key = self.title_key(title)
        return bool(key and key == self.title_key(self.title_for(target)))

    def pages(self, http, url):
        wire_url = urlunsplit(urlsplit(url)._replace(query=''))
        doc, final = self.document(http, wire_url)
        if urlsplit(final).path != urlsplit(wire_url).path:
            raise SourceError('Источник перенаправил запрос на другой выпуск.')
        return [picture(node, final, ('data-src',)) for node in doc.select('.post-body img[src], .check-box img[src]')]


def public_form(url, data):
    if url == RIZZ_ROOT + '/Index/live_search':
        return set(data) == {'search_value'} and isinstance(data['search_value'], str) and 1 <= len(data['search_value']) <= 160
    if url == RIZZ_ROOT + '/Index/filter_series':
        fields = {'OrderValue', 'StatusValue', 'TypeValue'}
        return (fields <= set(data) <= fields | {'genres_checked[]'} and data['OrderValue'] in ('update', 'popular')
                and data['StatusValue'] == data['TypeValue'] == 'all'
                and ('genres_checked[]' not in data or data['genres_checked[]'] in tuple(RIZZ_TERMS)))
    return False
