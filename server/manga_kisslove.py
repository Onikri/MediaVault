"""KissLove (klz9.com) JSON API (keiyoushi ``src/ja/kisslove`` at 6f345a8).

Every API call carries the web client's signature: SHA-256 of
``<unix seconds>.<public client id>``. Old image hosts are mapped to the
current CDN and the scanlator credit pages are left out, as upstream does.
"""

from datetime import datetime
import hashlib
import json
import re
import time
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_ninth_routes import Route, register
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://klz9.com'
CLIENT_ID = 'KL9K40zaSyC9K40vOMLLbEcepIFBhUKXwELqxlwTEF'
SLUG = r'[A-Za-z0-9][A-Za-z0-9._~%-]{0,250}'
CREDITS = {
    'https://1.bp.blogspot.com/-ZMyVQcnjYyE/W2cRdXQb15I/AAAAAAACDnk/8X1Hm7wmhz4hLvpIzTNBHQnhuKu05Qb0gCHMYCw/s0/LHScan.png',
    'https://s4.imfaclub.com/images/20190814/Credit_LHScan_5d52edc2409e7.jpg',
    'https://s4.imfaclub.com/images/20200112/5e1ad960d67b2_5e1ad962338c7.jpg',
}
IMAGE_HOSTS = {
    'imfaclub.com': 'j1.jfimv2.xyz', 's2.imfaclub.com': 'j2.jfimv2.xyz', 's4.imfaclub.com': 'j4.jfimv2.xyz',
    'ihlv1.xyz': 'j1.jfimv2.xyz', 's2.ihlv1.xyz': 'j2.jfimv2.xyz', 's4.ihlv1.xyz': 'j4.jfimv2.xyz',
    'h1.klimv1.xyz': 'j1.jfimv2.xyz', 'h2.klimv1.xyz': 'j2.jfimv2.xyz', 'h4.klimv1.xyz': 'j4.jfimv2.xyz',
}
LIST_KEYS = {'search', 'sort', 'order', 'genre', 'status', 'page'}


def public_api(host, path, query):
    if host != 'klz9.com':
        return False
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=8)
    except ValueError:
        return False
    args = dict(fields)
    if len(args) != len(fields):
        return False
    if path in {'/api/manga/trending-daily', '/api/genres'}:
        return not query
    if path == '/api/manga':
        return set(args) == {'page', 'limit'} and args['limit'] == '36' and bool(re.fullmatch(r'[1-9][0-9]{0,3}', args['page']))
    if path == '/api/manga/list':
        return (set(args) <= LIST_KEYS and len(args.get('search', '')) <= 160 and args.get('sort') == 'Popular'
                and args.get('order') == 'desc' and args.get('status', '') in {'', 'Ongoing', 'Completed'}
                and len(args.get('genre', '')) <= 80 and bool(re.fullmatch(r'[1-9][0-9]{0,3}', args.get('page', '1'))))
    return not query and bool(re.fullmatch(rf'/api/manga/slug/{SLUG}|/api/chapter/[1-9][0-9]{{0,12}}', path))


def signature():
    stamp = str(int(time.time()))
    return stamp, hashlib.sha256(f'{stamp}.{CLIENT_ID}'.encode()).hexdigest()


def route(url, method, data, headers):
    if url.netloc != 'klz9.com' or method != 'GET' or data is not None or not public_api(url.netloc, url.path, url.query):
        return None
    stamp, signed = headers.get('Kisslove-Time', ''), headers.get('Kisslove-Signature', '')
    if not re.fullmatch(r'[0-9]{10}', stamp) or abs(int(stamp) - time.time()) > 120:
        return None
    if signed != hashlib.sha256(f'{stamp}.{CLIENT_ID}'.encode()).hexdigest():
        return None
    return Route({'Accept': 'application/json', 'X-Client-Sig': signed, 'X-Client-Ts': stamp}, redirect=False)


register('kisslove', route, public_api)


class KissLove(JsonSeries):
    def __init__(self):
        super().__init__(('6304246026723672697', 'KissLove', 'ja', ROOT, True), rf'/({SLUG})\.html',
                         rf'/({SLUG}-chapter-[0-9]{{1,6}}(?:\.[0-9]{{1,3}})?)\.html', interval=.4)

    def is_title(self, url):
        return super().is_title(url) and not self.CHAPTER_PATH.fullmatch(urlsplit(url).path)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(r'[1-9][0-9]{0,12}', self.chapter_id(url)))

    def chapter_id(self, url):
        from manga_webcomics import param

        return param(url, 'mv_chapter')

    def title_for(self, url):
        key = self.chapter_key(url)
        return f'{ROOT}/{key.rsplit("-chapter-", 1)[0]}.html' if key else ''

    def chapter_identity(self, url):
        return self.chapter_id(url) or urlsplit(url).path

    def saved_title_url(self, url):
        if isinstance(url, str) and re.fullmatch(SLUG, url) and not url.startswith('http'):
            return f'{ROOT}/{url}.html'
        return self.canonical(url)

    def saved_chapter(self, row, root, title):
        # Suwayomi stored "<chapter id>/<slug>-chapter-<n>".
        value = str(row.get('realUrl') or row.get('url') or '')
        match = re.fullmatch(rf'([1-9][0-9]{{0,12}})/({SLUG}-chapter-[0-9.]{{1,10}})', value)
        if match:
            return query_url(f'{ROOT}/{match[2]}.html', mv_chapter=match[1])
        return super().saved_chapter(row, root, title)

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title)

    def api(self, http, path, **args):
        stamp, signed = signature()
        self.origin.wait(getattr(http, 'deadline', None))
        target = query_url(ROOT + path, **args) if args else ROOT + path
        raw, _, _ = http.document(target, headers={'Referer': ROOT + '/', 'Kisslove-Time': stamp,
                                                   'Kisslove-Signature': signed}, action='n9:kisslove')
        try:
            return json.loads(raw)
        except ValueError:
            raise SourceError('KissLove изменил формат API.') from None

    def record_from(self, item):
        if not isinstance(item, dict) or not isinstance(item.get('slug'), str) or not isinstance(item.get('name'), str):
            return None
        url = f'{ROOT}/{item["slug"]}.html'
        if not self.is_title(url):
            return None
        genres = item.get('genres')
        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(',')]
        description = BeautifulSoup(str(item.get('description') or ''), 'html.parser').get_text(' ').strip()
        aliases = [a.strip() for a in re.split(r'[,;]', str(item.get('other_name') or '')) if a.strip()]
        authors = [a.strip() for a in f"{item.get('authors') or ''},{item.get('artists') or ''}".split(',') if a.strip()]
        row = self.record(url, item['name'].strip(), str(item.get('cover') or ''), aliases=aliases, description=description,
                          genres=[g for g in genres or [] if isinstance(g, str) and g], authors=authors,
                          status='completed' if item.get('m_status') == 1 else 'ongoing')
        row['adult'] = True
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or tag:
            args = {'search': query, 'sort': 'Popular', 'order': 'desc'}
            if tag:
                if not re.fullmatch(r'[\w .&\'-]{1,60}', tag):
                    return [], False
                args['genre'] = tag
            if page > 1:
                args['page'] = str(page)
            data = self.api(http, '/api/manga/list', **args)
        elif sort == 'popular' and page == 1:
            data = self.api(http, '/api/manga/trending-daily')
        else:
            data = self.api(http, '/api/manga', page=str(page), limit='36')
        items = data if isinstance(data, list) else data.get('items') if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceError('KissLove не вернул каталог.')
        rows = [row for row in map(self.record_from, items) if row]
        more = isinstance(data, dict) and isinstance(data.get('currentPage'), int) and data['currentPage'] < (data.get('totalPages') or 0)
        if sort == 'popular' and page == 1 and not query and not tag:
            more = True
        return rows, more

    def vocabulary(self, http):
        data = self.api(http, '/api/genres')
        return [{'key': g['name'], 'label': g['name'], 'kind': 'genre'} for g in data if isinstance(g, dict)
                and isinstance(g.get('name'), str)] if isinstance(data, list) else []

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.api(http, f'/api/manga/slug/{slug}')
        row = self.record_from(data)
        if not row or self.title_key(row['url']) != slug:
            raise SourceError('KissLove не предоставил карточку тайтла.')
        chapters = {}
        for item in data.get('chapters') or []:
            if not isinstance(item, dict) or type(item.get('id')) is not int or not isinstance(item.get('chapter'), (int, float)):
                continue
            if item.get('hidden'):
                continue
            number = float(item['chapter'])
            label = f'{number:g}'
            date = ''
            try:
                date = datetime.fromisoformat(str(item.get('last_update', '')).replace('Z', '+00:00')).date().isoformat()
            except ValueError:
                pass
            target = query_url(f'{ROOT}/{slug}-chapter-{label}.html', mv_chapter=str(item['id']))
            name = item.get('name') if isinstance(item.get('name'), str) and item['name'].strip() else f'Chapter {label}'
            chapters[item['id']] = self.chapter(target, name, number, date)
        return row, self.order(chapters)

    def pages(self, http, url):
        data = self.api(http, f'/api/chapter/{self.chapter_id(url)}')
        content = data.get('content') if isinstance(data, dict) else None
        if not isinstance(content, str):
            raise SourceAccessError('KissLove не открыл эту главу.')
        pages = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line in CREDITS:
                continue
            parts = urlsplit(line)
            if parts.scheme not in {'http', 'https'} or not parts.netloc:
                continue
            pages.append(urlunsplit(parts._replace(scheme='https', netloc=IMAGE_HOSTS.get(parts.netloc, parts.netloc))))
        return pages


SOURCES = (KissLove(),)
