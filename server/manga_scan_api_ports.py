"""Arven Scans and ComicK Fanmade public catalogue protocols."""

import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_catalogues import MANGA, SERIES, SLUG
from manga_direct_payloads import JsonSeries, items, strings
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Cards, MAX_CHAPTERS, Meta, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ARVEN = 'api.arvenscans.net'
COMICK = 'comickfan.com'
KEY = r'[A-Za-z0-9_.-]{1,150}'
INDEX = r'[1-9]\d{0,3}'
ARVEN_STATIC = rf'/(?:{SEGMENT}/){{0,10}}{SEGMENT}\.(?:png|jpe?g|webp|gif|avif)'


def public_api(host, path, query):
    if host == COMICK:
        return query == 'translation_group_id=' and bool(re.fullmatch(rf'/api/comics/{SEGMENT}/chapter-list', path))
    if host != ARVEN:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(args) != len(pairs) or any(len(value) > 160 for value in args.values()):
        return False
    if path == '/works/most-read':
        return args == {'limit': '20'}
    if path == '/works' or re.fullmatch(rf'/genres/{SEGMENT}/works', path):
        return ({'page', 'limit'} <= set(args) <= {'page', 'limit', 'search', 'sort'}
                and args['limit'] == '24' and bool(re.fullmatch(INDEX, args['page']))
                and args.get('sort', 'updated') == 'updated')
    if re.fullmatch(rf'/works/{KEY}/chapters', path):
        return (set(args) == {'page', 'limit', 'order'} and args['limit'] == '100' and args['order'] == 'desc'
                and bool(re.fullmatch(INDEX, args['page'])))
    return not query and (path == '/genres' or bool(re.fullmatch(
        rf'/(?:works/{KEY}(?:/genres)?|chapters/{KEY}|resolve/work/{SEGMENT})', path)) or bool(
        re.fullmatch(ARVEN_STATIC, path, re.I)))


class ComicKFan(JsonSeries):
    cards = Cards('div:has(> form) + div.grid > a:has(img)', '', 'img', 'img', title_attr='alt',
                  next='a:has(img[alt=Next])')
    meta = Meta('h1', 'div.bg-card-section .thumb-cover img', 'div.comic-content.desk',
                genres='div.bg-card-section div.font-medium:-soup-contains("Genres") + div a')

    def __init__(self):
        super().__init__(('569821715369244319', 'ComicK Fanmade', 'en', 'https://' + COMICK, True),
                         MANGA, rf'/manga/{SLUG}/chapter-{SEGMENT}/?', interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/manga/' + key if key else ''

    def saved_title_url(self, value):
        target = self.canonical(value)
        return self.title_for(target) if self.is_chapter(target) else target

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'genres': tag if re.fullmatch(SEGMENT, tag) else '', 'status': '', 'type': '',
                'sort': 'latest' if sort == 'updated' else 'popular', 'name': query, 'page': page}
        return self.card_rows(*self.document(http, query_url(self.ROOT + '/advanced-search', **args)), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        def field(name):
            return node_text(doc.select_one(f'.bg-card-section div.flex-row.gap-4:has(> div.text-sm:-soup-contains-own("{name}")) > div.text-sm:nth-child(2)'))
        value = field('Author')
        row.update(authors=[part.strip() for part in value.split(',') if part.strip()], status=field('Status').lower())
        return row

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, self.meta)
        key = self.title_key(final)
        data = self.json(http, query_url(f'{self.ROOT}/api/comics/{key}/chapter-list', translation_group_id=''), final)
        chapters = {}
        for entry in items(data, 'data'):
            if not isinstance(entry, dict):
                continue
            cid, chapter = str(entry.get('hash_id') or ''), str(entry.get('chapter') or '')
            if not re.fullmatch(KEY, cid) or not re.fullmatch(SEGMENT, chapter):
                continue
            target = f'{self.ROOT}/manga/{key}/chapter-{chapter}-{cid}'
            labels = 'Chapter ' + chapter
            date = str(entry.get('created_at') or entry.get('published_at') or '')[:10]
            chapters[target] = self.chapter(target, labels, number(chapter), date,
                                            translator=', '.join(strings(entry.get('group_names'))))
        return row, self.order(chapters)

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return [picture(node, final) for node in doc.select('div.w-full > img[loading=lazy]')]


class ArvenScans(JsonSeries):
    API = 'https://' + ARVEN

    def __init__(self):
        super().__init__(('640484333556017983', 'Arven Scans', 'en', 'https://arvenscans.net', False),
                         SERIES, rf'/reader/({KEY})/?', hosts=('www.arvenscans.net',), interval=.35)

    def saved_title_url(self, url):
        target = self.canonical(url)
        if self.is_title(target):
            return target
        key = urlsplit(target).path.strip('/')
        return query_url(self.ROOT + '/series/' + key, mv_work=key) if re.fullmatch(KEY, key) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.chapter_key(url) or urlsplit(url).path.strip('/')
        if re.fullmatch(KEY, key) and self.is_title(title):
            return query_url(self.ROOT + '/reader/' + key, mv_title=self.title_key(title),
                             **({'mv_work': param(title, 'mv_work')} if param(title, 'mv_work') else {}))
        return ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(title) == self.title_key(self.title_for(target)))

    def metadata_row(self, data, genres=None):
        slug = data.get('slug') if isinstance(data, dict) else ''
        title = data.get('title') if slug else ''
        if not isinstance(slug, str) or not re.fullmatch(SEGMENT, slug) or not isinstance(title, str) or not title:
            return None
        url = self.ROOT + '/series/' + slug
        author = data.get('author')
        return self.record(url, title, image_url(data.get('cover_url'), self.API), aliases=strings(data.get('alt_titles')),
                           description=data.get('description') or '', genres=[item['name_en'] for item in genres or items(data, 'genres')
                               if isinstance(item, dict) and isinstance(item.get('name_en'), str)],
                           tags=strings(data.get('tags')), authors=[author] if isinstance(author, str) else [],
                           status=data.get('status') or '')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if not query and not tag and sort == 'popular':
            if page != 1:
                return [], False
            data = self.json(http, self.API + '/works/most-read?limit=20')
        else:
            args = {'page': page, 'limit': 24}
            if not query and tag and re.fullmatch(SEGMENT, tag):
                route = f'/genres/{tag}/works'
            else:
                route = '/works'
                args['sort'] = 'updated'
                if query:
                    args['search'] = query
            data = self.json(http, query_url(self.API + route, **args))
        pages = number((data.get('meta') or {}).get('total_pages')) or 1
        return [row for item in items(data, 'data') if (row := self.metadata_row(item))], page < pages

    def vocabulary(self, http):
        return [{'label': item['name_en'], 'sourceId': item['slug'], 'category': 'genre'}
                for item in items(self.json(http, self.API + '/genres'), 'data')
                if isinstance(item, dict) and item.get('name_en') and item.get('slug') and item.get('work_count', 1)]

    def series(self, http, url):
        slug = self.title_key(url)
        memo = param(url, 'mv_work')
        identity = memo or self.json(http, self.API + '/resolve/work/' + slug, url).get('work_id')
        if not isinstance(identity, str) or not re.fullmatch(KEY, identity):
            raise SourceError('Arven Scans не предоставил ID произведения.')
        root = self.API + '/works/' + identity
        details = self.json(http, root, url)
        if not isinstance(details, dict) or (memo and details.get('id') != memo) or (not memo and details.get('slug') != slug):
            raise SourceError('Arven Scans подменил запрошенное произведение.')
        genres = items(self.json(http, root + '/genres', url), 'data')
        card = self.metadata_row(details, genres)
        if not card:
            raise SourceError('Arven Scans не предоставил карточку.')
        chapters = {}
        for page in range(1, 101):
            data = self.json(http, query_url(root + '/chapters', page=page, limit=100, order='desc'), url)
            for item in items(data, 'data'):
                key = item.get('id') if isinstance(item, dict) else ''
                if not isinstance(key, str) or not re.fullmatch(KEY, key) or item.get('coins') != 0:
                    continue
                target = query_url(self.ROOT + '/reader/' + key, mv_title=slug, **({'mv_work': memo} if memo else {}))
                n = number(item.get('chapter_number'))
                label = item.get('title') or f'Chapter {item.get("chapter_number", key)}'
                chapters[key] = self.chapter(target, label, n, str(item.get('created_at') or '')[:10])
            if page >= (number((data.get('meta') or {}).get('total_pages')) or 1) or len(chapters) >= MAX_CHAPTERS:
                return card, self.order(chapters)[:MAX_CHAPTERS]
        raise SourceError('Arven Scans не предоставил полное оглавление.')

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            reply = self.json(http, self.API + '/chapters/' + self.chapter_key(url), url)
            key = reply.get('work_id')
            if not isinstance(key, str) or not re.fullmatch(KEY, key):
                raise SourceAccessError('Arven Scans не предоставил открытую главу.')
            url = query_url(url.split('?')[0], mv_title=key, mv_work=key)
        return super().inspect(url, http)

    def title_for(self, url):
        slug = param(url, 'mv_title')
        if not re.fullmatch(SEGMENT, slug):
            return ''
        target = self.ROOT + '/series/' + slug
        identity = param(url, 'mv_work')
        return query_url(target, mv_work=identity) if re.fullmatch(KEY, identity) else target

    def pages(self, http, url):
        reply = self.json(http, self.API + '/chapters/' + self.chapter_key(url), url)
        return [image_url(value, self.API) for value in items(reply, 'images')]


SOURCES = (ComicKFan(), ArvenScans())
