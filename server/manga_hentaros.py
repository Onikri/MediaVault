"""HentaRos (hentaros.com) public gallery reader.

Every catalogue card is one gallery page ``/<slug>``: its header names the
work and its ``.reader-urls`` block lists every page image (``data-full`` on
hentaros.com/img/). A gallery is read as one chapter; no JavaScript is run.
"""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_source_tags import unique
from source_parser import SourceError, public_url

HOST = 'hentaros.com'
ROOT = 'https://' + HOST
PROVIDER = HOST
NAME = 'Hentaros'
SLUG = re.compile(r'/([A-Za-z0-9][A-Za-z0-9_%.-]{0,300})/?')
# Site sections, never a gallery.
RESERVED = frozenset({'tag', 'artist', 'series', 'dmca', '2257', 'privacy', 'img', 'search', 'page', 'telegra',
                      'main.js', 'style.css', 'favicon.svg', 'manifest.json', 'wp-logo.svg'})
IMAGE = re.compile(r'/img/[A-Za-z0-9_-]{1,200}\.(?:jpe?g|png|webp|gif|avif)', re.I)
MAX_PAGES = 1500


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:500]


def gallery_url(value, base=ROOT):
    url = public_url(urljoin(base, value or ''), resolve_dns=False)
    parts = urlsplit(url)
    match = SLUG.fullmatch(parts.path)
    if (parts.scheme != 'https' or parts.hostname != HOST or parts.username or parts.password or not match
            or match[1].lower() in RESERVED):
        raise SourceError('Hentaros вернул ссылку вне своих галерей.')
    return ROOT + '/' + match[1]


def image_url(value, base):
    try:
        url = public_url(urljoin(base, value or ''), resolve_dns=False)
    except SourceError:
        return ''
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != HOST or parts.query or not IMAGE.fullmatch(parts.path):
        return ''
    return url


def inspect(url, http):
    target = gallery_url(url)
    text, final, _ = http.document(target)
    final = gallery_url(final)
    soup = BeautifulSoup(text, 'html.parser')
    heading = soup.select_one('.post-head h1')
    if not heading:
        raise SourceError('Hentaros не предоставил карточку галереи.')
    title = clean(heading.get_text(' ', strip=True))
    pages = []
    for node in soup.select('.reader-urls [data-full]')[:MAX_PAGES]:
        page = image_url(node['data-full'], final)
        if not page:
            raise SourceError('Hentaros указал страницу вне своей галереи.')
        pages.append(page)
    pages = list(dict.fromkeys(pages))
    if not pages:
        raise SourceError('Hentaros не предоставил страницы галереи.')
    aliases = [clean(row.get_text(' ', strip=True).split(' ', 1)[-1]) for row in soup.select('.post-head .kv')
               if (row.select_one('b') and clean(row.select_one('b').get_text()) in {'Оригинал', 'По-английски'})]
    poster = soup.select_one('.post-head .poster img[data-full]')
    chapter = {'number': 1.0, 'season': 1, 'url': final, 'title': title, 'translator': '', 'language': 'ru',
               'publishedAt': ''}
    return {'provider': PROVIDER, 'providerName': NAME, 'title': title, 'url': final, 'kind': 'manga',
            'language': 'ru', 'adult': True, 'age': 18,
            'cover': image_url(poster['data-full'], final) if poster else '',
            'aliases': unique([title, *aliases]),
            'tags': unique(a.get_text(' ', strip=True) for a in soup.select('.post-head .chip[href*="/tag/"]')),
            'genres': [], 'episodes': [chapter], 'pages': pages, 'available': True,
            'seasons': [{'number': 1, 'name': 'Том 1'}], 'translations': [], 'dubs': [], 'releases': [],
            'truncated': False}
