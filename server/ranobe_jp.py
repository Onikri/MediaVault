"""Public Japanese web-novel editions from Shōsetsuka ni Narō."""
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup

from source_parser import SourceError
from title_identity import aliases, normalized

API = 'https://api.syosetu.com/novelapi/api/'
ROOT = 'https://ncode.syosetu.com/'
SOURCE = ('narou', '小説家になろう', 'ja')
HEADERS = {'User-Agent': 'MediaVault/5.1 (https://github.com/Onikri/MediaVault; personal catalogue)'}
NCODE = r'n[0-9]{4}[a-z]{1,3}'


def _rows(http, **query):
    address = API + '?' + urlencode({'out': 'json', 'libtype': 2, 'of': 't-n-w-ga-nt', **query})
    text, final, _ = http.document(address, headers=HEADERS, action='ranobe')
    if not final.startswith(API):
        raise SourceError('Каталог Narō перенаправил запрос.')
    data = json.loads(text)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict) or 'allcount' not in data[0]:
        raise SourceError('Каталог Narō вернул неизвестный формат.')
    return [row for row in data[1:] if isinstance(row, dict) and re.fullmatch(NCODE, str(row.get('ncode', '')).lower())]


def search(title, http):
    names = [name for name in aliases(title) if re.search(r'[ぁ-ヿ一-鿿]', name)]
    exact = {normalized(name) for name in names}
    for name in names[:2]:
        # The published web edition can carry a subtitle after a spaced dash.
        found = []
        for row in _rows(http, word=name, title=1, lim=18, order='favnovelcnt'):
            label = str(row.get('title') or '')
            short = re.split(r'\s+[-―～~]\s*', label, maxsplit=1)[0]
            if not exact.intersection({normalized(label), normalized(short)}) or not row.get('general_all_no'):
                continue
            found.append({'provider': SOURCE[0], 'providerName': SOURCE[1], 'language': 'ja', 'kind': 'ranobe',
                          'title': label[:300], 'aliases': [label], 'url': ROOT + row['ncode'].lower() + '/',
                          'translator': '', 'description': '', 'cover': '', 'matchEvidence': 'web_edition'})
        if found:
            return found[:1]
    return []


def route(url):
    parts = urlsplit(str(url or ''))
    if parts.scheme != 'https' or parts.netloc != 'ncode.syosetu.com':
        return None
    match = re.fullmatch(r'/(' + NCODE + r')/(?:([1-9][0-9]{0,4})/?)?', parts.path)
    if not match:
        return None
    part = match[2] or parse_qs(parts.query).get('mv_chapter', [''])[0]
    if part and not re.fullmatch(r'[1-9][0-9]{0,4}', part):
        raise SourceError('Некорректная ссылка на главу Narō.')
    return match[1], part


def inspect(url, http):
    code, _ = route(url)
    rows = _rows(http, ncode=code)
    if not rows:
        raise SourceError('Произведение отсутствует в открытом каталоге Narō.')
    row = rows[0]
    title = str(row.get('title') or code)[:300]
    base = ROOT + code + '/'
    try:
        count = max(0, min(3000, int(row.get('general_all_no') or 0)))
    except (ValueError, TypeError):
        raise SourceError('Не удалось разобрать оглавление Narō.') from None
    short = row.get('noveltype') == 2
    episodes = [{'number': number, 'season': 1, 'title': title if short else 'Глава ' + str(number), 'language': 'ja',
                 'translator': '', 'url': base + ('?mv_chapter=1' if short else str(number) + '/')}
                for number in range(1, count + 1)]
    return {'provider': SOURCE[0], 'providerName': SOURCE[1], 'kind': 'ranobe', 'title': title, 'aliases': [title],
            'language': 'ja', 'url': base, 'episodes': episodes, 'seasons': [{'number': 1, 'name': 'Веб-роман'}]}


def chapter(url, http, paragraphs_from_html):
    code, number = route(url)
    if not number:
        raise SourceError('Выбери конкретную главу Narō.')
    short = urlsplit(url).path == '/' + code + '/'
    target = ROOT + code + '/' + ('' if short else number + '/')
    text, final, _ = http.document(target, headers=HEADERS, action='ranobe')
    if route(final) != (code, '' if short else number):
        raise SourceError('Narō перенаправил на другую главу.')
    soup = BeautifulSoup(text, 'html.parser')
    body = soup.select_one('.js-novel-text.p-novel__text, .p-novel__body > .p-novel__text')
    if not body:
        raise SourceError('Narō не вернул текст главы.')
    for ruby in body.select('rt, rp'):
        ruby.decompose()
    paragraphs = paragraphs_from_html(str(body))
    if not paragraphs:
        raise SourceError('Глава Narō пуста.')
    heading = soup.select_one('.p-novel__title, h1')
    return {'provider': SOURCE[0], 'url': url, 'language': 'ja', 'paragraphs': paragraphs,
            'title': heading.get_text(' ', strip=True)[:200] if heading else 'Глава ' + number}
