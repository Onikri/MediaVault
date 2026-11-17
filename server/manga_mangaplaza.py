"""MangaPlaza catalogue, chapter pagination and public SpeedBinb previews."""

import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import node_text
from manga_series_port import Cards, Meta, SeriesPort
from manga_speedbinb import CID, chapter_pages
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://mangaplaza.com'
API = ROOT + '/api'
READER = 'https://reader.mangaplaza.com/sws/apis/bibGetCntntInfo.php'
KEY = r'[A-Za-z0-9_.~-]{1,120}'
TITLE = rf'/title/({KEY})/?'
CHAPTER = rf'/reader/({KEY})(/preview)?/?'


def public_api(host, path, query):
    if host != 'mangaplaza.com':
        return False
    if path == '/api/genre/all_genre':
        return not query
    pairs = parse_qsl(query)
    args = dict(pairs)
    return (path == '/api/title/content_list' and len(args) == len(pairs) and set(args) == {'title_id', 'order', 'page'}
            and re.fullmatch(KEY, args['title_id']) and args['order'] == 'down' and re.fullmatch(r'[1-9]\d{0,3}', args['page']))


class MangaPlaza(JsonSeries):
    cards = Cards('ul.listBox > li', '.titleName a', cover='figure img', next='.pager li.selected + li a')
    meta = Meta('.detailBlock h1', '.detailBlock .thumBlock img', '.titleInfo .storytext',
                genres='.titleInfo .infoList a[href*="/genre/"]', tags='.titleInfo .infoList a[href*="/genre_tag/"]',
                author='.detailBlock .authorName a')

    def __init__(self):
        super().__init__(('2236200885810873895', 'MangaPlaza', 'en', ROOT, True), TITLE, CHAPTER, interval=.35)

    def title_for(self, url):
        key = param(url, 'mv_plaza_title')
        return ROOT + '/title/' + key if self.is_chapter(url) and re.fullmatch(KEY, key) else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/title/' + key if re.fullmatch(KEY, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if not self.is_chapter(url):
            key = urlsplit(url).path.strip('/')
            url = ROOT + '/reader/' + key if re.fullmatch(KEY, key) else ''
        return query_url(url, mv_plaza_title=self.title_key(title)) if self.is_chapter(url) and self.is_title(title) else ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(title) == param(target, 'mv_plaza_title'))

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        path = '/searchresult'
        if found := re.fullmatch(r'(genre|genre_tag):([\d]{1,12})', tag):
            path += f'/{found[1]}/{found[2]}'
        options = {'fre': query, 'sort': 'recommend' if query else 'new' if sort == 'updated' else 'rank', 'page': page}
        return self.card_rows(*self.document(http, query_url(ROOT + path, **options)), self.cards)

    def vocabulary(self, http):
        raw = self.json(http, API + '/genre/all_genre').get('data') or {}
        result = {}
        for field, kind, group in (('genre_info_list', 'genre', 'genre'), ('genre_tag_info_list', 'tag', 'genre_tag')):
            for item in raw.get(field) or []:
                if isinstance(item, dict) and item.get('genre_nm') and re.fullmatch(r'\d{1,12}', key := str(item.get(group + '_id', ''))):
                    marker = group + ':' + key
                    result[marker] = {'key': marker, 'label': item['genre_nm'], 'kind': kind}
        return list(result.values())

    def list_page(self, http, key, page):
        value = self.json(http, query_url(API + '/title/content_list', title_id=key, order='down', page=page))
        raw = value.get('data') or {}
        if not isinstance(raw.get('html_content'), str) or not isinstance(raw.get('html_page'), str):
            raise SourceError('MangaPlaza вернул неожиданный формат оглавления.')
        return BeautifulSoup(raw['html_content'], 'html.parser'), BeautifulSoup(raw['html_page'], 'html.parser')

    def series(self, http, url):
        key = self.title_key(url)
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        status = node_text(doc.select_one('.detailTopBlock .number')).casefold()
        row['status'] = 'completed' if status.startswith('complete') else 'ongoing' if status.startswith('ongoing') else ''
        first, paging = self.list_page(http, key, 1)
        last = max((int(n) for node in paging.select('a[data-page]') if re.fullmatch(r'\d{1,4}', n := node['data-page'])),
                   default=1)
        chapters = {}
        for page in range(1, min(last, 80) + 1):
            details = first if page == 1 else self.list_page(http, key, page)[0]
            for entry in details.select('ul.detailBox > li:not(:has(.nextUpdateBlock))'):
                identity = entry.get('id', '').removeprefix('_content_area_')
                if not re.fullmatch(KEY, identity):
                    continue
                links = [self.site_link(node.get('href'), final) for node in entry.select('.btnBox a[href]')]
                open_full = next((href for href in links if self.is_chapter(href)
                                  and self.chapter_key(href) == identity and '/preview' not in href), '')
                preview = any(self.is_chapter(href) and self.chapter_key(href) == identity and '/preview' in href for href in links)
                target = ROOT + '/reader/' + identity + ('/preview' if preview and not open_full else '')
                target = query_url(target, mv_plaza_title=key, mv_plaza_locked='1' if not open_full and not preview else [])
                label = node_text(entry.select_one('.titleName'))
                if preview and not open_full:
                    label += ' · Фрагмент'
                elif not open_full:
                    label = '🔒 ' + label
                chapters[target] = self.chapter(target, label)
        return row, self.order(chapters)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        cid = self.chapter_key(url)
        if param(url, 'mv_plaza_locked') or not CID.fullmatch(cid):
            raise SourceAccessError('MangaPlaza ограничивает доступ к выпуску.')
        preview = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)[2]
        return chapter_pages(http, READER, cid, ROOT + '/', {'u0': '1' if preview else '0', 'u1': ROOT})


SOURCES = (MangaPlaza(),)
