"""WebNovel comics (keiyoushi ``src/en/webnovel`` at 6f345a8).

The ``/go/pcm`` API of www.webnovel.com answers the comic category list,
search, details, the chapter list and chapter contents. Every call carries
the ``_csrfToken`` that the home page sets as a guest cookie, exactly like
the extension's CSRF interceptor. Only chapters open to a guest are listed
(free, or premium chapters the site marks as authorised); privileged early
chapters above the guest level stay hidden like upstream. Page links are
signed for about ten minutes.
"""

import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://www.webnovel.com'
API = ROOT + '/go/pcm'
ID = r'[1-9][0-9]{5,24}'
TOKEN = re.compile(r'[A-Za-z0-9-]{8,80}')
SORTS = {'popular': '1', 'updated': '5'}
GENRES = (
    ('60002', 'Action'), ('60014', 'Adventure'), ('60011', 'Comedy'), ('60009', 'Cooking'), ('60027', 'Diabolical'),
    ('60024', 'Drama'), ('60006', 'Eastern'), ('60022', 'Fantasy'), ('60017', 'Harem'), ('60018', 'History'),
    ('60015', 'Horror'), ('60013', 'Inspiring'), ('60029', 'LGBT+'), ('60016', 'Magic'), ('60008', 'Mystery'),
    ('60003', 'Romance'), ('60007', 'School'), ('60004', 'Sci-fi'), ('60019', 'Slice of Life'), ('60023', 'Sports'),
    ('60012', 'Transmigration'), ('60005', 'Urban'), ('60010', 'Wuxia'),
)
GENRE_KEYS = frozenset(key for key, _ in GENRES)
API_ROUTES = {
    '/category/categoryAjax': {'categoryType', 'pageIndex', 'categoryId', 'bookStatus', 'orderBy', '_csrfToken'},
    '/search/result': {'type', 'pageIndex', 'keywords', '_csrfToken'},
    '/comic/getComicDetailPage': {'comicId', '_csrfToken'},
    '/comic/getChapterList': {'comicId', '_csrfToken'},
    '/comic/getContent': {'comicId', 'chapterId', 'width', '_csrfToken'},
}


def api_args(path, query):
    names = API_ROUTES.get(path.removeprefix('/go/pcm'))
    if names is None:
        return None
    try:
        rows = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
    except ValueError:
        return None
    args = dict(rows)
    if len(rows) != len(args) or set(args) != names or not TOKEN.fullmatch(args['_csrfToken']):
        return None
    page = args.get('pageIndex', '1')
    if not re.fullmatch(r'[1-9][0-9]{0,3}', page):
        return None
    if 'categoryType' in args:
        ok = (args['categoryType'] == '2' and args['orderBy'] in SORTS.values() and args['bookStatus'] == ''
              and args['categoryId'] in GENRE_KEYS | {''})
    elif 'keywords' in args:
        ok = args['type'] == 'manga' and 1 <= len(args['keywords']) <= 160
    else:
        ok = (bool(re.fullmatch(ID, args['comicId'])) and args.get('width', '9999') == '9999'
              and bool(re.fullmatch(ID, args.get('chapterId', '100000'))))
    return args if ok else None


def route(url, method, data, headers):
    if url.netloc != 'www.webnovel.com' or method != 'GET' or data is not None:
        return None
    if url.path == '/' and not url.query:
        return Route(headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}, cookies=True, redirect=False)
    if api_args(url.path, url.query) is not None:
        return Route(headers={'Accept': 'application/json, text/javascript, */*; q=0.01', 'X-Requested-With': 'XMLHttpRequest',
                              'Referer': ROOT + '/'}, cookies=True, redirect=False)
    return None


register('webnovel', route)


def cover(comic, updated):
    return f'https://book-pic.webnovel.com/bookcover/{comic}?imageId={updated}&imageMogr2/thumbnail/1024x'


class WebNovel(JsonSeries):
    def __init__(self):
        super().__init__(('4081135203808920563', 'WebNovel', 'en', ROOT, False), rf'/comic/({ID})', rf'/comic/({ID})/({ID})',
                         interval=.3)

    def title_for(self, url):
        return f'{ROOT}/comic/{self.chapter_key(url)}'

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.groups() if match else ()

    def saved_title_url(self, value):
        target = self.canonical(value)
        if self.is_title(target):
            return target
        # Suwayomi stored the bare comic ID.
        key = urlsplit(target).path.strip('/')
        return f'{ROOT}/comic/{key}' if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        value = str(row.get('url') or '')
        found = re.fullmatch(rf'/?({ID}):({ID})', value)
        if found and found[1] == self.title_key(title):
            return f'{ROOT}/comic/{found[1]}/{found[2]}'
        return super().saved_chapter(row, root, title)

    def token(self, http):
        token = getattr(http, '_webnovel_csrf', None)
        if token:
            return token
        self.origin.wait(getattr(http, 'deadline', None))
        http.document(ROOT + '/', headers={'Referer': ROOT + '/'}, action='n9:webnovel')
        token = http.session.cookies.get('_csrfToken', domain='.webnovel.com') or http.session.cookies.get('_csrfToken')
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise SourceError('WebNovel не выдал гостевой токен.')
        http._webnovel_csrf = token
        return token

    def api(self, http, path, **args):
        token = self.token(http)
        self.origin.wait(getattr(http, 'deadline', None))
        raw, _, _ = http.document(query_url(API + path, **args, _csrfToken=token), headers={}, action='n9:webnovel')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('WebNovel изменил формат API.') from None
        if not isinstance(data, dict) or data.get('code') != 0 or not isinstance(data.get('data'), dict):
            raise SourceError('WebNovel отклонил запрос API.')
        return data['data']

    def item_row(self, item, key='bookId'):
        if not isinstance(item, dict) or not re.fullmatch(ID, str(item.get(key, ''))) or not item.get('bookName'):
            return None
        updated = item.get('coverUpdateTime', item.get('CV', 0))
        return self.record(f'{ROOT}/comic/{item[key]}', str(item['bookName']).strip(), cover(item[key], updated),
                           description=str(item.get('description') or ''), genres=[item.get('categoryName') or ''],
                           authors=[item.get('authorName') or ''])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in GENRE_KEYS:
            return [], False
        if query:
            data = self.api(http, '/search/result', type='manga', pageIndex=str(page), keywords=query)
            block = data.get('comicInfo') if isinstance(data.get('comicInfo'), dict) else {}
            items, key = block.get('comicItems'), 'comicId'
        else:
            block = self.api(http, '/category/categoryAjax', categoryType='2', pageIndex=str(page), categoryId=tag,
                             bookStatus='', orderBy=SORTS['updated' if sort == 'updated' else 'popular'])
            items, key = block.get('items'), 'bookId'
        if not isinstance(items, list):
            raise SourceError('WebNovel изменил формат каталога.')
        rows = [row for item in items if (row := self.item_row(item, key))]
        return rows, block.get('isLast') == 0

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for key, label in GENRES]

    def series(self, http, url):
        comic = self.title_key(url)
        info = self.api(http, '/comic/getComicDetailPage', comicId=comic).get('comicInfo')
        if not isinstance(info, dict) or str(info.get('comicId')) != comic or not info.get('comicName'):
            raise SourceError('WebNovel не предоставил карточку тайтла.')
        status = {1: 'ongoing', 2: 'completed', 3: 'hiatus'}.get(info.get('actionStatus'), '')
        row = self.record(f'{ROOT}/comic/{comic}', str(info['comicName']).strip(), cover(comic, info.get('CV', 0)),
                          description=str(info.get('description') or ''), genres=[info.get('categoryName') or ''],
                          authors=[info.get('authorName') or ''], status=status)
        data = self.api(http, '/comic/getChapterList', comicId=comic)
        items = data.get('comicChapters')
        if not isinstance(items, list):
            raise SourceError('WebNovel не предоставил список глав.')
        chapters = {}
        for item in items:
            if not isinstance(item, dict) or not re.fullmatch(ID, str(item.get('chapterId', ''))):
                continue
            levels = item.get('userLevel'), item.get('chapterLevel')
            if not all(type(value) is int for value in levels) or levels[0] < levels[1]:
                continue
            if (item.get('isVip') or item.get('price')) and item.get('isAuth') != 1:
                continue
            index = item.get('chapterIndex')
            target = f'{ROOT}/comic/{comic}/{item["chapterId"]}'
            chapters[target] = {**self.chapter(target, str(item.get('chapterName') or f'Chapter {index}'),
                                               float(index) if type(index) is int else None), 'season': 1}
        return row, self.order(chapters)

    def pages(self, http, url):
        comic, chapter = self.chapter_identity(url)
        data = self.api(http, '/comic/getContent', comicId=comic, chapterId=chapter, width='9999')
        info = data.get('chapterInfo') if isinstance(data.get('chapterInfo'), dict) else {}
        pages = []
        for page in info.get('chapterPage') or []:
            link = page.get('url') if isinstance(page, dict) else None
            target = urlsplit(link or '')
            if target.scheme != 'https' or target.netloc != 'comic-image.webnovel.com' or not param(link, 'sign'):
                raise SourceError('WebNovel изменил адрес страниц.')
            pages.append(link)
        if not pages:
            raise SourceAccessError('Глава WebNovel закрыта для открытого чтения.')
        return pages


SOURCES = (WebNovel(),)
