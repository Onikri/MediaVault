"""Comick (Unoriginal) public metadata, cursor catalogues and chapter reader."""

import json
import re
from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import items, strings
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import MAX_CHAPTERS, Meta, SeriesPort, number
from manga_webcomics import query_url
from source_parser import SourceError

ROOT = 'https://comick.live'
HOSTS = {'comick.live', 'comick.art'}
SLUG = rf'/comic/({SEGMENT})/?'
READ = rf'/comic/({SEGMENT})/({SEGMENT})/?'
PAGE = r'[1-9]\d{0,3}'
SORT = {'', 'user_follow_count', 'rating', 'uploaded'}


def public_api(host, path, query):
    if host not in HOSTS:
        return False
    pairs = parse_qsl(query, keep_blank_values=True)
    args = dict(pairs)
    if len(args) != len(pairs) or any(len(v) > 1600 for v in args.values()):
        return False
    if path == '/api/metadata':
        return not query
    if path == '/api/comics/top':
        return (set(args) == {'day', 'type'} and args['day'] in {'7', '30', '90'} and
                args['type'] in {'follow', 'most_follow_new'})
    if not re.fullmatch(PAGE, args.get('page', '')):
        return False
    if re.fullmatch(rf'/api/comics/{SEGMENT}/chapter-list', path):
        return set(args) <= {'page', 'lang'} and bool(re.fullmatch(r'(?:[a-z]{2,3}(?:-[a-zA-Z]{2,4})?)?', args.get('lang', '')))
    if path == '/api/chapters/latest':
        return {'order', 'page'} <= set(args) <= {'order', 'page', 'cursor'} and args['order'] == 'new'
    core = {'page', 'type', 'order_direction', 'showAll', 'exclude_mylist'}
    optional = {'q', 'cursor', 'order_by', 'tags', 'genres'}
    return (path == '/api/search' and core <= set(args) <= core | optional and args['type'] == 'comic'
            and args['showAll'] == args['exclude_mylist'] == 'false' and args['order_direction'] == 'desc'
            and args.get('order_by', '') in SORT and len(args.get('q', '')) <= 160)


class ComickLive(SeriesPort):
    meta = Meta('', '')

    def __init__(self):
        super().__init__(('4972933717624256217', 'Comick (Unoriginal)', 'all', ROOT, True), SLUG, READ,
                         hosts=('comick.art',), interval=.5)
        self.lock = Lock()
        self.cursors = OrderedDict()

    def title_url(self, slug):
        return ROOT + '/comic/' + slug

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.title_url(key) if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        slug = self.title_key(url) or self.chapter_key(url) or urlsplit(url).path.strip('/')
        return self.title_url(slug) if re.fullmatch(SEGMENT, slug) else ''

    def row_for(self, data):
        slug = data.get('slug', '')
        label = data.get('title')
        if not isinstance(slug, str) or not re.fullmatch(SEGMENT, slug) or not isinstance(label, str) or not label:
            return None
        target = self.title_url(slug)
        alias_entries = data.get('md_titles') or []
        if isinstance(alias_entries, dict):
            alias_entries = alias_entries.values()
        aliases = [row['title'] for row in alias_entries if isinstance(row, dict) and isinstance(row.get('title'), str)]
        preface = node_text(BeautifulSoup(str(data.get('desc') or ''), 'html.parser'))
        tags = [{'suggestive': 'Suggestive', 'erotica': 'Erotica'}.get(data.get('content_rating'), '')]
        genres = [(row.get('md_genres') or {}).get('name') for row in data.get('md_comic_md_genres') or []
                  if isinstance(row, dict)]
        credits = [row.get('name') for key in ('authors', 'artists') for row in data.get(key) or [] if isinstance(row, dict)]
        status = {1: 'ongoing', 2: 'completed' if data.get('translation_completed') else 'publishing_finished',
                  3: 'cancelled', 4: 'hiatus'}.get(data.get('status'), '')
        row = self.record(target, label, image_url(data.get('default_thumbnail'), target), aliases=aliases,
                          description=preface, tags=tags, genres=genres, authors=credits, status=status)
        row['format'] = {'jp': 'manga', 'ko': 'manhwa', 'cn': 'manhua'}.get(data.get('country'), 'manga')
        return row

    def cursor(self, target, params, page):
        key = target, tuple(sorted(params.items())), page
        with self.lock:
            entry = self.cursors.get(key)
            if entry is not None and monotonic() - entry[0] < 900:
                return entry[1]
        return ''

    def store_cursor(self, target, params, page, cursor):
        key = target, tuple(sorted(params.items())), page
        with self.lock:
            self.cursors[key] = monotonic(), cursor
            self.cursors.move_to_end(key)
            while len(self.cursors) > 2048:
                self.cursors.popitem(last=False)

    def paginate(self, http, target, params, page):
        index = page
        cursor = self.cursor(target, params, index)
        while index > 1 and not cursor and page - index < 8:
            index -= 1
            cursor = self.cursor(target, params, index)
        if index > 1 and not cursor:
            raise SourceError('Сначала загрузите предыдущие страницы каталога Comick.')
        while index <= page:
            current = {**params, 'page': index}
            if cursor:
                current['cursor'] = cursor
            data = self.json(http, query_url(target, **current))
            cursor = data.get('next_cursor') or ''
            if cursor:
                if not isinstance(cursor, str) or len(cursor) > 1600:
                    raise SourceError('Comick вернул ошибочный указатель каталога.')
                self.store_cursor(target, params, index + 1, cursor)
            if index == page:
                return items(data, 'data'), bool(cursor)
            if not cursor:
                return [], False
            index += 1
        return [], False

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if not query and not tag and sort == 'popular':
            if page > 6:
                return [], False
            day = (7, 30, 90)[(page - 1) % 3]
            target = query_url(ROOT + '/api/comics/top', day=day, type='follow' if page < 4 else 'most_follow_new')
            data, more = items(self.json(http, target), 'data'), page < 6
        elif not query and not tag:
            data, more = self.paginate(http, ROOT + '/api/chapters/latest', {'order': 'new'}, page)
        else:
            if query and len(query) < 3:
                return [], False
            args = {'type': 'comic', 'showAll': 'false', 'exclude_mylist': 'false', 'order_direction': 'desc'}
            if query:
                args['q'] = query
            if tag:
                field, _, value = tag.partition(':')
                args[field if field in ('genres', 'tags') and value else 'tags'] = (value or tag)[:160]
            data, more = self.paginate(http, ROOT + '/api/search', args, page)
        return [row for item in data if isinstance(item, dict) and (row := self.row_for(item))], more

    def vocabulary(self, http):
        data = self.json(http, ROOT + '/api/metadata')
        terms = []
        for key in ('genres', 'tags'):
            for item in data.get(key) or []:
                if isinstance(item, dict) and isinstance(item.get('slug'), str) and isinstance(item.get('name'), str):
                    terms.append({'key': key + ':' + item['slug'], 'label': item['name'], 'kind': key[:-1]})
        return terms

    def metadata(self, doc, url, spec):
        node = doc.select_one('#comic-data')
        data = json.loads(node.string or '') if node else {}
        row = self.row_for(data)
        if not row or self.title_key(row['url']) != self.title_key(url):
            raise SourceError('Comick не предоставил метаданные тайтла.')
        return row

    def chapters(self, http, doc, final):
        result = {}
        if not self.is_title(final):
            raise SourceError('Некорректная ссылка Comick.')
        slug = self.title_key(final)
        host = urlsplit(final).hostname
        root = 'https://' + host
        truncated = False
        for index in range(1, 81):
            data = self.json(http, query_url(root + '/api/comics/' + slug + '/chapter-list', page=index), final)
            for item in items(data, 'data'):
                chapter = str(item.get('chap') or '')
                lang = item.get('lang', '')
                hid = item.get('hid', '')
                if (not re.fullmatch(r'\d{1,8}(?:\.\d{1,4})?', chapter)
                        or not re.fullmatch(r'[A-Za-z0-9_-]{1,24}', hid)
                        or not re.fullmatch(r'[a-z]{2,3}(?:-[a-zA-Z]{2,4})?', lang)):
                    continue
                target = root + f'/comic/{slug}/{hid}-chapter-{chapter}-{lang}'
                title = 'Ch. ' + chapter + (': ' + str(item['title']) if item.get('title') else '')
                volume = number(item.get('vol'))
                row = self.chapter(target, title, number(chapter), date=str(item.get('created_at') or '')[:10],
                                   season=int(volume) if volume else 1,
                                   translator=', '.join(strings(item.get('group_name'))))
                row['language'] = lang
                result[target] = row
            more = index < (number((data.get('pagination') or {}).get('last_page')) or index)
            if not more or len(result) >= MAX_CHAPTERS:
                truncated = more
                break
        else:
            truncated = True
        return self.order(result)[:MAX_CHAPTERS], truncated

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        node = doc.select_one('#sv-data')
        data = json.loads(node.string or '') if node else {}
        children = (data.get('chapter') or {}).get('images') or []
        return [src for image in children if isinstance(image, dict) and (src := image_url(image.get('url'), final))]


SOURCES = (ComickLive(),)
