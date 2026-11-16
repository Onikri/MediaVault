"""Comic Grast open episodes and the publisher's seeded tile layout."""

import json
import math
import re
import struct
from collections import defaultdict
from urllib.parse import urlsplit

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://novema.jp'
ROOT_PATH = r'/(?:grast/)?comic/serial/(n[1-9]\d{0,8})'
CHAPTER = ROOT_PATH + r'/n[1-9]\d{0,8}(?:/\d{1,4})?/?'


def f32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


class SeedRandom:
    """Compatible with the upstream seedrandom port at revision 6f345a8."""

    def __init__(self, seed):
        encoded = seed.encode('utf-16-le')
        units = [value[0] for value in struct.iter_unpack('<H', encoded)]
        key = [0] * min(max(1, len(units)), 256)
        smear = 0
        for i, value in enumerate(units):
            index = i & 255
            smear ^= key[index] * 19
            key[index] = (smear + value) & 255
        self.s = list(range(256))
        self.i = self.j = 0
        cursor = 0
        for index, val in enumerate(self.s):
            cursor = (cursor + key[index % len(key)] + val) & 255
            self.s[index], self.s[cursor] = self.s[cursor], val
        self.advance(256)

    def advance(self, count):
        value = 0
        for _ in range(count):
            self.i = (self.i + 1) & 255
            one = self.s[self.i]
            self.j = (self.j + one) & 255
            other = self.s[self.j]
            self.s[self.i], self.s[self.j] = other, one
            value = value * 256 + self.s[(one + other) & 255]
        return value

    def next(self):
        n = float(self.advance(6))
        denominator = float(256**6)
        extra = 0
        while n < 2**52:
            n = (n + extra) * 256
            denominator *= 256
            extra = self.advance(1)
        while n >= 2**53:
            n /= 2
            denominator /= 2
            extra >>= 1
        return (n + extra) / denominator

    def permutation(self, length):
        remaining = list(range(length))
        return [remaining.pop(int(self.next() * size)) for size in range(length, 0, -1)]


def regions(width, height, size, seed):
    tile = f32(max(width, height) / size)
    cols = math.ceil(f32(width / tile))
    rows = math.ceil(f32(height / tile))
    groups = defaultdict(list)
    if tile < 1 or cols * rows > 16384:
        raise SourceError('Comic Grast вернул недопустимую сетку страницы.')
    for row in range(rows):
        for col in range(cols):
            x, y = int(f32(col * tile)), int(f32(row * tile))
            w = int(tile) if f32(x + tile) <= width else width - x
            h = int(tile) if f32(y + tile) <= height else height - y
            if min(w, h) <= 0:
                raise SourceError('Comic Grast вернул пустую плитку.')
            groups[w, h].append((x, y))
    for (w, h), coordinates in groups.items():
        left, top = coordinates[0]
        group_cols = sum(y == top for _, y in coordinates)
        permutation = SeedRandom(seed).permutation(len(coordinates))
        for index, (x, y) in zip(permutation, coordinates):
            source_x = left + (index % group_cols) * w
            source_y = top + (index // group_cols) * h
            if source_x + w > width or source_y + h > height:
                raise SourceError('Comic Grast указал плитку за пределами страницы.')
            yield source_x, source_y, w, h, x, y


class GrastPage:
    def __init__(self, seed, size):
        self.seed, self.size = seed, size

    def decode(self, raw):
        from io import BytesIO

        from PIL import Image
        from PIL.Image import DecompressionBombError

        try:
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if width * height > 35_000_000:
                    raise SourceError('Страница Comic Grast слишком большая.')
                bitmap = image.convert('RGB')
                result = Image.new('RGB', bitmap.size)
                for sx, sy, w, h, x, y in regions(width, height, self.size, self.seed):
                    result.paste(bitmap.crop((sx, sy, sx + w, sy + h)), (x, y))
                output = BytesIO()
                result.save(output, 'JPEG', quality=90)
                return output.getvalue()
        except (OSError, ValueError, DecompressionBombError):
            raise SourceError('Comic Grast вернул повреждённое изображение.') from None


class ComicGrast(SeriesPort):
    cards = Cards('ul.comicList > li', 'a[href]', 'dl > dt > p.line-clamp.n2',
                  'img', next='.pageList li.next', image_attrs=('data-src',))
    meta = Meta('.comicTit', '.serialMainImage', '.comicStory .txtAcd_text_inner', '',
                '', '.topCategoryTag ul li a', '.credit li')

    def __init__(self):
        super().__init__(('218928749727744731', 'Comic Grast', 'ja', ROOT, False),
                         ROOT_PATH + '/?', CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/comic/serial/' + key if key else ''

    def chapter_identity(self, url):
        path = urlsplit(url).path.removeprefix('/grast').rstrip('/')
        return re.sub(r'/(\d{1,4})$', '', path)

    def saved_title_url(self, value):
        url = self.canonical(value)
        return self.title_for(url) if self.is_chapter(url) else url if self.is_title(url) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        url = ROOT + f'/grast/comic/serial/{page}'
        if query or tag:
            url = query_url(ROOT + f'/grast/comic/search/{page}', type=0, word=query or tag[:160])
        return self.card_rows(*self.document(http, url), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['tags'] = [tag.lstrip('#').strip() for tag in row['tags']]
        return row

    def chapters(self, http, doc, final):
        result = {}
        for anchor in doc.select('.comicSerialList article a[href]'):
            target = self.site_link(anchor['href'], final)
            if not self.is_chapter(target) or self.chapter_key(target) != self.title_key(final):
                continue
            label = node_text(anchor.select_one('.storyTitle'))
            date = release_date(node_text(anchor.select_one('.update')).removesuffix(' 更新'), '%Y/%m/%d')
            result[self.chapter_identity(target)] = self.chapter(target, label, date=date)
        return self.order(result), False

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        node = doc.select_one('#comic-data')
        if not node:
            raise SourceAccessError('Comic Grast не предоставил открытые страницы этой главы.')
        item = json.loads(node.string or '')
        book, chapter = item.get('serial_comic_id'), item.get('story_number')
        if not all(type(value) is int and 0 < value < 10**9 for value in (book, chapter)):
            raise SourceError('Comic Grast вернул некорректный выпуск.')
        base = ROOT + f'/img/serial-comic/{book}/{chapter}/content/'
        raw, location, _ = http.document(base + 'index.json', headers={'Referer': final})
        if location != base + 'index.json':
            raise SourceError('Comic Grast перенаправил запрос списка страниц.')
        refs = []
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise SourceError('Comic Grast изменил формат списка страниц.')
        for page in payload:
            name, seed, size = page.get('name'), page.get('seed'), page.get('size')
            if (not isinstance(name, str) or not re.fullmatch(SEGMENT, name)
                    or not isinstance(seed, str) or not 1 <= len(seed) <= 256
                    or type(size) is not int or not 1 <= size <= 128):
                raise SourceError('Comic Grast вернул некорректный параметр изображения.')
            target = image_url(query_url(base + name, seed=seed, size=size), final)
            if target:
                refs.append((target, GrastPage(seed, size)))
        return remember(refs, final)


SOURCES = (ComicGrast(),)
