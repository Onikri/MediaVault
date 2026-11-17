"""Guest APIs of KadoComi, CyComi and Nicovideo Seiga."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text
from manga_publus_pack import rc4
from manga_rayuba import uploaded
from manga_series_port import MAX_PAGES, number
from manga_source_tags import labels
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


KADO = 'https://comic-walker.com'
CY = 'https://cycomi.com'
CY_API = 'https://web.cycomi.com/api'
NICO = 'https://sp.manga.nicovideo.jp'
NICO_API = 'https://api.nicomanga.jp/api/v1/app/manga'
NUMERIC = r'[1-9][0-9]{0,14}'
CRYPT_KEY = re.compile(r'(?:[0-9a-fA-F]{2}){1,128}')


def public_api(host, path, query):
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=6)
    except ValueError:
        return False
    args = dict(fields)
    if len(fields) != len(args):
        return False
    if host == 'comic-walker.com':
        if path in {'/api/ranking', '/api/series/new', '/api/search/keywords'}:
            if args.get('limit') != '30' or not re.fullmatch(r'[0-9]{1,5}', args.get('offset', '')):
                return False
            if path != '/api/search/keywords':
                return set(args) == {'limit', 'offset'}
            return (set(args) == {'limit', 'offset', 'keywords', 'sortBy'} and 0 < len(args['keywords']) <= 160
                    and args['sortBy'] in {'popularity', 'update'})
        if path == '/api/contents/details/work':
            return set(args) == {'workCode'} and bool(re.fullmatch(SEGMENT, args['workCode']))
        return (path == '/api/contents/viewer' and set(args) == {'episodeId', 'imageSizeType'}
                and bool(re.fullmatch(SEGMENT, args['episodeId'])) and args['imageSizeType'] == 'width:1284')
    if host == 'web.cycomi.com':
        if path == '/api/titleRanking/title/list':
            return args == {'categoryId': '1'}
        if re.fullmatch(r'/api/title/serialization/list/[0-7]', path):
            return not args
        if path == '/api/search/list/1':
            return set(args) == {'word'} and 0 < len(args['word']) <= 160
        if path in {'/api/title/detail', '/api/chapter/status/list', '/api/chapter/paginatedList'}:
            if not re.fullmatch(NUMERIC, args.get('titleId', '')):
                return False
            return args.get('sort') == '2' and len(args) == 2 if path.endswith('/paginatedList') else len(args) == 1
        return path == '/api/chapter/page/list' and not args
    if host == 'sp.manga.nicovideo.jp':
        return (path == '/manga/ajax/ranking' and set(args) == {'span', 'category', 'page'}
                and args['span'] == 'total' and args['category'] == 'all' and args['page'] in {'1', '2', '3', '4', '5'})
    if host != 'api.nicomanga.jp':
        return False
    if path == '/api/v1/app/manga/contents':
        return (set(args) == {'mode', 'sort', 'q', 'limit', 'offset'} and args['mode'] == 'keyword'
                and args['sort'] == 'score' and args['limit'] == '20' and 0 < len(args['q']) <= 160
                and bool(re.fullmatch(r'[0-9]{1,5}', args['offset'])))
    if re.fullmatch(rf'/api/v1/app/manga/contents/{NUMERIC}(?:/episodes)?', path):
        return not args
    return bool(re.fullmatch(rf'/api/v1/app/manga/episodes/{NUMERIC}/frames', path)) and args == {'enable_webp': 'true'}


def cy_viewer_form(url, raw, referer):
    if url != CY_API + '/chapter/page/list' or not isinstance(raw, bytes) or len(raw) > 100:
        return False
    match = re.fullmatch(r'/viewer/chapter/(' + NUMERIC + r')/?', urlsplit(referer).path)
    if not match or urlsplit(referer).netloc != 'cycomi.com':
        return False
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return False
    return (isinstance(data, dict) and set(data) == {'titleId', 'chapterId'}
            and all(type(v) is int and 0 < v < 10**15 for v in data.values()) and str(data['chapterId']) == match[1])


def array(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def body(raw):
    return raw.get('data') if isinstance(raw, dict) else None


def details_body(raw):
    if not isinstance(raw, dict):
        raise SourceError('Источник изменил формат карточки или оглавления.')
    return raw


@dataclass(frozen=True)
class JapanesePage:
    url: str
    key: bytes = b''
    algorithm: str = 'xor'
    network: bool = False

    def fetch(self, http, referer):
        from manga_page_media import read_image

        action = 'japanese-published-image' if self.network else None
        response, _ = http._open(self.url, headers={'Referer': referer}, action=action)
        data = read_image(http, response)
        if not self.key:
            return data
        if self.algorithm == 'rc4':
            return rc4(data, self.key)
        return bytes(value ^ self.key[index % len(self.key)] for index, value in enumerate(data))


def packed_refs(rows, chapter):
    if not 1 <= len(rows) <= MAX_PAGES or not all(row.url for row in rows):
        raise SourceError('Источник не предоставил полный список страниц открытой главы.')
    return remember([(row.url, row) for row in rows], chapter)


class KadoComi(JsonSeries):
    def __init__(self):
        super().__init__(('8396089563187142394', 'カドコミ', 'ja', KADO, False),
                         rf'/detail/({SEGMENT})/?', rf'/detail/({SEGMENT})/episodes/({SEGMENT})/?',
                         legacy_hosts=('www.comic-walker.com',), interval=.42)

    def title_for(self, url):
        return KADO + '/detail/' + self.chapter_key(url)

    def record_work(self, item):
        key = item.get('code')
        if not isinstance(key, str) or not re.fullmatch(SEGMENT, key) or not isinstance(item.get('title'), str):
            return None
        url = KADO + '/detail/' + key
        cover = image_url(item.get('bookCover') or item.get('originalThumbnail'), KADO)
        status = {'ongoing': 'ongoing', 'finished': 'completed'}.get(str(item.get('serializationStatus') or '').lower(), '')
        return self.record(url, item['title'].strip(), cover,
                           description=str(item.get('summary') or ''), authors=labels(item.get('authors')),
                           genres=labels([item.get('genre'), item.get('subGenre')]), tags=labels(item.get('tags')), status=status)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'limit': 30, 'offset': (page - 1) * 30}
        path = '/api/series/new' if sort == 'updated' else '/api/ranking'
        if query:
            path = '/api/search/keywords'
            args.update(keywords=query, sortBy='update' if sort == 'updated' else 'popularity')
        raw = details_body(self.json(http, query_url(KADO + path, **args)))
        paged = raw.get('pagination') if isinstance(raw.get('pagination'), dict) else {}
        total = raw.get('total', paged.get('total'))
        rows = [row for item in array(raw.get('result')) if (row := self.record_work(item))]
        return rows, bool(rows and type(total) is int and args['offset'] + args['limit'] < total)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        cid = urlsplit(target).path.strip('/')
        if not re.fullmatch(SEGMENT, cid) or not self.is_title(title):
            return ''
        from source_parser import PublicHttp

        client = PublicHttp(timeout=(3, 6))
        try:
            _, chapters = self.series(client, title)
        finally:
            client.close()
        return next((link for row in chapters if (link := self.site_link(row['url'])) and param(link, 'mv_episode_id') == cid), '')

    def series(self, http, url):
        url = self.canonical(url)
        code = self.title_key(url)
        raw = details_body(self.json(http, query_url(KADO + '/api/contents/details/work', workCode=code), url))
        work = details_body(raw.get('work'))
        if work.get('code') != code or not (row := self.record_work(work)):
            raise SourceError('KadoComi вернул карточку другого тайтла.')
        episodes = raw.get('latestEpisodes')
        chapters = {}
        for item in array(episodes.get('result') if isinstance(episodes, dict) else None):
            if item.get('isActive') is not True:
                continue
            ep, cid = str(item.get('code') or ''), str(item.get('id') or '')
            if not re.fullmatch(SEGMENT, ep) or not re.fullmatch(SEGMENT, cid):
                continue
            title = ' — '.join(str(item[k]) for k in ('title', 'subTitle') if item.get(k))
            target = query_url(f'{url.rstrip("/")}/episodes/{ep}', mv_episode_id=cid)
            details = item.get('internal') if isinstance(item.get('internal'), dict) else {}
            chapters[target] = self.chapter(target, title, number(details.get('episodeNo')),
                                            str(item.get('updateDate') or '').partition('T')[0])
        return row, self.order(chapters)

    def pages(self, http, url):
        cid = param(url, 'mv_episode_id')
        raw = details_body(self.json(http, query_url(KADO + '/api/contents/viewer', episodeId=cid, imageSizeType='width:1284'), url))
        rows = []
        for item in array(raw.get('manuscripts')):
            link = image_url(item.get('drmImageUrl'), KADO)
            key = str(item.get('drmHash') or '')
            if not link or not CRYPT_KEY.fullmatch(key):
                raise SourceError('KadoComi изменил формат страницы.')
            rows.append(JapanesePage(link, bytes.fromhex(key), network=True))
        return packed_refs(rows, url)


class CyComi(JsonSeries):
    def __init__(self):
        super().__init__(('8354556596244088751', 'CyComi', 'ja', CY, False),
                         rf'/title/({NUMERIC})/?', rf'/viewer/chapter/({NUMERIC})/?', interval=.5)

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = urlsplit(target).path.strip('/')
        return CY + '/title/' + key if re.fullmatch(NUMERIC, key) else target

    def title_for(self, url):
        key = param(url, 'mv_cy_title')
        return CY + '/title/' + key if re.fullmatch(NUMERIC, key) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.title_key(title)
        chapter = self.chapter_key(url) if self.is_chapter(url) else urlsplit(url).path.strip('/')
        if key and re.fullmatch(NUMERIC, chapter):
            return query_url(CY + '/viewer/chapter/' + chapter, mv_cy_title=key)
        return ''

    def saved_chapter_matches(self, target, title):
        key = self.title_key(title)
        return bool(key and self.is_chapter(target) and param(target, 'mv_cy_title') == key)

    def row_for(self, item):
        key = str(item.get('titleId') or '')
        if not re.fullmatch(NUMERIC, key) or not isinstance(item.get('titleName'), str):
            return None
        url = CY + '/title/' + key
        state = item.get('serialType')
        status = ('completed' if state in {'end', 'shot'} else 'ongoing') if isinstance(state, str) else ''
        return self.record(url, item['titleName'], image_url(item.get('image'), CY),
                           description=str(item.get('body') or ''), authors=(item.get('author'),), status=status)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        if query:
            raw = body(self.json(http, query_url(CY_API + '/search/list/1', word=query)))
        elif sort == 'updated' or tag:
            today = datetime.now(timezone(timedelta(hours=9))) - timedelta(hours=12)
            day = tag if re.fullmatch('[0-7]', tag) else today.isoweekday() % 7
            raw = body(self.json(http, f'{CY_API}/title/serialization/list/{day}'))
        else:
            raw = body(self.json(http, CY_API + '/titleRanking/title/list?categoryId=1'))
        values = raw.get('titles') if isinstance(raw, dict) else raw
        return [row for item in array(values) if (row := self.row_for(item))], False

    def series(self, http, url):
        url = self.saved_title_url(url)
        key = self.title_key(url)
        data = details_body(body(self.json(http, query_url(CY_API + '/title/detail', titleId=key), url)))
        if str(data.get('titleId')) != key or not (row := self.row_for(data)):
            raise SourceError('CyComi вернул карточку другого тайтла.')
        entries = body(self.json(http, query_url(CY_API + '/chapter/paginatedList', titleId=key, sort=2), url))
        chapters = {}
        for item in array(entries):
            cid = str(item.get('id') or '')
            if not re.fullmatch(NUMERIC, cid) or str(item.get('titleId')) != key:
                continue
            title = ' — '.join(str(item[k]) for k in ('name', 'subName') if item.get(k))
            target = query_url(CY + '/viewer/chapter/' + cid, mv_cy_title=key)
            chapters[target] = self.chapter(target, title, date=uploaded(item.get('startAt')))
        return row, self.order(chapters)

    def pages(self, http, url):
        raw = json.dumps({'titleId': int(param(url, 'mv_cy_title')), 'chapterId': int(self.chapter_key(url))}).encode()
        text, final, _ = http.document(CY_API + '/chapter/page/list', headers={'Referer': url},
                                       method='POST', data=raw, action='cycomi-reader')
        if final != CY_API + '/chapter/page/list':
            raise SourceError('CyComi перенаправил запрос другой главы.')
        try:
            payload = details_body(body(json.loads(text)))
        except ValueError:
            raise SourceError('CyComi изменил формат списка страниц.') from None
        entries = array(payload.get('pages'))
        if not entries:
            raise SourceAccessError('CyComi ограничил чтение этой главы.')
        rows = []
        for item in sorted(entries, key=lambda entry: number(entry.get('pageNumber')) or 0):
            link = image_url(item.get('image'), CY)
            path = urlsplit(link).path.strip('/').split('/')
            if not link or len(path) < 4 or len(path[3]) > 240:
                raise SourceError('CyComi изменил формат страницы.')
            key = b'' if 'end_page' in path[3] else unquote(path[3]).encode()
            rows.append(JapanesePage(link, key, 'rc4', True))
        return packed_refs(rows, url)


class NicoVideo(JsonSeries):
    def __init__(self):
        super().__init__(('1452408892924080686', 'Nicovideo Seiga', 'ja', NICO, False),
                         rf'/comic/({NUMERIC})/?', rf'/watch/mg({NUMERIC})/?',
                         legacy_hosts=('seiga.nicovideo.jp', 'manga.nicovideo.jp'), interval=.45)

    def title_for(self, url):
        key = param(url, 'mv_nico_title')
        return NICO + '/comic/' + key if re.fullmatch(NUMERIC, key) else ''

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = urlsplit(target).path.strip('/')
        return NICO + '/comic/' + key if re.fullmatch(NUMERIC, key) else target

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        chapter = self.chapter_key(url) if self.is_chapter(url) else urlsplit(url).path.strip('/')
        if re.fullmatch(NUMERIC, chapter) and (key := self.title_key(title)):
            return query_url(NICO + '/watch/mg' + chapter, mv_nico_title=key)
        return ''

    def saved_chapter_matches(self, target, title):
        key = self.title_key(title)
        return bool(key and self.is_chapter(target) and param(target, 'mv_nico_title') == key)

    def request(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': NICO + '/'}, action='nicovideo-public')
        if final != url:
            raise SourceError('Nicovideo перенаправил запрос API.')
        try:
            return json.loads(raw)
        except ValueError:
            raise SourceError('Nicovideo изменил формат ответа.') from None

    def row_for(self, item):
        key = str(item.get('id') or '')
        meta = item.get('meta') if isinstance(item.get('meta'), dict) else item
        title = meta.get('title')
        if not re.fullmatch(NUMERIC, key) or not isinstance(title, str):
            return None
        url = NICO + '/comic/' + key
        state = {'serial': 'ongoing', 'concluded': 'completed'}.get(str(meta.get('serial_status') or ''), '')
        description = node_text(BeautifulSoup(str(meta.get('description') or ''), 'html.parser'))
        return self.record(url, title, image_url(meta.get('square_image_url') or meta.get('thumbnail_url'), NICO),
                           description=description, authors=(meta.get('display_author_name') or meta.get('author'),), status=state)

    def result(self, http, url):
        raw = details_body(body(self.request(http, url)))
        result = raw.get('result')
        extra = raw.get('extra') if isinstance(raw.get('extra'), dict) else {}
        return [result] if isinstance(result, dict) else array(result), extra

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            url = query_url(NICO_API + '/contents', mode='keyword', sort='score', q=query, limit=20, offset=(page - 1) * 20)
            data, extra = self.result(http, url)
            more = extra.get('has_next') is True
        elif page <= 5:
            url = query_url(NICO + '/manga/ajax/ranking', span='total', category='all', page=page)
            data, more = array(self.request(http, url)), page < 5
        else:
            return [], False
        rows = [row for item in data if (row := self.row_for(item))]
        return rows, bool(rows and more)

    def series(self, http, url):
        key = self.title_key(self.saved_title_url(url))
        data, _ = self.result(http, NICO_API + '/contents/' + key)
        if not data or str(data[0].get('id')) != key or not (row := self.row_for(data[0])):
            raise SourceError('Nicovideo вернул карточку другого тайтла.')
        entries, _ = self.result(http, NICO_API + '/contents/' + key + '/episodes')
        chapters = {}
        for item in entries:
            meta = item.get('meta')
            ownership = item.get('own_status') if isinstance(item.get('own_status'), dict) else {}
            if not isinstance(meta, dict) or ownership.get('sell_status') in {'publication_finished', 'selling', 'pre_selling'}:
                continue
            cid = str(item.get('id') or '')
            if not re.fullmatch(NUMERIC, cid):
                continue
            target = query_url(NICO + '/watch/mg' + cid, mv_nico_title=key)
            chapters[target] = self.chapter(target, str(meta.get('title') or ''), number(meta.get('number')), uploaded(meta.get('created_at')))
        return row, self.order(chapters)

    def pages(self, http, url):
        cid = self.chapter_key(url)
        data, _ = self.result(http, NICO_API + '/episodes/' + cid + '/frames?enable_webp=true')
        rows = []
        for item in data:
            meta = details_body(item.get('meta'))
            link = image_url(meta.get('source_url'), NICO)
            parts = urlsplit(link)
            if not link or parts.hostname != 'deliver.cdn.nicomanga.jp':
                raise SourceAccessError('Nicovideo ограничил чтение этой главы.')
            rows.append(JapanesePage(link, network=True))
        return packed_refs(rows, url)


SOURCES = (KadoComi(), CyComi(), NicoVideo())
