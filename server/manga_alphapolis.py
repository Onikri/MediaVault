"""Alphapolis public manga catalogue, guest XSRF flow, and tile decoding."""

from base64 import b64decode
from dataclasses import dataclass
from io import BytesIO
import json
import re
from struct import iter_unpack, unpack_from
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from PIL import Image

from manga_clipstudio import json_data
from manga_direct_payloads import JsonSeries
from manga_madara import image_url, node_text, release_date
from manga_series_port import Cards, Meta
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://www.alphapolis.co.jp'
SCRIPT = ROOT + '/manga/official'
ID = r'[1-9]\d{0,9}'
TITLE = rf'/manga/official/({ID})/?'
CHAPTER = rf'/manga/official/({ID})/({ID})/?'
SESSION_TOKEN = re.compile(r'[A-Za-z0-9_+=./~%-]{12,500}')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')
CATEGORY = {'men': '男性向け', 'women': '女性向け', 'tl': 'TL', 'bl': 'BL'}


def public_transport(url, method, data, referer, action):
    parts = urlsplit(url)
    if parts.netloc != 'www.alphapolis.co.jp' or parts.query:
        return False
    if action == 'alphapolis-guest-title':
        return bool(method == 'GET' and data is None and re.fullmatch(TITLE, parts.path))
    if method != 'POST' or not isinstance(data, bytes) or len(data) > 350:
        return False
    ref = urlsplit(referer)
    if ref.netloc != parts.netloc:
        return False
    try:
        obj = json.loads(data)
    except ValueError:
        return False
    if not isinstance(obj, dict):
        return False
    if parts.path == '/manga/official/episodes.json':
        title = re.fullmatch(TITLE, ref.path)
        return bool(title and obj == {'manga_id': int(title[1])} and type(obj.get('manga_id')) is int)
    if parts.path != '/manga/official/viewer.json':
        return False
    chapter = re.fullmatch(CHAPTER, ref.path)
    return bool(chapter and obj == {'episode_no': int(chapter[2]), 'hide_page': False,
                'manga_sele_id': int(chapter[1]), 'preview': False, 'resolution': obj.get('resolution')}
                and obj.get('resolution') in ('full_hd', 'standard')
                and type(obj['preview']) is bool and type(obj['hide_page']) is bool
                and type(obj['episode_no']) is int and type(obj['manga_sele_id']) is int)


def cookie_token(session):
    for cookie in session.cookies:
        if cookie.name == 'XSRF-TOKEN' and cookie.domain.lstrip('.') in {'alphapolis.co.jp', 'www.alphapolis.co.jp'}:
            value = unquote(cookie.value)
            if SESSION_TOKEN.fullmatch(value):
                return value
    return ''


def tile_keys(value):
    try:
        b64 = value.partition('base64,')[2]
        raw = b64decode(b64, validate=True)
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid placeholder')
        pos, result = 33, []
        while pos + 2 <= len(raw):
            count = unpack_from('<H', raw, pos)[0]
            start = pos + 2
            end = start + count * 8
            if end > len(raw):
                break
            result.append(raw[start:end])
            pos = end
        return result
    except (ValueError, AttributeError):
        raise SourceError('Alphapolis изменил формат ключей страниц.') from None


@dataclass(frozen=True)
class AlphaPage:
    key: bytes

    def decode(self, raw):
        if len(self.key) < 8:
            return raw
        flags, geometry = unpack_from('<II', self.key)
        size, border = geometry >> 24, (flags >> 27) & 7
        if size == 0:
            return raw
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > 35_000_000:
                    raise ValueError('Image too large')
                original = image.convert('RGB')
            w, h = original.size
            cols, rows = (w + size - 1) // size, (h + size - 1) // size
            wall = border * 2
            step = size - wall
            width, height = w - cols * wall, h - rows * wall
            if min(width, height, step) < 1 or len(self.key) % 8:
                raise ValueError('Invalid tile metrics')
            output = Image.new('RGB', (width, height), 'white')
            rotates = (None, Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_270)
            for flags, geometry in iter_unpack('<II', self.key):
                flip, rotation = flags & 1, (flags >> 1) & 3
                top, left = (flags >> 3) & 4095, (flags >> 15) & 4095
                sx = min(((geometry >> 16) & 255) * size, w)
                sy = min(((geometry >> 8) & 255) * size, h)
                rect_w = (width - left if left // step == cols - 1 else step) + wall
                rect_h = (height - top if top // step == rows - 1 else step) + wall
                if rotation % 2:
                    rect_w, rect_h = rect_h, rect_w
                crop_w = min(rect_w, w - sx)
                crop_h = min(rect_h, h - sy)
                if min(crop_w, crop_h) < 1:
                    continue
                tile = original.crop((sx, sy, sx + crop_w, sy + crop_h))
                if flip:
                    tile = tile.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                if rotation:
                    tile = tile.transpose(rotates[rotation])
                x = left - border + (rect_w - tile.width) // 2
                y = top - border + (rect_h - tile.height) // 2
                output.paste(tile, (x, y))
            out = BytesIO()
            output.save(out, format='WEBP', lossless=True)
            return out.getvalue()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise SourceError('Alphapolis вернул повреждённую страницу.') from None


class Alphapolis(JsonSeries):
    sample = '.mangas-list .official-manga-panel > a, a.official-manga-sub-like_ranking--list, a.official-manga-sub-like_ranking--panel'
    cards = Cards(sample, '', '.title, .official-manga-sub-like_ranking--list_title, .official-manga-sub-like_ranking--panel_title',
                  '.panel, img, .official-manga-sub-like_ranking--panel_thumbnail', 'i.fa.fa-angle-double-right',
                  image_attrs=('data-src', 'data-bg'))
    meta = Meta('.manga-detail-description > .title > h1', '.manga-bigbanner img', '.manga-detail-outline .outline',
                tags='.manga-detail-tags .official-manga-tags .official-manga-tag',
                author='.manga-detail-description .author-label .authors .mangaka a')

    def __init__(self):
        super().__init__(('1943011614685426671', 'Alphapolis', 'ja', ROOT, True), TITLE, CHAPTER, interval=.5)

    def title_for(self, url):
        return SCRIPT + '/' + self.chapter_key(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = urlsplit(url).path.strip('/')
        return title.rstrip('/') + '/' + key if self.is_title(title) and re.fullmatch(ID, key) else url if self.is_chapter(url) else ''

    def public_doc(self, http, url, *, guest=False):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/', 'User-Agent': UA},
                                      action='alphapolis-guest-title' if guest else None)
        if not self.site_link(final):
            raise SourceError('Alphapolis перенаправил запрос на другой домен.')
        return BeautifulSoup(raw, 'html.parser'), final

    def ajax(self, http, action, referer, args):
        self.origin.wait(getattr(http, 'deadline', None))
        target = SCRIPT + '/' + action + '.json'
        raw, final, _ = http.document(target, headers={'Referer': referer, 'User-Agent': UA},
                                      method='POST', data=json.dumps(args).encode(), action='alphapolis-guest-form')
        if target != final:
            raise SourceError('Alphapolis перенаправил запрос оглавления.')
        return json_data(raw)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if not query and not tag and sort == 'popular':
            if page != 1:
                return [], False
            target = SCRIPT + '/ranking?category=total'
        else:
            args = {'page': page, 'query': query or []}
            if tag in CATEGORY:
                args['category[0]'] = tag
            target = query_url(SCRIPT + '/search', **args)
        return self.card_rows(*self.public_doc(http, target), self.cards)

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'category'} for key, label in CATEGORY.items()]

    def series(self, http, url):
        ident = self.title_key(url)
        doc, final = self.public_doc(http, SCRIPT + '/' + ident, guest=True)
        if self.title_key(final) != ident:
            raise SourceError('Alphapolis перенаправил на другой тайтл.')
        summary = self.metadata(doc, final, self.meta)
        status = node_text(doc.select_one('.wrap-content-status a[href*="complete"]'))
        summary['status'] = {'連載中': 'ongoing', '完結': 'completed', '休載中': 'hiatus'}.get(status, '')
        data = self.ajax(http, 'episodes', final, {'manga_id': int(ident)})
        results = {}
        for item in data.get('episodes') or []:
            if not isinstance(item, dict):
                continue
            link = self.site_link(item.get('url'), final)
            if not self.is_chapter(link) or self.chapter_key(link) != ident:
                continue
            rental = item.get('rental') or {}
            name = str(item.get('mainTitle') or '')
            if rental.get('isFree') is False and rental.get('isOnRental') is not True:
                name = '🔒 ' + name
            stamp = release_date(str(item.get('upTime') or ''), '%Y.%m.%d更新')
            results[link] = self.chapter(link, name, date=stamp)
        return summary, self.order(results)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        referer = SCRIPT + f'/{match[1]}/{match[2]}'
        for size in ('full_hd', 'standard'):
            data = self.ajax(http, 'viewer', referer, {'episode_no': int(match[2]), 'manga_sele_id': int(match[1]),
                             'hide_page': False, 'preview': False, 'resolution': size})
            if not isinstance(page := data.get('page'), dict):
                continue
            images = page.get('images')
            keys = tile_keys(page.get('placeholder'))
            if not isinstance(images, list) or len(images) > len(keys):
                raise SourceError('Alphapolis вернул неполные данные выпуска.')
            refs = [(image, AlphaPage(key)) for item, key in zip(images, keys) if isinstance(item, dict)
                    and (image := image_url(item.get('url'), referer))]
            if refs:
                return remember(refs, referer)
        raise SourceAccessError('Alphapolis требует покупку или аренду выпуска.')


SOURCES = (Alphapolis(),)
