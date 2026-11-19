"""Danbooru and e621 pool catalogues with ordered public posts."""

import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_madara import image_url, node_text
from manga_series_port import MAX_PAGES, Meta, SeriesPort
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError, public_url

DANBOORU = 'https://danbooru.donmai.us'
E621_ROOT = 'https://e621.net'
ID = r'[1-9]\d{0,12}'
PAGE = r'[1-9]\d{0,3}'
POOL = rf'/pools/({ID})/?'
POST = rf'/posts/({ID})/?'
READER = rf'/(?:pools|posts)/({ID})/?'
ALT_IMAGE = 'mv_danbooru_post'


def public_api(host, path, query):
    if host not in {'danbooru.donmai.us', 'e621.net'}:
        return False
    if not query and (re.fullmatch(rf'/pools/{ID}\.json', path) or
                      host == 'danbooru.donmai.us' and re.fullmatch(rf'/posts/{ID}\.json', path)):
        return True
    if host != 'e621.net':
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(pairs) != len(args):
        return False
    if path == '/posts.json':
        match = re.fullmatch(rf'(?:status:all )?id:({ID}(?:,{ID}){{0,199}})', args.get('tags', ''))
        return set(args) == {'tags', 'limit'} and bool(match) and args['limit'] == str(len(match[1].split(',')))
    core = {'limit', 'page', 'search[order]'}
    extra = {'search[category]', 'search[name_matches]', 'search[description_matches]'}
    return (path == '/pools.json' and core <= set(args) <= core | extra and args['limit'] == '24'
            and bool(re.fullmatch(PAGE, args['page'])) and args['search[order]'] in {'post_count', 'created_at', 'updated_at'}
            and args.get('search[category]', 'series') in {'series', 'collection'}
            and all(len(v) <= 128 for v in args.values()))


def pool_indices(data, key):
    values = data.get('post_ids')
    if str(data.get('id')) != key or not isinstance(values, list):
        raise SourceError('Источник подменил список страниц.')
    return list(dict.fromkeys(str(i) for i in values if type(i) is int and re.fullmatch(ID, str(i))))


def danbooru_reference(url):
    parts = urlsplit(url)
    if parts.netloc != 'danbooru.donmai.us' or parts.query or not re.fullmatch(POST, parts.path):
        raise SourceError('Некорректный адрес поста Danbooru.')
    return public_url(url, resolve_dns=False)


def danbooru_image(http, url):
    from manga_series_port import document_json

    post = danbooru_reference(url)
    identity = re.fullmatch(POST, urlsplit(post).path)[1]
    obj = document_json(http, post.rstrip('/') + '.json', post)
    if str(obj.get('id', identity)) != identity:
        raise SourceError('Danbooru подменил пост.')
    values = ('file_url', 'large_file_url', 'preview_file_url')
    link = next((src for name in values if (src := image_url(obj.get(name), url))), '')
    if not link:
        raise SourceAccessError('Danbooru не предоставил открытое изображение.')
    return link


class BooruPools(SeriesPort):
    def __init__(self, identity, interval):
        super().__init__(identity, POOL, READER, interval=interval)

    def title_url(self, key):
        return self.ROOT + '/pools/' + key

    def is_title(self, url):
        return super().is_title(url) and param(url, 'mv_pool_read') != '1'

    def title_for(self, url):
        key = self.title_key(url) or param(url, 'mv_pool')
        return self.title_url(key) if re.fullmatch(ID, key) else ''

    def chapter_identity(self, url):
        return urlsplit(url).path.rstrip('/')

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return self.title_url(key) if re.fullmatch(ID, key) else self.title_for(url)

    def pool(self, http, identity):
        url = self.title_url(identity)
        data = self.json(http, url + '.json', url)
        return data, pool_indices(data, identity)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_title(url):
            return query_url(url, mv_pool_read=1)
        if self.is_chapter(url):
            return url
        return ''

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target):
            return False
        key = self.title_key(title)
        if re.fullmatch(POOL, urlsplit(target).path):
            return self.title_key(target) == key
        if not key:
            return False
        from source_parser import PublicHttp

        http = PublicHttp(timeout=(3, 6))
        try:
            _, posts = self.pool(http, key)
            return self.chapter_key(target) in posts
        finally:
            http.close()

    def single_chapter(self, url, data):
        return [self.chapter(query_url(url, mv_pool_read=1), 'Oneshot', 0, str(data.get('updated_at') or '')[:10])]


class Danbooru(BooruPools):
    meta = Meta('.pool-category-series, .pool-category-collection, h1', 'article.post-preview img',
                '#description', author='#description a[href*="artists"]')

    def __init__(self):
        super().__init__(('7602260701584916302', 'Danbooru', 'all', DANBOORU, True), .5)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'search[category]': 'series', 'page': page}
        if sort == 'updated':
            args['search[order]'] = 'created_at'
        if query:
            args['search[name_contains]'] = query
        if tag:
            args['search[post_tags_match]'] = tag[:120]
        doc, final = self.document(http, query_url(DANBOORU + '/pools/gallery', **args))
        rows = {}
        for node in doc.select('article.post-preview'):
            anchor = node.select_one('a.post-preview-link[href]')
            title = node_text(node.select_one('div.text-center'))
            target = self.site_link(anchor['href'], final) if anchor else ''
            if not self.is_title(target) or not title:
                continue
            source = node.select_one('source[srcset]')
            src = source['srcset'].split(',')[-1].strip().split() if source else []
            cover = image_url(src[0], final) if src else ''
            rows[target] = self.record(target, title, cover)
        return list(rows.values()), bool(doc.select_one('a.paginator-next[href]'))

    def chapters(self, http, doc, final):
        data, posts = self.pool(http, self.title_key(final))
        return (self.single_chapter(final, data) if posts else []), False

    def pages(self, http, url):
        if re.fullmatch(POST, urlsplit(url).path):
            return [danbooru_reference(url.split('?', 1)[0]) + '#' + ALT_IMAGE]
        _, ids = self.pool(http, self.title_key(url))
        if len(ids) > MAX_PAGES:
            raise SourceError('Альбом Danbooru превышает лимит страниц.')
        return [f'{DANBOORU}/posts/{i}#{ALT_IMAGE}' for i in ids]


class E621(BooruPools):
    def __init__(self):
        super().__init__(('3580576879040377475', 'e621', 'all', E621_ROOT, True), .5)

    def json(self, http, url, referer=None):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'User-Agent': 'MediaVault/1.0 (public comic reader)',
                                                    'Referer': referer or E621_ROOT + '/'}, action='native-series-json')
        if final != url:
            raise SourceError('e621 перенаправил запрос данных.')
        return json.loads(raw)

    def posts(self, http, ids):
        result = {}
        for start in range(0, len(ids), 200):
            batch = ids[start:start + 200]
            query = 'status:all id:' + ','.join(batch)
            data = self.json(http, query_url(E621_ROOT + '/posts.json', tags=query, limit=len(batch)))
            # Since Nov 2026 posts.json answers a bare list; it used to be {"posts": [...]}.
            entries = data if isinstance(data, list) else data.get('posts') or [] if isinstance(data, dict) else []
            for entry in entries:
                key = str(entry.get('id') or '')
                if key in batch:
                    result[key] = entry
        return result

    def image(self, entry, cover=False):
        if not isinstance(entry, dict) or (entry.get('flags') or {}).get('deleted'):
            return ''
        order = ('preview', 'sample', 'file') if cover else ('file', 'sample', 'preview')
        files = entry.get('files') if isinstance(entry.get('files'), dict) else {}
        for kind in order:
            if files:
                # Current shape: files.original.url, files.sample/preview.{webp,jpg}. A null URL
                # means e621 withholds the file from anonymous readers; it is not rebuilt.
                found = files.get('original' if kind == 'file' else kind) or {}
                candidates = [found.get('url'), found.get('jpg'), found.get('webp')] if isinstance(found, dict) else []
            else:
                candidates = [(entry.get(kind) or {}).get('url')]
            for value in candidates:
                url = image_url(value, E621_ROOT) if value else ''
                if url and not re.search(r'\.(?:mp4|webm)$', urlsplit(url).path, re.I):
                    return url
        return ''

    def row_for(self, data, cover=''):
        key = str(data.get('id', ''))
        name = str(data.get('name') or '').replace('_', ' ')
        if not re.fullmatch(ID, key) or not name:
            raise SourceError('e621 не предоставил карточку альбома.')
        status = 'ongoing' if data.get('is_active') is True else 'completed' if data.get('is_active') is False else ''
        return self.record(self.title_url(key), name, cover, description=str(data.get('description') or '')[:420], status=status)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)[:120]
        mode = 'created_at' if sort == 'updated' else 'post_count' if sort == 'popular' else 'updated_at'
        args = {'search[order]': mode, 'limit': 24, 'page': page}
        if tag in ('series', 'collection'):
            args['search[category]'] = tag
        if query:
            args['search[name_matches]'] = '*' + query.replace(' ', '_') + '*'
        rows = self.json(http, query_url(E621_ROOT + '/pools.json', **args))
        if not isinstance(rows, list):
            raise SourceError('e621 изменил формат каталога.')
        cover_ids = [str((entry.get('post_ids') or [0])[0]) for entry in rows]
        first_pages = self.posts(http, list(dict.fromkeys(i for i in cover_ids if re.fullmatch(ID, i))))
        return [self.row_for(entry, self.image(first_pages.get(cover), True)) for entry, cover in zip(rows, cover_ids)], len(rows) == 24

    def details(self, http, value):
        url = self.saved_title_url(value)
        if not self.is_title(url):
            raise SourceError('Некорректный альбом e621.')
        data, posts = self.pool(http, self.title_key(url))
        cover = self.posts(http, posts[:1]).get(posts[0]) if posts else None
        return self.row_for(data, self.image(cover, True))

    def pages(self, http, url):
        if re.fullmatch(POST, urlsplit(url).path):
            ids = [self.chapter_key(url)]
        else:
            _, ids = self.pool(http, self.title_key(url))
        if len(ids) > MAX_PAGES:
            raise SourceError('Альбом e621 превышает лимит страниц.')
        rows = self.posts(http, ids)
        return [image for key in ids if (image := self.image(rows.get(key)))]

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            return super().inspect(url, http)
        data, posts = self.pool(http, self.title_key(url))
        cover = self.posts(http, posts[:1]).get(posts[0]) if posts else None
        row = self.row_for(data, self.image(cover, True))
        return self.reader_result(row, url, self.single_chapter(url, data) if posts else [], [])


SOURCES = (Danbooru(), E621())
