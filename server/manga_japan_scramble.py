"""Page image descramblers of four Japanese readers (Keiyoushi, Apache-2.0, 6f345a8).

Each function is a direct port of the extension's image interceptor:
``ja/fodfuji``, ``ja/linemanga`` (portal pages), ``ja/sokuyomi`` and
``ja/soraraw`` (``CanvaDescrambler`` and ``Canva2Descrambler``). They take the
encoded image and return the readable page as JPEG bytes.
"""

import hashlib
import hmac
from io import BytesIO
import math
import re

from PIL import Image

from source_parser import SourceError

MASK32 = 0xFFFFFFFF


def _open(data):
    try:
        with Image.open(BytesIO(data)) as image:
            return image.convert('RGB')
    except (OSError, ValueError, Image.DecompressionBombError):
        raise SourceError('Источник вернул повреждённое изображение.') from None


def _jpeg(image):
    output = BytesIO()
    image.save(output, 'JPEG', quality=90)
    return output.getvalue()


def _array(image):
    import numpy

    return numpy.asarray(image, dtype=numpy.uint8)


def _image(array):
    return Image.fromarray(array, 'RGB')


# ------------------------------------------------------------------ FOD


class _FodRandom:
    def __init__(self, key):
        total, chars, index = 0, [ord(c) for c in key], 0
        while index < len(chars):
            high = chars[index]
            index += 1
            low = chars[index] if index < len(chars) else 0
            index += 1
            total = (total + ((high << 8) | low)) & MASK32
        self.next = total - (1 << 32) if total & 0x80000000 else total

    def rand(self, maximum):
        self.next = (self.next * 1103515245 + 12345) % 32768
        return self.next // (32767 // (maximum + 1) + 1)


def fod(data, key):
    """96×128 blocks shuffled by the viewer's LCG keyed with the page key."""
    if not re.fullmatch(r'[0-9A-Za-z]{1,64}', key or ''):
        raise SourceError('FOD не предоставил ключ страницы.')
    source = _open(data)
    width, height = source.size
    cols, rows = width // 96, height // 128
    order = list(range(cols * rows))
    rng = _FodRandom(key)
    for index in range(len(order)):
        pick = rng.rand(len(order) - 1)
        order[pick], order[index] = order[index], order[pick]
    result = Image.new('RGB', (width, height), 'white')
    for slot, target in enumerate(order):
        sx, sy = slot % cols * 96, slot // cols * 128
        dx, dy = target % cols * 96, target // cols * 128
        result.paste(source.crop((sx, sy, sx + 96, sy + 128)), (dx, dy))
    if width % 96:
        result.paste(source.crop((cols * 96, 0, width, height)), (cols * 96, 0))
    if height % 128:
        result.paste(source.crop((0, rows * 128, cols * 96, height)), (0, rows * 128))
    return _jpeg(result)


# ------------------------------------------------------------------ LINE Manga


def line(data, columns, block, blocks):
    """Portal pages: block i in reading order comes from base-35 index blocks[i]."""
    if not (1 <= columns <= 64 and 8 <= block <= 2048 and 1 <= len(blocks) <= 4096 and len(blocks) % columns == 0):
        raise SourceError('LINE Manga изменила схему страницы.')
    try:
        sources = [int(value, 35) for value in blocks]
    except ValueError:
        raise SourceError('LINE Manga изменила схему страницы.') from None
    if sorted(sources) != list(range(len(sources))):
        raise SourceError('LINE Manga изменила схему страницы.')
    source = _open(data)
    width, height = source.size
    grid_w, grid_h = columns * block, len(blocks) // columns * block
    result = Image.new('RGB', (width, height), 'white')
    if grid_w < width:
        result.paste(source.crop((grid_w, 0, width, height)), (grid_w, 0))
    if grid_h < height:
        result.paste(source.crop((0, grid_h, grid_w, height)), (0, grid_h))
    for index, origin in enumerate(sources):
        sx, sy = origin % columns * block, origin // columns * block
        dx, dy = index % columns * block, index // columns * block
        result.paste(source.crop((sx, sy, sx + block, sy + block)), (dx, dy))
    return _jpeg(result)


# ------------------------------------------------------------------ Sokuyomi


def sokuyomi(data):
    """A 4×4 grid transposed: tile (row, col) is drawn at (col, row)."""
    source = _open(data)
    width, height = source.size
    tile_w, tile_h = width // 4, height // 4
    result = source.copy()
    for row in range(4):
        for col in range(4):
            tile = source.crop((col * tile_w, row * tile_h, (col + 1) * tile_w, (row + 1) * tile_h))
            result.paste(tile, (row * tile_w, col * tile_h))
    return _jpeg(result)


# ------------------------------------------------------------------ SoraRaw "canva"

TARGET, SEG_MAX, SEG_MIN = 222, 259, 185


def _seed(value):
    from manga_comic_grast import SeedRandom

    return SeedRandom(value)


def _shuffle(values, rng):
    for index in range(len(values) - 1, 0, -1):
        pick = math.floor(rng.next() * (index + 1))
        values[index], values[pick] = values[pick], values[index]


def _split(total, rng):
    count = max(1, math.floor(total / TARGET + .5))
    while total // count > SEG_MAX:
        count += 1
    while total // count < SEG_MIN and count > 1:
        count -= 1
    base, rest = divmod(total, count)
    sizes = [base + 1 if index < rest else base for index in range(count)]
    _shuffle(sizes, rng)
    return sizes


def _transform(rng, swap, square):
    if swap:
        rotation = 1 if rng.next() < .5 else 3
    elif square:
        rotation = math.floor(rng.next() * 4)
    else:
        rotation = 0 if rng.next() < .5 else 2
    return rotation, rng.next() < .5, rng.next() < .5


def _draw_canva(pixels, src, out, dst, transform):
    import numpy

    rotation, flip_h, flip_v = transform
    r00, r01, r10, r11 = {1: (0, 1, -1, 0), 2: (-1, 0, 0, -1), 3: (0, -1, 1, 0)}.get(rotation, (1, 0, 0, 1))
    odd = rotation % 2 == 1
    out_w, out_h = (src[3], src[2]) if odd else (src[2], src[3])
    sx, sy = (-1 if flip_h else 1), (-1 if flip_v else 1)
    a00, a01, a10, a11 = r00 * sx, r01 * sy, r10 * sx, r11 * sy
    t2x, t2y = (out_w if flip_h else 0), (out_h if flip_v else 0)
    t1x, t1y = {1: (0, out_w), 2: (out_w, out_h), 3: (out_h, 0)}.get(rotation, (0, 0))
    bx = r00 * t2x + r01 * t2y + t1x + (-1 if a00 + a01 < 0 else 0)
    by = r10 * t2x + r11 * t2y + t1y + (-1 if a10 + a11 < 0 else 0)
    ys, xs = numpy.mgrid[0:src[3], 0:src[2]]
    ox, oy = a00 * xs + a01 * ys + bx, a10 * xs + a11 * ys + by
    keep = (ox >= 0) & (ox < out_w) & (oy >= 0) & (oy < out_h)
    out[dst[1] + oy[keep], dst[0] + ox[keep]] = pixels[src[1] + ys[keep], src[0] + xs[keep]]


def canva(data, chapter, token):
    import numpy

    if not re.fullmatch(r'[0-9]{1,15}', chapter or '') or not re.fullmatch(r'[0-9A-Za-z-]{1,80}', token or ''):
        raise SourceError('SoraRaw не предоставил ключ страницы.')
    pixels = _array(_open(data))
    height, width = pixels.shape[:2]
    key = hmac.new(token.encode(), chapter.encode(), hashlib.sha256).hexdigest()
    split = _seed(key)
    cols, rows = _split(width, split), _split(height, split)
    tiles, y = [], 0
    for tile_h in rows:
        x = 0
        for tile_w in cols:
            tiles.append((x, y, tile_w, tile_h))
            x += tile_w
        y += tile_h
    classes = {}
    for index, tile in enumerate(tiles):
        classes.setdefault(f'{tile[2]}x{tile[3]}', []).append(index)
    moves, done = {}, set()

    def rest(values, perm_seed, tf_seed, square):
        if values:
            order = list(values)
            _shuffle(order, _seed(perm_seed))
            for index, slot in enumerate(values):
                moves[slot] = (order[index], _transform(_seed(f'{tf_seed}|{index}'), False, square))

    for name, members in classes.items():
        if name in done:
            continue
        done.add(name)
        aw, ah = map(int, name.split('x'))
        square = aw == ah
        partner_name = f'{ah}x{aw}'
        partner = classes.get(partner_name) if partner_name != name else None
        if partner is None:
            order = list(members)
            _shuffle(order, _seed(f'{key}|perm|{name}'))
            for index, slot in enumerate(members):
                moves[slot] = (order[index], _transform(_seed(f'{key}|tf|self|{name}|{index}'), False, square))
            continue
        done.add(partner_name)
        pair = _seed(f'{key}|pair|{name}|{partner_name}')
        first, second = list(members), list(partner)
        _shuffle(first, pair)
        _shuffle(second, pair)
        common = min(len(first), len(second))
        for index in range(common):
            moves[first[index]] = (second[index], _transform(_seed(f'{key}|tf|AtoB|{name}|{index}'), True, False))
        for index in range(common):
            moves[second[index]] = (first[index], _transform(_seed(f'{key}|tf|BtoA|{partner_name}|{index}'), True, False))
        rest(first[common:], f'{key}|perm|A|{name}', f'{key}|tf|A|{name}|rest', square)
        rest(second[common:], f'{key}|perm|B|{partner_name}', f'{key}|tf|B|{partner_name}|rest', square)
    out = numpy.full_like(pixels, 255)
    for slot, (origin, transform) in moves.items():
        _draw_canva(pixels, tiles[origin], out, tiles[slot], transform)
    return _jpeg(_image(out))


# ------------------------------------------------------------------ SoraRaw "canva2"

SALT = '6a0248ad1ca4208275aed64d336e81595ecb149422a8e621f70e23b9f01b9c1c'
GRID = 8


class _Mulberry32:
    def __init__(self, state):
        self.state = state & MASK32

    def next(self):
        self.state = (self.state + 0x6D2B79F5) & MASK32
        state = self.state
        t = ((state ^ (state >> 15)) * (state | 1)) & MASK32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK32)) & MASK32) ^ t
        return ((t ^ (t >> 14)) & MASK32) / 4294967296.0

    def below(self, bound):
        return int(self.next() * bound)


def canva2(data, chapter):
    import numpy

    if not re.fullmatch(r'[0-9]{1,15}', chapter or ''):
        raise SourceError('SoraRaw не предоставил ключ страницы.')
    pixels = _array(_open(data))
    height, width = pixels.shape[:2]
    first = hashlib.sha256((chapter + SALT).encode()).hexdigest()
    second = hashlib.sha256(f'{first}:nxn:{GRID}:{width}x{height}'.encode()).digest()
    rng = _Mulberry32(int.from_bytes(second[:4], 'big'))
    tile_w, tile_h = width // GRID, height // GRID
    extra_w, extra_h = width - tile_w * GRID, height - tile_h * GRID
    tiles, y = [], 0
    for row in range(GRID):
        h = tile_h + 1 if row < extra_h else tile_h
        x = 0
        for col in range(GRID):
            w = tile_w + 1 if col < extra_w else tile_w
            tiles.append((x, y, w, h))
            x += w
        y += h
    classes = {}
    for index, tile in enumerate(tiles):
        classes.setdefault((tile[2], tile[3]), []).append(index)
    sources, rotations = {}, {}
    for size, members in classes.items():
        order = list(members)
        for count in range(len(order), 1, -1):
            pick = rng.below(count)
            order[count - 1], order[pick] = order[pick], order[count - 1]
        sources[size] = order
        rotations[size] = [rng.below(4) if size[0] == size[1] else (0 if rng.next() < .5 else 2) for _ in order]
    out = numpy.zeros_like(pixels)
    position = {}
    for dst in tiles:
        size = (dst[2], dst[3])
        index = position.get(size, 0)
        position[size] = index + 1
        src = tiles[sources[size][index]]
        rotation = rotations[size][index]
        w, h = size
        rs, cs = numpy.mgrid[0:h, 0:w]
        if rotation == 1:
            ys, xs = cs, h - 1 - rs
        elif rotation == 2:
            ys, xs = h - 1 - rs, w - 1 - cs
        elif rotation == 3:
            ys, xs = w - 1 - cs, rs
        else:
            ys, xs = rs, cs
        out[dst[1] + ys, dst[0] + xs] = pixels[src[1] + rs, src[0] + cs]
    return _jpeg(_image(out))


def apply(data, scheme):
    """Dispatch a page's descrambling scheme recorded by its adapter."""
    kind, _, rest = (scheme or '').partition(':')
    if not kind:
        return data
    if kind == 'fod':
        return fod(data, rest)
    if kind == 'line':
        parts = rest.split(':')
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            raise SourceError('LINE Manga изменила схему страницы.')
        return line(data, int(parts[0]), int(parts[1]), parts[2:])
    if kind == 'sokuyomi':
        return sokuyomi(data)
    if kind == 'canva':
        chapter, _, token = rest.partition(':')
        return canva(data, chapter, token)
    if kind == 'canva2':
        return canva2(data, rest)
    raise SourceError('Неизвестная схема перемешивания страницы.')
