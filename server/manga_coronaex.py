"""Corona EX public catalogue and images from open chapters."""

from base64 import b64decode
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
import re
from threading import Lock
from time import monotonic
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from PIL import Image

from manga_clipstudio import json_data
from manga_direct_payloads import JsonSeries
from manga_dynasty import entries
from manga_madara import image_url, release_date
from manga_mangaplus import XorPage
from manga_series_port import SeriesPort, number
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://to-corona-ex.com'
API = 'https://api.to-corona-ex.com'
ID = r'[1-9]\d{0,19}'
TITLE = rf'/comics/({ID})/?'
CHAPTER = rf'/episodes/({ID})/?'
APP_SCRIPT = re.compile(r'/_next/static/chunks/pages/_app-[a-f0-9]{8,36}\.js')
APP_KEY = re.compile(r'''["']X-API-Environment-Key["']\]\s*=\s*["']([A-Za-z0-9._~+/=-]{6,150})["']''', re.I)
KEY_VALUE = re.compile(r'[A-Za-z0-9._~+/=-]{6,150}')
GENRES = dict(zip(('41114554925057', '41114574733314', '41114587152387', '41114611564548', '233327015772195',
                   '234901641199652', '235983585656869', '235983604236326', '235983620751399',
                   '235983640330280', '235983659499561', '235983673786410', '235983689498667',
                   '235983706292268', '235983724527661', '235983737339950', '235983751118895',
                   '235983762554928', '235983773859889', '235983791898674', '235983807610931',
                   '235983822307380', '236305616191542'),
                  ('少女マンガ', '青年マンガ', '少年マンガ', '4コママンガ', 'Celicaコミックス', '女性マンガ',
                   'コロナ・コミックス', '完結', '特別短期連載', 'アニメ化', 'オリジナル作品', '恋愛', 'ファンタジー',
                   '異世界・転生', 'VRゲーム', 'ほのぼの', 'ハーレム', 'グルメ', '学園・青春', '悪役令嬢',
                   'ホラー・ミステリー', '歴史・時代', 'バトル・アクション')))


def public_api(host, path, query):
    if host != 'api.to-corona-ex.com':
        return False
    if re.fullmatch(rf'/comics/{ID}|/episodes/{ID}/begin_reading', path):
        return not query
    raw = parse_qsl(query)
    args = dict(raw)
    cursor = args.pop('after_than', '')
    if len({key for key, _ in raw}) != len(raw) or len(cursor) > 2000:
        return False
    if path == '/search/comics':
        return set(args) == {'keyword', 'limit'} and args['limit'] == '24' and 1 <= len(args['keyword']) <= 160
    if path == '/comics':
        genre = args.pop('genre_id', '')
        return (not genre or genre in GENRES) and args in (
            {'limit': '24', 'order': 'asc', 'sort': 'title_yomigana'},
            {'limit': '12', 'order': 'desc', 'sort': 'latest_episode_published_at'})
    return (path == '/episodes' and bool(re.fullmatch(ID, args.get('comic_id', '')))
            and args == {'comic_id': args['comic_id'], 'episode_status': 'free_viewing,only_for_subscription',
                         'limit': '100', 'order': 'desc', 'sort': 'episode_order'})


@dataclass(frozen=True)
class CoronaPage:
    grid: bytes

    def decode(self, raw):
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > 35_000_000:
                    raise ValueError('Image exceeds limits')
                original = image.convert('RGB')
            output = original.copy()
            cols, rows = self.grid[:2]
            width, height = original.size
            x_step, y_step = width // 8 * 8 // cols, height // 8 * 8 // rows
            if not x_step or not y_step:
                raise ValueError('Invalid tile size')
            for dst, src in enumerate(self.grid[2:]):
                x, y = src % cols * x_step, src // cols * y_step
                output.paste(original.crop((x, y, x + x_step, y + y_step)),
                             (dst % cols * x_step, dst // cols * y_step))
            dest = BytesIO()
            output.save(dest, format='PNG')
            return dest.getvalue()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise SourceError('Corona EX вернул повреждённую страницу.') from None


def read_grid(value):
    try:
        data = b64decode(value.replace(' ', '+'), validate=True)
        cols, rows = data[:2]
        blocks = cols * rows
        if not 1 <= blocks <= 256 or len(data) != blocks + 2 or set(data[2:]) != set(range(blocks)):
            raise ValueError('Invalid grid')
        return data
    except (AttributeError, ValueError):
        raise SourceError('Corona EX изменил формат плиток.') from None


class CoronaEx(JsonSeries):
    def __init__(self):
        super().__init__(('4760608706245794364', 'Corona EX', 'ja', ROOT, False), TITLE, CHAPTER, interval=.35)
        self.guard = Lock()
        self._key = ('', 0.)
        self.cursors = OrderedDict()

    def environment_key(self, http):
        with self.guard:
            if self._key[1] > monotonic():
                return self._key[0]
            raw, final, _ = http.document(ROOT + '/')
            if urlsplit(final).netloc != 'to-corona-ex.com':
                raise SourceError('Corona EX перенаправил конфигурацию.')
            doc = BeautifulSoup(raw, 'html.parser')
            script = next((node['src'] for node in doc.select('script[src]') if APP_SCRIPT.fullmatch(node['src'])), None)
            if not script:
                raise SourceError('Corona EX не предоставил публичные настройки.')
            raw, final, _ = http.document(ROOT + script, headers={'Referer': ROOT + '/'})
            match = APP_KEY.search(raw) if final == ROOT + script else None
            if not match:
                raise SourceError('Corona EX изменил публичные настройки.')
            self._key = (match[1], monotonic() + 900)
            return self._key[0]

    def request(self, http, path, **params):
        self.origin.wait(getattr(http, 'deadline', None))
        target = query_url(API + path, **params) if params else API + path
        headers = {'Referer': ROOT + '/', 'Corona-Environment': self.environment_key(http)}
        raw, final, _ = http.document(target, headers=headers, action='coronaex-public')
        if final != target:
            raise SourceError('Corona EX перенаправил запрос каталога.')
        return json_data(raw)

    def title_for(self, url):
        key = param(url, 'mv_corona_title')
        return ROOT + '/comics/' + key if self.is_chapter(url) and re.fullmatch(ID, key) else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/comics/' + key if re.fullmatch(ID, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = urlsplit(url).path.strip('/')
        if re.fullmatch(ID, key):
            url = ROOT + '/episodes/' + key
        return query_url(url, mv_corona_title=self.title_key(title)) if self.is_title(title) and self.is_chapter(url) else ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title))

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def row_for(self, data):
        title, key = data.get('title'), str(data.get('id') or '')
        if not isinstance(title, str) or not title or not re.fullmatch(ID, key):
            return None
        target = ROOT + '/comics/' + key
        return self.record(target, title, image_url(data.get('cover_image_url'), target),
                           aliases=[data.get('title_alphanumeric') or '', data.get('title_yomigana') or ''],
                           description='\n\n'.join(str(data[k]) for k in ('description', 'copyright') if data.get(k)),
                           authors=[item['name'] for item in entries(data.get('authors')) if isinstance(item.get('name'), str)],
                           genres=[item['name'] for item in entries(data.get('genres')) if isinstance(item.get('name'), str)])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        path = '/search/comics' if query else '/comics'
        if query:
            args = {'keyword': query, 'limit': 24}
        elif sort == 'updated' and not tag:
            args = {'limit': 12, 'order': 'desc', 'sort': 'latest_episode_published_at'}
        else:
            args = {'limit': 24, 'order': 'asc', 'sort': 'title_yomigana'}
            if tag in GENRES:
                args['genre_id'] = tag
        key = (path, tuple(sorted(args.items())))
        with self.guard:
            index = page
            while index > 1 and (key, index) not in self.cursors and page - index < 8:
                index -= 1
            if index > 1 and (key, index) not in self.cursors:
                raise SourceError('Corona EX требует начать с первой страницы каталога.')
            cursor = self.cursors.get((key, index), '')
        data = {}
        for current in range(index, page + 1):
            data = self.request(http, path, **{**args, 'after_than': cursor or []})
            following = data.get('next_cursor')
            cursor = following if isinstance(following, str) and 0 < len(following) <= 2000 and following != cursor else ''
            if cursor:
                with self.guard:
                    self.cursors[(key, current + 1)] = cursor
                    self.cursors.move_to_end((key, current + 1))
                    if len(self.cursors) > 2048:
                        self.cursors.popitem(last=False)
            if not cursor and current < page:
                return [], False
        return [row for item in entries(data.get('resources')) if (row := self.row_for(item))], bool(cursor)

    def vocabulary(self, http):
        return [{'key': key, 'label': value, 'kind': 'genre'} for key, value in GENRES.items()]

    def series(self, http, url):
        key = self.title_key(url)
        row = self.row_for(self.request(http, '/comics/' + key))
        if not row or self.title_key(row['url']) != key:
            raise SourceError('Corona EX вернул другое произведение.')
        cursor, seen, chapters = '', set(), {}
        for _ in range(60):
            data = self.request(http, '/episodes', comic_id=key, episode_status='free_viewing,only_for_subscription',
                                limit=100, order='desc', sort='episode_order', after_than=cursor or [])
            for item in entries(data.get('resources')):
                cid = str(item.get('id') or '')
                if not re.fullmatch(ID, cid):
                    continue
                locked = item.get('episode_status') == 'only_for_subscription'
                target = query_url(ROOT + '/episodes/' + cid, mv_corona_title=key, mv_corona_locked='1' if locked else [])
                name = ('🔒 ' if locked else '') + str(item.get('title') or '')
                stamp = release_date(str(item.get('published_at') or '').partition('T')[0], '%Y-%m-%d')
                chapters[target] = self.chapter(target, name, number(item.get('episode_order')), stamp)
            following = data.get('next_cursor')
            if not isinstance(following, str) or not 0 < len(following) <= 2000 or following in seen:
                break
            seen.add(following)
            cursor = following
        return row, self.order(chapters)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        if param(url, 'mv_corona_locked'):
            raise SourceAccessError('Corona EX требует подписку для этого выпуска.')
        results = self.request(http, '/episodes/' + self.chapter_key(url) + '/begin_reading')
        refs = []
        for item in entries(results.get('pages')):
            link = image_url(item.get('page_image_url'), url)
            if not link:
                raise SourceError('Corona EX вернул неполный набор изображений.')
            marker = param(link, 'drm_hash')
            refs.append((link, CoronaPage(read_grid(marker)) if marker else XorPage(b'')))
        return remember(refs, url)


SOURCES = (CoronaEx(),)
