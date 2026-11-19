"""Toomics published search, language catalogues and open episodes."""

import json
import re
from html import unescape
from urllib.parse import parse_qsl, unquote, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, node_text, release_date
from manga_series_port import Meta, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://global.toomics.com'
HOST = 'global.toomics.com'
LANGS = ('en', 'es', 'mx', 'esp', 'fr', 'de', 'it', 'por', 'sc', 'tc')
# Since Nov 2026 the Spanish (/es) and Latin American (/mx) stores redirect to
# one /esp store; saved links keep their old prefix.
VARIANTS = {'zh-Hans': 'sc', 'zh-Hant': 'tc', 'es': 'esp', 'es-419': 'esp', 'pt-BR': 'por'}
LEGACY = {'esp': ('es', 'mx')}
LANG_PATH = '(?:' + '|'.join(LANGS) + ')'
ID = r'[1-9]\d{0,12}'
TITLE = rf'/{LANG_PATH}/webtoon/episode/toon/({ID})(?:/search/Y)?/?'
CHAPTER = rf'/{LANG_PATH}/webtoon/(?:viewer|view|detail|reading)(?:/{SEGMENT}){{0,12}}/?'
SEARCH = rf'/{LANG_PATH}/webtoon/ajax_search'
AGE_GATE = rf'/{LANG_PATH}/index/set_display/?'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
REF = re.compile(r'''(?:href\s*=\s*|Base\.setFamilyMode\(\s*['"]N['"],\s*)['"]([^'"]+)''')
TILE = 'mv_toomics_title'


def form(url, data):
    parts = urlsplit(url)
    return (parts.netloc == HOST and not parts.query and re.fullmatch(SEARCH, parts.path)
            and set(data) == {'toonData'} and isinstance(data['toonData'], str) and 1 <= len(data['toonData']) <= 160)


def routed(value, action):
    parts = urlsplit(value)
    if parts.netloc != HOST:
        return False
    if action == 'toomics-public-view':
        return bool(re.fullmatch(CHAPTER, parts.path))
    prefix = '/' + parts.path.strip('/').split('/', 1)[0]
    return bool(re.fullmatch(AGE_GATE, parts.path) and param(value, 'display') == 'A' and param(value, 'return') == prefix)


def decode_markup(value):
    def scalar(match):
        point = int(match[1] or match[2], 16)
        return chr(point) if point <= 0x10ffff else ''

    clean = re.sub(r'\\u([a-f\d]{4})|\\U([a-fA-F\d]{8})', scalar, value, flags=re.I)
    return unescape(re.sub(r'\\[nr]|\\', '', clean))


class Toomics(SeriesPort):
    meta = Meta('#glo_contents section.relative:has(img[src*="thumb"]) h2', 'meta[property="og:image"]',
                '#glo_contents .break-noraml.text-xs', '', '', '',
                '#glo_contents section.relative:has(img[src*="thumb"]) a[href*="searchtype=author"]')

    def __init__(self, sid, lang):
        self.locale = VARIANTS.get(lang, lang)
        super().__init__((sid, 'Toomics (Only free chapters)', lang, ROOT, True), TITLE, rf'({CHAPTER})', interval=.35)

    def parent_url(self, identity):
        return f'{ROOT}/{self.locale}/webtoon/episode/toon/{identity}/search/Y'

    def own_path(self, url):
        prefix = urlsplit(url).path.strip('/').split('/', 1)[0]
        return prefix == self.locale or prefix in LEGACY.get(self.locale, ())

    def is_title(self, url):
        return super().is_title(url) and self.own_path(url)

    def is_chapter(self, url):
        return super().is_chapter(url) and self.own_path(url)

    def chapter_identity(self, url):
        parsed = urlsplit(url)
        return parsed.path.rstrip('/'), tuple(sorted((key, value) for key, value in parse_qsl(parsed.query) if key != TILE))

    def title_for(self, url):
        current = param(url, TILE) or param(url, 'toon')
        path = re.search(rf'/toon/({ID})(?:/|$)', urlsplit(url).path)
        if not current and path:
            current = path[1]
        return self.parent_url(current) if re.fullmatch(ID, current) else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = self.title_key(url) or param(url, 'toon') or urlsplit(url).path.strip('/')
        return self.parent_url(key) if re.fullmatch(ID, key) else ''

    def saved_chapter_matches(self, target, title):
        bound = self.title_for(target)
        return bool(self.is_chapter(target) and (self.title_key(bound) == self.title_key(title)
                                                if bound else self.confirm_archive_membership(target, title)))

    def document(self, http, url, *, action=None):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/' + self.locale,
                                                    'User-Agent': USER_AGENT}, action=action)
        if urlsplit(final).netloc != HOST:
            raise SourceError('Toomics перенаправил на другой сайт.')
        return BeautifulSoup(raw, 'html.parser'), final

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page > 1:
            return [], False
        path = f'{ROOT}/{self.locale}/webtoon'
        if query:
            target = path + '/ajax_search'
            raw, final, _ = http.document(target, method='POST', data={'toonData': query}, action='native-series-form',
                                          headers={'Referer': ROOT + '/' + self.locale, 'User-Agent': USER_AGENT})
            if final != target:
                raise SourceError('Toomics перенаправил поиск.')
            payload = json.loads(raw)
            # Since Nov 2026 the results are {"webtoon": {"sHtml": ...}} (the
            # extension reads the same field); older answers used "content".
            content = payload.get('content') if isinstance(payload, dict) else None
            if content is None and isinstance(payload, dict) and isinstance(payload.get('webtoon'), dict):
                content = payload['webtoon'].get('sHtml')
            if not isinstance(content, str):
                raise SourceError('Toomics изменил формат поиска.')
            doc = BeautifulSoup(decode_markup(content), 'html.parser')
            nodes = doc.select('#search-list-items li')
        else:
            doc, final = self.document(http, path + ('/new_comics' if sort == 'updated' else '/ranking'))
            nodes = doc.select('li > div.visual a:has(img)')
        rows = {}
        for node in nodes:
            name = node_text(node.select_one('strong' if query else 'h4[class$="title"]'))
            anchor = node.select_one('a.relative[href]') if query else node
            raw_href = anchor.get('href', '') if anchor else ''
            if match := REF.search(raw_href):
                raw_href = unquote(match[1])
            url = self.site_link(raw_href, ROOT)
            key = self.title_key(url) or param(url, 'toon')
            if name and re.fullmatch(ID, key):
                rows[key] = self.record(self.parent_url(key), name,
                                        picture(node.select_one('img'), ROOT, ('data-original',)))
        return list(rows.values()), False

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        header = doc.select_one('#glo_contents section.relative:has(img[src*="thumb"])')
        row['genres'] = [tag.strip() for tag in node_text(header.select_one('h2 + div li:nth-child(2)')).split('·')
                         if tag.strip()] if header else []
        row['tags'] = [node['data-tag-name'].strip() for node in header.select('a[data-tag-name]')
                       if node['data-tag-name'].strip()] if header else []
        row['format'] = 'webtoon'
        return row

    def chapters(self, http, doc, final):
        key = self.title_key(final)
        rows = {}
        for node in doc.select('li.normal_ep:has(.coin-type1, .coin-type6)'):
            anchor = node.select_one('a[onclick]')
            match = REF.search(anchor['onclick']) if anchor else None
            if not match:
                continue
            target = self.site_link(match[1], final)
            if not self.is_chapter(target):
                continue
            label = node_text(node.select_one('div.cell-title strong'))
            raw_num = node_text(node.select_one('div.cell-num'))
            time = node.select_one('div.cell-time time')
            stamp = (time.get('datetime') or node_text(time)) if time else ''
            stamp = stamp[:10] if re.match(r'\d{4}-\d\d-\d\d', stamp) else stamp.replace('.', ' ')
            stamp = next((day for fmt in ('%b %d, %Y', '%d %b, %Y', '%Y %m %d')
                          if (day := release_date(stamp, fmt))), '')
            url = query_url(target, **{TILE: key})
            rows[url] = self.chapter(url, (raw_num + ' - ' if raw_num else '') + label,
                                     number(raw_num), date=stamp, translator='Toomics')
        return self.order(rows), False

    def pages(self, http, url):
        target = query_url(url, **{TILE: []})
        doc, final = self.document(http, target, action='toomics-public-view')
        if doc.select_one('div.section_age_verif'):
            confirm = query_url(ROOT + '/' + self.locale + '/index/set_display/', display='A', **{'return': '/' + self.locale})
            self.document(http, confirm, action='toomics-display')
            doc, final = self.document(http, target, action='toomics-public-view')
        if doc.select_one('div.section_age_verif') or not self.is_chapter(final):
            raise SourceAccessError('Toomics не предоставил открытый выпуск.')
        return [src for image in doc.select('div[id^="load_image_"] img')
                if (src := picture(image, final, ('data-src',)))]


LANGUAGE_IDS = (('371640888113435809', 'zh-Hant'), ('2191753978421234924', 'zh-Hans'),
                ('2289891939341407590', 'fr'), ('4230797637510582729', 'de'), ('4488498756724948818', 'pt-BR'),
                ('4863693274136077953', 'es'), ('7004582542854505662', 'en'), ('7362369816539610504', 'es-419'),
                ('7652402685655897221', 'it'))
SOURCES = tuple(Toomics(*identity) for identity in LANGUAGE_IDS)
