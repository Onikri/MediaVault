"""E4P reader manifests and pages (keiyoushi ``lib/e4p`` at 6f345a8).

An E4P delivery is a Protobuf ticket (``E4PQSTicket``). A ``TDRM_V1``
ticket hides its wrapper behind RC4 and a Blowfish variant with the
reader's own tables; a ``CDRM_V1`` wrapper is ChaCha8 with a BLAKE2b key
derived from the content ID. The decoded ``ProtoPub`` lists the page
variants. Each page lives inside a QSC archive (a 4 KB directory and the
files) fetched with byte ranges; an ``XEBP`` page is a WebP plus a
ChaCha8-encrypted TIFF patch (nonce from an XXTEA-sealed ``ZSTR`` chunk)
that the official viewer draws over the top-left corner, exactly as the
extension's ``XebpDecoder`` does.
"""

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import struct
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import zlib

from PIL import Image

from manga_japanese_readers import JapanesePage
from manga_million_wire import Message
from source_parser import SourceAccessError, SourceError

MASK = 0xFFFFFFFF
A6 = (11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 67, 71, 73, 79, 83, 69)
ALPHABET = b'R5zRO0qEKFDfaP3OrLIbbQkjrcwWdgb4f7k6LLJjehQtvTrNXuzLp2_NT-eRnHK1'
FINAL_MASK = bytes((0xD9, 0xAD, 0xBE, 0xEF, 0xC0, 0xDE, 0xAD))
XXTEA_KEY = bytes.fromhex('6ca87b0fa8513e36165347af5de51989')
DIR_SIZE = 4096
QSC_MAGIC = b'E4PQSC\x01\x00'
MAX_MANIFEST = 4 * 1024 * 1024
BLOWFISH_P = 'DvkjivaXokwc2uOuQv7MCnIYSqteJh5cCoK/vx0BMyf1IvfsEnVw5wzMOTSwI7WW7s7+x71uM9VgSspOTfCxQS5knBlOncoD'
BLOWFISH_S = (
    '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'
    'q+BqevGcdUWK7bb2ClfkCg=='
)


def rc4(data, key, skip=0):
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    out = bytearray(len(data))
    for index in range(skip + len(data)):
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        if index >= skip:
            out[index - skip] = data[index - skip] ^ state[(state[i] + state[j]) & 255]
    return bytes(out)


VF124 = rc4(bytes((0x8F, 0x08, 0xBE, 0x6C, 0x0F, 0xDE, 0x6A, 0xF8, 0x20, 0xED, 0x7E, 0xAF, 0x0E, 0x52, 0xDD, 0x9D)),
            b'error', 771)
_BLOWFISH = []


def blowfish_tables():
    if not _BLOWFISH:
        s = rc4(base64.b64decode(BLOWFISH_S), b'undefined', 769)
        p = rc4(base64.b64decode(BLOWFISH_P), b'undefined', 769)
        _BLOWFISH.append((struct.unpack('<18I', p[:72]),
                          tuple(struct.unpack_from('<256I', s, box * 1024) for box in range(4))))
    return _BLOWFISH[0]


def blowfish_cbc_decrypt(data, iv):
    p, s = blowfish_tables()

    def f(x):
        return ((((s[0][x >> 24] + s[1][(x >> 16) & 255]) & MASK) ^ s[2][(x >> 8) & 255]) + s[3][x & 255]) & MASK

    prev_l, prev_r = struct.unpack('>II', iv)
    out = bytearray()
    for offset in range(0, len(data), 8):
        cl, cr = struct.unpack_from('>II', data, offset)
        xl, xr = cl ^ p[17], cr ^ p[16]
        xl, xr = xr, xl
        for index in range(15, -1, -1):
            xl, xr = xr, xl
            xr ^= f(xl)
            xl ^= p[index]
        out += struct.pack('>II', xl ^ prev_l, xr ^ prev_r)
        prev_l, prev_r = cl, cr
    return bytes(out)


def xor_a6(buffer, shift):
    return bytes(value ^ A6[(A6[index] + shift) % len(A6)] for index, value in enumerate(buffer))


def chacha8(data, key, nonce, counter=0):
    constants = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)
    base = list(constants) + list(struct.unpack('<8I', key)) + [0, 0] + list(struct.unpack('<2I', nonce))

    def rotate(value, bits):
        return ((value << bits) & MASK) | (value >> (32 - bits))

    def quarter(x, a, b, c, d):
        x[a] = (x[a] + x[b]) & MASK
        x[d] = rotate(x[d] ^ x[a], 16)
        x[c] = (x[c] + x[d]) & MASK
        x[b] = rotate(x[b] ^ x[c], 12)
        x[a] = (x[a] + x[b]) & MASK
        x[d] = rotate(x[d] ^ x[a], 8)
        x[c] = (x[c] + x[d]) & MASK
        x[b] = rotate(x[b] ^ x[c], 7)

    out = bytearray(len(data))
    for position in range(0, len(data), 64):
        state = list(base)
        state[12], state[13] = counter & MASK, (counter >> 32) & MASK
        work = list(state)
        for _ in range(4):
            quarter(work, 0, 4, 8, 12)
            quarter(work, 1, 5, 9, 13)
            quarter(work, 2, 6, 10, 14)
            quarter(work, 3, 7, 11, 15)
            quarter(work, 0, 5, 10, 15)
            quarter(work, 1, 6, 11, 12)
            quarter(work, 2, 7, 8, 13)
            quarter(work, 3, 4, 9, 14)
        stream = struct.pack('<16I', *((work[i] + state[i]) & MASK for i in range(16)))
        block = data[position:position + 64]
        out[position:position + len(block)] = bytes(a ^ b for a, b in zip(block, stream))
        counter += 1
    return bytes(out)


def raw_bytes(message, number):
    return next(message.values(number, 2), b'')


def unwrap_tdrm(content, consumer, expires, iv, data):
    if len(iv) != 32 or len(content) < 3 or len(consumer) < 3:
        raise SourceError('Читалка E4P изменила формат билета.')
    ids = content.encode()
    tweak = bytes((expires % 100, expires // 100 % 100, expires // 10_000 % 100, expires // 1_000_000 % 100,
                   expires // 100_000_000 % 100, ids[-1], ids[-2], ids[-3]))
    tweak = xor_a6(tweak, 0)
    blowfish_iv = xor_a6(hashlib.sha1(VF124 + tweak).digest()[7:15], 3)
    key = (consumer.encode() + ids + VF124)[:256]
    head = min(len(data), 123 + ids[2])
    opened = rc4(iv + data[:head], key, 769)
    return blowfish_cbc_decrypt(opened[:32], blowfish_iv), opened[32:32 + head] + data[head:]


def cdrm_key(content, iv):
    ids = content.encode()[:24]
    key = bytearray(hashlib.blake2b(ids + ALPHABET[:64 - len(ids)], digest_size=32).digest())
    for index in range(16):
        key[2 * index] ^= iv[index]
    k, l, m, n, o, p, q = iv[25:32]
    for index, value in (((q & 15) + 2, k), ((p & 15) + 5, l), ((o & 15) + 5, m), ((n & 15) + 6, n),
                         ((m & 15) + 5, o), ((l & 15) + 0, p), ((k & 15) + 0, q)):
        key[index] ^= value
    for index in range(32):
        key[index] ^= FINAL_MASK[(index + 3) % 7]
    return bytes(key)


@dataclass(frozen=True)
class Manifest:
    pages: tuple
    content: str
    consumer: bytes
    seed: bytes


def decode_manifest(raw):
    """Decode an ``application/vnd.e4p.prpb+deflate+vnd.e4p.qst`` ticket."""
    ticket = Message(raw, 'E4P')
    content, consumer = ticket.string(2), ticket.string(3)
    child = ticket.message(5) if ticket.fields.get(5) else Message(b'', 'E4P')
    kind, iv, data, data_type = child.integer(1), raw_bytes(child, 2), raw_bytes(child, 4), child.integer(5)
    if ticket.integer(1) == 2:
        expires = ticket.message(4).integer(1) if ticket.fields.get(4) else 0
        iv, data = unwrap_tdrm(content, consumer, expires, iv, data)
    elif ticket.integer(1) != 0:
        raise SourceError('Читалка E4P прислала неизвестный тип билета.')
    if kind == 2:
        if len(iv) != 32:
            raise SourceError('Читалка E4P изменила формат билета.')
        data = chacha8(data, cdrm_key(content, iv), iv[16:24], iv[24])
    elif kind != 0:
        raise SourceError('Читалка E4P прислала неизвестную обёртку.')
    seed = b''
    if len(data) >= 52 and data[:4] == b'PBEX':
        seed, data = data[4:52], data[52:]
    if data_type == 5:
        try:
            data = zlib.decompressobj(15 + 32).decompress(data, MAX_MANIFEST)
        except zlib.error:
            try:
                data = zlib.decompressobj(-15).decompress(data, MAX_MANIFEST)
            except zlib.error:
                raise SourceError('Читалка E4P прислала повреждённый манифест.') from None
    elif data_type != 2:
        raise SourceError('Читалка E4P прислала неизвестный формат манифеста.')
    return Manifest(tuple(Message(data, 'E4P').messages(2)), content,
                    (consumer + '0' * 32)[:32].encode('ascii', 'replace'), seed)


def plain_manifest(raw):
    return Manifest(tuple(Message(raw, 'E4P').messages(2)), '', b'', b'')


@dataclass(frozen=True)
class E4PPage(JapanesePage):
    entry: str = ''
    iv: bytes = b''
    content: str = ''
    consumer: bytes = b''
    seed: bytes = b''
    # Pages share one QSC archive; ``url`` carries a page marker so that
    # every page has its own grant, ``archive`` is the real address.
    archive: str = ''

    def fetch(self, http, referer):
        from manga_page_media import read_image

        target = self.archive or self.url
        if not self.entry:
            response, _ = http._open(target, headers={'Referer': referer})
            return read_image(http, response)
        response, _ = http._open(target, headers={'Referer': referer}, byte_range=f'bytes=0-{DIR_SIZE - 1}')
        directory = bytes(read_image(http, response)[:DIR_SIZE])
        start, size = qsc_entry(directory, self.entry)
        response, _ = http._open(target, headers={'Referer': referer},
                                 byte_range=f'bytes={DIR_SIZE + start}-{DIR_SIZE + start + size - 1}')
        data = bytes(read_image(http, response))
        if len(data) > size:
            # The server ignored the range and sent the whole archive.
            data = data[DIR_SIZE + start:DIR_SIZE + start + size]
        if len(data) != size:
            raise SourceError('Читалка E4P прислала неполную страницу.')
        if len(self.iv) == 32 and len(self.seed) == 48:
            return xebp_render(data, self.iv, self.seed)
        return strip_webp(data)


def qsc_entry(directory, name):
    if len(directory) < DIR_SIZE or directory[:8] != QSC_MAGIC:
        raise SourceError('Читалка E4P прислала повреждённый архив страниц.')
    offset = 0
    for index in range(127):
        base = 32 + index * 32
        size = struct.unpack_from('<I', directory, base + 4)[0]
        if not size:
            break
        if directory[base + 8:base + 32].rstrip(b'\0').decode('latin-1') == name:
            return offset, size
        offset += size
    raise SourceError('Читалка E4P не нашла страницу в архиве.')


def strip_webp(data):
    if len(data) < 20 or data[:4] != b'RIFF':
        return data
    size = struct.unpack_from('<I', data, 16)[0]
    end = 20 + size + (size & 1)
    if end > len(data):
        return data
    return b'RIFF' + struct.pack('<I', end - 8) + b'WEBP' + data[12:end]


def xxtea_decrypt(values, key):
    k = struct.unpack('<4I', key)
    n = len(values)
    rounds = 6 + 52 // n
    delta = 0x9E3779B9
    total = (rounds * delta) & MASK
    y = values[0]
    for _ in range(rounds):
        e = (total >> 2) & 3
        for p in range(n - 1, -1, -1):
            z = values[p - 1] if p else values[n - 1]
            mx = ((((z >> 5) ^ (y << 2) & MASK) + ((y >> 3) ^ (z << 4) & MASK)) & MASK) ^ (((total ^ y) + (k[(p & 3) ^ e] ^ z)) & MASK)
            values[p] = (values[p] - mx) & MASK
            y = values[p]
        total = (total - delta) & MASK
    return values


def xebp_chunks(data):
    if len(data) < 20 or data[:4] != b'RIFF':
        raise SourceError('Читалка E4P прислала повреждённую страницу.')
    chunks, offset, image = {}, 12, None
    while offset + 8 <= len(data):
        name, size = data[offset:offset + 4], struct.unpack_from('<I', data, offset + 4)[0]
        if name in {b'VP8 ', b'VP8L', b'VP8X'}:
            image = (offset, size)
        elif name in {b'ZSTR', b'tfix'}:
            chunks[name] = data[offset + 8:offset + 8 + size]
        offset += 8 + size + (size & 1)
    if b'ZSTR' not in chunks or b'tfix' not in chunks or image is None:
        raise SourceError('Читалка E4P изменила формат страницы.')
    end = image[0] + 8 + image[1] + (image[1] & 1)
    webp = b'RIFF' + struct.pack('<I', end - 8) + b'WEBP' + data[12:end]
    return webp, chunks[b'ZSTR'], bytearray(chunks[b'tfix'])


def zstr_meta(raw):
    lines = raw.decode('latin-1').rstrip('\0').split('\n')
    try:
        if len(lines) < 3 or int(lines[0].strip()) != 1:
            raise ValueError
        length = (int(lines[1].strip()) ^ 65) & 0xFFFF
        sealed = bytes.fromhex(lines[2].strip())
    except ValueError:
        raise SourceError('Читалка E4P изменила формат страницы.') from None
    count = len(sealed) // 4
    if count < 2 or len(sealed) % 4:
        raise SourceError('Читалка E4P изменила формат страницы.')
    values = xxtea_decrypt(list(struct.unpack(f'<{count}I', sealed)), XXTEA_KEY)
    real = values[-1]
    if not 1 <= real <= (count - 1) * 4:
        raise SourceError('Читалка E4P изменила формат страницы.')
    plain = struct.pack(f'<{count}I', *values)[:real]
    return (plain + b'\0' * 8)[:8], length


def xebp_render(data, iv, seed):
    webp, zstr, tfix = xebp_chunks(data)
    nonce, length = zstr_meta(zstr)
    key = bytes(seed[16 + index] ^ iv[index] for index in range(32))
    length = min(length, len(tfix))
    for index in range(length):
        tfix[index] ^= 0x11
    tiff = chacha8(bytes(tfix), key, nonce, length)
    if tiff[:4] != b'II*\x00':
        raise SourceError('Читалка E4P не расшифровала страницу.')
    try:
        with Image.open(BytesIO(webp)) as base, Image.open(BytesIO(tiff)) as patch:
            page = base.convert('RGB')
            layer = patch.convert('RGB')
            page.paste(layer.crop((0, 0, min(layer.width, page.width), min(layer.height, page.height))), (0, 0))
            output = BytesIO()
            page.save(output, 'JPEG', quality=92)
            return output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise SourceError('Читалка E4P прислала повреждённую страницу.') from None


def page_refs(manifest, manifest_url):
    """The best variant of every spine item, with the manifest's auth query."""
    import re

    base = urlsplit(manifest_url)
    auth = parse_qsl(base.query, keep_blank_values=True)
    rows = []
    for link in manifest.pages:
        best, height = None, -1
        for variant in link.messages(1):
            if not variant.fields.get(2):
                continue
            found = re.match(r'h(\d+)/', variant.string(1))
            value = int(found[1]) if found else 0
            if value > height:
                best, height = variant, value
        if best is None:
            continue
        target = urlsplit(urljoin(manifest_url, best.string(1)))
        if target.scheme != 'https' or target.netloc != base.netloc:
            raise SourceError('Читалка E4P указала страницу на другом сервере.')
        query = dict(parse_qsl(target.query, keep_blank_values=True))
        query.update(auth)
        url = urlunsplit(target._replace(query=urlencode(query), fragment=''))
        drm = best.message(2).message(3) if best.message(2).fields.get(3) else None
        iv = raw_bytes(drm, 3) if drm is not None and drm.integer(1) == 2 else b''
        marked = url + ('&' if '?' in url else '?') + 'mv_page=' + str(len(rows) + 1)
        rows.append(E4PPage(marked, archive=url, entry=target.fragment, iv=iv, content=manifest.content, consumer=manifest.consumer,
                            seed=manifest.seed))
    if not rows:
        raise SourceAccessError('Читалка E4P не открыла страницы главы.')
    return rows
