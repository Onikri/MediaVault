"""Dragon Ball Multiverse public comics and lazy page composition."""

from io import BytesIO
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

from manga_global_dbm_profiles import DRAGON
from manga_madara import image_url, node_text
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceError, public_url


ROOT = 'https://www.dragonball-multiverse.com'
HOST = 'www.dragonball-multiverse.com'
KEY = r'[a-zA-Z0-9][a-zA-Z0-9-]{0,60}'
NUMBER = r'[0-9]{1,5}'
LOCALE = r'[A-Za-z_]{2,8}'
CHAPTERS = re.compile(rf'/({LOCALE})/chapters\.html')
PAGE = re.compile(rf'/({LOCALE})/({KEY})-({NUMBER})\.html')
MARKER = 'mv_dbm_page='
BACKGROUND = re.compile(r"""url\(\s*['"]?([^)'"]+)['"]?\s*\)""")
SCALE = re.compile(r'scale\(\s*(\d+(?:\.\d+)?)\s*\)')
CSS = re.compile(r'(?:^|;)\s*(left|top|width)\s*:\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*(?=;|$)')
DEBIAN_FONTS = Path('/usr/share/fonts/opentype/noto')
NOTO = Path('/usr/share/fonts/truetype/noto')
WINDOWS_FONTS = Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts'


def page_marker(value):
    try:
        sid, raw = split_reader_url(value)
        parts = urlsplit(raw)
        page = PAGE.fullmatch(parts.path)
    except ValueError:
        raise SourceError('Некорректный адрес страницы Dragon Ball Multiverse.') from None
    profile = BY_ID.get(sid)
    if (profile is None or parts.scheme != 'https' or parts.netloc != HOST or parts.query
            or parts.fragment != MARKER + sid or not page or page[1] != profile.locale):
        raise SourceError('Некорректный адрес страницы Dragon Ball Multiverse.')
    return profile, ROOT + parts.path


def read_layout(http, value):
    profile, url = page_marker(value)
    doc, final = profile.document(http, url)
    page = doc.select_one('#balloonsimg')
    if not page:
        raise SourceError('Dragon Ball Multiverse не предоставил изображение страницы.')
    image = page.select_one('img')
    style = page.get('style', '')
    background = BACKGROUND.search(style)
    source = page.get('src') or (image or {}).get('src') or (background[1] if background else '')
    url = image_url(source, final)
    if not url:
        raise SourceError('Dragon Ball Multiverse вернул неверный адрес изображения.')
    scale = float(m.group(1)) if (m := SCALE.search(style)) else 1
    if not .1 <= scale <= 10:
        raise SourceError('Dragon Ball Multiverse вернул неверный масштаб страницы.')
    balloons = []
    nodes = page.select('.balloon')
    if len(nodes) > 250:
        raise SourceError('Слишком много реплик на странице Dragon Ball Multiverse.')
    for balloon in nodes:
        text = node_text(balloon)
        if not text:
            continue
        positions = {match[1]: float(match[2]) for match in CSS.finditer(balloon.get('style', ''))}
        if not positions.keys() >= {'left', 'top', 'width'} or len(text) > 1000:
            raise SourceError('Dragon Ball Multiverse вернул неверную разметку реплики.')
        balloons.append((text, positions['left'] * scale, positions['top'] * scale, positions['width'] * scale))
    return profile, url, balloons


def balloon_font(language):
    cjk = {'ja': 0, 'ko': 1, 'zh': 2}
    if language in cjk:
        available = [(DEBIAN_FONTS / 'NotoSansCJK-Regular.ttc', cjk[language]),
                     (WINDOWS_FONTS / {'ja': 'meiryo.ttc', 'ko': 'malgun.ttf', 'zh': 'msyh.ttc'}[language], 0)]
    else:
        special = {'ar': 'NotoSansArabic-Regular.ttf', 'he': 'NotoSansHebrew-Regular.ttf'}
        available = [(NOTO / special.get(language, 'NotoSans-Regular.ttf'), 0),
                     ('DejaVuSans.ttf', 0), (WINDOWS_FONTS / 'arial.ttf', 0)]
    for path, index in available:
        try:
            return ImageFont.truetype(str(path), 14, index=index)
        except OSError:
            continue
    raise SourceError('На сервере нет шрифта для реплик Dragon Ball Multiverse.')


def wrap(text, font, width):
    line = ''
    rows = []
    for word in text.split():
        candidate = line + ' ' + word if line else word
        if font.getlength(candidate) <= width:
            line = candidate
            continue
        if line:
            rows.append(line)
        line = ''
        for char in word:
            if line and font.getlength(line + char) > width:
                rows.append(line)
                line = ''
            line += char
    if line:
        rows.append(line)
    return rows


def compose(raw, language, balloons):
    try:
        with Image.open(BytesIO(raw)) as image:
            w, h = image.size
            if min(w, h) < 4 or w*h > 24_000_000:
                raise ValueError
            with image.convert('RGB') as output:
                font = balloon_font(language)
                canvas = ImageDraw.Draw(output)
                for text, x, y, width in balloons:
                    if x >= w or y >= h or width < 1:
                        continue
                    height = sum(font.getmetrics())
                    width = min(width, w - x)
                    for index, line in enumerate(wrap(text, font, width)):
                        if y + index * height >= h:
                            break
                        canvas.text((x + width/2, y + index*height), line, anchor='mt', font=font, fill=(0, 0, 0))
                encoded = BytesIO()
                output.save(encoded, 'JPEG', quality=95)
                return encoded.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise SourceError('Dragon Ball Multiverse вернул повреждённое изображение.') from None


class DragonBall:
    ROOT = ROOT
    IS_NSFW = False
    scoped_urls = True

    def __init__(self, sid, language, name, locale):
        self.SOURCE_ID, self.LANGUAGE, self.NAME, self.locale = sid, language, name, locale
        self.TITLE_PATH = self.CHAPTER_PATH = re.compile(rf'/({locale})/chapters\.html')

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            sid, raw = split_reader_url(urljoin(base or ROOT + '/' + self.locale + '/', value))
            url = urlsplit(raw)
            if sid not in (None, self.SOURCE_ID) or url.scheme != 'https' or url.netloc not in {HOST, 'dragonball-multiverse.com'}:
                return ''
            if url.path != '/' and not url.path.startswith('/' + self.locale + '/'):
                return ''
            return public_url(urlunsplit(url._replace(netloc=HOST)), resolve_dns=False)
        except (ValueError, SourceError):
            return ''

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def parse(self, target):
        parts = urlsplit(self.site_link(target))
        if not CHAPTERS.fullmatch(parts.path):
            return None
        try:
            args = parse_qs(parts.query, keep_blank_values=True, max_num_fields=5)
        except ValueError:
            return None
        comic = args.get('comic', ['page'])
        chapter = args.get('chapter', [''])
        if len(comic) == len(chapter) == 1 and re.fullmatch(KEY, comic[0]) and (
                not chapter[0] or re.fullmatch(NUMBER, chapter[0])):
            return comic[0], chapter[0]
        return None

    def comic_url(self, key, chapter=''):
        args = {'comic': key}
        if chapter:
            args['chapter'] = chapter
        return ROOT + f'/{self.locale}/chapters.html?' + urlencode(args)

    def document(self, http, url):
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/' + self.locale + '/'})
        target = self.site_link(final)
        if not target or urlsplit(url).path != urlsplit(target).path or self.parse(url) != self.parse(target):
            raise SourceError('Dragon Ball Multiverse перенаправил запрос на другой маршрут.')
        return BeautifulSoup(raw, 'html.parser'), target

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or page < 1 or not isinstance(query, str) or tag:
            raise SourceError('Некорректные параметры каталога Dragon Ball Multiverse.')
        if page != 1:
            return [], False
        doc, final = self.document(http, ROOT + f'/{self.locale}/read.html')
        rows = {}
        term = query.strip().casefold()
        for item in doc.select('#dbm-reads .dbm-read'):
            anchor = item.select_one('a[href]')
            name = node_text(item.select_one('h3'))
            parsed = self.parse(self.site_link(anchor['href'], final)) if anchor else None
            if not parsed or not name or term and term not in name.casefold():
                continue
            key = parsed[0]
            url = self.reader_url(self.comic_url(key))
            raw_cover = item.select_one('img')
            rows.setdefault(key, {'id': f'suwayomi:{self.SOURCE_ID}:native:{key}', 'sourceId': self.SOURCE_ID,
                                  'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME, 'sourceOnly': True,
                                  'url': url, 'sourceUrl': url, 'kind': 'manga', 'format': 'comic',
                                  'language': self.LANGUAGE, 'title': name, 'aliases': [name],
                                  'description': node_text(item.select_one(':scope > div')),
                                  'cover': image_url(raw_cover.get('src'), final) if raw_cover else '',
                                  'genres': [], 'tags': [], 'ids': {}})
        return list(rows.values()), False

    def vocabulary(self, http):
        return []

    def work(self, http, key):
        doc, final = self.document(http, self.comic_url(key))
        rows, _ = self.catalogue(http)
        item = next((row for row in rows if self.parse(row['url']) == (key, '')), None)
        if item is None:
            raise SourceError('Комикс отсутствует в каталоге Dragon Ball Multiverse для этого языка.')
        episodes = []
        for entry in doc.select('.cadrelect.chapter'):
            anchor = entry.select_one('a[href]')
            if parsed := self.parse(self.site_link(anchor['href'], final)) if anchor else None:
                if parsed[0] == key and parsed[1]:
                    episodes.append({'url': self.reader_url(self.comic_url(*parsed)), 'number': int(parsed[1]), 'season': 1,
                                     'language': self.LANGUAGE, 'title': node_text(entry.select_one('h4'))})
        return item, list(reversed(episodes))

    def details(self, http, value):
        parsed = self.parse(value)
        if not parsed or parsed[1]:
            raise SourceError('Некорректная ссылка на тайтл Dragon Ball Multiverse.')
        return self.work(http, parsed[0])[0]

    def inspect(self, value, http):
        parsed = self.parse(value)
        if not parsed:
            raise SourceError('Некорректная ссылка на читалку Dragon Ball Multiverse.')
        key, chapter = parsed
        row, episodes = self.work(http, key)
        pages = []
        target = self.reader_url(self.comic_url(key, chapter))
        if chapter:
            episodes = [entry for entry in episodes if entry['url'] == target]
            if len(episodes) != 1:
                raise SourceError('Глава отсутствует в оглавлении Dragon Ball Multiverse.')
            doc, final = self.document(http, self.comic_url(key, chapter))
            for item in doc.select('.pageslist a[href]'):
                link = self.site_link(item['href'], final)
                page = PAGE.fullmatch(urlsplit(link).path)
                if page and page[2] == key:
                    pages.append(self.reader_url(ROOT + urlsplit(link).path) + '#' + MARKER + self.SOURCE_ID)
            pages = list(dict.fromkeys(pages))
            if not 1 <= len(pages) <= 500:
                raise SourceError('Dragon Ball Multiverse не предоставил список страниц главы.')
        return {**row, 'url': target, 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': False, 'dubs': [], 'releases': [],
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else [], 'translations': []}

    def saved_title_url(self, value):
        parsed = self.parse(value)
        return self.comic_url(parsed[0]) if parsed else ''

    def saved_chapter_url(self, value, locale, root):
        parsed = self.parse(self.site_link(value, root + '/' + locale + '/'))
        return self.comic_url(*parsed) if parsed and parsed[1] else ''

    def saved_chapter_matches(self, chapter, title):
        which, part = self.parse(chapter) or ('', '')
        work, _ = self.parse(title) or ('', '')
        return bool(part and which == work)


SOURCES = tuple(DragonBall(*profile) for profile in DRAGON)
BY_ID = {profile.SOURCE_ID: profile for profile in SOURCES}
