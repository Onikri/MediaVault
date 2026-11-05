"""The public video list used by the YummyAnime title page."""
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from player_catalog import choice
from source_parser import PublicHttp, SourceError, public_url

ORIGIN = 'https://ru.yummyani.me'
REZE_PAGE = ORIGIN + '/catalog/item/chelovek-benzopila-reze-2026-02-24'
PROVIDER = 'yummy-official'


def is_title_page(url):
    parts = urlsplit(url)
    return parts.hostname == 'ru.yummyani.me' and bool(re.fullmatch(r'/catalog/item/[a-z0-9-]+/?', parts.path))


def inspect(url, http, *, dub_url=None):
    text, final, _ = http.document(url)
    if not is_title_page(final):
        raise SourceError('YummyAnime перенаправил на другую страницу.')
    soup = BeautifulSoup(text, 'html.parser')
    entry = soup.select_one('main > [data-id]')
    heading = soup.select_one('main h1')
    identifier = entry.get('data-id', '') if entry else ''
    if not heading or not re.fullmatch(r'[1-9]\d{0,9}', identifier):
        raise SourceError('YummyAnime не подтвердил страницу тайтла.')
    ids = {}
    for link in soup.select('main a[href]'):
        parts = urlsplit(urljoin(final, link['href']))
        if parts.hostname == 'myanimelist.net':
            match = re.match(r'/anime/([1-9]\d*)(?:/|$)', parts.path)
            if match:
                ids.setdefault('mal', int(match[1]))
    raw, _, _ = http.document(ORIGIN + '/api/anime/' + identifier + '/videos', headers={'Referer': final})
    try:
        payload = json.loads(raw)
    except ValueError:
        raise SourceError('YummyAnime вернул неизвестный формат списка видео.') from None
    rows = payload.get('response') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SourceError('YummyAnime вернул неизвестный формат списка видео.')
    translations = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('data'), dict):
            continue
        target = row.get('iframe_url')
        if not isinstance(target, str):
            continue
        try:
            target = public_url(urljoin(final, target), resolve_dns=False)
        except SourceError:
            continue
        parts = urlsplit(target)
        if parts.hostname != 'alloha.yani.tv' or parts.path != '/':
            continue
        params = parse_qs(parts.query)
        translation = params.get('translation', [''])[0]
        label = row['data'].get('dubbing')
        number = str(row.get('number', ''))
        if not translation.isdigit() or not isinstance(label, str) or not re.fullmatch(r'[1-9]\d{0,4}', number):
            continue
        label = re.sub(r'^Озвучка\s+', '', label).strip()
        if label == 'Дублированная':
            label = 'Дублированный'
        season = params.get('season', ['1'])[0]
        if not re.fullmatch(r'[1-9]\d{0,3}', season) or not label:
            continue
        number = int(number)
        episodes = translations.setdefault(translation, (label, {}))[1]
        episodes.setdefault((int(season), number), {'number': number, 'season': int(season), 'url': target})
    dubs = []
    for translation, (label, entries) in translations.items():
        episodes = [entries[key] for key in sorted(entries)]
        dubs.append(choice(label, episodes[0]['url'], identity='alloha:'+translation,
                           player='Alloha', episodes=episodes))
    selected = next((v for v in dubs if any(e['url'] == dub_url for e in v['episodes'])), None) if dub_url else None
    if dub_url and not selected:
        raise SourceError('Выбранная озвучка больше не опубликована в YummyAnime.')
    return {'provider': PROVIDER, 'providerName': 'YummyAnime', 'url': final, 'ids': ids,
            'title': heading.get_text(' ', strip=True), 'dubs': dubs,
            'episodes': selected['episodes'] if selected else [], 'seasons': [],
            'releases': [], 'complete': True}


def discover_reze():
    result = {'provider': PROVIDER, 'name': 'YummyAnime', 'complete': True, 'sources': []}
    http = PublicHttp(timeout=(4, 8))
    try:
        source = inspect(REZE_PAGE, http)
        if source['ids'].get('mal') != 57555:
            raise SourceError('YummyAnime не подтвердил ID фильма.')
        source['matchEvidence'] = 'external_id'
        return {**result, 'status': 'ok' if source['dubs'] else 'no_players', 'sources': [source]}
    except SourceError as error:
        return {**result, 'status': 'unavailable', 'complete': False, 'message': str(error)}
    finally:
        http.close()
