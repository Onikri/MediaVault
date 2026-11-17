"""WebComics app catalogue (keiyoushi ``src/all/webcomics`` at 6f345a8).

Listings come from the Nuxt payload of the site's genre pages; details,
chapters, free chapter images and text search use the public JSON API with
the site's language id header. Paid chapters stay out of open reading.
"""

from datetime import datetime, timezone
import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://webcomicsapp.com'
API = 'https://official-website-api.webcomicsapp.com/api/web/v4/book'
BOOK = re.compile(r'[0-9a-f]{24}')
LANG_IDS = {'en': '0', 'fr': '5', 'pt': '6', 'es': '7', 'id': '1'}
GENRE_TITLE = {'en': 'Genres', 'fr': 'Genres', 'pt': 'Gêneros', 'es': 'Géneros', 'id': 'Genre'}
GENRES = {
    'en': ('All', 'Romance', 'Action', 'Fantasy', 'BL', 'Eastern Fantasy', 'Eastern Romance', 'Drama', 'GL', 'LGBTQ+',
           'Slice of Life', 'Comedy', 'Horror', 'Mystery', 'Sci-Fi'),
    'fr': ('Tous', 'Amour', 'Action', 'Fantaisie', 'BL', 'Fantaisie orientale', 'Amour orientale', 'Drame', 'Comédie',
           'Science-fiction'),
    'pt': ('Todos', 'Romance', 'Ação', 'Fantasia', 'BL', 'Fantasia Oriental Antiga', 'Romance Oriental Antigo', 'Drama',
           'Humor', 'Ficção'),
    'es': ('Todos', 'Romance', 'Acción', 'Fantasía', 'BL', 'Fantasía Oriental', 'Romance Oriental', 'Drama', 'Comedia',
           'Ciencia Ficción'),
    'id': ('Semua', 'Romantis', 'Aksi', 'Fantasi', "Boys' Love", 'Fantasi Asia', 'Romantis Asia', 'Drama', 'Komedi',
           'Sci-Fi'),
}
STATUSES = {'en': ('All', 'Ongoing', 'Completed'), 'fr': ('Tous', 'Sérialisé', 'Terminé'),
            'pt': ('Todos', 'Em série', 'Concluído'), 'es': ('Todos', 'En curso', 'Terminado'),
            'id': ('Semua', 'Berlangsung', 'Tamat')}
SORTS = {'en': ('Hottest', 'Best-rated', 'Newest'), 'fr': ('Top', 'Mieux notés', 'Nouveautés'),
         'pt': ('Mais populares', 'Mais avaliados', 'Mais recentes'), 'es': ('Populares', 'Mejor calificados', 'Más nuevos'),
         'id': ('Terpopuler', 'Rating Tertinggi', 'Terbaru')}
FORMS = {
    '/info': {'book_id'},
    '/chapter/list': {'book_id', 'page', 'size', 'sort'},
    '/chapter/detail': {'book_id', 'chapter_id', 'index'},
    '/search': {'word', 'page', 'size'},
}


def path_segment(value):
    return re.sub(r'\s+', '-', re.sub(r'''[!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~]''', '', value)).lower()


def slug(value):
    return re.sub(r'[^\w]+', '-', value.lower()).strip('-')


def valid_form(path, data):
    fields = FORMS.get(path)
    if not isinstance(data, dict) or fields is None or set(data) != fields:
        return False
    if 'book_id' in data and not BOOK.fullmatch(str(data['book_id'])):
        return False
    if 'chapter_id' in data and not BOOK.fullmatch(str(data['chapter_id'])):
        return False
    if 'index' in data and not (type(data['index']) is int and 0 <= data['index'] <= 100000):
        return False
    if path == '/chapter/list':
        return data['page'] == 1 and data['size'] == 9999 and data['sort'] == 'desc'
    if path == '/search':
        return (isinstance(data['word'], str) and 0 < len(data['word']) <= 160 and data['size'] == 20
                and type(data['page']) is int and 1 <= data['page'] <= 500)
    return True


def route(url, method, data, headers):
    language = headers.get('Webcomics-Language', '')
    if (method != 'POST' or url.netloc != 'official-website-api.webcomicsapp.com' or url.query
            or not url.path.startswith('/api/web/v4/book') or language not in LANG_IDS.values()):
        return None
    path = url.path[len('/api/web/v4/book'):]
    if not valid_form(path, data):
        return None
    return Route({'lang': language, 'Content-Type': 'application/json', 'Accept': 'application/json',
                  'Origin': ROOT, 'Referer': ROOT + '/'}, post=True,
                 data=json.dumps(data, separators=(',', ':'), ensure_ascii=False).encode(), redirect=False)


def public_api(host, path, query):
    return host == 'official-website-api.webcomicsapp.com' and path[len('/api/web/v4/book'):] in FORMS and not query


register('webcomicsapp', route, public_api)


def unflatten(values, index, depth=0):
    if depth > 64 or type(index) is not int or not 0 <= index < len(values):
        return None
    value = values[index]
    if isinstance(value, dict):
        return {key: unflatten(values, item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        if value and value[0] in {'Reactive', 'ShallowReactive', 'Ref', 'ShallowRef'} and len(value) == 2:
            return unflatten(values, value[1], depth + 1)
        return [unflatten(values, item, depth + 1) for item in value]
    return value


class WebComicsApp(JsonSeries):
    def __init__(self, identity):
        lang = identity[2]
        super().__init__(identity, rf'/{lang}/([^/]{{1,200}}/[^/]{{1,300}}/[0-9a-f]{{24}})',
                         rf'/{lang}/([^/]{{1,200}}/[^/]{{1,300}}/[0-9]{{1,6}}/[0-9a-f]{{24}})', interval=1 / 3)
        self.lang = lang
        self.lang_id = LANG_IDS[lang]

    def book_id(self, url):
        return urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]

    def title_for(self, url):
        parts = urlsplit(url).path.strip('/').split('/')
        return f'{ROOT}/{"/".join(parts[:3])}/{parts[4]}' if len(parts) == 5 else ''

    def title_identity(self, value):
        return self.book_id(value)

    def chapter_identity(self, url):
        return param(url, 'mv_chapter') or urlsplit(url).path

    def saved_chapter(self, row, root, title):
        value = str(row.get('realUrl') or row.get('url') or '')
        if BOOK.fullmatch(value) and self.is_title(title):
            prefix = urlsplit(title).path.rstrip('/').rsplit('/', 1)[0]
            return query_url(f'{ROOT}{prefix}/0/{self.book_id(title)}', mv_chapter=value)
        return super().saved_chapter(row, root, title)

    def saved_title_url(self, url):
        if isinstance(url, str) and BOOK.fullmatch(url):
            return f'{ROOT}/{self.lang}/comic/comic/{url}'
        return self.canonical(url)

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.book_id(target) == self.book_id(title)

    def api(self, http, path, body):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(API + path, method='POST', data=body,
                                  headers={'Webcomics-Language': self.lang_id}, action='n9:webcomicsapp')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('WebComics изменил формат API.') from None
        if not isinstance(data, dict):
            raise SourceError('WebComics изменил формат API.')
        return data.get('code'), data.get('data')

    def title_url(self, book, category, name):
        return f'{ROOT}/{self.lang}/{slug(category) or "comic"}/{slug(name) or "comic"}/{book}'

    def card(self, item):
        if not isinstance(item, dict) or not BOOK.fullmatch(str(item.get('book_id', ''))) or not isinstance(item.get('name'), str):
            return None
        categories = item.get('sub_title') or item.get('category') or []
        if isinstance(categories, str):
            categories = re.findall(r"'([^']+)'", categories) or [categories]
        categories = [c for c in categories if isinstance(c, str)]
        url = self.title_url(item['book_id'], categories[0] if categories else '', item['name'])
        row = self.record(url, item['name'].strip(), item.get('cover') or '', genres=categories)
        row['format'] = 'manhwa'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            code, data = self.api(http, '/search', {'word': query, 'page': page, 'size': 20})
            if code != 1000 or not isinstance(data, dict):
                raise SourceError('WebComics не выполнил поиск.')
            items, more = data.get('list') or [], bool((data.get('pagination') or {}).get('next'))
        else:
            genres = GENRES[self.lang]
            if tag and tag not in genres:
                return [], False
            order = SORTS[self.lang][2 if sort in {'updated', 'new'} else 1 if sort == 'rating' else 0]
            path = '/'.join(path_segment(part) for part in (GENRE_TITLE[self.lang], tag or genres[0],
                                                            STATUSES[self.lang][0], order))
            raw, _, _ = http.document(f'{ROOT}/{self.lang}/{path}/{page}', headers={'Referer': ROOT + '/'})
            node = BeautifulSoup(raw, 'html.parser').select_one('script#__NUXT_DATA__')
            try:
                values = json.loads(node.string)
            except (AttributeError, TypeError, ValueError):
                raise SourceError('WebComics изменил формат каталога.') from None
            index = next((i for i, v in enumerate(values) if isinstance(v, dict) and 'list' in v and 'pagination' in v), None)
            listing = unflatten(values, index) if index is not None else None
            if not isinstance(listing, dict):
                return [], False
            items, more = listing.get('list') or [], bool((listing.get('pagination') or {}).get('next'))
        rows = [row for row in map(self.card, items) if row]
        return rows, more and bool(rows)

    def vocabulary(self, http):
        return [{'key': name, 'label': name, 'kind': 'genre'} for name in GENRES[self.lang][1:]]

    def series(self, http, url):
        book = self.book_id(url)
        code, data = self.api(http, '/info', {'book_id': book})
        if code != 1000 or not isinstance(data, dict) or not isinstance(data.get('name'), str):
            raise SourceError('WebComics не предоставил карточку тайтла.')
        categories = data.get('category')
        if isinstance(categories, str):
            categories = re.findall(r"'([^']+)'", categories)
        categories = [c for c in categories or [] if isinstance(c, str)]
        title = self.title_url(book, categories[0] if categories else '', data['name'])
        row = self.record(title, data['name'].strip(), data.get('cover') or '', description=str(data.get('description') or ''),
                          genres=categories, authors=[a for a in str(data.get('author') or '').split('+') if a],
                          status='ongoing' if data.get('status') == STATUSES[self.lang][1] else 'completed')
        row['format'] = 'manhwa'
        code, listing = self.api(http, '/chapter/list', {'book_id': book, 'page': 1, 'size': 9999, 'sort': 'desc'})
        if code != 1000 or not isinstance(listing, dict):
            raise SourceError('WebComics не предоставил список глав.')
        prefix = urlsplit(title).path.rstrip('/').rsplit('/', 1)[0]
        chapters = []
        for item in listing.get('list') or []:
            if not isinstance(item, dict) or item.get('is_pay') or not BOOK.fullmatch(str(item.get('chapter_id', ''))):
                continue
            if type(item.get('index')) is not int:
                continue
            stamp = item.get('update_time')
            date = datetime.fromtimestamp(stamp / 1000, timezone.utc).date().isoformat() if type(stamp) is int and stamp > 0 else ''
            target = query_url(f'{ROOT}{prefix}/{item["index"]}/{book}', mv_chapter=item['chapter_id'])
            chapters.append(self.chapter(target, str(item.get('name') or ''), float(item['index']), date))
        return row, self.order({c['url']: c for c in chapters})

    def pages(self, http, url):
        chapter = param(url, 'mv_chapter')
        index = int(urlsplit(url).path.rstrip('/').split('/')[-2])
        code, data = self.api(http, '/chapter/detail', {'book_id': self.book_id(url), 'chapter_id': chapter, 'index': index})
        if code == 1208:
            raise SourceAccessError('Глава WebComics платная.')
        if code != 1000 or not isinstance(data, dict) or not isinstance(data.get('base_url'), str):
            raise SourceError('WebComics не открыл главу.')
        return [data['base_url'] + item['url'] for item in data.get('images') or []
                if isinstance(item, dict) and isinstance(item.get('url'), str)]


SOURCES = tuple(WebComicsApp((sid, 'Webcomics', lang, ROOT, False)) for sid, lang in (
    ('5830834696627804450', 'en'), ('5885774493166465039', 'fr'), ('3396104446323720599', 'pt'),
    ('8965174723997547979', 'es'), ('1203016038113719139', 'id')))
