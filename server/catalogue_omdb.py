"""Bulk title metadata from omdb.org's CC BY 2.0 Germany CSV exports."""

import bz2
import csv
import io
import os
import re
import threading
import time
from bisect import bisect_right
from datetime import date
from functools import lru_cache
from pathlib import Path

import requests

ROOT = 'https://www.omdb.org'
PAGE_SIZE = 100  # content_catalog.ingest accepts at most 100 rows per write
MAX_EXPORT = 32 * 1024 * 1024
LANGUAGES = {'en', 'ru', 'uk', 'ja', 'ko', 'zh'}
EXPORTS = ('all_movies', 'all_series', 'all_movie_aliases_iso', 'movie_links',
           'all_categories', 'category_names', 'movie_categories')
_snapshot_lock = threading.Lock()


def decoded_csv(packed):
    with bz2.BZ2File(packed) as data, io.TextIOWrapper(data, encoding='utf-8-sig', newline='') as text:
        yield from csv.DictReader(text)


def csv_rows(name):
    with requests.get(f'{ROOT}/data/{name}.csv.bz2', stream=True, timeout=(12, 30),
                      headers={'User-Agent': 'MediaVault-Catalogue/1.0'}) as response:
        response.raise_for_status()
        packed = io.BytesIO()
        for chunk in response.iter_content(65536):
            packed.write(chunk)
            if packed.tell() > MAX_EXPORT:
                raise ValueError('OMDB export exceeded the download limit')
    packed.seek(0)
    yield from decoded_csv(packed)


def load_snapshot(read_csv=csv_rows):
    kinds = {}
    titles = {}
    today = date.today()
    for kind, filename in (('movie', 'all_movies'), ('tv', 'all_series')):
        kind_ids = []
        for record in read_csv(filename):
            if not re.fullmatch(r'[1-9]\d{0,10}', record['id']):
                continue
            identity = int(record['id'])
            name = record['name'].strip()
            if identity in titles or not 0 < len(name) <= 500:
                continue
            year = re.match(r'^([1-9]\d{3})(?:-|$)', record['date'])
            titles[identity] = {
                'id': f'omdb:{identity}', 'provider': 'omdb', 'providerId': str(identity),
                'kind': kind, 'title': name, 'titles': {'native': name}, 'aliases': [],
                'year': int(year[1]) if year else None, 'genres': [], 'tags': [], 'ids': {},
                'sourceUrl': f'{ROOT}/movie/{identity}',
            }
            if year:
                titles[identity]['startDate'] = record['date']
            if kind=='movie':
                try:release_day=date.fromisoformat(record['date'])
                except ValueError:pass
                else:titles[identity]['status']='anons' if release_day>today else 'released'
            kind_ids.append(identity)
        if not kind_ids:
            raise ValueError(f'Empty OMDB {kind} export')
        kinds[kind] = sorted(kind_ids)

    for record in read_csv('all_movie_aliases_iso'):
        language, name = record['language_iso_639_1'], record['name'].strip()
        row = titles.get(int(record['movie_id']))
        if not row or language not in LANGUAGES or not 0 < len(name) <= 120:
            continue
        if name not in row['aliases'] and len(row['aliases']) < 80:
            row['aliases'].append(name)
        if language in {'ru', 'uk', 'en'} and record['official_translation'] == '1':
            row['titles'].setdefault(language, name)
    for row in titles.values():
        row['title'] = row['titles'].get('ru') or row['title']

    for record in read_csv('movie_links'):
        source, key = record['source'], record['key']
        if source == 'imdbmovie' and re.fullmatch(r'tt\d{7,12}', key):
            id_kind = 'imdb'
        elif source == 'wikidata' and re.fullmatch(r'Q[1-9]\d*', key):
            id_kind = 'wikidata'
        else:
            continue
        row = titles.get(int(record['movie_id']))
        if row:
            row['ids'].setdefault(id_kind, key)

    # OMDB uses separate category trees for genres (1) and keywords (8).
    by_category = {record['id']: record for record in read_csv('all_categories')
                   if record['root_id'] in {'1', '8'} and record['id'] != record['root_id']}
    labels = {}
    for record in read_csv('category_names'):
        if record['category_id'] in by_category and record['language_iso_639_1'] in {'ru', 'en'}:
            labels.setdefault(record['category_id'], {}).setdefault(record['language_iso_639_1'], record['name'])
    for record in read_csv('movie_categories'):
        row = titles.get(int(record['movie_id']))
        category = by_category.get(record['category_id'])
        if not row or not category:
            continue
        is_genre = category['root_id'] == '1'
        field = 'genres' if is_genre else 'tags'
        visited = set()
        while category and category['id'] not in visited:
            key = category['id']
            visited.add(key)
            names = labels.get(key, {})
            name = (names.get('en') or names.get('ru')) if is_genre else (names.get('ru') or names.get('en'))
            if name and name not in row[field] and len(row[field]) < 120:
                row[field].append(name)
            category = by_category.get(category['parent_id']) if is_genre else None
    return kinds, titles


@lru_cache(maxsize=1)
def _daily_snapshot(day):
    folder = Path(os.getenv('DATA_DIR','/data'))/'catalogue-omdb'
    files = {name:folder/(name+'.csv.bz2') for name in EXPORTS}
    local = all(path.is_file() for path in files.values())
    read_local = lambda name: decoded_csv(files[name])
    if local and min(path.stat().st_mtime for path in files.values()) >= time.time()-86400:
        return load_snapshot(read_local)
    try:
        return load_snapshot()
    except requests.RequestException:
        if not local:
            raise
        return load_snapshot(read_local)


def catalogue(kind, cursor, snapshot=None):
    if snapshot is None:
        with _snapshot_lock:
            snapshot = _daily_snapshot(int(time.time()) // 86400)
    kinds, titles = snapshot
    ids = kinds[kind]
    start = bisect_right(ids, int(cursor.get('after', 0)))
    page = ids[start:start + PAGE_SIZE]
    return {
        'rows': [titles[identity] for identity in page],
        'next': {'after': page[-1]} if start + len(page) < len(ids) else None,
        'total': len(ids),
    }
