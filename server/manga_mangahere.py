"""MangaHere catalogue and lazy reader without running upstream JavaScript."""

from dataclasses import dataclass, replace
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_catalogues import Browse
from manga_html_readers import FanFox
from manga_madara import image_url
from manga_mangalix import LiteralReader, quoted
from manga_series_port import Archive, MAX_PAGES
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ROOT = 'https://www.mangahere.cc'
HOST = urlsplit(ROOT).hostname
IDENTITY = ('2', 'Mangahere', 'en', ROOT, False)
LITERAL = r"""(?:'(?:[^'\\]|\\[\s\S])*'|"(?:[^"\\]|\\[\s\S])*")"""
PACKED = re.compile(r'}\s*\(\s*(' + LITERAL + r')\s*,\s*(\d{1,2})\s*,\s*(\d{1,4})\s*,\s*('
                    + LITERAL + r""")\.split\(\s*['"]\|['"]\s*\)""")
TOKEN = re.compile(r'\b[A-Za-z0-9_]+\b', re.ASCII)
ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
KEY = re.compile(r'\bguidkey\s*=\s*(' + LITERAL + r'(?:\s*\+\s*' + LITERAL + r')*)\s*;')
LITERALS = re.compile(LITERAL)
INDEX = re.compile(r'\bchapterid\s*=\s*["\']?(\d{1,18})["\']?\s*;', re.I)
IMAGE_HOST = re.compile(r'\bpix\s*=\s*(' + LITERAL + ')')
IMAGE_NAME = re.compile(r'\bpvalue\s*=\s*\[\s*(' + LITERAL + ')')
LAST_DIGITS = re.compile(r'(\d{2})\.[^./]+$')
CHAPTER_DIR = r'/manga/[A-Za-z0-9_-]{1,160}/(?:[A-Za-z0-9_.-]{1,80}/){1,3}'
IMAGE_ROUTE = re.compile(CHAPTER_DIR + r'chapterfun\.ashx')
REFERER_ROUTE = re.compile(CHAPTER_DIR + r'(?:[0-9]{1,4}\.html)?')
KEY_FORMAT = re.compile(r'[a-zA-Z0-9_-]{0,128}')


def base_digit(number, radix):
    result = ''
    while number:
        number, digit = divmod(number, radix)
        result = ALPHABET[digit] + result
    return result or '0'


def unpack(data):
    if len(data) > 1_000_000:
        raise SourceError('Сценарий MangaHere превышает лимит.')
    match = PACKED.search(data)
    if not match:
        raise SourceError('MangaHere изменил формат данных читалки.')
    radix, count = int(match[2]), int(match[3])
    words = quoted(match[4]).split('|')
    if not 2 <= radix <= len(ALPHABET) or not 1 <= count <= 6500 or len(words) < count:
        raise SourceError('Некорректный словарь читалки MangaHere.')
    table = {base_digit(index, radix): word for index, word in enumerate(words[:count]) if word}
    return TOKEN.sub(lambda piece: table.get(piece[0], piece[0]), quoted(match[1]))


def xhr_route(value, referer):
    parts, ref = urlsplit(value), urlsplit(referer)
    ref_dir = ref.path.rsplit('/', 1)[0] if ref.path.endswith('.html') else ref.path.rstrip('/')
    if (parts.hostname != HOST or ref.hostname != HOST or ref.scheme != 'https'
            or not IMAGE_ROUTE.fullmatch(parts.path) or not REFERER_ROUTE.fullmatch(ref.path)
            or parts.path.rsplit('/', 1)[0] != ref_dir):
        return False
    try:
        values = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=4)
    except ValueError:
        return False
    args = dict(values)
    return (len(values) == 3 and set(args) == {'cid', 'page', 'key'}
            and bool(re.fullmatch(r'[0-9]{1,18}', args['cid']))
            and bool(re.fullmatch(r'[0-9]{1,4}', args['page'])) and 1 <= int(args['page']) <= MAX_PAGES
            and bool(KEY_FORMAT.fullmatch(args['key'])))


def resolve_page(http, target, referer, key):
    for token in (key, '') if key else ('',):
        wire = query_url(target, key=token)
        raw, final, _ = http.document(wire, headers={'Referer': referer}, action='mangahere-xhr')
        if final != wire:
            raise SourceError('MangaHere перенаправил запрос на другую страницу.')
        if not raw.strip():
            continue
        decoded = unpack(raw)
        base, path = IMAGE_HOST.search(decoded), IMAGE_NAME.search(decoded)
        if base and path and (target := image_url(quoted(base[1]) + quoted(path[1]), referer)):
            return target
        raise SourceError('MangaHere не предоставил адрес изображения.')
    raise SourceError('MangaHere вернул пустую страницу главы.')


def consecutive(a, b):
    left = LAST_DIGITS.search(urlsplit(a).path)
    right = LAST_DIGITS.search(urlsplit(b).path)
    if not left or not right:
        return False
    n, m = int(left[1]), int(right[1])
    return (m - n) % 100 == 1


@dataclass(frozen=True)
class MangaHerePage:
    target: str
    key: str = ''
    image: str = ''

    def fetch(self, http, referer):
        from manga_page_media import read_image

        url = self.image or resolve_page(http, self.target, referer, self.key)
        response, _ = http._open(url, headers={'Referer': referer})
        return read_image(http, response)


class MangaHere(FanFox):
    def __init__(self):
        super().__init__(IDENTITY)
        self.reader_hosts = self.reader_hosts | {'mangahere.cc'}
        self.origin.interval = 2
        self.layout = replace(self.layout, popular=Browse('/directory/{page}.htm'),
                              archive=Archive('ul.detail-main-list li a[href]', anchor='', title='p.title3',
                                              date='p.title2', date_pattern='%b %d,%Y'))

    def site_link(self, value, base=None):
        target = super().site_link(value, base)
        if urlsplit(target).hostname == 'mangahere.cc':
            return target.replace('https://mangahere.cc', ROOT, 1)
        return target

    def chapter_identity(self, url):
        return re.sub(r'/[0-9]{1,4}\.html$', '', super().chapter_identity(url))

    def pages(self, http, url):
        doc, referer = self.page_document(http, url)
        if doc.select_one('p.detail-block-content'):
            raise SourceAccessError('MangaHere ограничил чтение этой главы.')
        script = next((s.string for s in doc.select('script') if s.string and 'function(p,a,c,k,e,d)' in s.string), '')
        decoded = unpack(script)
        if doc.select_one('script[src*="chapter_bar"]'):
            match = re.search(r'\bnewImgs\s*=\s*\[', decoded)
            if not match:
                raise SourceError('MangaHere не предоставил список изображений.')
            try:
                sources = LiteralReader(decoded, match.end() - 1).value()
            except (ValueError, OverflowError, RecursionError):
                raise SourceError('Некорректный список изображений MangaHere.') from None
            if not isinstance(sources, list):
                return []
            pages = [image_url(item, referer) for item in sources]
            if len(pages) > 1 and not consecutive(*pages[-2:]):
                pages.pop()
            return pages

        match = KEY.search(decoded)
        key = ''.join(quoted(piece[0]) for piece in LITERALS.finditer(match[1])) if match else ''
        chapter_id = next((match[1] for s in doc.select('script') if s.string and (match := INDEX.search(s.string))), '')
        entries = [int(a['data-page']) for a in doc.select('.pager-list-left > span a[data-page]')
                   if re.fullmatch(r'[0-9]{1,4}', a['data-page'])]
        count = max(entries, default=0)
        path = urlsplit(referer).path
        root = path.rsplit('/', 1)[0].rstrip('/')
        if not chapter_id or not 1 <= count <= MAX_PAGES or not KEY_FORMAT.fullmatch(key):
            raise SourceError('MangaHere не предоставил параметры открытой главы.')
        base = ROOT + root + '/chapterfun.ashx'
        targets = [query_url(base, cid=chapter_id, page=index) for index in range(1, count + 1)]
        pages = [(target, MangaHerePage(target, key)) for target in targets]
        if count > 1:
            penultimate = resolve_page(http, targets[-2], referer, key)
            try:
                last = resolve_page(http, targets[-1], referer, key)
            except SourceError:
                last = ''
            pages[-2] = (targets[-2], MangaHerePage(targets[-2], image=penultimate))
            if last and consecutive(penultimate, last):
                pages[-1] = (targets[-1], MangaHerePage(targets[-1], image=last))
            else:
                pages.pop()
        return remember(pages, referer)


SOURCES = (MangaHere(),)
