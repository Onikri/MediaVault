"""Language-scoped gallery search and lazy page retrieval through the public reader."""

from collections import OrderedDict
from dataclasses import dataclass
import re
from threading import Lock
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import OriginPace, node_text, release_date
from manga_series_port import MAX_PAGES, picture
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ROOT = 'https://akuma.moe'
SLUG = r'[A-Za-z0-9_-]{1,128}'
TITLE = rf'/g/({SLUG})'
READER = re.compile(TITLE + r'/([1-9][0-9]{0,3})/?')
TOKEN = re.compile(r'[A-Za-z0-9_=-]{12,256}')
CURSOR = re.compile(r'[A-Za-z0-9_\-+/=:.]{1,768}')
TITLE_NOTES = re.compile(r'\[[^]]*]|[({][^)}]*[)}]')
PROFILE_IDS = (
    ('77326570497325152', 'eo'), ('186393818771246102', 'ca'), ('1099564256126272699', 'hi'),
    ('1422819830508615430', 'hu'), ('1707768678643970514', 'id'), ('1740877429814102450', 'vi'),
    ('1843646695111412994', 'all'), ('2760962895634785428', 'tr'), ('3825200464570758229', 'jv'),
    ('3989593922015638091', 'cs'), ('5014742859693294263', 'ceb'), ('5085561039221748061', 'it'),
    ('5229751861519354976', 'uk'), ('5253884715906393116', 'pt'), ('5330127039501257395', 'ja'),
    ('5371778608318819884', 'es'), ('5610655855358487221', 'nl'), ('5988433661218368889', 'da'),
    ('7045343433771927648', 'ru'), ('7558912456429140642', 'zh'), ('8163761313345392776', 'pl'),
    ('8167173986295647123', 'et'), ('8353987132172753017', 'ko'), ('8524245811050879736', 'de'),
    ('8524619729907384865', 'en'), ('8600626646399125374', 'ar'), ('9222445553932717105', 'fr'),
)
LANGUAGE = dict(zip(
    ('eo', 'ca', 'hi', 'hu', 'id', 'vi', 'tr', 'jv', 'cs', 'ceb', 'it', 'uk', 'pt',
     'ja', 'es', 'nl', 'da', 'ru', 'zh', 'pl', 'et', 'ko', 'de', 'en', 'ar', 'fr'),
    ('esperanto', 'catalan', 'hindi', 'hungarian', 'indonesian', 'vietnamese', 'turkish',
     'javanese', 'czech', 'cebuano', 'italian', 'ukrainian', 'portuguese', 'japanese', 'spanish',
     'dutch', 'danish', 'russian', 'chinese', 'polish', 'estonian', 'korean', 'german', 'english',
     'arabic', 'french'),
))
ORIGIN = OriginPace()
ORIGIN.interval = .55


def guest_route(url, method, data, csrf):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.netloc != 'akuma.moe' or parts.path != '/':
        return False
    if method == 'GET':
        return not parts.query and data is None
    if method != 'POST' or data != {'view': '3'} or not TOKEN.fullmatch(csrf):
        return False
    try:
        fields = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=3)
    except ValueError:
        return False
    args = dict(fields)
    return (len(args) == len(fields) and set(args) in ({'q'}, {'q', 'cursor'})
            and len(args['q']) <= 330 and ('cursor' not in args or bool(CURSOR.fullmatch(args['cursor']))))


def short_title(value):
    value = value.replace('"', '').strip()
    return TITLE_NOTES.sub('', value).strip() or value


def page_document(http, url, referer):
    raw, final, _ = http.document(url, headers={'Referer': referer})
    if urlsplit(final).hostname != 'akuma.moe' or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
        raise SourceError('Источник перенаправил читалку на другую страницу.')
    return BeautifulSoup(raw, 'html.parser')


@dataclass(frozen=True)
class AkumaPage:
    sheet: str
    image: str = ''

    def fetch(self, http, referer):
        from manga_page_media import read_image

        target = self.image
        if not target:
            target = picture(page_document(http, self.sheet, referer).select_one('.entry-content img'), self.sheet)
        if not target:
            raise SourceError('Источник не предоставил изображение страницы.')
        response, _ = http._open(target, headers={'Referer': self.sheet})
        return read_image(http, response)


class Akuma(JsonSeries):
    def __init__(self, sid, language):
        super().__init__((sid, 'Akuma', language, ROOT, True), TITLE + '/?', TITLE + '/1/?')
        self.origin = ORIGIN
        self.next_pages = OrderedDict()
        self.guard = Lock()

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/g/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        match = READER.fullmatch(urlsplit(url).path)
        return ROOT + '/g/' + match[1] if match else url

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        match = READER.fullmatch(urlsplit(url).path)
        return ROOT + '/g/' + match[1] + '/1' if match else url

    def search_document(self, http, url):
        for attempt in range(2):
            csrf = getattr(http, 'akuma_csrf', '') if attempt == 0 else ''
            if not csrf:
                self.origin.wait(getattr(http, 'deadline', None))
                raw, final, _ = http.document(ROOT + '/', headers={'Referer': ROOT + '/'}, action='akuma-guest')
                if final != ROOT + '/':
                    raise SourceError('Источник перенаправил гостевую сессию.')
                meta = BeautifulSoup(raw, 'html.parser').select_one('head meta[name*="csrf-token"][content]')
                csrf = meta['content'] if meta else ''
                if not TOKEN.fullmatch(csrf):
                    raise SourceAccessError('Источник не предоставил гостевую сессию для поиска.')
                http.akuma_csrf = csrf
            self.origin.wait(getattr(http, 'deadline', None))
            headers = {'Referer': ROOT + '/', 'X-CSRF-TOKEN': csrf}
            try:
                raw, final, _ = http.document(url, method='POST', data={'view': '3'}, headers=headers, action='akuma-guest')
            except SourceError as error:
                if attempt or str(error) != 'Источник вернул HTTP 419.':
                    raise
                continue
            if final != url:
                raise SourceError('Источник изменил маршрут поиска.')
            return BeautifulSoup(raw, 'html.parser')
        raise SourceAccessError('Источник не обновил гостевую сессию.')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        tokens = [query]
        if lang := LANGUAGE.get(self.LANGUAGE):
            tokens.append(f'language:{lang}$')
        if tag:
            key, _, label = tag.partition(':')
            if key not in {'category', 'artist', 'parody', 'character', 'group', 'female', 'male', 'other'} or not label:
                return [], False
            safe = label.replace('"', '').replace('\\', '')[:120]
            tokens.append(f'{key}:"{safe}"')
        term = ' '.join(filter(None, tokens))
        with self.guard:
            cursor = self.next_pages.get((term, page)) if page > 1 else ''
        if page > 1 and not cursor:
            return [], False
        target = query_url(ROOT + '/', q=term, **({'cursor': cursor} if cursor else {}))
        doc = self.search_document(http, target)
        text = node_text(doc.select_one('main'))
        if 'Max keywords of' in text and 'exceeded' in text:
            raise SourceAccessError('Источник ограничил число условий гостевого поиска.')
        rows = {}
        for item in doc.select('.post-loop li:has(.overlay-title)'):
            anchor = item.select_one('a[href]')
            url = self.site_link(anchor['href']) if anchor else ''
            title = short_title(node_text(item.select_one('.overlay-title')))
            if self.is_title(url) and title:
                rows[url] = self.record(url, title, picture(item.select_one('img'), url))
        next_link = doc.select_one('.page-item a[rel*="next"][href]')
        next_cursor = param(next_link['href'], 'cursor') if next_link else ''
        more = bool(rows and CURSOR.fullmatch(next_cursor) and next_cursor != cursor)
        if more:
            with self.guard:
                self.next_pages[(term, page + 1)] = next_cursor
                self.next_pages.move_to_end((term, page + 1))
                while len(self.next_pages) > 512:
                    self.next_pages.popitem(last=False)
        return list(rows.values()), more

    def series(self, http, url):
        doc, final = self.title_document(http, self.saved_title_url(url))
        title = short_title(node_text(doc.select_one('.entry-title')))
        if not title:
            raise SourceError('Источник не предоставил карточку.')
        alt = node_text(doc.select_one('.entry-title + span'))
        tags = [node_text(node) for node in doc.select(
            '.male ~ .value, .female ~ .value, .other ~ .value, .character ~ .value, .parody ~ .value')]
        authors = [node_text(node) for node in doc.select('.group ~ .value, .artist ~ .value')]
        date = doc.select_one('.date .value > time')
        stamp = release_date(date.get('datetime', '')[:10], '%Y-%m-%d') if date and date.get('datetime') else ''
        if not stamp:
            stamp = release_date(node_text(date), '%Y-%m-%d %H:%M')
        row = self.record(final, title, picture(doc.select_one('.img-thumbnail'), final),
                          aliases=(alt,), tags=tags, authors=authors, status='completed')
        return row, [self.chapter(final.rstrip('/') + '/1', 'Глава', 1, stamp)]

    def pages(self, http, url):
        title = self.title_for(url)
        doc = page_document(http, url, title)
        options = [int(node['value']) for node in doc.select('.nav-select option[value]')
                   if re.fullmatch(r'[1-9][0-9]{0,3}', node['value'])]
        count = max(options, default=0)
        first = picture(doc.select_one('.entry-content img'), url)
        if not first or not 1 <= count <= MAX_PAGES:
            raise SourceError('Источник не предоставил список страниц.')
        refs = []
        for index in range(1, count + 1):
            target = f'{title}/{index}'
            refs.append((target, AkumaPage(target, first if index == 1 else '')))
        return remember(refs, url)


SOURCES = tuple(Akuma(sid, lang) for sid, lang in PROFILE_IDS)
