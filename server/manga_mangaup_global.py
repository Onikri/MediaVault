"""Manga UP! global (keiyoushi ``src/all/mangaup`` at 6f345a8).

The web client reads Protobuf from ``global-api.manga-up.com/api``: the full
title list (sorted locally by bookmarks or update date), word and tag
search, title details and the viewer. Guests send no ``secret``; only
chapters without a price open (the others stay listed as paid), because the viewer returns no pages
for the others. Page images are AES-CBC encrypted with the key and IV of
the same viewer response, decoded like the extension's ``ImageInterceptor``.
"""

from datetime import datetime
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries
from manga_japanese_next import AesCbcPage
from manga_million_wire import Message
from manga_ninth_routes import Route, register
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError, SourceTemporaryError

ROOT = 'https://global.manga-up.com'
API = 'https://global-api.manga-up.com/api/'
IMAGES = 'https://global-img.manga-up.com'
ID = r'[1-9][0-9]{0,9}'
HEX = re.compile(r'[0-9a-f]{32}|[0-9a-f]{64}')
TAGS = (('13', 'Action'), ('14', 'Adventure'), ('15', 'Comedy'), ('16', 'School Life'), ('17', 'Dark Fantasy'),
        ('18', 'Suspense'), ('19', 'Historical'), ('20', 'Game'), ('21', 'Media Tie-ins'), ('253', 'LGBTQ+'),
        ('256', 'Completed'))
TAG_KEYS = frozenset(key for key, _ in TAGS)
COMMON = {'app_ver': '0', 'os_ver': '0'}
ROUTES = {
    'search': {'lang'},
    'manga/search': {'word', 'lang'},
    'manga/tag': {'tag_id', 'lang'},
    'manga/detail_v2': {'title_id', 'quality', 'ui_lang'},
    'manga/viewer_v2': {'chapter_id', 'quality', 'lang'},
}


def accepted(name, query, method):
    names = ROUTES.get(name)
    if names is None or (method == 'POST') != (name == 'manga/viewer_v2'):
        return False
    try:
        rows = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
    except ValueError:
        return False
    args = dict(rows)
    if len(rows) != len(args) or set(args) != names | set(COMMON) or any(args[key] != value for key, value in COMMON.items()):
        return False
    if args.get('lang', 'en') != 'en' or args.get('ui_lang', 'en') != 'en' or args.get('quality', 'high') != 'high':
        return False
    return (1 <= len(args.get('word', 'x')) <= 160 and args.get('tag_id', '13') in TAG_KEYS
            and all(re.fullmatch(ID, args.get(key, '1')) for key in ('title_id', 'chapter_id')))


def route(url, method, data, headers):
    if url.netloc != 'global-api.manga-up.com' or not url.path.startswith('/api/'):
        return None
    name = url.path.removeprefix('/api/')
    if not accepted(name, url.query, method) or data not in (None, b''):
        return None
    return Route(headers={'Accept': 'application/protobuf, */*', 'Origin': ROOT, 'Referer': ROOT + '/'},
                 post=method == 'POST', data=b'' if method == 'POST' else None, redirect=False)


register('mangaup-global', route)


def date_of(value):
    try:
        return datetime.strptime(value, '%b %d, %Y')
    except ValueError:
        return None


class MangaUpGlobal(JsonSeries):
    def __init__(self):
        super().__init__(('7689478295161479290', 'Manga UP!', 'en', ROOT, False), rf'/manga/({ID})', rf'/manga/({ID})/({ID})',
                         hosts=('www.global.manga-up.com',), interval=.35)

    def title_for(self, url):
        return f'{ROOT}/manga/{self.chapter_key(url)}'

    def chapter_identity(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match.groups() if match else ()

    def saved_title_url(self, value):
        # Suwayomi stored the bare title ID (older versions "/manga/<id>").
        target = self.canonical(value)
        key = urlsplit(target).path.strip('/').removeprefix('manga/')
        return f'{ROOT}/manga/{key}' if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        value = str(row.get('url') or '').strip('/')
        key = self.title_key(title)
        return f'{ROOT}/manga/{key}/{value}' if re.fullmatch(ID, value) and key else ''

    def call(self, http, name, post=False, **args):
        from manga_mangaplus import MAX_DOCUMENT
        from requests import RequestException

        target = query_url(API + name, **COMMON, **args)
        self.origin.wait(getattr(http, 'deadline', None))
        response, final = http._open(target, method='POST' if post else 'GET', data=b'' if post else None,
                                     headers={'Referer': ROOT + '/'}, action='n9:mangaup-global')
        try:
            if final != target:
                raise SourceError('Manga UP! перенаправил запрос.')
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > MAX_DOCUMENT:
                    raise SourceError('Manga UP! превысил лимит ответа.')
            return Message(bytes(raw), 'Manga UP!')
        except RequestException:
            raise SourceTemporaryError('Manga UP! прервал выдачу данных.') from None
        finally:
            response.close()

    def title_row(self, item, **extra):
        key, name, cover = item.integer(1), item.string(2), item.string(3)
        if not 1 <= key < 10 ** 10 or not name:
            return None
        return self.record(f'{ROOT}/manga/{key}', name.strip(), IMAGES + cover if cover.startswith('/') else '', **extra)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page > 1 or tag and tag not in TAG_KEYS:
            return [], False
        if query:
            items = list(self.call(http, 'manga/search', word=query, lang='en').messages(1))
        elif tag:
            items = list(self.call(http, 'manga/tag', tag_id=tag, lang='en').messages(1))
        else:
            items = list(self.call(http, 'search', lang='en').messages(2))
            if sort == 'updated':
                items.sort(key=lambda item: date_of(item.string(9)) or datetime.min, reverse=True)
            else:
                items.sort(key=lambda item: item.integer(7), reverse=True)
        return [row for item in items if (row := self.title_row(item))], False

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for key, label in TAGS]

    def series(self, http, url):
        key = self.title_key(url)
        data = self.call(http, 'manga/detail_v2', title_id=key, quality='high', ui_lang='en')
        name = data.string(3)
        if not name:
            raise SourceError('Manga UP! не предоставил карточку тайтла.')
        chapters = list(data.messages(13))
        description = '\n\n'.join(value for value in (data.string(8), data.string(5), data.string(6), data.string(7)) if value)
        cover = data.string(11)
        row = self.record(f'{ROOT}/manga/{key}', name.strip(), IMAGES + cover if cover.startswith('/') else '',
                          description=description, genres=[tag.string(2) for tag in data.messages(10)],
                          authors=[data.string(4)], status='completed' if any(item.integer(12) for item in chapters) else 'ongoing')
        rows = {}
        for item in chapters:
            cid = item.integer(1)
            if not 1 <= cid < 10 ** 10:
                continue
            title = item.string(2) + (f' - {item.string(3)}' if item.string(3) else '')
            date = date_of(item.string(9))
            target = f'{ROOT}/manga/{key}/{cid}'
            rows[target] = {**self.chapter(target, title, None, date.date().isoformat() if date else ''), 'season': 1,
                            'locked': bool(item.fields.get(6))}
        return row, self.order(rows)

    def pages(self, http, url):
        _, chapter = self.chapter_identity(url)
        data = self.call(http, 'manga/viewer_v2', post=True, chapter_id=chapter, quality='high', lang='en')
        block = next((item for item in data.messages(3) if str(item.integer(1)) == chapter), None)
        pages = [page for page in block.messages(3) if 'tutorial' not in page.string(1)] if block else []
        if not pages:
            raise SourceAccessError('Глава Manga UP! доступна только после покупки.')
        refs = []
        for page in pages:
            path, key, iv = page.string(1), page.string(5), page.string(6)
            if not path.startswith('/') or '//' in path or not HEX.fullmatch(key) or not re.fullmatch(r'[0-9a-f]{32}', iv):
                raise SourceError('Manga UP! изменил формат страниц.')
            refs.append((IMAGES + path, AesCbcPage(bytes.fromhex(key), bytes.fromhex(iv))))
        return remember(refs, url)


SOURCES = (MangaUpGlobal(),)
