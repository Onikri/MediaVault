"""EbookRenta catalogue and open image reader."""

import json
import re
from dataclasses import dataclass
from html import unescape
from io import BytesIO
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from PIL import Image

from manga_direct_payloads import JsonSeries
from manga_madara import node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError, public_url

ROOT = 'https://www.ebookrenta.com'
ID = r'[1-9]\d{0,12}'
TITLE = rf'/renta/sc/frm/item/({ID})/?'
VIEWER = '/renta/sc/jump/viewer'
CHAPTER = r'(/renta/sc/jump/viewer)/?'
FACETS = ('genm', 'gend', 'keyword', 'deals', 'keyword_sales')
FREE = ('prd_rental_free', 'prd_rental_free_buy', 'prd_rental_all_free', 'prd_rental_all_free_buy')
SHUFFLE = ((1, 0, 3, 2, 5, 4, 6), (0, 4, 1, 5, 2, 6, 3))
VAR = re.compile(r'\b(url_base2|max_page|auth_key|prd_ser)\s*=\s*(?:parseInt\(\s*)?"([^"]*)"')


def public_api(host, path, query):
    pairs = parse_qsl(query)
    args = dict(pairs)
    return (host == 'www.ebookrenta.com' and path == '/renta/sc/get_search_data_en.php'
            and len(pairs) == len(args) and set(args) == {'target_column', 'mode'}
            and args['target_column'] in FACETS and args['mode'] == 'facet')


def layout(page, product):
    seed = page + product
    if seed % 20 == 0:
        seed = abs(page - product) + 21
    positions = [0] * 49
    for col in range(7):
        column = [(row - col) % 7 * 7 + (2 * col - row) % 7 for row in range(7)]
        count = ((col + 1) * seed + page // 20) % 20
        for round_no in range(count - 1, -1, -1):
            column = [column[index] for index in SHUFFLE[round_no % 2]]
        for row, tile in enumerate(column):
            positions[tile] = row * 7 + col
    return positions


@dataclass(frozen=True)
class RentaPage:
    page: int
    product: int

    def decode(self, raw):
        try:
            if not re.fullmatch(rb'\d{9}', raw[:9]):
                raise ValueError('Invalid header')
            header_end = 9 + int(raw[:9])
            if not 9 < header_end <= min(len(raw), 128000):
                raise ValueError('Invalid header size')
            header = raw[9:header_end].decode('ascii').split('|')
            w, h = map(int, header[:2])
            if len(header) < 53 or min(w, h) < 7 or w * h > 35_000_000:
                raise ValueError('Invalid dimensions')
            canvas = Image.new('RGB', (w, h), 'white')
            tile_w, offset_x = divmod(w, 7)
            tile_h, offset_y = divmod(h, 7)
            dests = [(0, 0)] * 2 + [(cell % 7 * tile_w + offset_x, cell // 7 * tile_h + offset_y)
                                   for cell in layout(self.page, self.product)]
            pos = header_end
            for token, (x, y) in zip(header[2:53], dests):
                size = int(token.partition(',')[2] or '0')
                if size < 0 or pos + size > len(raw):
                    raise ValueError('Incomplete tile')
                if size:
                    with Image.open(BytesIO(raw[pos:pos + size])) as tile:
                        if tile.width * tile.height > w * h:
                            raise ValueError('Oversized tile')
                        if 'A' in tile.getbands():
                            layer = tile.convert('RGBA')
                            canvas.paste(layer, (x, y), layer)
                        else:
                            canvas.paste(tile, (x, y))
                    pos += size
            out = BytesIO()
            canvas.save(out, format='JPEG', quality=90)
            return out.getvalue()
        except (OSError, ValueError, Image.DecompressionBombError):
            raise SourceError('EbookRenta вернул неполное изображение.') from None


class EbookRenta(JsonSeries):
    cards = Cards('.search-typeDesc-listItem', 'a.search-typeDesc-titleLink', next='')
    meta = Meta('h1.fvSeries-desc-title', 'img.fvSeries-cover-image', '[data-text-type="textViewMore_toggle"]',
                genres='.item-tags_wrap a:not([href*="price"])', author='#js-productDetailsSection [data-schema-attribute="author"] a')

    def __init__(self):
        super().__init__(('8412178155364465470', 'EbookRenta', 'en', ROOT, True), TITLE, CHAPTER,
                         hosts=('ebookrenta.com',), interval=.35)

    def is_chapter(self, url):
        return bool(super().is_chapter(url) and re.fullmatch(r'9-' + ID, param(url, 'prd_tid'))
                    and param(url, 'type') in {'free', 'smpl', 'read'})

    def title_for(self, url):
        identity = param(url, 'mv_renta_title')
        return ROOT + '/renta/sc/frm/item/' + identity if self.is_chapter(url) and re.fullmatch(ID, identity) else ''

    def chapter_key(self, url):
        return param(url, 'prd_tid').removeprefix('9-') if self.is_chapter(url) else ''

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def target(self, cid, mode, key):
        return query_url(ROOT + VIEWER, type=mode, prd_tid='9-' + cid, style='ch', mv_renta_title=key)

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/renta/sc/frm/item/' + key if re.fullmatch(ID, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        cid = self.chapter_key(url) or urlsplit(url).path.strip('/')
        key = self.title_key(title)
        return self.target(cid, param(url, 'type') or 'read', key) if key and re.fullmatch(ID, cid) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'word': query, 'sort': 'new' if sort == 'updated' else 'rank_w', 'type': 'desc', 'page': page}
        facet, separator, key = tag.partition(':')
        if separator and facet in FACETS and 1 <= len(key) <= 160:
            args[facet] = key
        doc, final = self.document(http, query_url(ROOT + '/renta/sc/frm/search', **args))
        rows, _ = self.card_rows(doc, final, self.cards)
        paging = doc.select_one('#ja-search-Pn-wrap')
        return rows, bool(rows and paging and paging.get('data-now') != paging.get('data-max'))

    def vocabulary(self, http):
        data = []
        for name in FACETS:
            dest = query_url(ROOT + '/renta/sc/get_search_data_en.php', target_column=name, mode='facet')
            for item in self.json(http, dest).get('response') or []:
                if isinstance(item, dict) and item.get('value') and isinstance(key := item.get('value_enc'), str):
                    data.append({'key': name + ':' + unquote(key), 'kind': 'genre' if name in ('genm', 'gend') else 'tag',
                                 'label': str(item['value']).replace('_', ' ')})
        return data

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        summary = self.metadata(doc, final, self.meta)
        summary['status'] = 'completed' if doc.select_one('.item-tags_wrap a[href$="keyword=Completed"]') else 'ongoing'
        for item in doc.select('script:not([src])'):
            raw = item.string or ''
            if 'ItemStore.set' in raw and (found := re.search(r'JSON\.parse\(`((?:[^\\`]|\\.)*)`\)', raw, re.S)):
                try:
                    products = json.loads(re.sub(r'\\(.)', r'\1', found[1]))
                except ValueError:
                    raise SourceError('EbookRenta изменил формат оглавления.') from None
                break
        else:
            raise SourceError('EbookRenta не предоставил оглавление.')
        if not isinstance(products, dict):
            raise SourceError('EbookRenta изменил формат оглавления.')
        chapters = {}
        for product in reversed(list(products.values())):
            if not isinstance(product, dict) or product.get('prd_rental_future') == 1:
                continue
            cid = str(product.get('prd_ser') or '')
            if not re.fullmatch(ID, cid):
                continue
            mode = 'free' if any(product.get(field) == 1 for field in FREE) else 'smpl' if product.get('block_sample') == 1 else 'read'
            name = unescape(str(product.get('prd_name') or ''))
            name = ('🔒 ' + name if mode == 'read' else name + ' · Фрагмент' if mode == 'smpl' else name)
            stamp = str(product.get('date_s') or '').partition('T')[0]
            target = self.target(cid, mode, self.title_key(url))
            chapters[target] = self.chapter(target, name, date=release_date(stamp, '%Y-%m-%d'))
        return summary, self.order(chapters)

    def pages(self, http, url):
        mode, key = param(url, 'type'), self.chapter_key(url)
        if mode == 'read':
            raise SourceAccessError('EbookRenta требует покупку или аренду тома.')
        target = query_url(ROOT + VIEWER, type=mode, prd_tid='9-' + key, style='ch')
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        referer = self.title_for(url) or ROOT + '/'
        raw, final, _ = http.document(target, headers={'Referer': referer})
        doc = BeautifulSoup(raw, 'html.parser')
        redirect = doc.select_one('meta[http-equiv="refresh"][content]')
        if redirect and (match := re.search(r'\burl\s*=\s*(.*)', redirect['content'], re.I)):
            link = public_url(urljoin(final, match[1].strip(' \'"')), resolve_dns=False)
            raw, final, _ = http.document(link, headers={'Referer': referer})
        if '/view_strm/' in urlsplit(final).path:
            raise SourceAccessError('Этот выпуск EbookRenta предоставляется как видео.')
        values = dict(VAR.findall(raw))
        count = values.get('max_page', '')
        if (not re.fullmatch(r'[1-9]\d{0,3}', count) or int(count) > 1500 or values.get('prd_ser') != key
                or not values.get('url_base2') or len(values.get('auth_key', '')) > 4096):
            raise SourceAccessError('EbookRenta не передал открытые страницы тома.')
        base = urlsplit(public_url(values['url_base2'], resolve_dns=False))
        refs = [(urlunsplit(base._replace(path=base.path.rstrip('/') + '/' + str(index), query=values.get('auth_key', ''))),
                 RentaPage(index, int(key))) for index in range(1, int(count) + 1)]
        return remember(refs, referer)


SOURCES = (EbookRenta(),)
