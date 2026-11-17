"""Clip Studio Reader page transport for open comic and EPUB previews.

Protocol inputs follow the Apache-2.0 Keiyoushi clipstudioreader library.
"""

from dataclasses import dataclass
from io import BytesIO
import json
import re
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

from PIL import Image

from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError, public_url

MAX_PAGES = 1500
TOKEN = re.compile(r'[A-Za-z0-9_.~+/=-]{1,4096}')
IMAGE = re.compile(r'\.(?:png|jpe?g|webp|gif|avif)$', re.I)
PARAMETER = re.compile(r'[^\x00-\x20\x7f]{1,4096}')
CONTENT_ID = re.compile(r'[A-Za-z0-9_.-]{1,180}')


def endpoint(value, document):
    if not isinstance(value, str) or not value:
        raise SourceError('Clip Studio Reader не указал публичный адрес.')
    raw = urljoin(document, value)
    if urlsplit(raw).fragment:
        raise SourceError('Clip Studio Reader вернул адрес с ошибочным фрагментом.')
    return public_url(raw, resolve_dns=False, allow_api=True)


def cgi_route(url, referer):
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    args = dict(pairs)
    if (referer != urljoin(url, './') or not parts.path or parts.path.endswith('/')
            or len(args) != len(pairs) or args.get('vm') not in ('2', '4')
            or not PARAMETER.fullmatch(args.get('param', ''))):
        return False
    mode = args.get('mode')
    if mode == '999':
        return args.get('reqtype') == '1' and set(args) == {'mode', 'reqtype', 'vm', 'param'}
    if args.get('reqtype') != '0' or set(args) != {'mode', 'reqtype', 'vm', 'param', 'file'}:
        return False
    file = args['file']
    if mode == '7':
        return file == 'face.xml'
    if mode == '8':
        return bool(re.fullmatch(r'\d{4}\.xml', file))
    return mode in ('1', '2', '3') and bool(re.fullmatch(r'\d{4}_\d{4}\.bin', file))


def epub_route(url, bearer):
    parts = urlsplit(url)
    if bearer and (not isinstance(bearer, str) or not TOKEN.fullmatch(bearer)):
        return False
    tail = parts.path
    if tail.endswith('/tokens/viewer'):
        params = parse_qsl(parts.query)
        return len(params) == 1 and params[0][0] == 'content_id' and bool(CONTENT_ID.fullmatch(params[0][1]))
    return bool(bearer and not parts.query and (tail.endswith(('/preprocess-settings.json', '/META-INF/container.xml'))
                or re.search(r'/contents/[A-Za-z0-9_.-]{1,180}/meta$', tail) or IMAGE.search(tail)
                or tail.endswith('.opf')))


def xml(data):
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', data, re.I):
        raise SourceError('Clip Studio Reader вернул недопустимый XML.')
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise SourceError('Clip Studio Reader изменил разметку XML.') from None
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1].casefold()
    return root


def node_value(tree, tag):
    node = next(tree.iter(tag.casefold()), None)
    return (node.text or '').strip() if node is not None else ''


def required_int(value, low, high):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,9}', value) or not low <= int(value) <= high:
        raise SourceError('Clip Studio Reader вернул неверные размеры или номера страниц.')
    return int(value)


def unique_links(episode, pages):
    stable = urlunsplit(urlsplit(episode)._replace(fragment=''))
    return remember([(query_url(stable, mv_clip=index), operation) for index, operation in enumerate(pages)], stable)


def xml_request(http, target, referer):
    data, final, _ = http.document(target, headers={'Referer': referer}, action='clipstudio-cgi')
    if final != target:
        raise SourceError('Clip Studio Reader перенаправил запрос XML.')
    return xml(data)


def arrange(raw, rows, columns, grid, half):
    if not grid and not half:
        return raw
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 35_000_000 or image.width < 2:
                raise SourceError('Изображение Clip Studio Reader превышает лимит.')
            original = image.convert('RGB')
        output = original.copy()
        width, height = original.size
        piece_w, piece_h = width // columns // 8 * 8, height // rows // 8 * 8
        if grid and piece_h and piece_w:
            for dest, src in enumerate(grid):
                x, y = src % columns * piece_w, src // columns * piece_h
                output.paste(original.crop((x, y, x + piece_w, y + piece_h)),
                             (dest % columns * piece_w, dest // columns * piece_h))
        if half == 'L':
            output = output.crop((0, 0, width // 2, height))
        if half == 'R':
            output = output.crop((width // 2, 0, width, height))
        written = BytesIO()
        output.save(written, format='PNG')
        return written.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise SourceError('Clip Studio Reader вернул повреждённое изображение.') from None


@dataclass(frozen=True)
class ComicPage:
    target: str
    columns: int
    rows: int
    half: str = ''

    def fetch(self, http, referer):
        from manga_page_media import read_image

        origin = urljoin(self.target, './')
        page = xml_request(http, self.target, origin)
        if not node_value(page, 'pageno'):
            raise SourceAccessError('Издатель ограничивает доступ к этой странице.')
        number = required_int(node_value(page, 'pageno'), 0, 9999)
        kind = next((node for node in page.iter('kind') if (node.text or '').strip() in ('1', '2', '3')), None)
        if kind is None:
            raise SourceError('Clip Studio Reader не предоставил файл страницы.')
        attrs = {key.casefold(): value for key, value in kind.attrib.items()}
        part = required_int(attrs.get('no'), 0, 9999)
        address = query_url(self.target, mode=kind.text.strip(), file=f'{number:04}_{part:04}.bin')
        grid = []
        if attrs.get('scramble') == '1':
            pieces = node_value(page, 'scramble').split(',')
            count = self.columns * self.rows
            if len(pieces) != count:
                raise SourceError('Неверный порядок плиток Clip Studio Reader.')
            grid = [required_int(piece.strip(), 0, count - 1) for piece in pieces]
            if len(set(grid)) != count:
                raise SourceError('Неверный порядок плиток Clip Studio Reader.')
        response, _ = http._open(address, headers={'Referer': origin}, action='clipstudio-cgi')
        return arrange(read_image(http, response), self.rows, self.columns, grid, self.half)


def comic_pages(http, url, param, preview):
    if not isinstance(param, str) or not PARAMETER.fullmatch(param) or urlsplit(url).query:
        raise SourceError('Некорректные параметры Clip Studio Reader.')
    referer = urljoin(url, './')
    args = {'mode': '999', 'reqtype': '1', 'param': param}
    mode = '4'
    result = xml_request(http, query_url(url, vm=mode, **args), referer)
    if node_value(result, 'code') == '2005':
        mode = '2'
        result = xml_request(http, query_url(url, vm=mode, **args), referer)
    if node_value(result, 'code') != '1000':
        raise SourceAccessError('Издатель не предоставил открытый выпуск.')
    key = node_value(result, 'content')
    if not PARAMETER.fullmatch(key):
        raise SourceError('Clip Studio Reader не предоставил ключ открытого выпуска.')
    args = {'reqtype': '0', 'vm': mode, 'param': key}
    face = xml_request(http, query_url(url, mode='7', file='face.xml', **args), referer)
    total = required_int(node_value(face, 'totalpage'), 1, MAX_PAGES)
    scramble = next(face.iter('scramble'), None)
    if scramble is None:
        raise SourceError('Clip Studio Reader не предоставил размеры плиток.')
    cols = required_int(node_value(scramble, 'width'), 1, 64)
    rows = required_int(node_value(scramble, 'height'), 1, 64)
    start, stop = 0, total - 1
    if preview:
        found = re.fullmatch(r'(\d{1,4})_(\d{1,4})', preview)
        if not found:
            raise SourceError('Clip Studio Reader изменил границы ознакомительного выпуска.')
        start, stop = map(int, found.groups())
        if not 0 <= start <= stop < total:
            raise SourceError('Границы ознакомительного выпуска выходят за пределы книги.')
    spreads = set()
    if 'Omf' in node_value(face, 'optionid'):
        spreads = {int(n) for raw in node_value(face, 'doublepagesmap').split(',')
                   if re.fullmatch(r'\d{1,4}', n := raw.strip())}
    halves = ('L', 'R') if node_value(face, 'binding') == '1' else ('R', 'L')
    return [ComicPage(query_url(url, mode='8', file=f'{n:04}.xml', **args), cols, rows, half)
            for n in range(start, stop + 1) for half in (halves if n in spreads else ('',))]


def authorized_document(http, url, referer, token=''):
    headers = {'Referer': referer}
    if token:
        headers['ClipStudio-Token'] = token
    raw, final, _ = http.document(url, headers=headers, action='clipstudio-epub')
    if final != url:
        raise SourceError('Clip Studio Reader перенаправил запрос EPUB.')
    return raw


def json_data(text):
    try:
        found = json.loads(text)
    except ValueError:
        raise SourceError('Издатель не предоставил данные EPUB.') from None
    if not isinstance(found, dict):
        raise SourceError('Издатель изменил формат данных EPUB.')
    return found


@dataclass(frozen=True)
class EpubPage:
    target: str
    token: str
    key: int | None

    def fetch(self, http, referer):
        from manga_page_media import read_image

        response, _ = http._open(self.target, headers={'Referer': referer, 'ClipStudio-Token': self.token}, action='clipstudio-epub')
        raw = read_image(http, response)
        if self.key is None or raw.startswith((b'\xff\xd8', b'GIF8', b'\x89PNG')):
            return raw
        return bytes(byte ^ self.key for byte in raw[:100]) + raw[100:]


def epub_pages(http, viewer, content, variant, token):
    if not CONTENT_ID.fullmatch(content) or not CONTENT_ID.fullmatch(variant):
        raise SourceError('Некорректный идентификатор EPUB.')
    config_url = endpoint(variant + '.jsonc', viewer)
    raw, final, _ = http.document(config_url, headers={'Referer': urljoin(viewer, './')})
    if final != config_url:
        raise SourceError('Издатель перенаправил запрос настроек EPUB.')
    config = json_data(raw)
    ref = urljoin(viewer, './')
    api = endpoint(config.get('api') or '', viewer).rstrip('/') + '/'
    if api == ref or urlsplit(api).query:
        raise SourceError('Clip Studio Reader не указал API EPUB.')
    request = query_url(api + 'tokens/viewer', content_id=content)
    token = json_data(authorized_document(http, request, ref, token)).get('token')
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise SourceAccessError('Издатель не предоставил пропуск на открытый выпуск EPUB.')
    meta = json_data(authorized_document(http, api + f'contents/{content}/meta', ref, token))
    base = endpoint((meta.get('content') or {}).get('baseUrl') or '', viewer).rstrip('/') + '/'
    if base == ref or urlsplit(base).query:
        raise SourceError('Clip Studio Reader не указал хранилище EPUB.')
    preprocess = json_data(authorized_document(http, base + 'preprocess-settings.json', ref, token))
    key = preprocess.get('obfuscateImageKey') if preprocess.get('obfuscateImage') else None
    if type(key) is int:
        key &= 255
    else:
        key = None
    container = xml(authorized_document(http, base + 'META-INF/container.xml', ref, token))
    root = next(container.iter('rootfile'), None)
    if root is None or not root.get('full-path'):
        raise SourceError('Clip Studio Reader не предоставил манифест EPUB.')
    manifest_url = endpoint(root['full-path'], base)
    if not manifest_url.startswith(base):
        raise SourceError('Манифест EPUB находится на другом маршруте.')
    manifest = xml(authorized_document(http, manifest_url, ref, token))
    refs = []
    for item in manifest.iter('item'):
        if not item.get('media-type', '').startswith('image/') or not item.get('href'):
            continue
        target = endpoint(item.get('href'), manifest_url)
        if not target.startswith(base):
            raise SourceError('Изображение EPUB находится за пределами издания.')
        refs.append(EpubPage(target, token, key))
    return refs


def viewer_pages(http, viewer, episode, doc=None):
    parts = urlsplit(viewer)
    args = dict(parse_qsl(parts.query, keep_blank_values=True))
    if args.get('c'):
        pages = epub_pages(http, viewer, args['c'], args.get('s') or 'default', args.get('t') or '')
    else:
        meta = doc.select_one('#meta') if doc else None
        if meta:
            args = {node['name']: node.get('value', '') for node in meta.select('input[name]')}
        if not args.get('cgi'):
            raise SourceAccessError('Издатель не передал открытую читалку Clip Studio.')
        param = (args.get('param') or '') if meta else (args.get('param') or '').replace(' ', '+')
        pages = comic_pages(http, endpoint(args['cgi'], viewer), param, args.get('trial'))
    if not 1 <= len(pages) <= MAX_PAGES:
        raise SourceError('Clip Studio Reader не предоставил изображения выпуска.')
    return unique_links(episode, pages)
