"""Rawkuma.me catalogue and language-specific comic text layers."""

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
import math
import re
from threading import Lock
from urllib.parse import parse_qsl, quote, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from PIL import Image, ImageColor, ImageDraw, ImageFont
from PIL.Image import DecompressionBombError

from manga_additional_catalogues import flight_objects
from manga_direct_payloads import JsonSeries, strings
from manga_madara import SEGMENT, image_url
from manga_series_port import number
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceError

# Rawkuma.me moved to mangamachina.com (extension ceb9d60b, 2026-11-15); saved
# rawkuma.me links keep opening on the new host.
HOST = 'mangamachina.com'
ROOT = 'https://' + HOST
LEGACY_HOSTS = ('rawkuma.me', 'www.rawkuma.me')
TITLE = rf'/(?:es/)?manga/({SEGMENT})/?'
CHAPTER = rf'/(?:es/)?manga/({SEGMENT})/({SEGMENT})/?'
FAMILY = re.compile(r'[A-Za-z0-9_ -]{1,64}')
FONT_CACHE = OrderedDict()
CACHE_GUARD = Lock()
MAX_OVERLAY = 64 * 1024


def public_api(host, path, query):
    if host != HOST or path != '/api/series':
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    return (len(pairs) == 2 and set(args) == {'lang', 'slugs'} and args['lang'] in {'en', 'es'}
            and bool(re.fullmatch(SEGMENT, args['slugs'])))


def float_px(value, default=0):
    try:
        result = float(str(value).removesuffix('px'))
        return result if math.isfinite(result) and abs(result) <= 100_000 else default
    except (TypeError, ValueError):
        return default


def color(value, fallback=None):
    if value in (None, '', 'none'):
        return fallback
    try:
        return ImageColor.getcolor(value, 'RGBA') if len(value) <= 40 else fallback
    except ValueError:
        return fallback


def font_file(http, family, referer):
    with CACHE_GUARD:
        if family in FONT_CACHE:
            FONT_CACHE.move_to_end(family)
            return FONT_CACHE[family]
    target = ROOT + '/media/_fonts/' + quote(family, safe='') + '.ttf'
    response, final = http._open(target, headers={'Referer': referer})
    try:
        if final != target:
            raise SourceError('Rawkuma.me перенаправил запрос шрифта.')
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 4 * 1024 * 1024:
                raise SourceError('Шрифт Rawkuma.me превышает лимит.')
    finally:
        response.close()
    if raw[:4] not in (b'\x00\x01\x00\x00', b'OTTO', b'true', b'ttcf'):
        raise SourceError('Rawkuma.me вернул неизвестный формат шрифта.')
    with CACHE_GUARD:
        FONT_CACHE[family] = bytes(raw)
        if len(FONT_CACHE) > 32:
            FONT_CACHE.popitem(last=False)
        return FONT_CACHE[family]


def load_font(http, family, fonts, referer, size):
    if family in fonts and FAMILY.fullmatch(family):
        try:
            return ImageFont.truetype(BytesIO(font_file(http, family, referer)), size)
        except (OSError, SourceError):
            pass
    return ImageFont.load_default(size=size)


def svg_nodes(svg):
    if not isinstance(svg, str) or len(svg) > MAX_OVERLAY or re.search(r'<!\s*(DOCTYPE|ENTITY)', svg, re.I):
        raise SourceError('Rawkuma.me вернул некорректный слой текста.')
    try:
        tree = ElementTree.fromstring('<overlay>' + svg + '</overlay>')
    except ElementTree.ParseError:
        raise SourceError('Rawkuma.me изменил формат слоя текста.') from None
    if len(list(tree.iter())) > 1000:
        raise SourceError('Текстовый слой Rawkuma.me превышает лимит.')
    return tree


@dataclass(frozen=True)
class RawkumaPage:
    width: float
    height: float
    markup: str
    fonts: tuple

    def draw_text(self, bitmap, group, http, referer, sx, sy):
        css = dict(item.split(':', 1) for item in group.get('style', '').split(';') if ':' in item)
        css = {k.strip(): v.strip() for k, v in css.items()}
        family = css.get('font-family', '').split(',', 1)[0].strip(' \'\"')
        size = round(float_px(css.get('font-size'), 16) * sy)
        if not 1 <= size <= 512:
            return
        font = load_font(http, family, self.fonts, referer, size)
        ink = color(css.get('fill'), (0, 0, 0, 255))
        stroke = color(css.get('stroke'))
        stroke_width = min(32, max(0, round(float_px(css.get('stroke-width'), 1) * sy))) if stroke else 0
        for line in group.iter('text'):
            wording = ' '.join(''.join(line.itertext()).split())
            if not wording or len(wording) > 600:
                continue
            left, top, right, bottom = font.getbbox(wording, anchor='ls', stroke_width=stroke_width)
            width, height = max(1, right - left), max(1, bottom - top)
            target = float_px(line.get('textLength'))
            scale = (target * sx / max(1, font.getlength(wording))) if target > 0 else sx / sy
            span = max(1, round(width * scale))
            if width * height > 4_000_000 or span * height > 4_000_000:
                continue
            text = Image.new('RGBA', (width, height))
            draw = ImageDraw.Draw(text)
            draw.text((-left, -top), wording, font=font, anchor='ls', fill=ink, stroke_width=stroke_width, stroke_fill=stroke)
            if span != width:
                text = text.resize((span, height), Image.Resampling.LANCZOS)
            x = round(float_px(line.get('x')) * sx + left * scale)
            y = round(float_px(line.get('y')) * sy + top)
            bitmap.alpha_composite(text, (x, y))

    def overlay(self, raw, http, referer):
        try:
            with Image.open(BytesIO(raw)) as source:
                if source.width * source.height > 35_000_000:
                    raise SourceError('Страница Rawkuma.me слишком большая.')
                bitmap = source.convert('RGBA')
            sx, sy = bitmap.width / self.width, bitmap.height / self.height
            tree = svg_nodes(self.markup)
            draw = ImageDraw.Draw(bitmap, 'RGBA')
            for element in tree:
                if element.tag == 'g':
                    self.draw_text(bitmap, element, http, referer, sx, sy)
                elif element.tag == 'rect':
                    x, y, w, h = (float_px(element.get(key)) for key in ('x', 'y', 'width', 'height'))
                    if min(w, h) <= 0:
                        continue
                    radius = max(0, round(float_px(element.get('rx')) * min(sx, sy)))
                    border = min(32, max(1, round(float_px(element.get('stroke-width'), 1) * min(sx, sy))))
                    draw.rounded_rectangle((x * sx, y * sy, (x + w) * sx, (y + h) * sy), radius=radius,
                                           fill=color(element.get('fill')), outline=color(element.get('stroke')), width=border)
            output = BytesIO()
            bitmap.convert('RGB').save(output, 'JPEG', quality=95)
            return output.getvalue()
        except (OSError, ValueError, DecompressionBombError):
            raise SourceError('Rawkuma.me вернул повреждённое изображение.') from None


class RawkumaMe(JsonSeries):
    def __init__(self, sid, lang):
        super().__init__((sid, 'Rawkuma.me', lang, ROOT, True), TITLE, CHAPTER, interval=.35, legacy_hosts=LEGACY_HOSTS)

    @property
    def site(self):
        return ROOT + ('/es' if self.LANGUAGE == 'es' else '')

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.site + '/manga/' + key if key else ''

    def chapter_identity(self, url):
        return urlsplit(url).path.removeprefix('/es/').lstrip('/').rstrip('/')

    def saved_title_url(self, value):
        url = self.canonical(value)
        slug = self.title_key(url) or self.chapter_key(url) or urlsplit(url).path.strip('/')
        return self.site + '/manga/' + slug if re.fullmatch(SEGMENT, slug) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        path = urlsplit(url).path.strip('/')
        if re.fullmatch(rf'{SEGMENT}/{SEGMENT}', path):
            return self.site + '/manga/' + path
        return ''

    def summary(self, data):
        slug, name = data.get('slug'), data.get('title')
        if not isinstance(slug, str) or not re.fullmatch(SEGMENT, slug) or not isinstance(name, str) or not name:
            return None
        target = self.site + '/manga/' + slug
        row = self.record(target, name, image_url(data.get('cover'), ROOT + '/'),
                          description=data.get('synopsis') or '', aliases=strings(data.get('altTitles')),
                          authors=[data.get('author'), data.get('artist')], genres=strings(data.get('genres')),
                          status=str(data.get('status') or ''))
        if data.get('type'):
            row['format'] = str(data['type']).casefold()
        return row

    def flight(self, http, target):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(target)
        if urlsplit(final).netloc != HOST or self.chapter_identity(final) != self.chapter_identity(target):
            raise SourceError('Rawkuma.me перенаправил запрос на другую страницу.')
        try:
            return raw, flight_objects(raw)
        except SourceError:
            # MangaMachina pages repeat shared references so often that resolving
            # them exceeds the parse budget; the cards, series and reader objects
            # are literal, so read the stream's objects as they are.
            from manga_additional_catalogues import flight_models, flight_stream
            from manga_vinetheme import dictionaries

            return raw, [node for model in flight_models(flight_stream(raw)).values() for node in dictionaries(model)]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        params = {'lang': self.LANGUAGE, 'order': 'date' if sort == 'updated' else 'popular', 'page': page}
        if query:
            params['q'] = query
        if re.fullmatch(SEGMENT, tag):
            params['genre'] = tag
        raw, values = self.flight(http, query_url(ROOT + '/manga', **params))
        rows = {}
        for item in values:
            # Listing cards carry only slug, title and cover since the move.
            if all(k in item for k in ('slug', 'title', 'cover')) and not {'pages', 'fonts'} & item.keys():
                if row := self.summary(item):
                    rows[row['url']] = row
        return list(rows.values()), bool(BeautifulSoup(raw, 'html.parser').select_one('a[rel=next]'))

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.json(http, query_url(ROOT + '/api/series', lang=self.LANGUAGE, slugs=slug))
        item = next((row for row in data if isinstance(row, dict) and row.get('slug') == slug), {})
        summary = self.summary(item)
        if not summary:
            raise SourceError('Rawkuma.me не предоставил указанное произведение.')
        result = {}
        for row in item.get('chapters') or []:
            cid = row.get('slug', '')
            if re.fullmatch(SEGMENT, cid) and self.LANGUAGE in strings(row.get('langs')):
                target = self.site + '/manga/' + slug + '/' + cid
                n = number(row.get('number'))
                if n is not None:
                    date = str(row.get('translatedAt') or row.get('releasedAt') or '')[:10]
                    result[target] = self.chapter(target, f'Chapter {n:g}', n=n, date=date)
        return summary, self.order(result)

    def pages(self, http, url):
        target = ROOT + urlsplit(url).path.removeprefix('/es')
        _, values = self.flight(http, target)
        data = next((row for row in values if isinstance(row.get('pages'), list) and isinstance(row.get('fonts'), list)), {})
        fonts = tuple(family for family in strings(data.get('fonts')) if FAMILY.fullmatch(family))[:32]
        refs = []
        for item in data.get('pages', []):
            src = image_url(item.get('url'), target)
            styles = item.get('text') or {}
            svg = styles.get(self.LANGUAGE) if isinstance(styles, dict) else ''
            width, height = float_px(item.get('width')), float_px(item.get('height'))
            if not src:
                raise SourceError('Rawkuma.me вернул некорректный адрес изображения.')
            if svg:
                if not 1 <= width <= 16000 or not 1 <= height <= 16000:
                    raise SourceError('Rawkuma.me изменил размер слоя текста.')
                svg_nodes(svg)
            refs.append((src, RawkumaPage(width, height, svg, fonts) if svg else ('', '')))
        return remember(refs, target)


SOURCES = (RawkumaMe('5509878196968851775', 'en'), RawkumaMe('3962273475579482161', 'es'))
