"""COMIC FUZ (keiyoushi ``src/ja/comicfuz`` at 6f345a8).

The web client talks Protobuf to ``api.comic-fuz.com/v1``: search (also the
popular list), tag lists, the weekday list, title details and the viewer.
Only chapters without a point price are listed, because the guest viewer
does not open the others. Viewer pages are AES-CBC encrypted with the key
and IV of the same response, decoded like the extension's ``ImageInterceptor``.
"""

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlsplit

from manga_direct_payloads import JsonSeries
from manga_japanese_next import AesCbcPage
from manga_madara import image_url
from manga_million_wire import Message
from manga_ninth_routes import Route, register
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError, SourceTemporaryError

ROOT = 'https://comic-fuz.com'
API = 'https://api.comic-fuz.com/v1/'
CDN = 'https://img.comic-fuz.com'
ID = r'[1-9][0-9]{0,9}'
HEX = re.compile(r'[0-9a-f]{32}|[0-9a-f]{64}')
TAGS = (
    (7, '日曜日'), (12, 'オリジナル'), (38, 'グルメ'), (138, 'FUZコミックス'), (288, '広告で人気の作品'),
    (462, 'オリジナル作品の最新話が無料化！'), (540, 'ギャグ・コメディ'), (552, '日常'), (23, '学園'),
    (26, 'SF・ファンタジー'), (29, '恋愛'), (13, '男性向け'), (549, '百合'), (41, 'お仕事・趣味'),
    (56, '週刊漫画TIMES'), (150, '芳文社コミックス'), (537, 'スポーツ'), (68, 'まんがタイムきららフォワード'),
    (141, 'まんがタイムKRコミックス'), (291, '新規連載作品'), (204, 'まんがタイムオリジナル'), (6, '土曜日'),
    (2, '火曜日'), (14, '女性向け'), (44, 'バトル・アクション'), (47, 'ミステリー・サスペンス'), (83, 'BL'),
    (32, 'メディア化'), (50, '歴史・時代'), (20, '４コマ'), (147, 'まんがタイムコミックス'), (5, '金曜日'),
    (543, '異世界'), (35, 'ヒューマンドラマ'), (65, 'まんがタイムきららキャラット'), (4, '木曜日'),
    (59, 'まんがタイムきらら'), (153, 'ラバココミックス'), (201, 'まんがタイム'), (3, '水曜日'),
    (62, 'まんがタイムきららMAX'), (17, '読切'), (1, '月曜日'), (74, 'ゆるキャン△'), (207, 'コミックトレイル'),
    (77, '城下町のダンデライオン'), (156, 'トレイルコミックス'), (198, 'まんがホーム'),
    (71, '魔法少女まどか☆マギカ'), (177, '花音コミックス'), (1175, '価格改定対象作品'),
)
TAG_NAMES = {str(key): label for key, label in TAGS}
TOKYO = timezone(timedelta(hours=9))


def varint(value):
    out = bytearray()
    while True:
        low, value = value & 127, value >> 7
        out.append(low | (128 if value else 0))
        if not value:
            return bytes(out)


def field(number, value):
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode('utf-8')
    return varint(number << 3 | 2) + varint(len(value)) + value


DEVICE = field(1, field(3, 2))  # DeviceInfo { deviceType = BROWSER }


def request_body(route, *values):
    """Encode the exact request messages of the extension."""
    if route == 'search':
        query, page = values
        return DEVICE + field(2, query) + field(3, page) + field(4, 1)
    if route in {'manga_list', 'manga_detail', 'mangas_by_day_of_week'}:
        return DEVICE + field(2, values[0])
    if route == 'manga_viewer':
        # useTicket = false, consumePoint = {0, 0}, viewerMode = {HIGH}
        return DEVICE + field(2, values[0]) + field(3, False) + field(4, field(1, 0) + field(2, 0)) + field(5, field(1, 1))
    raise SourceError('Некорректный запрос COMIC FUZ.')


def accepted_body(route, data):
    if not isinstance(data, bytes) or len(data) > 512:
        return False
    try:
        message = Message(data, 'COMIC FUZ')
        if route == 'search':
            query, page = message.string(2), message.integer(3)
            return 1 <= page <= 2000 and len(query) <= 160 and data == request_body(route, query, page)
        value = message.integer(2)
        if route == 'mangas_by_day_of_week':
            return 0 <= value <= 7 and data == request_body(route, value)
        return 1 <= value < 10 ** 10 and data == request_body(route, value)
    except SourceError:
        return False


def route(url, method, data, headers):
    name = url.path.removeprefix('/v1/')
    if (url.netloc != 'api.comic-fuz.com' or url.query or method != 'POST'
            or name not in {'search', 'manga_list', 'mangas_by_day_of_week', 'manga_detail', 'manga_viewer'}
            or not accepted_body(name, data)):
        return None
    return Route(headers={'Content-Type': 'application/protobuf', 'Accept': 'application/protobuf',
                          'Origin': ROOT, 'Referer': ROOT + '/'}, post=True, data=data, redirect=False)


register('comicfuz', route)


class ComicFuz(JsonSeries):
    def __init__(self):
        super().__init__(('7341666123577520203', 'COMIC FUZ', 'ja', ROOT, False),
                         rf'/manga/({ID})', rf'/manga/viewer/({ID})', interval=.4)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(ID, param(url, 'mv_title')))

    def title_for(self, url):
        key = param(url, 'mv_title')
        return f'{ROOT}/manga/{key}' if re.fullmatch(ID, key) else ''

    def chapter_identity(self, url):
        return urlsplit(url).path

    def saved_title_url(self, value):
        target = self.canonical(value)
        return target if self.is_title(target) else ''

    def saved_chapter(self, row, root, title):
        # Suwayomi stored "/manga/viewer/<chapter id>".
        target = super().saved_chapter(row, root, title)
        key = self.title_key(title)
        chapter = re.fullmatch(rf'/manga/viewer/({ID})/?', urlsplit(target).path)
        return query_url(f'{ROOT}/manga/viewer/{chapter[1]}', mv_title=key) if key and chapter else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'mv_title') == self.title_key(title)

    def call(self, http, name, *values):
        from manga_mangaplus import MAX_DOCUMENT
        from requests import RequestException

        self.origin.wait(getattr(http, 'deadline', None))
        response, final = http._open(API + name, method='POST', data=request_body(name, *values),
                                     headers={'Referer': ROOT + '/'}, action='n9:comicfuz')
        try:
            if final != API + name:
                raise SourceError('COMIC FUZ перенаправил запрос.')
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > MAX_DOCUMENT:
                    raise SourceError('COMIC FUZ превысил лимит ответа.')
            return Message(bytes(raw), 'COMIC FUZ')
        except RequestException:
            raise SourceTemporaryError('COMIC FUZ прервал выдачу данных.') from None
        finally:
            response.close()

    def manga(self, data, **extra):
        key, name = data.integer(1), data.string(2)
        if not 1 <= key < 10 ** 10 or not name:
            return None
        url = f'{ROOT}/manga/{key}'
        cover = data.string(4)
        return self.record(url, name.strip(), image_url(CDN + cover, ROOT) if cover.startswith('/') else '',
                           description=data.string(14), **extra)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and not query:
            if tag not in TAG_NAMES or page != 1:
                return [], False
            data = self.call(http, 'manga_list', int(tag))
            return [row for item in data.messages(1) if (row := self.manga(item))], False
        if sort == 'updated' and not query:
            if page != 1:
                return [], False
            data = self.call(http, 'mangas_by_day_of_week', datetime.now(TOKYO).isoweekday())
            return [row for item in data.messages(1) if (row := self.manga(item))], False
        data = self.call(http, 'search', query, page)
        rows = [row for item in data.messages(2) if (row := self.manga(item))]
        return rows, data.integer(6) > page

    def vocabulary(self, http):
        return [{'key': str(key), 'label': label, 'kind': 'genre'} for key, label in TAGS]

    def series(self, http, url):
        url = self.saved_title_url(url)
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка на тайтл COMIC FUZ.')
        data = self.call(http, 'manga_detail', int(key))
        tags = [item.string(2) for item in data.messages(7)]
        authors = [item.message(1).string(2) for item in data.messages(4)]
        row = self.manga(data.message(2), genres=tags, authors=authors)
        if row is None or self.title_key(row['url']) != key:
            raise SourceError('COMIC FUZ вернул карточку другого тайтла.')
        chapters = [item for group in data.messages(3) for item in group.messages(2)]
        rows = {}
        for index, item in enumerate(reversed(chapters), 1):
            price = next(item.messages(5), None)
            cid = item.integer(1)
            if not 1 <= cid < 10 ** 10 or price is not None and price.integer(2) > 0:
                continue
            date = ''
            try:
                date = datetime.strptime(item.string(8), '%Y/%m/%d').date().isoformat()
            except ValueError:
                pass
            target = query_url(f'{ROOT}/manga/viewer/{cid}', mv_title=key)
            rows[target] = {**self.chapter(target, item.string(2) or f'第{index}話', float(index), date), 'season': 1}
        return row, list(rows.values())

    def pages(self, http, url):
        data = self.call(http, 'manga_viewer', int(self.chapter_key(url)))
        plain, sealed = [], []
        for page in data.messages(3):
            if not page.fields.get(1):
                continue
            image = page.message(1)
            if image.integer(7):
                continue
            path, iv, key = image.string(1), image.string(3), image.string(4)
            if not path.startswith('/') or '//' in path:
                raise SourceError('COMIC FUZ изменил адрес изображений.')
            link = CDN + path
            if iv or key:
                if not HEX.fullmatch(iv) or len(iv) != 32 or not HEX.fullmatch(key):
                    raise SourceError('COMIC FUZ изменил формат страницы.')
                sealed.append((link, AesCbcPage(bytes.fromhex(key), bytes.fromhex(iv))))
            plain.append(link)
        if not plain:
            raise SourceAccessError('Глава COMIC FUZ недоступна для открытого чтения.')
        if not sealed:
            return plain
        if len(sealed) != len(plain):
            raise SourceError('COMIC FUZ смешал зашифрованные и открытые страницы.')
        return remember(sealed, url)


SOURCES = (ComicFuz(),)
