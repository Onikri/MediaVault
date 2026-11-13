#!/usr/bin/env python3
"""Build a provenance-aware, static manga tag vocabulary for MediaVault.

Only public, bounded taxonomy endpoints or one public HTML catalogue per
registered source. No credentials, pagination crawling, anti-bot workarounds,
reader image downloads or arbitrary URL injection. Outputs one static JSON.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from manga_source_coverage import SOURCES
from manga_source_tags import clean_label
from manga_catalog_index import tag_key

OUTPUT = ROOT / 'public' / 'data' / 'manga-tags.json'
UA = 'MediaVault-Taxonomy/1.0 (+https://github.com/Onikri/MediaVault)'
TIMEOUT = (4, 10)
MAX_HTML_BYTES = 1_500_000
MAX_TAGS_PER_SOURCE = 1500
MAX_LABEL_LENGTH = 120
MAX_TOTAL_TAGS = 15000

# Site catalogue routes; these are not invented API endpoints. A host is
# allowed to redirect only to itself or one explicitly permitted mirror.
HTML = {
    'hentaichan.live': ('https://x17.h-chan.me/', {'x17.h-chan.me', 'xxl.hentaichan.live'}),
    'h-chan.me': ('https://manga.h-chan.me/', {'manga.h-chan.me'}),
    'manga-chan.me': ('https://manga-chan.me/catalog', {'manga-chan.me', 'im.manga-chan.me'}),
    'henchan.pro': ('https://henchan.pro/', {'henchan.pro'}),
    'hentaichan.cc': ('https://hentaichan.cc/', {'hentaichan.cc'}),
    'y.hentaichan.live': ('https://y.hentaichan.live/', {'y.hentaichan.live'}),
    'yaoi-chan.me': ('https://v18.yaoi-chan.me/catalog', {'v18.yaoi-chan.me'}),
    'hmanga.su': ('https://hmanga.me/', {'hmanga.me'}),
    'hentaros.com': ('https://hentaros.com/', {'hentaros.com'}),
    'online.hentaimoody.com': ('https://online.hentaimoody.com/', {'online.hentaimoody.com'}),
    'nude-moon.org': ('https://nude-moon.org/', {'nude-moon.org'}),
    '20.allhen.online': ('https://20.allhen.online/', {'20.allhen.online'}),
    'remanga.org': ('https://remanga.org/', {'remanga.org'}),
}
LIB = {'mangalib.org': (1, 'https://mangalib.me/'),
       'hentailib.me': (4, 'https://hentailib.me/'),
       'v2.shlib.life': (2, 'https://v2.shlib.life/')}

# Taxonomy terms categorizing sexual content depicting minors are never
# published into the static public autocomplete index.
MINOR_SEXUAL = re.compile(
    r'(?:\b(?:lolicon|shotacon|loli|shota|underage|child[ -]?porn|preteen)\b'
    r'|(?:детское\s*порно|малолет(?:к|ние)|несовершеннолетн))', re.I
)
TAXONOMY_PATH = re.compile(
    r'/(?:tags?|genres?|categories?)(?:/|$)|[?&](?:tag|genre|category)=', re.I
)
TAGS_SELECTOR = ','.join((
    'a[href*="/tag"]','a[href*="/genre"]','a[href*="/categor"]',
    'a[href*="tag="]','a[href*="genre="]',
    '.tags a[href]','.tag-list a[href]','.genres a[href]',
    '.genre-list a[href]','.manga-tags a[href]','a[rel="tag"]',
))


def clean(value):
    label = clean_label(value)
    if not label or len(label) > MAX_LABEL_LENGTH or MINOR_SEXUAL.search(label):
        return ''
    return label


def timezone_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')


def host(url):
    p = urlsplit(url)
    return p.hostname if p.scheme == 'https' and not p.username and not p.password else None


def checked_get(session, url, hosts, *, limit=MAX_HTML_BYTES):
    """Follow at most two same-trust HTTPS redirects; bound the response size."""
    current = url
    for _ in range(3):
        if host(current) not in hosts:
            raise ValueError('unexpected redirect host')
        with session.get(current, headers={'User-Agent': UA}, timeout=TIMEOUT,
                         allow_redirects=False, stream=True) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    raise ValueError('empty redirect')
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            chunks = bytearray()
            for part in response.iter_content(chunk_size=64 * 1024):
                chunks.extend(part)
                if len(chunks) > limit:
                    raise ValueError('response too large')
            return bytes(chunks), current
    raise ValueError('too many redirects')


def allowed_by_robots(session, url, hosts):
    base = urlsplit(url)
    robots_url = base.scheme + '://' + base.netloc + '/robots.txt'
    try:
        raw, _ = checked_get(session, robots_url, hosts, limit=100_000)
        parser = RobotFileParser()
        parser.parse(raw.decode('utf-8', errors='replace').splitlines())
        return parser.can_fetch(UA, url)
    except requests.HTTPError as error:
        # A 404 robots file means the server has no published robots rules.
        return getattr(error.response, 'status_code', None) == 404
    except (requests.RequestException, ValueError):
        # A temporary failure should not turn into aggressive crawling.
        return False


def parse_html_taxonomy(data, page_url, permitted_hosts):
    soup = BeautifulSoup(data, 'html.parser')
    collected = {}
    for node in soup.select(TAGS_SELECTOR)[:4000]:
        href = node.get('href', '')
        target = urljoin(page_url, href)
        if host(target) not in permitted_hosts:
            continue
        classes = ' '.join(node.get('class', [])) + ' ' + (
            ' '.join(node.parent.get('class', [])) if node.parent else '')
        if not TAXONOMY_PATH.search(target) and not re.search(r'\b(?:tags?|genres?)\b', classes, re.I):
            continue
        label = clean(node.get_text(' ', strip=True))
        if not label:
            continue
        key = tag_key(label)
        category = 'genre' if 'genre' in target.casefold() or 'genre' in classes.casefold() else 'tag'
        collected[(category, key, label.casefold())] = (category, label)
        if len(collected) >= MAX_TAGS_PER_SOURCE:
            break
    return list(collected.values())


def parse_lib_taxonomy(raw, site_id=None):
    data = json.loads(raw)
    payload = data.get('data', data) if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return [], False
    # Only fields explicitly present in a catalogue taxonomy response.
    seen = []
    discovered_field = False
    for field, category in [('genres', 'genre'), ('tags', 'tag')]:
        rows = payload.get(field)
        if not isinstance(rows, list):
            continue
        discovered_field = True
        for row in rows[:MAX_TAGS_PER_SOURCE]:
            if isinstance(row, dict) and site_id is not None and isinstance(row.get('site_ids'), list) and site_id not in row['site_ids']:
                continue
            if isinstance(row, str):
                names = [row]
            elif isinstance(row, dict):
                value = row.get('name') or row.get('label') or row.get('title')
                if isinstance(value, str):
                    names = [value]
                elif isinstance(value, dict):
                    names = [v for v in value.values() if isinstance(v, str)]
                else:
                    names = []
            else:
                names = []
            for text in names:
                if label := clean(text):
                    seen.append((category, label))
    return seen[:MAX_TAGS_PER_SOURCE], discovered_field


def source_tags(session, domain):
    """Return tags, state and reason. An HTML listing is always partial."""
    if domain in LIB:
        site_id, referer = LIB[domain]
        url = 'https://api.cdnlibs.org/api/constants?fields%5B%5D=genres&fields%5B%5D=tags'
        permitted = {'api.cdnlibs.org'}
        if not allowed_by_robots(session, url, permitted):
            return [], 'unavailable', 'robots_or_network'
        with requests.Session() as lib_session:
            lib_session.headers.update({'Site-Id': str(site_id), 'Referer': referer,
                                        'Accept': 'application/json', 'User-Agent': UA})
            try:
                raw, _ = checked_get(lib_session, url, permitted)
                values, explicit = parse_lib_taxonomy(raw, site_id=site_id)
            except (requests.RequestException, ValueError, json.JSONDecodeError):
                return [], 'unavailable', 'public_api_unavailable'
        return values, ('complete' if explicit else 'unavailable'), (
            'explicit_public_taxonomy' if explicit else 'taxonomy_not_provided')
    if domain not in HTML:
        return [], 'unavailable', 'not_configured'
    url, permitted = HTML[domain]
    if not allowed_by_robots(session, url, permitted):
        return [], 'unavailable', 'robots_or_network'
    try:
        raw, final = checked_get(session, url, permitted)
        values = parse_html_taxonomy(raw, final, permitted)
    except (requests.RequestException, ValueError):
        return [], 'unavailable', 'public_catalogue_unavailable'
    return values, ('partial' if values else 'unavailable'), (
        'one_public_catalogue_page' if values else 'no_public_tags_found')


def previous_snapshot(path):
    try:
        data = json.loads(path.read_text('utf-8'))
        if data.get('schemaVersion') == 1 and isinstance(data.get('tags'), list):
            return data
    except (OSError, ValueError):
        pass
    return {'sources': [], 'tags': []}


def build(session, old=None, *, now=None, pause=0.6):
    old = old or {'sources': [], 'tags': []}
    old_source = {s.get('domain'): s for s in old.get('sources', []) if isinstance(s, dict)}
    old_tags = {}
    for item in old.get('tags', []):
        for domain in item.get('sources', []):
            if isinstance(domain, str):
                for label in item.get('originalLabels', [])[:10]:
                    name = clean(label)
                    if name:
                        old_tags.setdefault(domain, []).append((item.get('category', 'tag'), name))
    collected = {}
    states = []
    for domain, display_name, integration, _, _, note in SOURCES:
        if integration == 'closed':
            values, state, reason = [], 'closed', 'site_closed'
        else:
            try:
                values, state, reason = source_tags(session, domain)
            except Exception:
                values, state, reason = [], 'unavailable', 'unexpected_source_error'
        if state == 'unavailable' and domain in old_source and old_tags.get(domain):
            values = old_tags[domain]
            state, reason = 'stale', reason
        # Only the vocabulary is retained; do not retain page or title data.
        actual = 0
        for category, name in values[:MAX_TAGS_PER_SOURCE]:
            if category not in {'tag','genre'} or not (label := clean(name)):
                continue
            key = tag_key(label)
            token = (category, key)
            entry = collected.setdefault(token, {'key': key, 'category': category,
                                                  'label': label, 'originalLabels': set(),
                                                  'sources': set()})
            entry['originalLabels'].add(label)
            entry['sources'].add(domain)
            actual += 1
            if len(collected) > MAX_TOTAL_TAGS:
                raise ValueError('global taxonomy limit reached')
        states.append({'domain': domain, 'name': display_name, 'integration': integration,
                       'status': state, 'tagsFound': actual, 'reason': reason, 'note': note})
        if pause:
            time.sleep(pause)
    result = [{'key': v['key'], 'category': v['category'], 'label': min(v['originalLabels'], key=lambda x:(len(x), x)),
               'originalLabels': sorted(v['originalLabels'], key=str.casefold),
               'sources': sorted(v['sources'])}
              for v in collected.values()]
    result.sort(key=lambda x:(x['category'], x['key']))
    return {'schemaVersion': 1, 'generatedAt': now or timezone_now(),
            'scope': 'public_taxonomy_only', 'coverageGuaranteed': False,
            'sources': states, 'tags': result}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--no-network', action='store_true', help='schema-only bootstrap for tests')
    args = parser.parse_args(argv)
    old = previous_snapshot(args.output)
    with requests.Session() as session:
        if args.no_network:
            snapshot = build(_Offline(), old, pause=0)
        else:
            snapshot = build(session, old)
    # Repeated, identical no-op runs should not create commits.
    if not snapshot['tags'] and old.get('tags') and not args.no_network:
        raise RuntimeError('No tags could be generated; refusing to erase the prior manifest')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Sources: {len(snapshot['sources'])}; indexed tag keys: {len(snapshot['tags'])}")
    for item in snapshot['sources']:
        print(f"{item['domain']}: {item['status']} / {item['tagsFound']} tags ({item['reason']})")
    return 0


class _Offline:
    def get(self, *_args, **_kwargs):
        raise requests.RequestException('offline test mode')


if __name__ == '__main__':
    raise SystemExit(main())
