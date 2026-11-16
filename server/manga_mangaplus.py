"""MANGA Plus by SHUEISHA, using public WEB Protobuf routes and reader tokens."""

from datetime import datetime, timezone
from itertools import chain
import re
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from requests import RequestException

from manga_direct_payloads import JsonSeries
from manga_madara import image_url
from manga_million_wire import Message
from manga_series_port import MAX_PAGES, number
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import MAX_DOCUMENT, SourceAccessError, SourceError, SourceTemporaryError


ROOT = 'https://mangaplus.shueisha.co.jp'
HOST = 'jumpg-webapi.tokyo-cdn.com'
API = 'https://' + HOST + '/api'
ID = r'[1-9]\d{0,9}'
KEY = re.compile(r'(?:[A-Fa-f0-9]{2}){1,128}')
TOKEN = re.compile(r'[\x21-\x7e]{1,1500}')
SESSION = str(uuid4())
LANGUAGES = {
    'en': ('eng', 0), 'es': ('esp', 1), 'fr': ('fra', 2), 'id': ('ind', 3), 'pt-BR': ('ptb', 4),
    'ru': ('rus', 5), 'th': ('tha', 6), 'de': ('deu', 7), 'vi': ('vie', 9),
}
CODES = {code for code, _ in LANGUAGES.values()}
STATUS_COMPLETE = re.compile(r'completado|completed?|completo', re.I)
VIEW = '/manga_viewer_v3'
ALL = '/title_list/allV2'
GENRES = '/title_list/all_v3'
POPULAR = '/title_list/rankingV2'
LATEST = '/web/web_homeV4'
DETAIL = '/title_detailV3'
DATA_FIELDS = {VIEW: 10, ALL: 25, GENRES: 35, POPULAR: 37, LATEST: 38, DETAIL: 8}


def public_api(host, path, query):
    key = path.removeprefix('/api')
    if host != HOST or not path.startswith('/api/') or key not in DATA_FIELDS:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(pairs) != len(args) or any(len(value) > 30 for value in args.values()):
        return False
    if key == ALL:
        return not query
    if args.get('clang') not in CODES:
        return False
    if key == VIEW:
        return (set(args) == {'chapter_id', 'split', 'img_quality', 'clang'} and bool(re.fullmatch(ID, args['chapter_id']))
                and args['split'] == 'yes' and args['img_quality'] == 'super_high')
    if key == DETAIL:
        return set(args) == {'title_id', 'clang'} and bool(re.fullmatch(ID, args['title_id']))
    if args.get('lang') != args['clang']:
        return False
    if key == LATEST:
        return set(args) == {'lang', 'clang'}
    return set(args) == {'lang', 'clang', 'type'} and args['type'] == ('hottest' if key == POPULAR else 'serializing')


def page_host(host):
    return (host == 'tokyo-cdn.com' or host.endswith('.tokyo-cdn.com')
            or host == 'mangaplus.shueisha.co.jp' or host.endswith('.mangaplus.shueisha.co.jp'))


class XorPage:
    def __init__(self, key):
        self.key = key

    def decode(self, raw):
        key = self.key
        if not key:
            return raw
        source = bytearray(raw)
        for index, value in enumerate(key):
            source[index::len(key)] = source[index::len(key)].translate(bytes(byte ^ value for byte in range(256)))
        return bytes(source)


class MangaPlusPage(XorPage):
    def __init__(self, key, token):
        super().__init__(key)
        self.token = token


def protobuf(http, url, source, headers, action):
    response, final = http._open(url, headers=headers, action=action)
    try:
        if final != url:
            raise SourceError(f'{source} перенаправил маршрут читалки.')
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > MAX_DOCUMENT:
                raise SourceError(f'{source} превысил лимит ответа.')
        return Message(raw, source)
    except RequestException:
        raise SourceTemporaryError(f'{source} прервал выдачу данных.') from None
    finally:
        response.close()


class MangaPlus(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/titles/({ID})/?', rf'/viewer/({ID})/?',
                         hosts=('www.mangaplus.shueisha.co.jp', HOST, 'www.' + HOST), interval=.6)
        self.lang_code, self.language_id = LANGUAGES[self.LANGUAGE]

    def canonical(self, value):
        target = super().canonical(value)
        if not target:
            return ''
        url = urlsplit(target)
        fragment = tuple(url.fragment.strip('/').split('/'))
        if len(fragment) == 2 and fragment[0] in ('titles', 'viewer') and re.fullmatch(ID, fragment[1]):
            return f'{self.ROOT}/{fragment[0]}/{fragment[1]}'
        if url.path.rstrip('/').endswith('/sns_share') and re.fullmatch(ID, param(target, 'title_id')):
            return self.ROOT + '/titles/' + param(target, 'title_id')
        if self.TITLE_PATH.fullmatch(url.path) or self.CHAPTER_PATH.fullmatch(url.path):
            return self.ROOT + url.path.rstrip('/') + ('?' + url.query if url.query else '')
        return target

    def title_for(self, url):
        key = param(url, 'mv_title')
        return self.ROOT + '/titles/' + key if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        target = self.canonical(row.get('realUrl') or row.get('url'))
        if self.is_chapter(target) and self.is_title(title):
            return query_url(target.split('?')[0], mv_title=self.title_key(title))
        return ''

    def saved_chapter_matches(self, target, title):
        key = self.title_key(title)
        return bool(self.is_chapter(target) and key and self.title_key(self.title_for(target)) == key)

    def request(self, http, route, **params):
        self.origin.wait(getattr(http, 'deadline', None))
        url = query_url(API + route, **params)
        result = protobuf(http, url, 'MANGA Plus', {'Referer': ROOT + '/', 'Session-Token': SESSION}, 'mangaplus-proto')
        if next(result.messages(2), None):
            raise SourceAccessError('MANGA Plus не предоставил открытый выпуск на выбранном языке.')
        return result.message(1).message(DATA_FIELDS[route])

    def entry(self, data, **updates):
        identifier, title = str(data.integer(1)), data.string(2)
        if data.integer(7) != self.language_id or not re.fullmatch(ID, identifier) or not title:
            return None
        url = self.ROOT + '/titles/' + identifier
        author = data.string(3)
        return self.record(url, title, image_url(data.string(4), url), authors=[author] if author else [], **updates)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        locale = {'lang': self.lang_code, 'clang': self.lang_code}
        if tag:
            data = self.request(http, GENRES, type='serializing', **locale)
            titles = (entry.message(2) for entry in data.messages(3) if any(term.string(2) == tag for term in entry.messages(3)))
        elif query:
            data = self.request(http, ALL)
            titles = chain.from_iterable(group.messages(2) for group in data.messages(1))
        elif sort == 'updated':
            data = self.request(http, LATEST, **locale)
            featured = (feature.message(2) for feature in data.messages(7))
            updated = chain(chain.from_iterable(group.messages(2) for group in data.messages(2)), featured)
            sorted_titles = sorted(updated, key=lambda item: item.integer(6), reverse=True)
            titles = (chapter.message(1) for group in sorted_titles for chapter in group.messages(3))
        else:
            data = self.request(http, POPULAR, type='hottest', **locale)
            titles = chain.from_iterable(section.messages(2) for section in data.messages(3))
        rows = {}
        for title in titles:
            if (row := self.entry(title)) and (not query or any(query in item.casefold() for item in (row['title'], *row['authors']))):
                rows[row['id']] = row
        return list(rows.values()), False

    def vocabulary(self, http):
        data = self.request(http, GENRES, type='serializing', lang=self.lang_code, clang=self.lang_code)
        return [{'label': row.string(1), 'sourceId': row.string(2), 'category': 'genre'}
                for row in data.messages(2) if row.string(1) and row.string(2)]

    def series(self, http, url):
        key = self.title_key(url)
        data = self.request(http, DETAIL, title_id=key, clang=self.lang_code)
        overview, release = data.string(3), data.string(7)
        genres = [(row.string(1), row.string(2)) for row in data.messages(31)]
        end = any(slug == 'one-shot' for _, slug in genres)
        status = ('completed' if end or STATUS_COMPLETE.search(data.string(8)) or 'latest 0 chapters' in release
                  else 'hiatus' if 'on a hiatus' in data.string(8).lower() else 'ongoing')
        row = self.entry(data.message(1), description='\n\n'.join(value for value in (overview, release) if value),
                         genres=[label for label, _ in genres if label], status=status)
        if not row or self.title_key(row['url']) != key:
            raise SourceAccessError('MANGA Plus не предоставил тайтл на выбранном языке.')
        chapters = {}
        for group in data.messages(28):
            for chapter in chain(group.messages(2), group.messages(4)):
                cid = str(chapter.integer(2))
                subtitle = next(chapter.strings(4), None)
                if subtitle is None or not re.fullmatch(ID, cid):
                    continue
                title = chapter.string(3)
                target = query_url(self.ROOT + '/viewer/' + cid, mv_title=key)
                timestamp = chapter.integer(6)
                date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat() if 0 < timestamp <= 4_102_444_800 else ''
                chapters[cid] = self.chapter(target, ' · '.join(filter(None, (title, subtitle))),
                                             number(title.lstrip('#')), date, translator='MANGA Plus')
        return row, self.order(chapters)

    def viewer(self, http, url):
        return self.request(http, VIEW, chapter_id=self.chapter_key(url), split='yes',
                            img_quality='super_high', clang=self.lang_code)

    def references(self, viewer):
        token = viewer.string(19)
        if token and not TOKEN.fullmatch(token):
            raise SourceError('MANGA Plus вернул некорректный токен читалки.')
        refs = []
        for entry in viewer.messages(1):
            page = next(entry.messages(1), None)
            if page is None:
                continue
            url, key = image_url(page.string(1), self.ROOT), page.string(5)
            if not url or not page_host(urlsplit(url).hostname or '') or (key and not KEY.fullmatch(key)):
                raise SourceError('MANGA Plus вернул некорректную страницу.')
            refs.append((url, MangaPlusPage(bytes.fromhex(key) if key else b'', token)))
            if len(refs) > MAX_PAGES:
                raise SourceError('MANGA Plus превысил лимит страниц выпуска.')
        return remember(refs, self.ROOT + '/')

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            viewer = self.viewer(http, url)
            key = str(viewer.integer(9))
            if not re.fullmatch(ID, key):
                raise SourceError('MANGA Plus не подтвердил тайтл выбранного выпуска.')
            row, all_chapters = self.series(http, self.ROOT + '/titles/' + key)
            chapters = [c for c in all_chapters if self.chapter_key(c['url']) == self.chapter_key(url)]
            if not chapters:
                raise SourceAccessError('MANGA Plus не предоставил выпуск в открытом оглавлении.')
            target = self.site_link(chapters[0]['url'])
            return self.reader_result(row, target, chapters, self.references(viewer))
        return super().inspect(url, http)

    def pages(self, http, url):
        viewer = self.viewer(http, url)
        if str(viewer.integer(9)) != param(url, 'mv_title'):
            raise SourceError('MANGA Plus вернул страницы другого произведения.')
        return self.references(viewer)


SOURCES = tuple(MangaPlus((sid, 'MANGA Plus by SHUEISHA', lang, ROOT, False)) for sid, lang in (
    ('932564577108614127', 'id'), ('1286073245950890830', 'es'), ('1893513843840146580', 'de'),
    ('1998944621602463790', 'en'), ('3444662672352788181', 'pt-BR'), ('3520485566708512181', 'ru'),
    ('4696259977267090434', 'vi'), ('6345211913721743017', 'th'), ('7642759409549978864', 'fr'),
))
