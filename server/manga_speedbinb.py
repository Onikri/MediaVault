"""SpeedBinb public reader transport and image layout, ported from Keiyoushi (Apache-2.0)."""

from collections import OrderedDict
from io import BytesIO
import json
import re
import secrets
from threading import Lock
from time import monotonic, time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
import warnings

from bs4 import BeautifulSoup
from PIL import Image

from source_parser import SourceAccessError, SourceError, public_url


ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
GRID_A = 'aAbBcCdDeEfFgGhHiIjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ'
GRID_F = re.compile(r'=([1-9][0-9]?)-([1-9][0-9]?)([-+])([0-9]{1,2})-([-_0-9A-Za-z]{1,144})')
SEGMENT = re.compile(r'[^/\\\s?#]{1,255}')
CID = re.compile(r'[A-Za-z0-9_.~:-]{1,180}')
COORD = re.compile(r'i:(\d{1,5}),(\d{1,5})\+(\d{1,5}),(\d{1,5})>(\d{1,5}),(\d{1,5})')
MARKER = 'mv_speedbinb='
MAX_PAGES = 1500
READER_HOSTS = ('booklive.jp', 'cmoa.jp', 'kirapo.jp', 'futabanet.jp', 'ohtabooks.com',
                'yondemill.jp', 'yanmaga.jp', 'yomonga.com', 'mangaplaza.com',
                # Yondemill (Ohta Web Comic) opens chapters in Bricks' SpeedBinb since Nov 2026.
                'bricks.pub')
ALLOWED_INFO = re.compile(r'/[^?#]*bibGetCntntInfo(?:\.php)?')
U_KEYS = tuple(f'u{i}' for i in range(10))
GRANTS = OrderedDict()
GUARD = Lock()


def same_network(host, domains):
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def reader_url(value):
    result = public_url(value, resolve_dns=False)
    if not same_network(urlsplit(result).hostname or '', READER_HOSTS):
        raise SourceError('Неизвестный домен читалки SpeedBinb.')
    return result


def query_url(url, values):
    return urlunsplit(urlsplit(url)._replace(query=urlencode(values), fragment=''))


def shared_key(cid):
    repeated = cid * ((len(cid) + 15) // len(cid))
    first, last = repeated[:16], repeated[-16:]
    s = h = u = 0
    result = []
    for head, tail in zip(first, last):
        char = secrets.choice(ALPHABET)
        s ^= ord(char)
        h ^= ord(head)
        u ^= ord(tail)
        result.extend((char, ALPHABET[(s + h + u) & 63]))
    return ''.join(result)


def decode_table(cid, key, text):
    if not isinstance(text, str) or len(text) > 18000:
        raise ValueError('Invalid table size')
    seed = sum(ord(char) << (i % 16) for i, char in enumerate(f'{cid}:{key}')) & 0x7fffffff
    seed = seed or 0x12345678
    decoded = []
    for char in text:
        seed = (seed >> 1) ^ (1210056708 & -(seed & 1))
        decoded.append(chr((ord(char) - 32 + seed % 94) % 94 + 32))
    table = json.loads(''.join(decoded))
    if not isinstance(table, list) or len(table) < 8 or not all(
            isinstance(value, str) and len(value) <= 200 for value in table[:8]):
        raise ValueError('Invalid key table')
    return table


def _segments(path):
    values = path.split('/')
    if not 1 <= len(values) <= 8 or not all(
            SEGMENT.fullmatch(unquote(value)) and unquote(value) not in ('.', '..') for value in values):
        raise ValueError('Invalid image path')
    return values


def api_route(url, referer, action):
    """Allow the three read-only upstream endpoints used by the official reader."""
    parts, origin = urlsplit(url), urlsplit(referer or '')
    if origin.scheme != 'https' or not same_network(origin.hostname or '', READER_HOSTS):
        return False
    fields = parse_qsl(parts.query, keep_blank_values=True)
    params = dict(fields)
    if len(fields) != len(params) or not all(len(value) <= 1200 for value in params.values()):
        return False
    if action == 'speedbinb-info':
        return (same_network(parts.hostname or '', READER_HOSTS)
                and bool(ALLOWED_INFO.fullmatch(parts.path))
                and set(params) <= {'cid', 'k', 'dmytime', *U_KEYS}
                and bool(CID.fullmatch(params.get('cid', '')))
                and bool(re.fullmatch(r'[A-Za-z0-9_-]{32}', params.get('k', '')))
                and bool(re.fullmatch(r'[0-9]{13}', params.get('dmytime', ''))))
    name = parts.path.rsplit('/', 1)[-1]
    if name in {'content.js', 'content'}:
        return not fields
    return (name == 'sbcGetCntnt.php' and set(params) <= {'cid', 'p', 'q', 'vm', 'dmytime', *U_KEYS}
            and bool(CID.fullmatch(params.get('cid', ''))) and params.get('q') == '1'
            and params.get('vm') in ('1', '2', '3') and bool(params.get('dmytime')))


def _load(http, url, referer, action, callback=False):
    raw, final, _ = http.document(url, headers={'Referer': referer}, action=action)
    if final != url:
        raise SourceError('Сервер SpeedBinb изменил маршрут читалки.')
    if callback:
        wrapped = re.fullmatch(r'\s*DataGet_Content\((.*)\)\s*;?\s*', raw, re.S)
        if not wrapped:
            raise ValueError('Invalid content callback')
        raw = wrapped[1]
    return json.loads(raw)


def remember(refs, referer):
    if not 1 <= len(refs) <= MAX_PAGES:
        raise SourceError('SpeedBinb не предоставил список страниц главы.')
    token = secrets.token_urlsafe(15)
    refs = [(public_url(url, resolve_dns=False), data) for url, data in refs]
    with GUARD:
        GRANTS[token] = (monotonic() + 1800, referer, dict(refs))
        while len(GRANTS) > 256:
            GRANTS.popitem(last=False)
    return [url + '#' + MARKER + token for url, _ in refs]


def grant(value):
    parsed = urlsplit(value)
    token = parsed.fragment.removeprefix(MARKER)
    target = urlunsplit(parsed._replace(fragment=''))
    entry = None
    if parsed.fragment.startswith(MARKER) and re.fullmatch(r'[A-Za-z0-9_-]{20}', token):
        with GUARD:
            entry = GRANTS.get(token)
    if not entry or monotonic() >= entry[0] or target not in entry[2]:
        raise SourceAccessError('Список страниц SpeedBinb устарел. Открой главу повторно.')
    return target, entry[1], entry[2][target]


def reader_pages(http, doc, final):
    final = reader_url(final)
    content = doc.select_one('#content')
    if not content:
        raise SourceAccessError('Источник не предоставил открытую версию главы.')
    if not content.get('data-ptbinb'):
        refs = []
        for node in content.select('[data-ptimg]'):
            url = urljoin(final, node['data-ptimg'])
            if not urlsplit(url).path.endswith('.ptimg.json'):
                raise SourceError('Неизвестный формат списка плиток SpeedBinb.')
            refs.append((url, 'ptimg'))
        return remember(refs, final)
    reader_args = dict(parse_qsl(urlsplit(final).query))
    info = urljoin(final, content['data-ptbinb'])
    args = {key: value for key, value in reader_args.items() if key in U_KEYS}
    args.update((key, value) for key, value in parse_qsl(urlsplit(info).query) if key in U_KEYS)
    cid = content.get('data-ptbinb-cid') or reader_args.get('cid', '')
    return chapter_pages(http, info, cid, final, args)


def chapter_pages(http, endpoint, cid, referer, reader_args=None):
    referer = reader_url(referer)
    if not CID.fullmatch(cid):
        raise SourceError('Некорректный идентификатор главы SpeedBinb.')
    timer = str(int(time() * 1000))
    u_args = reader_args or {}
    key = shared_key(cid)
    info_url = query_url(endpoint, {**u_args, 'cid': cid, 'k': key, 'dmytime': timer})
    try:
        meta = _load(http, info_url, referer, 'speedbinb-info')
        if meta.get('result') != 1:
            raise SourceAccessError('Источник не предоставил открытую версию главы.')
        item = meta['items'][0]
        ctbl, ptbl = (decode_table(cid, key, item[field]) for field in ('ctbl', 'ptbl'))
        base = public_url(item['ContentsServer'], resolve_dns=False, allow_api=True)
        base_parts = urlsplit(base)
        if base_parts.query or base_parts.fragment:
            raise ValueError('Invalid content base')
        base = base.rstrip('/') + '/'
        server = int(item['ServerType'])
        args = {'cid': cid, 'q': '1', 'vm': str(item['ViewMode']),
                'dmytime': item.get('ContentDate') or timer, **u_args}
        if item.get('p'):
            args['p'] = item['p']
        content_url = {0: 'sbcGetCntnt.php', 1: 'content.js', 2: 'content'}[server]
        content_url = query_url(base + content_url, args if server == 0 else {})
        data = _load(http, content_url, referer, 'speedbinb-body', callback=server == 1)
        if data.get('result') != 1:
            raise SourceAccessError('Сервер SpeedBinb не открыл страницы главы.')
        first_case = re.search(r'<t-case\b[^>]*>(.*?)</t-case>', data['ttx'], re.I | re.S)
        if not first_case:
            raise ValueError('Missing page list')
        single = data.get('ImageClass') == 'singlequality'
        pages = []
        for node in BeautifulSoup(first_case[1], 'html.parser').select('t-img[src]', limit=MAX_PAGES + 1):
            src = node['src']
            basename = _segments(src)[-1]
            keys = ptbl[sum(map(ord, basename[::2])) % 8], ctbl[sum(map(ord, basename[1::2])) % 8]
            dated = {'dmytime': item['ContentDate']} if item.get('ContentDate') else {}
            if server == 0:
                quality = '1' if single or args['vm'] in ('2', '3') else '0'
                url = query_url(base + 'sbcGetImg.php', {**args, 'q': quality, 'src': src})
            elif server == 1:
                url = query_url(base + src + ('/M.jpg' if single else '/M_H.jpg'), dated)
            else:
                url = query_url(base + 'img/' + src, {**dated, **u_args})
            pages.append((url, keys))
        return remember(pages, referer)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, RecursionError):
        raise SourceError('Источник изменил данные открытой главы SpeedBinb.') from None


def grid_f(source, destination, width, height):
    src, dst = GRID_F.fullmatch(source), GRID_F.fullmatch(destination)
    if not src or not dst or src.group(1, 2, 4) != dst.group(1, 2, 4) or (src[3], dst[3]) != ('-', '+'):
        raise ValueError('Invalid F keys')
    cols, rows, pad = map(int, src.group(1, 2, 4))
    cells = cols * rows
    if not 8 <= cols <= 64 or not 8 <= rows <= 64 or cells != 64:
        raise ValueError('Invalid F grid')
    sx, sy, source_order = _grid_f_key(src[5], cols, rows)
    dx, dy, destination_order = _grid_f_key(dst[5], cols, rows)
    target_w, target_h = width - 2 * cols * pad, height - 2 * rows * pad
    if min(target_w, target_h) < 64 or width * height < (320 + 2 * cols * pad) * (320 + 2 * rows * pad):
        return width, height, []
    step_w, step_h = (target_w + cols - 1) // cols, (target_h + rows - 1) // rows
    edge_w, edge_h = target_w - (cols - 1) * step_w, target_h - (rows - 1) * step_h
    pieces = []
    for index, slot in enumerate(source_order):
        sc, sr = index % cols, index // cols
        dest = destination_order[slot]
        dc, dr = dest % cols, dest // cols
        pieces.append((pad + sc * (step_w + 2 * pad) + (edge_w - step_w if sx[sr] < sc else 0),
                       pad + sr * (step_h + 2 * pad) + (edge_h - step_h if sy[sc] < sr else 0),
                       edge_w if sx[sr] == sc else step_w, edge_h if sy[sc] == sr else step_h,
                       dc * step_w + (edge_w - step_w if dx[dr] < dc else 0),
                       dr * step_h + (edge_h - step_h if dy[dc] < dr else 0)))
    return target_w, target_h, pieces


def _grid_f_key(value, cols, rows):
    data = [ALPHABET.index(char) for char in value]
    y, x, order = data[:cols], data[cols:cols + rows], data[cols + rows:]
    if len(data) != cols + rows + cols * rows or max(y) >= rows or max(x) >= cols or set(order) != set(range(cols * rows)):
        raise ValueError('Invalid F pieces')
    return x, y, order


def _grid_a_key(value):
    match = re.fullmatch(r'([1-8])-([1-8])-([A-Za-z]{2,128})', value)
    if not match:
        raise ValueError('Invalid A key')
    cols, rows = map(int, match.group(1, 2))
    if len(match[3]) != 2 * cols * rows:
        raise ValueError('Invalid A pieces')
    positions = [GRID_A.index(char) for char in match[3]]
    return cols, rows, list(zip(positions[::2], positions[1::2]))


def grid_a(source, destination, width, height):
    cols, rows, src = _grid_a_key(destination)
    dest_cols, dest_rows, dst = _grid_a_key(source)
    if (cols, rows) != (dest_cols, dest_rows):
        raise ValueError('Invalid A grid')
    if min(width, height) < 64 or width * height < 102400:
        return width, height, []
    aligned_w, aligned_h = width // 8 * 8, height // 8 * 8
    step_w, step_h = (aligned_w - 1) // 56 * 8, (aligned_h - 1) // 56 * 8
    edge_w, edge_h = aligned_w - 7 * step_w, aligned_h - 7 * step_h
    pieces = []
    sizes = ([(step_w, step_h)] * ((cols - 1) * (rows - 1)) + [(step_w, edge_h)] * (cols - 1)
             + [(edge_w, step_h)] * (rows - 1) + [(edge_w, edge_h)])
    for (sx, sy), (dx, dy), (w, h) in zip(src, dst, sizes):
        pieces.append((sx // 2 * step_w + sx % 2 * edge_w, sy // 2 * step_h + sy % 2 * edge_h, w, h,
                       dx // 2 * step_w + dx % 2 * edge_w, dy // 2 * step_h + dy % 2 * edge_h))
    right, bottom = step_w * (cols - 1) + edge_w, step_h * (rows - 1) + edge_h
    if right < width:
        pieces.append((right, 0, width - right, bottom, right, 0))
    if bottom < height:
        pieces.append((0, bottom, width, height - bottom, 0, bottom))
    return width, height, pieces


def ptimg(http, url, referer):
    try:
        raw, final, _ = http.document(url, headers={'Referer': referer}, action='speedbinb-image')
        if final != url:
            raise ValueError('Manifest redirected')
        data = json.loads(raw)
        view = data['views'][0]
        name = data['resources']['i']['src']
        if len(_segments(name)) != 1:
            raise ValueError('Expected sibling image')
        parsed = urlsplit(url)
        image = urlunsplit(parsed._replace(path=parsed.path.rsplit('/', 1)[0] + '/' + quote(unquote(name), safe='')))
        coords = view['coords']
        if not isinstance(coords, list) or len(coords) > 4096:
            raise ValueError('Invalid tile count')
        tiles = [tuple(map(int, match.groups())) for coord in coords if (match := COORD.fullmatch(coord))]
        if len(tiles) != len(coords):
            raise ValueError('Invalid tile')
        return image, (int(view['width']), int(view['height']), tiles)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, RecursionError):
        raise SourceError('Источник вернул некорректную карту плиток SpeedBinb.') from None


def compose(raw, layout):
    if layout == ('', ''):
        return raw
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                sw, sh = image.size
                if sw * sh > 24_000_000:
                    raise ValueError('Image size')
                if len(layout) == 3:
                    width, height, tiles = layout
                elif all(value.startswith('=') for value in layout):
                    width, height, tiles = grid_f(*layout, sw, sh)
                else:
                    width, height, tiles = grid_a(*layout, sw, sh)
                if not tiles:
                    return raw
                if min(width, height) < 1 or width * height > 24_000_000:
                    raise ValueError('Canvas size')
                with image.convert('RGB') as source, Image.new('RGB', (width, height)) as output:
                    for sx, sy, w, h, dx, dy in tiles:
                        if min(sx, sy, dx, dy) < 0 or min(w, h) <= 0 or (
                                sx + w > sw or sy + h > sh or dx + w > width or dy + h > height):
                            raise ValueError('Tile bounds')
                        with source.crop((sx, sy, sx + w, sy + h)) as piece:
                            output.paste(piece, (dx, dy))
                    buffer = BytesIO()
                    output.save(buffer, 'JPEG', quality=90)
                    return buffer.getvalue()
    except (OSError, TypeError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise SourceError('SpeedBinb вернул повреждённую страницу или карту плиток.') from None
