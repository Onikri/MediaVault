"""Video whose CDN serves only the viewer's own connection (Collaps).

Collaps answers HTTP 410 to media requested from data-centre addresses, so the
viewer's browser downloads the published HLS segments itself and uploads them
here. The server never contacts the CDN: it validates the two playlists the
browser read, lists the exact resources it will accept, writes local playlists
and remuxes them with the same ffmpeg step as every other import.
"""
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit
import re

import m3u8

from source_parser import SourceError, public_url

COLLAPS_EMBED = re.compile(r'https://api\.(?:nextembed\.ws|delivembd\.ws|namy\.ws|bhcesh\.me)/embed/[a-z]+/\d{1,10}(?:\?[\w=&%.-]{0,300})?')
MAX_SEGMENTS = 20000
MAX_PLAYLIST = 4 * 1024**2
EXTENSIONS = {'.ts', '.m4s', '.mp4', '.aac', '.m4a', '.mp3'}


def browser_only(url):
    return bool(COLLAPS_EMBED.fullmatch(str(url or '')))


def _track(name, value, urls, files):
    base = public_url(str(value.get('url') or ''), resolve_dns=False)
    if urlsplit(base).scheme != 'https':
        raise SourceError('Плейлист серии должен быть по HTTPS.')
    text = str(value.get('text') or '')
    if len(text.encode()) > MAX_PLAYLIST or not text.lstrip().startswith('#EXTM3U'):
        raise SourceError('Браузер передал не плейлист серии.')
    playlist = m3u8.loads(text, uri=base)
    if playlist.is_variant:
        raise SourceError('Нужен плейлист одной дорожки, а не список качеств.')
    if not playlist.is_endlist or not playlist.segments:
        raise SourceError('Нужна законченная серия. Прямые эфиры не сохраняются.')
    if len(playlist.segments) > MAX_SEGMENTS:
        raise SourceError('В серии слишком много сегментов.')
    if playlist.session_keys or any(s.key and s.key.method != 'NONE' for s in playlist.segments):
        raise SourceError('Зашифрованные потоки не сохраняются.')
    # Absolute addresses first: m3u8 shares one init-section object between segments.
    resolved = []
    for segment in playlist.segments:
        if segment.byterange or segment.init_section and segment.init_section.byterange:
            raise SourceError('HLS с диапазонами байтов не поддерживается.')
        resolved.append((urljoin(base, segment.uri),
                         urljoin(base, segment.init_section.uri) if segment.init_section else None))
    maps = {}
    for index, (segment, (address, initialization)) in enumerate(zip(playlist.segments, resolved)):
        if initialization:
            if initialization not in maps:
                maps[initialization] = f'map-{len(maps)}.mp4'
                urls.append(initialization)
                files.append(f'{name}/{maps[initialization]}')
            segment.init_section.uri = maps[initialization]
        extension = PurePosixPath(urlsplit(address).path).suffix.lower()
        if extension not in EXTENSIONS:
            extension = '.m4s' if initialization else '.ts'
        filename = f'segment-{index:06d}{extension}'
        urls.append(address)
        files.append(f'{name}/{filename}')
        segment.uri = filename
    for address in urls:
        if urlsplit(public_url(address, resolve_dns=False)).scheme != 'https':
            raise SourceError('Сегменты серии должны быть по HTTPS.')
    return {'name': name, 'playlist': playlist.dumps()}


def plan(stream):
    """Validated track playlists plus the ordered list of resources to upload."""
    if not isinstance(stream, dict) or not isinstance(stream.get('video'), dict):
        raise SourceError('Браузер не передал плейлист серии.')
    urls, files = [], []
    tracks = [_track('video', stream['video'], urls, files)]
    if stream.get('audio'):
        tracks.append(_track('audio', stream['audio'], urls, files))
    return {'tracks': tracks, 'urls': urls, 'files': files, 'sizes': {}}


def path(directory, staged, index):
    return Path(directory) / staged['files'][index]


def missing(directory, staged):
    return [index for index in range(len(staged['files'])) if not path(directory, staged, index).is_file()]


def write_playlists(directory, staged):
    inputs = []
    for track in staged['tracks']:
        target = Path(directory) / track['name']
        target.mkdir(exist_ok=True)
        manifest = target / 'local.m3u8'
        manifest.write_text(track['playlist'], encoding='utf-8')
        inputs.append(manifest)
    return inputs
