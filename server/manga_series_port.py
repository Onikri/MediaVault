"""Common server contract for website catalogues with a series and chapter hierarchy."""

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_madara import CHAPTER_NUMBER, VOLUME_NUMBER, OriginPace, image_from, image_url, node_text, release_date
from manga_source_tags import unique
from manga_webcomics import Profile, Webcomic, Work
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


WORD = r'(?:[^/\s?#.]+|\.(?!\.?/|$)){1,200}'
NUMBER = r'[0-9]{1,9}(?:[.,][0-9]{1,4})?'
MAX_CHAPTERS = 10000
MAX_PAGES = 1500
PAYWALL = 'form.purchase-form, .chapter-locked, .purchase-required, .paywall'


def series_api(host, path, query):
    from manga_alpha_manga import public_api as alpha
    from manga_asura_native import public_api as asura
    from manga_booru_pools import public_api as booru
    from manga_bookwalker_jp import public_api as bookwalker
    from manga_ciaoplus import public_api as ciao
    from manga_clipstudio_sources import public_api as firecross
    from manga_comicklive import public_api as comicklive
    from manga_coronaex import public_api as coronaex
    from manga_corocoro import public_api as corocoro
    from manga_archive_ports import public_api as archives
    from manga_catalogue_api_ports import public_api as catalogue_api
    from manga_creator_feeds import public_api as creator_feed
    from manga_cubari import public_api as cubari
    from manga_direct_catalogues import public_api as direct_html
    from manga_direct_payloads import public_api as payloads
    from manga_dmm import public_api as dmm
    from manga_docomo import public_api as docomo
    from manga_drecomics import public_api as drecomics
    from manga_dynasty import public_api as dynasty
    from manga_ebookrenta import public_api as ebookrenta
    from manga_gallery_archive_ports import public_api as gallery_archives
    from manga_hakusensha import public_api as hakusensha
    from manga_honeytoon_native import public_api as honeytoon
    from manga_html_families import public_api as html
    from manga_html_archives import public_api as html_archives
    from manga_illustrated_archives import public_api as illustrated
    from manga_independent_json_ports import public_api as independent_json
    from manga_initmanga import public_api as initmanga
    from manga_inkstory import public_api as ink
    from manga_jjcos import public_api as jjcos
    from manga_japanese_readers import public_api as japanese_readers
    from manga_json_families import public_api as api
    from manga_kappabeast import public_api as kappa
    from manga_klto9 import public_api as klto9
    from manga_korean_seventh import public_api as korean_seventh
    from manga_mangaplus import public_api as mangaplus
    from manga_mangamee import public_api as mangamee
    from manga_mangabox import public_api as mangabox
    from manga_mangack import public_api as mangack
    from manga_mangameets import public_api as mangameets
    from manga_mangaone import public_api as mangaone
    from manga_mangafive import public_api as mangafive
    from manga_mangalix import public_api as mangalix
    from manga_mangaplaza import public_api as mangaplaza
    from manga_park_publisher import public_api as manga_park
    from manga_manta_native import public_api as manta
    from manga_luscious_native import public_api as luscious
    from manga_lusttoon import public_api as lusttoon
    from manga_mangataro import public_api as mangataro
    from manga_mokuro import public_api as mokuro
    from manga_pandachaika import public_api as pandachaika
    from manga_natsuid import public_api as natsuid
    from manga_ninehentai import public_api as ninehentai
    from manga_ososedki import public_api as ososedki
    from manga_pixivcomic import public_api as pixivcomic
    from manga_pornpics import public_api as pornpics
    from manga_public_galleries import public_api as gallery_api
    from manga_publus_sources import public_api as publus
    from manga_rayuba import public_api as rayuba
    from manga_reimanga import public_api as rei
    from manga_rawkuma_overlay import public_api as rawkuma_me
    from manga_remaining_families import public_api as remaining
    from manga_ru_families import public_api as ru
    from manga_ru_json_ports import public_api as ru_json
    from manga_russian_direct import public_api as russian_direct
    from manga_sacachispa import public_api as sacachispa
    from manga_scan_directory import public_api as scan_directory
    from manga_scan_api_ports import public_api as scan_api
    from manga_scanlation_json import public_api as scanlation
    from manga_scanlation_catalogues import public_api as scan_cats
    from manga_senkuro_native import public_api as senkuro
    from manga_simply_native import public_api as simply
    from manga_sixth_profiles import public_api as sixth
    from manga_seventh_data import public_api as seventh
    from manga_small_readers import public_api as small_readers
    from manga_spa_catalogues import public_api as spa_catalogue
    from manga_speedbinb_sources import public_api as speedbinb
    from manga_webtoons_native import public_api as webtoon_native
    from manga_webnex import public_api as webnex
    from manga_standalone_ports import public_api as standalone
    from manga_toonlook import public_api as toonlook
    from manga_toonkotsu import public_api as toonkotsu
    from manga_toonz import public_api as toonz
    from manga_twicomi import public_api as twicomi
    from manga_voyceme import public_api as voyceme
    from manga_yarnovel import public_api as yarnovel
    from manga_zerosum import public_api as zerosum

    if host == 'mangarw.com' and path == '/api/v1/chapters':
        return bool(re.fullmatch(r'id=[0-9]{1,18}', query))
    return any(route(host, path, query) for route in (html, api, ru, archives, direct_html, payloads, remaining, senkuro, ink,
                                                     standalone, independent_json, natsuid, creator_feed, spa_catalogue,
                                                     russian_direct, yarnovel, gallery_api, scanlation, scan_directory, ru_json,
                                                     mangataro, initmanga, scan_cats, html_archives, kappa, illustrated,
                                                     sacachispa, speedbinb, webtoon_native, sixth, luscious, simply,
                                                     pandachaika, toonlook, alpha, catalogue_api, klto9, mangaplus,
                                                     small_readers, scan_api, manta, gallery_archives, mangamee, webnex,
                                                     seventh, rayuba, zerosum, rei, rawkuma_me, korean_seventh, ninehentai,
                                                     comicklive, jjcos, twicomi, booru, ososedki, honeytoon, voyceme,
                                                     mangameets, manga_park, mangabox, mangaone, asura, lusttoon, corocoro,
                                                     ciao, dynasty, mokuro, toonkotsu, firecross, hakusensha,
                                                     drecomics, ebookrenta, mangaplaza, coronaex, publus, docomo, mangafive,
                                                     dmm, pixivcomic, bookwalker, mangalix, toonz, cubari, mangack, pornpics,
                                                     japanese_readers))


def public_form(url, data, headers):
    if not isinstance(data, dict):
        return False
    if url == 'https://mangabuff.ru/chapters/load':
        token = headers.get('X-CSRF-TOKEN', '')
        referer = urlsplit(headers.get('Referer', ''))
        return (set(data) == {'manga_id'} and re.fullmatch(r'\d{1,14}', str(data['manga_id']))
                and isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9+/=_-]{16,200}', token)
                and referer.netloc == 'mangabuff.ru' and re.fullmatch(r'/manga/[^/]+/?', referer.path))
    if url == 'https://cutiecomics.com/index.php?do=search':
        page = str(data.get('search_start', ''))
        return (set(data) == {'do', 'subaction', 'full_search', 'search_start', 'result_from', 'story'}
                and data['do'] == data['subaction'] == 'search' and data['full_search'] == '0'
                and bool(re.fullmatch(r'[1-9]\d{0,3}', page)) and int(page) <= 2000
                and data['result_from'] == str((int(page)-1)*20+1)
                and isinstance(data['story'], str) and 4 <= len(data['story']) <= 160)
    from manga_standalone_ports import public_form as standalone
    from manga_fifth_families import public_form as fifth
    from manga_hentailoop import public_form as loop
    from manga_ru_html_ports import public_form as russian_html
    from manga_small_readers import public_form as small_readers
    from manga_rinko import public_form as rinko
    from manga_girlstop import search_form as girlstop
    from manga_honeytoon_native import search_form as honeytoon
    from manga_toomics import form as toomics
    from manga_dle_readers import public_form as dle_readers

    return (standalone(url, data) or fifth(url, data) or russian_html(url, data) or loop(url, data) or small_readers(url, data)
            or rinko(url, data, headers.get('Referer', '')) or girlstop(url, data) or honeytoon(url, data)
            or toomics(url, data) or dle_readers(url, data))


def document_json(http, url, referer):
    text, final, _ = http.document(url, headers={'Referer': referer}, action='native-series-json')
    if final != url:
        raise SourceError('Источник перенаправил запрос данных на другой маршрут.')
    try:
        return json.loads(text)
    except ValueError:
        raise SourceError('Источник изменил формат ответа каталога.') from None


def label_number(value, pattern=CHAPTER_NUMBER):
    found = pattern.search(str(value or ''))
    return float(found[1].replace(',', '.')) if found else None


def number(value):
    return float(str(value).replace(',', '.')) if re.fullmatch(NUMBER, str(value)) else None


def leaf(node, selector):
    return node.select_one(selector) if selector else node


def picture(node, base, attrs=()):
    if node is None:
        return ''
    for attr in attrs:
        value = image_url(node.get(attr), base)
        if value:
            return value
    if match := re.search(r'''url\(["']?([^"')]+)''', node.get('style', '')):
        return image_url(match[1], base)
    return image_from(node, base)


@dataclass(frozen=True)
class Cards:
    rows: str
    link: str
    title: str = ''
    cover: str = 'img'
    next: str = 'a[rel=next], a.next'
    title_attr: str = ''
    image_attrs: tuple = ('data-original',)


@dataclass(frozen=True)
class Meta:
    title: str
    cover: str
    description: str = ''
    aliases: str = ''
    genres: str = ''
    tags: str = ''
    author: str = ''
    status: str = ''


@dataclass(frozen=True)
class Archive:
    rows: str
    anchor: str = 'a[href]'
    title: str = ''
    date: str = ''
    date_pattern: str = '%Y-%m-%d'
    label_attr: str = ''
    next: str = ''
    fragment: str = ''
    number_attr: str = ''


class SeriesPort(Webcomic):
    def __init__(self, identity, title, chapter, *, hosts=(), legacy_hosts=(), interval=0):
        super().__init__(identity, Profile(title_path=title, chapter_path=chapter, hosts=hosts))
        self.TITLE_PATH = re.compile(title)
        self.CHAPTER_PATH = re.compile(chapter)
        self.legacy_hosts = frozenset(legacy_hosts)
        self.origin = OriginPace()
        self.origin.interval = interval

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        doc, final = super().document(http, url)
        from manga_sources import guard

        guard(doc)
        return doc, final

    def json(self, http, url, referer=None):
        self.origin.wait(getattr(http, 'deadline', None))
        return document_json(http, url, referer or self.ROOT + '/')

    def canonical(self, value):
        target = self.site_link(value)
        if target:
            return target
        if not isinstance(value, str) or not value:
            return ''
        try:
            parsed = urlsplit(value)
            if parsed.scheme in {'http', 'https'} and parsed.netloc in self.legacy_hosts:
                return self.site_link(self.ROOT + urlunsplit(('', '', parsed.path, parsed.query, parsed.fragment)))
        except ValueError:
            pass
        return ''

    def record(self, url, title, cover='', *, aliases=(), description='', genres=(), tags=(), authors=(), status=''):
        row = self.row(Work(url, title, cover, description, aliases=tuple(aliases)), url)
        row.update(genres=unique(genres), tags=unique(tags), authors=unique(authors), status=status)
        row['format'] = 'manga'
        return row

    def card_rows(self, doc, final, spec):
        result = {}
        for node in doc.select(spec.rows):
            anchor = leaf(node, spec.link)
            title_node = leaf(node, spec.title) if spec.title else anchor
            url = self.canonical(urljoin(final, anchor.get('href', ''))) if anchor else ''
            title = title_node.get(spec.title_attr, '') if title_node and spec.title_attr else node_text(title_node)
            if url and title and self.is_title(url):
                row = self.record(url, title, picture(leaf(node, spec.cover), final, spec.image_attrs))
                result[row['id']] = row
        return list(result.values()), bool(spec.next and doc.select_one(spec.next))

    def metadata(self, doc, url, spec):
        title = node_text(leaf(doc, spec.title))
        if not title:
            raise SourceError('Источник не предоставил карточку указанного тайтла.')
        values = lambda selector: [node_text(node) for node in doc.select(selector)] if selector else []
        cover = picture(leaf(doc, spec.cover), url, ('data-original',))
        if not cover:
            meta = doc.select_one('meta[property="og:image"][content]')
            cover = image_url(meta['content'], url) if meta else ''
        aliases = re.split(r'\s*[;|]\s*|\s+/\s+', node_text(leaf(doc, spec.aliases))) if spec.aliases else []
        return self.record(url, title, cover, aliases=aliases, description=node_text(leaf(doc, spec.description)) if spec.description else '',
                           genres=values(spec.genres), tags=values(spec.tags), authors=values(spec.author),
                           status=node_text(leaf(doc, spec.status)) if spec.status else '')

    def title_document(self, http, url):
        doc, final = self.document(http, url)
        if not self.is_title(final) or self.title_key(final) != self.title_key(url):
            raise SourceError('Источник перенаправил на другой тайтл.')
        return doc, final

    def title_key(self, url):
        match = self.TITLE_PATH.fullmatch(urlsplit(url).path)
        return match[1] if match else ''

    def chapter_key(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return match[1] if match else ''

    def title_for(self, url):
        return self.ROOT + '/' + self.chapter_key(url)

    def saved_title_url(self, url):
        return self.canonical(url)

    def saved_chapter(self, row, root, title):
        value = row.get('realUrl') or row.get('url') or ''
        return self.canonical(urljoin(root.rstrip('/') + '/', value))

    def saved_chapter_matches(self, target, title):
        return bool(self.chapter_key(target) and self.chapter_key(target) == self.title_key(title))

    def chapter(self, url, title='', n=None, date='', season=None, translator=''):
        if n is None:
            n = label_number(title)
        if n is None:
            n = label_number(urlsplit(url).path)
        vol = VOLUME_NUMBER.search(title + ' ' + urlsplit(url).path)
        return {**self.episode(url, title, n, date),
                'season': season or (int(vol[1]) if vol else 1), 'translator': translator}

    def list_chapters(self, http, doc, final, spec):
        seen, rows = set(), {}
        for _ in range(80):
            seen.add(final)
            for item in doc.select(spec.rows):
                anchor = leaf(item, spec.anchor)
                if not anchor:
                    continue
                url = self.site_link(anchor.get('href'), final)
                if not url or not self.is_chapter(url):
                    continue
                fragment = item.get(spec.fragment, '') if spec.fragment else ''
                if fragment:
                    url = urlunsplit(urlsplit(url)._replace(fragment=fragment))
                title = anchor.get(spec.label_attr) if spec.label_attr else ''
                title = title or node_text(leaf(item, spec.title) if spec.title else anchor)
                date = node_text(leaf(item, spec.date)) if spec.date else ''
                n = number((item.select_one(f'[{spec.number_attr}]') or item).get(spec.number_attr)) if spec.number_attr else None
                rows[url] = self.chapter(url, title, n, release_date(date, spec.date_pattern))
                if len(rows) >= MAX_CHAPTERS:
                    return self.order(rows), True
            anchor = doc.select_one(spec.next) if spec.next else None
            if not anchor:
                return self.order(rows), False
            more = self.site_link(anchor.get('href'), final)
            if not more or more in seen or self.title_key(more) != self.title_key(final):
                raise SourceError('Некорректная пагинация оглавления источника.')
            doc, final = self.document(http, more)
        return self.order(rows), True

    def order(self, rows):
        result = list(rows.values())
        for idx, row in enumerate(result):
            if row['number'] is None:
                row['number'] = len(result) - idx
        return sorted(result, key=lambda row: (row['season'], row['number']))

    def page_document(self, http, url):
        doc, final = self.document(http, url)
        if not self.is_chapter(final) or self.chapter_identity(url) != self.chapter_identity(final):
            raise SourceError('Источник перенаправил на другую главу.')
        if doc.select_one(PAYWALL):
            raise SourceAccessError('Глава доступна на условиях источника.')
        return doc, final

    def chapter_identity(self, url):
        return urlsplit(url).path.rstrip('/')

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_title(url):
            doc, final = self.title_document(http, url)
            row = self.metadata(doc, final, self.meta)
            chapters, truncated = self.chapters(http, doc, final)
            pages = []
        elif self.is_chapter(url):
            pages = self.pages(http, url)
            if not 1 <= len(pages) <= MAX_PAGES or not all(pages):
                raise SourceError('Источник не предоставил полный список изображений главы.')
            title = self.title_for(url)
            slug = self.title_key(title) or self.chapter_key(url)
            row = self.record(title or url, slug.replace('-', ' '))
            chapters, truncated = [self.chapter(url, n=label_number(url) or 0)], False
        else:
            raise SourceError('Некорректная ссылка на тайтл или главу.')
        return self.reader_result(row, url, chapters, pages, truncated)

    def reader_result(self, row, url, chapters, pages, truncated=False):
        return {**row, 'url': self.reader_url(url), 'episodes': chapters, 'pages': pages, 'available': bool(chapters),
                'truncated': truncated, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({c['season'] for c in chapters})],
                'dubs': [], 'releases': [], 'translations': unique(c.get('translator', '') for c in chapters)}

    def details(self, http, url):
        url = self.saved_title_url(url)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на карточку источника.')
        return self.metadata(*self.title_document(http, url), self.meta)

    def catalogue_params(self, page, query, tag):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры каталога.')
        return query.strip()[:160]

    def confirm_archive_membership(self, target, title):
        http = PublicHttp(timeout=(3, 6))
        try:
            doc, final = self.title_document(http, title)
            rows, _ = self.chapters(http, doc, final)
            return any(self.chapter_identity(self.site_link(row['url'])) == self.chapter_identity(target)
                       for row in rows)
        finally:
            http.close()
