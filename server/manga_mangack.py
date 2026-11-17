"""Mangack's Ifenzi catalogue and public WordPress chapter contents."""

from html import unescape
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, picture
from manga_webcomics import param, query_url
from source_parser import SourceError


ROOT = 'https://mangack.com'
REST = ROOT + '/wp-json/wp/v2'
TITLE = rf'/manga/({SEGMENT})/?'
CHAPTER = rf'/chapter/({SEGMENT})/?'
SKIP_ASSET = re.compile(r'/wp-content/(?:themes|plugins)/|/(?:logo|icon|cropped|preroll|placeholder|'
                        r'loading|spinner|chainsaw)[^/]*\.(?:png|jpe?g|webp|gif|svg)', re.I)
STATUSES = {'ongoing': 'ongoing', 'publishing': 'ongoing', 'updating': 'ongoing',
            'completed': 'completed', 'complete': 'completed', 'finished': 'completed',
            'hiatus': 'hiatus', 'on-hiatus': 'hiatus', 'on-hold': 'hiatus',
            'cancelled': 'cancelled', 'canceled': 'cancelled', 'dropped': 'cancelled'}


def rendered(value):
    field = value.get('rendered') if isinstance(value, dict) else ''
    return field if isinstance(field, str) else ''


def public_api(host, path, query):
    if host != 'mangack.com' or path not in {'/wp-json/wp/v2/manga', '/wp-json/wp/v2/chapter', '/wp-json/wp/v2/Genres'}:
        return False
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=8)
    except ValueError:
        return False
    args = dict(fields)
    if len(fields) != len(args):
        return False
    route = path.rsplit('/', 1)[-1]
    if route == 'manga':
        return (set(args) <= {'page', 'per_page', '_embed', 'search', 'Genres', 'orderby', 'order'}
                and bool(re.fullmatch(r'[1-9]\d{0,3}', args.get('page', '')))
                and args.get('per_page') == '24' and args.get('_embed') == 'wp:featuredmedia'
                and len(args.get('search', '')) <= 160
                and ('Genres' not in args or bool(re.fullmatch(r'[1-9]\d{0,9}', args['Genres'])))
                and args.get('orderby', 'date') == 'date' and args.get('order', 'desc') == 'desc')
    if route == 'chapter':
        return set(args) == {'slug', '_fields'} and bool(re.fullmatch(SEGMENT, args['slug'])) and args['_fields'] == 'id,content'
    return route == 'Genres' and args == {'per_page': '100', 'hide_empty': 'true'}


class Mangack(JsonSeries):
    def __init__(self):
        super().__init__(('7208855238528281651', 'Mangack', 'en', ROOT, False), TITLE, CHAPTER, interval=.5)

    def title_for(self, url):
        # Chapters have standalone WordPress slugs. The reliable parent is in the
        # chapter URL we publish or the upstream chapter's title link.
        title = self.site_link('/manga/' + param(url, 'mv_mangack_title'))
        return title if self.is_title(title) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if sort == 'updated' and not query and not tag:
            path = '/updates/' if page == 1 else f'/updates/page/{page}/'
            spec = Cards('.latestmanga .Latest_chapter_update', 'a[href*="/manga/"]',
                         next='.pagination a.next, a.next.page-numbers')
            return self.card_rows(*self.document(http, ROOT + path), spec)
        args = {'page': page, 'per_page': 24, '_embed': 'wp:featuredmedia'}
        if query:
            args['search'] = query
        else:
            args.update(orderby='date', order='desc')
        if tag:
            if not re.fullmatch(r'[1-9]\d{0,9}', tag):
                return [], False
            args['Genres'] = tag
        target = query_url(REST + '/manga', **args)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, headers = http.document(target, headers={'Referer': ROOT + '/'}, action='native-series-json')
        if final != target:
            raise SourceError('Mangack перенаправил каталог.')
        try:
            data = json.loads(raw)
            total = int(headers.get('X-WP-TotalPages', 1))
        except (ValueError, TypeError):
            raise SourceError('Mangack изменил формат каталога.') from None
        if not isinstance(data, list):
            raise SourceError('Mangack вернул неизвестный формат списка тайтлов.')
        found = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            url = self.site_link(item.get('link'))
            title = unescape(rendered(item.get('title'))).strip()
            if title and self.is_title(url):
                embedded = item.get('_embedded')
                photos = embedded.get('wp:featuredmedia') if isinstance(embedded, dict) else None
                photo = photos[0].get('source_url') if isinstance(photos, list) and photos and isinstance(photos[0], dict) else ''
                found[url] = self.record(url, title, image_url(photo, url))
        return list(found.values()), bool(found and page < total)

    def vocabulary(self, http):
        data = self.json(http, query_url(REST + '/Genres', per_page=100, hide_empty='true'))
        if not isinstance(data, list):
            return []
        return [{'key': str(item['id']), 'label': unescape(item['name']), 'kind': 'genre'}
                for item in data if isinstance(item, dict) and type(item.get('id')) is int and isinstance(item.get('name'), str)]

    def series(self, http, url):
        doc, final = self.title_document(http, self.canonical(url))
        article = doc.select_one('article')
        classes = article.get('class', []) if article else []
        meta = lambda prop: (node['content'] if (node := doc.select_one(f'meta[property="og:{prop}"][content]')) else '')
        title = node_text(doc.select_one('h1.entry-title')) or meta('title').removesuffix(' mangack').strip()
        if not title:
            raise SourceError('Mangack не предоставил карточку тайтла.')
        fields = {}
        for row in doc.select('table.infobox tr'):
            tds = row.find_all(['td', 'th'], recursive=False)
            if len(tds) >= 2:
                fields[node_text(tds[0]).casefold()] = node_text(tds[1])
        status = next((STATUSES.get(name.removeprefix('manga-status-'), '')
                       for name in classes if name.startswith('manga-status-')), '')
        genres = [name.removeprefix('Genres-').replace('-', ' ').title() for name in classes if name.startswith('Genres-')]
        cover = image_url(meta('image'), final) or picture(doc.select_one('article figure img, .mediumthumbnail1 img'), final)
        aliases = re.split(r'[,|;]', fields.get('alternative', ''))
        row = self.record(final, title, cover, aliases=filter(None, map(str.strip, aliases)),
                          description=meta('description').strip(), genres=genres, status=status)
        if re.fullmatch(r'(?:19|20)\d{2}', year := fields.get('realized in', '')):
            row['year'] = int(year)
        format_map = {'manhwa': 'manhwa', 'manhua': 'manhua', 'manga': 'manga', 'comic': 'comic'}
        kind = next((name.removeprefix('comic-type-') for name in classes if name.startswith('comic-type-')), '')
        row['format'] = format_map.get(kind, row['format'])
        spec = Archive('ul.chapterslist li', anchor='a.title, a[href*="/chapter/"]', date='.entry-date')
        chapters, _ = self.list_chapters(http, doc, final, spec)
        for chapter in chapters:
            target = self.site_link(chapter['url'])
            chapter['url'] = self.reader_url(query_url(target, mv_mangack_title=self.title_key(final)))
        return row, chapters

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target) or not self.is_title(title):
            return False
        return self.chapter_identity(self.title_for(target)) == self.chapter_identity(title)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if target and self.is_chapter(target) and self.is_title(title) and not self.title_for(target):
            return query_url(target, mv_mangack_title=self.title_key(title))
        return target

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            doc, final = self.page_document(http, url)
            candidates = {self.title_key(link) for a in doc.select(
                '.breadcrumb a[href*="/manga/"], .entry-header a[href*="/manga/"], p a[href*="/manga/"]'
            ) if self.is_title(link := self.site_link(a['href'], final))}
            if len(candidates) != 1:
                raise SourceError('Mangack не указал родительский тайтл главы.')
            url = query_url(url, mv_mangack_title=candidates.pop())
        return super().inspect(url, http)

    def pages(self, http, url):
        target = query_url(REST + '/chapter', slug=self.chapter_key(url), _fields='id,content')
        data = self.json(http, target, self.title_for(url))
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            return []
        doc = BeautifulSoup(rendered(data[0].get('content')), 'html.parser')
        return [link for img in doc.select('img[src]') if not SKIP_ASSET.search(img['src'])
                and (link := image_url(img['src'], url))]


SOURCES = (Mangack(),)
