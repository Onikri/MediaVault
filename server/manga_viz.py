"""VIZ Manga and Shonen Jump's public catalogue and free chapter viewer."""

from dataclasses import dataclass
from io import BytesIO
import json
import re
from urllib.parse import parse_qsl, urlsplit

from PIL import Image

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import MAX_PAGES, number, picture
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError


ROOT = 'https://www.viz.com'
HOST = 'www.viz.com'
READER = ROOT + '/manga/get_manga_url'
ID = r'[0-9]{1,15}'
SERVICE = r'(?:shonenjump|vizmanga)'
CHAPTER_PATH = re.compile(rf'/{SERVICE}/{SEGMENT}/chapter/({ID})/?')
COUNT = re.compile(r'\bvar\s+pages\s*=\s*(\d{1,4})\s*;')
UNIQUE_IMAGE_ID = 42016
EXIF_IFD = 34665
COLS, ROWS, GAP = 10, 15, 10


def viewer_route(value, referer):
    parts, ref = urlsplit(value), urlsplit(referer)
    match = CHAPTER_PATH.fullmatch(ref.path)
    if (parts.hostname != HOST or parts.path != '/manga/get_manga_url'
            or ref.hostname != HOST or ref.scheme != 'https' or not match):
        return False
    try:
        fields = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=4)
    except ValueError:
        return False
    args = dict(fields)
    return (len(fields) == 3 and set(args) == {'device_id', 'manga_id', 'pages'} and args['device_id'] == '3'
            and args['manga_id'] == match[1] and bool(re.fullmatch(r'\d{1,4}', args['pages']))
            and 0 <= int(args['pages']) < MAX_PAGES)


def unscramble(data):
    try:
        with Image.open(BytesIO(data)) as image:
            exif = image.getexif()
            raw = exif.get_ifd(EXIF_IFD).get(UNIQUE_IMAGE_ID) or exif.get(UNIQUE_IMAGE_ID)
            if not raw:
                return data
            if isinstance(raw, bytes):
                raw = raw.decode('ascii')
            key = [int(value, 16) for value in raw.rstrip('\0').split(':')]
            width, height = image.width - (COLS - 1) * GAP, image.height - (ROWS - 1) * GAP
            w, h = width // COLS, height // ROWS
            sw, sh = w + GAP, h + GAP
            inner = COLS - 2
            if (min(w, h) < 1 or image.width * image.height > 24_000_000
                    or len(key) != inner * (ROWS - 2) or set(key) != set(range(len(key)))):
                raise ValueError('Invalid tile dimensions or order')
            with image.convert('RGB') as source, Image.new('RGB', (width, height)) as result:
                def draw(x, y, span, depth, dx, dy):
                    with source.crop((x, y, x + span, y + depth)) as tile:
                        result.paste(tile, (dx, dy))

                draw(0, 0, width, h, 0, 0)
                draw(0, sh, w, height - 2 * h, 0, h)
                bottom = (ROWS - 1) * sh
                draw(0, bottom, width, image.height - bottom, 0, (ROWS - 1) * h)
                draw((COLS - 1) * sw, sh, width - (COLS - 1) * w, height - 2 * h, (COLS - 1) * w, h)
                for index, destination in enumerate(key):
                    draw((index % inner + 1) * sw, (index // inner + 1) * sh, w, h,
                         (destination % inner + 1) * w, (destination // inner + 1) * h)
                out = BytesIO()
                result.save(out, 'JPEG', quality=90)
                return out.getvalue()
    except (OSError, AttributeError, ValueError, TypeError, Image.DecompressionBombError):
        raise SourceError('VIZ вернул повреждённую страницу.') from None


def page_target(http, target, referer):
    raw, final, _ = http.document(target, headers={'Referer': referer}, action='viz-page')
    if final != target:
        raise SourceError('VIZ перенаправил запрос страницы.')
    try:
        data = json.loads(raw)
        if data.get('ok') == 0:
            raise SourceAccessError('Глава недоступна в открытом просмотре VIZ.')
        entry = data.get('data')
        if isinstance(entry, dict):
            for value in entry.values():
                if url := image_url(value, ROOT):
                    return url
    except (ValueError, AttributeError):
        pass
    raise SourceError('VIZ не предоставил адрес страницы.')


@dataclass(frozen=True)
class VizPage:
    target: str
    image: str = ''

    def fetch(self, http, referer):
        from manga_page_media import read_image

        image = self.image or page_target(http, self.target, referer)
        response, _ = http._open(image, headers={'Referer': referer})
        return unscramble(read_image(http, response))


class Viz(JsonSeries):
    def __init__(self, sid, name, service, category):
        super().__init__((sid, name, 'en', ROOT, False),
                         rf'/{service}/chapters/({SEGMENT})/?',
                         rf'/{service}/({SEGMENT})/chapter/({ID})/?',
                         legacy_hosts=('viz.com',), interval=.5)
        self.service, self.category = service, category

    def title_for(self, url):
        return f'{ROOT}/{self.service}/chapters/{self.chapter_key(url)}'

    def saved_title_url(self, value):
        target = self.canonical(value)
        slug = urlsplit(target).path.strip('/')
        return f'{ROOT}/{self.service}/chapters/{slug}' if re.fullmatch(SEGMENT, slug) else target

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        parts = urlsplit(target)
        slug, cid = self.title_key(title), parts.path.strip('/')
        if slug and parts.fragment == slug and re.fullmatch(ID, cid):
            return f'{ROOT}/{self.service}/{slug}/chapter/{cid}'
        return target

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        section = 'free-chapters' if sort == 'updated' else 'trending-manga'
        url = query_url(ROOT + '/search', search=query, category=self.category) if query else (
            f'{ROOT}/manga-books/{self.service}/section/{section}')
        doc, final = self.document(http, url)
        links = doc.select('div.p-cs-tile a.o_property-link' if query else 'div.o_sortable > a.o_chapters-link')
        if not query and not links and urlsplit(final).path != urlsplit(url).path:
            raise SourceAccessError('Открытый каталог VIZ недоступен для этого региона.')
        rows = {}
        for anchor in links:
            found = self.site_link(anchor.get('href'), final)
            title = node_text(anchor.select_one('div.pad-x-rg'))
            if not title or not self.is_title(found) or query.casefold() not in title.casefold():
                continue
            cover = picture(anchor.select_one('div.pos-r img.disp-bl, img'), final, ('data-original',))
            rows[found] = self.record(found, title, cover)
        return list(rows.values()), False

    def series(self, http, url):
        doc, final = self.title_document(http, self.saved_title_url(url))
        intro = doc.select_one('section#series-intro')
        if not intro:
            raise SourceAccessError('Карточка VIZ недоступна для этого региона.')
        title = node_text(intro.select_one('h2'))
        if not title:
            raise SourceError('VIZ не предоставил название тайтла.')
        author = node_text(intro.select_one('span.disp-bl--bm')).removeprefix('Created by ')
        cover = doc.select_one('meta[property="og:image"][content]')
        row = self.record(final, title, image_url(cover['content'], final) if cover else '',
                          authors=(author,), description=node_text(intro.select_one('h2 + div')))
        found = {}
        for chapter in doc.select('section.section_chapters a.o_chapter-container[id^="ch-"][data-target-url]'):
            target = self.site_link(chapter['data-target-url'], final)
            if not self.is_chapter(target) or self.chapter_key(target) != self.title_key(final):
                continue
            label = node_text(chapter.select_one('div:nth-child(2) table td')) or node_text(chapter)
            numeral = re.search(r'\bCh\.\s*([0-9]+(?:\.[0-9]+)?)', label)
            stamp = node_text(chapter.select_one('div:nth-child(1) table td[align="right"], div:nth-child(1) table td > span'))
            found[target] = self.chapter(target, label, number(numeral[1]) if numeral else None,
                                         release_date(stamp, '%B %d, %Y'))
        return row, self.order(found)

    def pages(self, http, url):
        doc, referer = self.page_document(http, url)
        match = CHAPTER_PATH.fullmatch(urlsplit(referer).path)
        if not match:
            raise SourceAccessError('VIZ ограничил доступ к выпуску.')
        count = next((int(item[1]) + 1 for script in doc.select('script')
                      if script.string and (item := COUNT.search(script.string))), 0)
        if not 1 <= count <= MAX_PAGES:
            raise SourceError('VIZ не предоставил числа страниц открытого выпуска.')
        targets = [query_url(READER, device_id=3, manga_id=match[1], pages=index) for index in range(count)]
        first = page_target(http, targets[0], referer)
        return remember([(target, VizPage(target, first if index == 0 else ''))
                         for index, target in enumerate(targets)], referer)


SOURCES = (
    Viz('5065732785260259278', 'VIZ Shonen Jump', 'shonenjump', 'SjChapterSeries'),
    Viz('7652472715104061281', 'VIZ Manga', 'vizmanga', 'VmChapterSeries'),
)
