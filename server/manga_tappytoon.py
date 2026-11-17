"""Tappytoon guest catalogue (keiyoushi ``src/all/tappytoon`` at 6f345a8).

The web app embeds an anonymous guest token and device UUID in
``__NEXT_DATA__``; the global API answers catalogue, chapter and free
content requests with them. Locked chapters stay out of open reading.
"""

from datetime import datetime
import json
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

API = 'https://api-global.tappytoon.com'
TOKEN = re.compile(r'Bearer [A-Za-z0-9/+=_.-]{16,200}')
DEVICE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
GENRES = (('Action', 'action'), ('Romance', 'romance'), ('Fantasy', 'fantasy'), ('School', 'school'),
          ('Slice of Life', 'slice'), ('BL', 'bl'), ('Comedy', 'comedy'), ('GL', 'gl'))
GENRE_KEYS = {key for _, key in GENRES}
API_KEYS = {'sort_by', 'filter', 'locale', 'genre', 'limit', 'keyword', 'day_of_week', 'chapterId', 'variant', 'page'}


def public_api(host, path, query):
    if host != 'api-global.tappytoon.com':
        return False
    if not re.fullmatch(r'/comics(?:/[1-9][0-9]{0,9}(?:/chapters)?)?|/content-delivery/contents', path):
        return False
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=8, strict_parsing=True)
    except ValueError:
        return False
    args = dict(fields)
    return (len(args) == len(fields) and set(args) <= API_KEYS and args.get('locale') in {'en', 'fr', 'de'}
            and len(args.get('keyword', '')) <= 160 and args.get('genre', 'action') in GENRE_KEYS
            and args.get('variant', 'high') == 'high' and bool(re.fullmatch(r'[0-9]{0,12}', args.get('chapterId', '')))
            and bool(re.fullmatch(r'[0-9]{0,4}', args.get('page', '') + args.get('limit', ''))))


def route(url, method, data, headers):
    if method != 'GET' or data is not None:
        return None
    if url.netloc == 'www.tappytoon.com' and re.fullmatch(r'/(?:en|fr|de)', url.path) and not url.query:
        return Route({'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'})
    token, device = headers.get('Tappytoon-Token', ''), headers.get('Tappytoon-Device', '')
    if url.netloc == 'api-global.tappytoon.com' and public_api(url.netloc, url.path, url.query) \
            and TOKEN.fullmatch(token) and DEVICE.fullmatch(device):
        locale = param('?' + url.query, 'locale')
        return Route({'Accept': 'application/json', 'Authorization': token, 'X-Device-Uuid': device,
                      'Accept-Language': locale, 'Origin': 'https://www.tappytoon.com',
                      'Referer': 'https://www.tappytoon.com/'}, redirect=False)
    return None


register('tappytoon', route, public_api)


class Tappytoon(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/{identity[2]}/comics/({SEGMENT})', rf'/{identity[2]}/chapters/([1-9][0-9]{{0,11}})',
                         interval=.3)
        self.ROOT = 'https://www.tappytoon.com'
        self.locale = identity[2]
        self.session = None

    def page_headers(self, url):
        return {'Referer': 'https://www.tappytoon.com/'}

    def guest(self, http):
        cached = getattr(http, '_tappytoon_guest', None)
        if cached:
            return cached
        raw, _, _ = http.document(f'{self.ROOT}/{self.locale}', headers={'Referer': self.ROOT + '/'}, action='n9:tappytoon')
        node = BeautifulSoup(raw, 'html.parser').select_one('script#__NEXT_DATA__')
        try:
            axios = json.loads(node.string)['props']['initialState']['axios']['headers']
            token, device = axios['Authorization'], axios['X-Device-Uuid']
        except (AttributeError, KeyError, TypeError, ValueError):
            raise SourceError('Tappytoon не выдал гостевой доступ.') from None
        if not TOKEN.fullmatch(token or '') or not DEVICE.fullmatch(device or ''):
            raise SourceError('Tappytoon изменил формат гостевого доступа.')
        http._tappytoon_guest = {'Tappytoon-Token': token, 'Tappytoon-Device': device}
        return http._tappytoon_guest

    def api(self, http, path, **args):
        headers = self.guest(http)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, response_headers = http.document(query_url(API + path, **args, locale=self.locale),
                                                 headers=headers, action='n9:tappytoon')
        try:
            return json.loads(raw), response_headers
        except ValueError:
            raise SourceError('Tappytoon изменил формат API.') from None

    def title_url(self, slug, comic_id):
        return query_url(f'{self.ROOT}/{self.locale}/comics/{slug}', mv_comic=str(comic_id))

    def is_title(self, url):
        return super().is_title(url) and bool(re.fullmatch(r'[1-9][0-9]{0,9}', param(url, 'mv_comic')))

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(r'[1-9][0-9]{0,9}', param(url, 'mv_comic')))

    def title_for(self, url):
        return query_url(f'{self.ROOT}/{self.locale}/comics/{param(url, "mv_slug")}', mv_comic=param(url, 'mv_comic'))

    def title_identity(self, value):
        return param(value, 'mv_comic') or super().title_identity(value)

    def saved_title_url(self, url):
        # Suwayomi stored "slug|id".
        if isinstance(url, str) and re.fullmatch(rf'{SEGMENT}\|[1-9][0-9]{{0,9}}', url):
            slug, comic = url.split('|')
            return self.title_url(slug, comic)
        return self.canonical(url)

    def saved_chapter(self, row, root, title):
        value = str(row.get('realUrl') or row.get('url') or '')
        if re.fullmatch(r'[1-9][0-9]{0,11}', value) and self.is_title(title):
            return query_url(f'{self.ROOT}/{self.locale}/chapters/{value}', mv_comic=param(title, 'mv_comic'),
                             mv_slug=self.title_key(title))
        return super().saved_chapter(row, root, title)

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'mv_comic') == param(title, 'mv_comic')

    def record_from(self, item):
        if not isinstance(item, dict) or type(item.get('id')) is not int or not isinstance(item.get('slug'), str):
            return None
        if not item.get('isAccessible', True) or not isinstance(item.get('title'), str):
            return None
        names = lambda key: [n['name'] for n in item.get(key) or [] if isinstance(n, dict) and isinstance(n.get('name'), str)]
        status = 'completed' if item.get('isCompleted') else 'hiatus' if item.get('isHiatus') else 'ongoing'
        row = self.record(self.title_url(item['slug'], item['id']), item['title'].strip(), item.get('posterThumbnailUrl') or '',
                          description=(item.get('longDescription') or '').strip(), genres=names('genres'),
                          authors=names('authors'), status=status)
        row['format'] = 'manhwa'
        rating = (item.get('ageRating') or {}).get('name') if isinstance(item.get('ageRating'), dict) else ''
        if isinstance(rating, str) and re.search(r'18|mature', rating, re.I):
            row['adult'] = True
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in GENRE_KEYS:
            return [], False
        if tag:
            args = {'genre': tag, 'limit': '50', 'page': str(page)}
        elif query:
            args = {'keyword': query, 'page': str(page)}
        elif page > 1:
            return [], False
        elif sort == 'updated':
            args = {'day_of_week': datetime.utcnow().strftime('%a').lower()}
        else:
            args = {'sort_by': 'trending', 'filter': 'completed'}
        data, headers = self.api(http, '/comics', **args)
        if not isinstance(data, list):
            raise SourceError('Tappytoon изменил формат каталога.')
        rows = [row for row in map(self.record_from, data) if row]
        return rows, bool(rows and 'rel="next"' in headers.get('Link', ''))

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for label, key in GENRES]

    def series(self, http, url):
        comic = param(url, 'mv_comic')
        slug = self.title_key(url)
        item, _ = self.api(http, f'/comics/{comic}')
        row = self.record_from(item)
        if not row or param(row['url'], 'mv_comic') != comic:
            raise SourceAccessError('Tappytoon не открывает этот тайтл гостям.')
        slug = self.title_key(row['url'])
        data, _ = self.api(http, f'/comics/{comic}/chapters')
        if not isinstance(data, list):
            raise SourceError('Tappytoon не предоставил список глав.')
        chapters = []
        for item in data:
            if not isinstance(item, dict) or type(item.get('id')) is not int or not item.get('isAccessible'):
                continue
            if not item.get('isFree'):
                continue
            name = str(item.get('title') or '')
            if item.get('subtitle'):
                name += ' - ' + str(item['subtitle'])
            date = ''
            try:
                date = datetime.fromisoformat(str(item.get('willAccessibleAt', '')).replace('Z', '+00:00')).date().isoformat()
            except ValueError:
                pass
            order = item.get('order')
            target = query_url(f'{self.ROOT}/{self.locale}/chapters/{item["id"]}', mv_comic=comic, mv_slug=slug)
            chapters.append(self.chapter(target, name, float(order) + 1 if isinstance(order, (int, float)) else None, date))
        return row, self.order({c['url']: c for c in chapters})

    def pages(self, http, url):
        data, _ = self.api(http, '/content-delivery/contents', chapterId=self.chapter_key(url), variant='high')
        media = data.get('media') if isinstance(data, dict) else None
        if not isinstance(media, list):
            raise SourceAccessError('Tappytoon не открыл эту главу гостям.')
        return [item['path'] for item in media if isinstance(item, dict) and isinstance(item.get('path'), str)]


SOURCES = tuple(Tappytoon((sid, 'Tappytoon', lang, f'https://www.tappytoon.com/{lang}', True)) for sid, lang in (
    ('7049142072741547166', 'en'), ('8311223969496865438', 'fr'), ('8708489334089410870', 'de')))
