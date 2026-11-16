"""Japanese publisher HTML and Next.js reader adapters."""

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from manga_additional_catalogues import flight_objects
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort, number, picture
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

MANGA_UP = 'https://www.manga-up.com'
GANGAN = 'https://www.ganganonline.com'
GORAKU = 'https://gorakuweb.com'
ID = r'[1-9]\d{0,19}'
UP_TITLE = rf'/titles/({ID})/?'
UP_CHAPTER = rf'/titles/({ID})/chapters/({ID})/?'
GANGAN_TITLE = rf'/title/({ID})/?'
GANGAN_CHAPTER = rf'/title/({ID})/chapter/({ID})/?'
GORAKU_TITLE = rf'/episode/({ID})/?'
GORAKU_CHAPTER = rf'/episode/({ID})/({ID})/?'
UP_FILTERS = dict(zip(('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'end'), '月 火 水 木 金 土 日 完'.split()))
GANGAN_FILTERS = {'rensai': '連載作品', 'finish': '連載終了作品', 'pixiv': 'ガンガンpixiv', 'ga': 'ガンガンGA'}
HEX_KEY = re.compile(r'(?:[a-f\d]{32}|[a-f\d]{48}|[a-f\d]{64})', re.I)
HEX_IV = re.compile(r'[a-f\d]{32}', re.I)


def public_rsc(host, path, query):
    if host == 'www.manga-up.com':
        return not query and bool(re.fullmatch(UP_TITLE, path) or re.fullmatch(UP_CHAPTER, path))
    if host != 'gorakuweb.com':
        return False
    if path == '/series':
        return query in ('', 'completed=false', 'completed=true')
    return not query and bool(path == '/' or re.fullmatch(GORAKU_TITLE, path) or re.fullmatch(GORAKU_CHAPTER, path))


def rsc(http, target, referer):
    text, final, _ = http.document(target, headers={'Referer': referer}, action='native-series-rsc')
    before, after = urlsplit(target), urlsplit(final)
    if before.netloc != after.netloc or before.path.rstrip('/') != after.path.rstrip('/'):
        raise SourceError('Издатель перенаправил данные читалки на другой адрес.')
    return flight_objects(text)


def date_prefix(value, fmt):
    text = str(value or '').split('〜', 1)[0].strip()
    return release_date(text, fmt)


@dataclass(frozen=True)
class AesCbcPage:
    key: bytes
    iv: bytes

    def decode(self, raw):
        try:
            decoder = Cipher(algorithms.AES(self.key), modes.CBC(self.iv)).decryptor()
            page = decoder.update(raw) + decoder.finalize()
            padding = PKCS7(128).unpadder()
            return padding.update(page) + padding.finalize()
        except ValueError:
            raise SourceError('Издатель изменил формат страницы.') from None


class MangaUp(SeriesPort):
    cards = Cards('div.grid > a[href]', '', 'div.line-clamp-2', 'img', next='')
    meta = Meta('h2', 'section > img', 'h2:-soup-contains-own("あらすじ") + div', '',
                'a[href*="/genres/"]', '', 'div.flex.flex-col.gap-2xsmall > div')

    def __init__(self):
        super().__init__(('697820552173578283', 'Manga UP! (Japan)', 'ja', MANGA_UP, False),
                         UP_TITLE, UP_CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return MANGA_UP + '/titles/' + key if key else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        parts = urlsplit(url)
        chapter = parts.path.strip('/')
        if re.fullmatch(ID, chapter) and parts.fragment == self.title_key(title):
            return title.rstrip('/') + '/chapters/' + chapter
        return ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page > 1:
            return [], False
        if query:
            url = query_url(MANGA_UP + '/titles', word=query)
        elif tag in UP_FILTERS:
            url = MANGA_UP + '/series/' + tag
        else:
            url = MANGA_UP + ('/series' if sort == 'updated' else '/rankings/1')
        return self.card_rows(*self.document(http, url), self.cards)

    def vocabulary(self, http):
        return [{'key': key, 'label': value, 'kind': 'category'} for key, value in UP_FILTERS.items()]

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['status'] = ('completed' if doc.select_one('div:-soup-contains-own("完結")') else
                         'ongoing' if doc.select_one('div:-soup-contains-own("更新")') else '')
        return row

    def chapters(self, http, doc, final):
        data = next((row['chapters'] for row in rsc(http, final, MANGA_UP + '/')
                     if isinstance(row.get('chapters'), list) and 'currentChapter' in row), [])
        chapters = {}
        for index, entry in enumerate(reversed(data), 1):
            identity = str(entry.get('id') or '')
            if not re.fullmatch(ID, identity):
                continue
            title = str(entry.get('name') or '')
            sub = entry.get('subName')
            label = (str(sub) + ' - ' if sub else '') + title
            preview = entry.get('publishingStatus') != 3
            target = final.rstrip('/') + '/chapters/' + identity
            chapter = self.chapter(target, ('🔒 (Preview) ' if preview else '') + label, index)
            if preview:
                chapter['preview'] = True
            chapters[target] = chapter
        return self.order(chapters), False

    def pages(self, http, url):
        data = next((row['pages'] for row in rsc(http, url, MANGA_UP + '/')
                     if isinstance(row.get('pages'), list) and any(isinstance(p, dict) and 'content' in p for p in row['pages'])), [])
        result = []
        for item in data:
            value = (item.get('content') or {}).get('value') or {}
            if src := image_url(value.get('imageUrl'), url):
                result.append(src)
        return result


class GanganOnline(SeriesPort):
    def __init__(self):
        super().__init__(('1467355738916791140', 'Gangan Online', 'ja', GANGAN, False),
                         GANGAN_TITLE, GANGAN_CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return GANGAN + '/title/' + key if key else ''

    def data(self, http, url):
        doc, final = self.document(http, url)
        if urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('Gangan Online перенаправил запрос.')
        script = doc.select_one('script#__NEXT_DATA__')
        document = json.loads(script.string or '') if script else {}
        data = (((document.get('props') or {}).get('pageProps') or {}).get('data') or {})
        if not data or not isinstance(data, dict):
            raise SourceError('Gangan Online изменил данные каталога.')
        return data

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page > 1:
            return [], False
        path = '/' + (tag if tag in GANGAN_FILTERS else 'rensai')
        url = query_url(GANGAN + '/search/result', keyword=query) if query else GANGAN + path
        data = self.data(http, url)
        lists = [data.get('ganganTitles') or []]
        lists += [section.get('titleLinks', []) for section in data.get('sections') or []]
        lists += [section.get('titles', []) for section in data.get('titleSections') or []]
        lists += [(data.get(field) or {}).get('titles', []) for field in ('ongoingTitleSection', 'finishedTitleSection')]
        rows = {}
        for sources in lists:
            for item in sources:
                key = str(item.get('titleId') or '')
                title = item.get('title') or item.get('header') or item.get('name')
                if not item.get('isNovel') and re.fullmatch(ID, key) and title:
                    target = GANGAN + '/title/' + key
                    rows[key] = self.record(target, title, image_url(item.get('imageUrl'), GANGAN))
        return list(rows.values()), False

    def vocabulary(self, http):
        return [{'key': key, 'label': value, 'kind': 'category'} for key, value in GANGAN_FILTERS.items()]

    def loaded_title(self, http, url):
        data = self.data(http, url).get('default') or {}
        name = data.get('titleName')
        if not name:
            raise SourceError('Gangan Online не предоставил карточку.')
        row = self.record(url, name, image_url(data.get('imageUrl'), GANGAN),
                          authors=[data.get('author')], description=data.get('description') or '')
        return row, data

    def details(self, http, value):
        url = self.canonical(value)
        if not self.is_title(url):
            raise SourceError('Некорректная карточка Gangan Online.')
        return self.loaded_title(http, url)[0]

    def pages(self, http, url):
        data = self.data(http, url).get('pages') or ()
        return [src for item in data if (src := image_url(((item.get('image') or item.get('linkImage') or {}).get('imageUrl')), GANGAN))]

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            return super().inspect(url, http)
        row, data = self.loaded_title(http, url)
        chapters = {}
        for item in data.get('chapters') or []:
            key = str(item.get('id') or '')
            status = item.get('status')
            if not re.fullmatch(ID, key) or status is not None and (type(status) is not int or status < 4):
                continue
            target = url.rstrip('/') + '/chapter/' + key
            name = ' - '.join(filter(None, (item.get('mainText'), item.get('subText'))))
            stamp = date_prefix(item.get('publishingPeriod'), '%Y.%m.%d')
            chapters[target] = self.chapter(target, name, date=stamp)
        return self.reader_result(row, url, self.order(chapters), [])


class GorakuWeb(SeriesPort):
    cards = Cards('div.bdr_lg.group', 'a[href]', 'h3', 'img', next='')

    def __init__(self):
        super().__init__(('8261703368756535165', 'Goraku Web', 'ja', GORAKU, True),
                         GORAKU_TITLE, GORAKU_CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return GORAKU + '/episode/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = self.title_key(url) or self.chapter_key(url) or urlsplit(url).path.strip('/')
        return GORAKU + '/episode/' + key if re.fullmatch(ID, key) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page > 1:
            return [], False
        if query or (tag.isnumeric() and len(tag) <= 20):
            args = {'keyword': query} if query else {'id': tag}
            doc, final = self.document(http, query_url(GORAKU + '/search', **args))
            entries = doc.select(self.cards.rows)
        elif sort == 'updated':
            doc, final = self.document(http, GORAKU + '/')
            entries = doc.select('section:has(h2:-soup-contains-own("更新作品")) div.bdr_lg.group')
        else:
            path = query_url(GORAKU + '/series', completed=tag) if tag in ('true', 'false') else GORAKU + '/'
            result = rsc(http, path, GORAKU + '/')
            rows = {}
            for item in result:
                if 'imageSrc' not in item or not isinstance(item.get('title'), str):
                    continue
                url = self.saved_title_url(item.get('href') or '')
                if self.is_title(url):
                    rows[url] = self.record(url, item['title'], image_url(item.get('imageSrc'), url))
            return list(rows.values()), False
        rows = {}
        for item in entries:
            a = item.select_one('a[href]')
            url = self.saved_title_url(self.site_link(a['href'], final)) if a else ''
            title = node_text(item.select_one('h3'))
            if url and title:
                rows[url] = self.record(url, title, picture(item.select_one('img'), final))
        return list(rows.values()), False

    def reader_props(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        rows = rsc(http, url, GORAKU + '/')
        data = next((item for item in rows if isinstance(item.get('shareUrl'), str)
                     and isinstance(item.get('episodeList'), list)), None)
        if data is None:
            raise SourceAccessError('Goraku Web не предоставил открытый выпуск.')
        target = self.site_link(data['shareUrl'], url)
        parent = self.saved_title_url(url)
        if self.saved_title_url(target) != parent:
            raise SourceError('Goraku Web вернул другое произведение.')
        return data

    def summary(self, http, url):
        data = self.reader_props(http, url)
        title = data.get('seriesTitle')
        if not isinstance(title, str) or not title:
            raise SourceError('Goraku Web не предоставил метаданные тайтла.')
        row = self.record(url, title, image_url(data.get('seriesThumbnailUrl'), url), authors=[data.get('author')],
                          description=node_text(BeautifulSoup(data.get('seriesDescription') or '', 'html.parser')))
        return row, data

    def details(self, http, url):
        target = self.saved_title_url(url)
        if not self.is_title(target):
            raise SourceError('Некорректная карточка Goraku Web.')
        return self.summary(http, target)[0]

    def pages(self, http, url):
        if param(url, 'mv_goraku_locked') == '1':
            raise SourceAccessError('Глава доступна на условиях Goraku Web.')
        data = self.reader_props(http, url)
        key, iv = data.get('keyBytes', ''), data.get('ivBytes', '')
        base = image_url(data.get('base'), url)
        token = data.get('accessKey', '')
        if not re.fullmatch(r'[!-~]{1,1800}', token) or not HEX_KEY.fullmatch(key) or not HEX_IV.fullmatch(iv) or not base:
            raise SourceAccessError('Goraku Web не предоставил открытые страницы.')
        cipher = AesCbcPage(bytes.fromhex(key), bytes.fromhex(iv))
        pages = (data.get('metadata') or {}).get('pages') or []
        references = []
        for item in sorted(pages, key=lambda row: number(row.get('page')) or 0):
            name = item.get('filename', '')
            if re.fullmatch(SEGMENT, name):
                references.append((query_url(base.rstrip('/') + '/' + name, __token__=token), cipher))
        return remember(references, url)

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            return super().inspect(url, http)
        row, data = self.summary(http, url)
        chapters = {}
        for item in data['episodeList']:
            target = self.site_link(item.get('href'), url)
            if not self.is_chapter(target) or self.chapter_key(target) != self.title_key(url):
                continue
            title = str(item.get('title') or '')
            lock = item.get('disabled') is True
            if lock:
                target = query_url(target, mv_goraku_locked=1)
            stamp = date_prefix(item.get('openAt'), '%Y/%m/%d')
            chapter = self.chapter(target, ('🔒 ' if lock else '') + title, date=stamp)
            if lock:
                chapter['available'] = False
            chapters[target] = chapter
        return self.reader_result(row, url, self.order(chapters), [])


SOURCES = (MangaUp(), GanganOnline(), GorakuWeb())
