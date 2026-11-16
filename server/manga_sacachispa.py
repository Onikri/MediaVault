"""Sacachispa catalogue and releases with stable IDs across the site rewrite."""

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from manga_direct_payloads import JsonSeries, items, segment
from manga_madara import SEGMENT, image_url
from manga_series_port import MAX_CHAPTERS, number
from manga_source_tags import labels
from manga_webcomics import param, query_url
from source_parser import SourceError


HOST = 'api.sacachispa.site'
API = 'https://' + HOST + '/api'
CDN = 'https://cdn.sacachispa.site/'
ART = rf'/manga/({SEGMENT})(?:/{SEGMENT})?/?'
KEY = r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}'
RELEASE = rf'/read/({KEY})/?'


def public_api(host, path, query):
    if host != HOST:
        return False
    args = parse_qs(query)
    if not all(len(v) == 1 and 1 <= len(v[0]) <= 160 for v in args.values()):
        return False
    if path in {'/api/manga', '/api/manga/search'}:
        fields = {'page', 'limit'} | ({'q'} if path.endswith('/search') else set())
        return (set(args) == fields and args['limit'] in (['24'], ['100'])
                and bool(re.fullmatch(r'[1-9]\d{0,4}', args['page'][0])))
    if path == '/api/releases':
        if set(args) == {'page', 'limit', 'mangaId'}:
            return args['limit'] == ['500'] and bool(re.fullmatch(KEY, args['mangaId'][0])) and bool(re.fullmatch(
                r'[1-9]\d{0,4}', args['page'][0]))
        return set(args) == {'page', 'limit'} and args['page'] == ['1'] and args['limit'] == ['100']
    return not query and bool(re.fullmatch(rf'/api/(?:manga/{SEGMENT}|releases/{KEY}(?:/pages)?)', path))


def locked(chapter):
    stamp = chapter.get('freeAt')
    if isinstance(stamp, str) and stamp:
        try:
            now = datetime.now(UTC)
            value = datetime.fromisoformat(stamp)
            return (value if value.tzinfo else value.replace(tzinfo=UTC)) > now
        except ValueError:
            pass
    return chapter.get('patreonOnly') is True


class Sacachispa(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, ART, RELEASE, interval=.35)

    def api(self, http, route, **args):
        endpoint = API + route
        return self.json(http, query_url(endpoint, **args) if args else endpoint)

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(SEGMENT, value):
            return self.ROOT + '/manga/' + value
        return super().saved_title_url(value)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_for(url))

    def title_for(self, url):
        key = param(url, 'mv_manga')
        return self.ROOT + '/manga/' + key if re.fullmatch(KEY, key) else ''

    def saved_chapter(self, row, root, title):
        value = row.get('realUrl') or row.get('url') or ''
        link = self.site_link(value, root)
        key = self.title_key(title)
        if isinstance(value, str) and re.fullmatch(KEY, value):
            link = self.ROOT + '/read/' + value
        if super().is_chapter(link) and re.fullmatch(KEY, key):
            return query_url(link, mv_manga=key)
        return link if super().is_chapter(link) else ''

    def saved_chapter_matches(self, target, title):
        key = self.title_key(title)
        if key and key == self.title_key(self.title_for(target)):
            return True
        match = self.CHAPTER_PATH.fullmatch(urlsplit(target).path)
        if not match or not key:
            return False
        from source_parser import PublicHttp

        http = PublicHttp(timeout=(3, 6))
        try:
            reply = self.api(http, '/releases/' + match[1])
        finally:
            http.close()
        parent = ((reply.get('data') or {}).get('manga') or {}) if isinstance(reply, dict) else {}
        return key in {parent.get('id'), segment(parent.get('slug'))}

    def row_data(self, row):
        key, title = row.get('id'), row.get('title')
        slug = segment(row.get('slug'))
        if not isinstance(key, str) or not re.fullmatch(KEY, key) or not isinstance(title, str) or not title.strip():
            raise SourceError('Sacachispa не предоставил карточку тайтла.')
        path = f'{self.ROOT}/manga/{key}/{slug or key}'
        synopsis = row.get('synopses') or ()
        description = next((item['synopsis'] for item in synopsis if isinstance(item, dict) and isinstance(item.get('synopsis'), str)), '')
        tags = [row['demographic']] if row.get('demographic') and row['demographic'] != 'NONE' else []
        return self.record(path, title, image_url(row.get('cover'), CDN), description=description,
                           aliases=labels(row.get('titles')), genres=labels(row.get('genres')), tags=tags,
                           authors=labels(row.get('authors')), status=str(row.get('status') or '').casefold())

    def vocabulary(self, http):
        data = self.api(http, '/manga/genres')
        return [{'label': row, 'sourceId': row, 'category': 'genre'} for row in labels(items(data, 'data'))]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if sort == 'updated' and not (query or tag):
            if page != 1:
                return [], False
            data = self.api(http, '/releases', page=1, limit=100)
            rows = {row['id']: self.row_data(row) for release in items(data, 'data') if isinstance(release, dict)
                    and isinstance(row := release.get('manga'), dict) and isinstance(row.get('id'), str)}
            return list(rows.values()), False
        args = {'page': page, 'limit': 100 if tag else 24}
        if query:
            args['q'] = query
        data = self.api(http, '/manga/search' if query else '/manga', **args)
        rows = [self.row_data(item) for item in items(data, 'data') if isinstance(item, dict)
                and (not tag or any(label.casefold() == tag.casefold() for label in labels(item.get('genres'))))]
        return rows, page < (number((data.get('pagination') or {}).get('pages')) or page)

    def details(self, http, url):
        key = self.title_key(self.saved_title_url(url))
        if not key:
            raise SourceError('Некорректная ссылка на тайтл Sacachispa.')
        data = self.api(http, '/manga/' + key)
        row = data.get('data') if isinstance(data, dict) else None
        if not isinstance(row, dict) or key not in {str(row.get('id')), segment(row.get('slug'))}:
            raise SourceError('Sacachispa вернул другой тайтл.')
        return self.row_data(row)

    def series(self, http, url):
        row = self.details(http, url)
        key = self.title_key(row['sourceUrl'])
        chapters = {}
        for page in range(1, 101):
            data = self.api(http, '/releases', mangaId=key, page=page, limit=500)
            for entry in items(data, 'data'):
                if not isinstance(entry, dict) or not isinstance(ref := entry.get('chapter'), dict) or locked(ref):
                    continue
                release = entry.get('id')
                if not isinstance(release, str) or not re.fullmatch(KEY, release) or (entry.get('manga') or {}).get('id') != key:
                    continue
                n = number(ref.get('chapter'))
                target = query_url(f'{self.ROOT}/read/{release}', mv_manga=key)
                name = f'Chapter {ref.get("chapter", "")}' + (' - ' + ref['title'] if ref.get('title') else '')
                chapters[target] = self.chapter(target, name, n, str(entry.get('publishedAt') or '')[:10])
            if page >= (number((data.get('pagination') or {}).get('pages')) or page):
                return row, self.order(chapters)
            if len(chapters) > MAX_CHAPTERS:
                break
        raise SourceError('Sacachispa не предоставил полное оглавление.')

    def inspect(self, value, http):
        url = self.canonical(value)
        if super().is_chapter(url) and not self.title_for(url):
            data = self.api(http, '/releases/' + self.chapter_key(url))
            parent = (data.get('data') or {}).get('manga') if isinstance(data, dict) else None
            if not isinstance(parent, dict) or not isinstance(key := parent.get('id'), str) or not re.fullmatch(KEY, key):
                raise SourceError('Sacachispa не предоставил тайтл главы.')
            url = query_url(url, mv_manga=key)
        return super().inspect(url, http)

    def pages(self, http, url):
        response = self.api(http, '/releases/' + self.chapter_key(url) + '/pages')
        return [image_url(row.get('url'), CDN) if isinstance(row, dict) else ''
                for row in items(response.get('data'), 'items')]
