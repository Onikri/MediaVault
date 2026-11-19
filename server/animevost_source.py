"""Read the AnimeVost episode list and its published HTTP video links."""

import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from source_parser import Page, SourceError, episode_number, playback_headers, public_url

HOSTS = ('animevost.org', 'v14.vost.pw')
MEDIA_HOSTS = {'std.miskuzi.link': 480, 'hd.miskuzi.link': 720}
SELECTOR = 'mv_animevost_id'
TITLE_PATH = re.compile(r'/(?:[a-z0-9_-]+/)*[1-9]\d{0,9}-[a-z0-9_-]+\.html', re.I)
PLAYLIST = re.compile(r'\bvar\s+data\s*=\s*(\{[^{}]{1,300000}\})\s*;')


def is_title_page(url):
    parts = urlsplit(url)
    return parts.hostname in HOSTS and bool(TITLE_PATH.fullmatch(parts.path))


def published_episodes(text, url):
    if not is_title_page(url):
        return {}
    parts = urlsplit(url)
    for match in PLAYLIST.finditer(text):
        try:
            data = json.loads(re.sub(r',\s*}$', '}', match[1]))
        except ValueError:
            continue
        rows = {}
        for label, identity in data.items():
            number = episode_number(label)
            if number is None or not isinstance(identity, str) or not re.fullmatch(r'\d{1,12}', identity):
                continue
            episode_url = urlunsplit(parts._replace(query=urlencode({SELECTOR: identity}), fragment=''))
            rows.setdefault(identity, {'number': number, 'title': label[:180], 'url': episode_url, 'season': 1})
        if rows:
            return dict(sorted(rows.items(), key=lambda entry: entry[1]['number']))
    return {}


def episode_list(text, url):
    return list(published_episodes(text, url).values())


def resolve(url, http):
    parts = urlsplit(url)
    selected = [value for key, value in parse_qsl(parts.query, keep_blank_values=True) if key == SELECTOR]
    if len(selected) > 1 or selected and not re.fullmatch(r'\d{1,12}', selected[0]):
        raise SourceError('Некорректный номер серии AnimeVost.')
    base = urlunsplit(parts._replace(query='', fragment=''))
    text, final, _ = http.document(base)
    published = published_episodes(text, final)
    identity = selected[0] if selected else next(iter(published), None)
    if identity not in published:
        raise SourceError('Выбранная серия больше не опубликована на AnimeVost.')
    endpoint = urljoin(final, '/frame2.php?' + urlencode({'play': identity}))
    markup, returned, _ = http.document(endpoint, headers={'Referer': final})
    iframe = BeautifulSoup(markup, 'html.parser').select_one('iframe[src]')
    if iframe is None or returned != endpoint:
        raise SourceError('AnimeVost не опубликовал плеер выбранной серии.')
    embed = urljoin(returned, iframe['src'])
    if embed != urljoin(final, '/frame5.php?' + urlencode({'play': identity})):
        raise SourceError('AnimeVost вернул плеер другой серии.')
    payload, returned, _ = http.document(embed, headers={'Referer': endpoint})
    if returned != embed:
        raise SourceError('AnimeVost перенаправил плеер на другую страницу.')
    streams = {}
    headers = playback_headers({'Referer': embed})
    for link in BeautifulSoup(payload, 'html.parser').select('a[download][href]'):
        try:
            target = urljoin(embed, link['href'])
            parts = urlsplit(target)
            quality = MEDIA_HOSTS.get(parts.hostname)
            if not quality or not parts.path.lower().endswith('.mp4'):
                continue
            target = public_url(target, resolve_dns=False)
        except (ValueError, SourceError):
            continue
        streams[target] = {'url': target, 'type': 'mp4', 'quality': quality, 'headers': headers}
    if not streams:
        raise SourceError('AnimeVost не вернул открытое видео выбранной серии.')
    return Page(title=published[identity]['title'], streams=list(streams.values()), episodes=list(published.values()))
