"""Dispatch migrated Suwayomi IDs to native catalogue and reader adapters."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urljoin, urlsplit

import manga_mangashi
import manga_mangahub
from source_parser import PublicHttp, SourceError


ADAPTERS = {adapter.SOURCE_ID: adapter for adapter in (manga_mangashi, *manga_mangahub.SOURCES)}
HOSTS = {urlsplit(adapter.ROOT).hostname: adapter for adapter in ADAPTERS.values()}


def merge_source_list(installed):
    sources = {str(row['id']): row for row in installed}
    for sid, adapter in ADAPTERS.items():
        sources.setdefault(sid, {
            'id': sid, 'name': adapter.NAME, 'lang': adapter.LANGUAGE,
            'baseUrl': adapter.ROOT, 'isNsfw': adapter.IS_NSFW,
        })
    return list(sources.values())


def for_source(source):
    return ADAPTERS.get(str(source.get('id', '')))


def for_url(url):
    return HOSTS.get(urlsplit(url).hostname)


def search(adapter, source, query):
    from manga_discovery import query_matches
    from title_identity import match_title

    selected = source.get('_title') or source.get('_alias_title')
    http = PublicHttp(timeout=(3, 7), deadline=time.monotonic() + 18)
    try:
        for term in source.get('_queries', [query]):
            rows, _ = adapter.catalogue(http, query=term)
            found = []
            for row in rows:
                if selected:
                    if not match_title(selected, row)[0]:
                        continue
                    row['aliases'] = list(dict.fromkeys([*row['aliases'], selected['title']]))
                elif not query_matches(term, row['aliases']):
                    continue
                found.append(row)
            if found:
                return found
        return []
    finally:
        http.close()


def catalogue_job(adapter, spec, page):
    from manga_source_tags import unique

    http = PublicHttp(timeout=(3, 12), deadline=time.monotonic() + 22)
    try:
        if spec['type'] == 'bridge-vocabulary':
            return {'rows': [], 'next': None, 'vocabulary': adapter.vocabulary(http)}
        if spec['type'] == 'bridge-detail':
            stored = spec['row']
            url = stored.get('sourceUrl') or stored['url']
            found = adapter.details(http, url)
            for field in ('genres', 'tags'):
                found[field] = unique([*found[field], *(stored.get(field) or [])])
            return {'rows': [{**stored, **found, 'metadataInspected': True}], 'next': None}
        term = spec.get('term')
        tag = term['sourceId'] if term else ''
        if isinstance(tag, dict):
            # A queued Suwayomi job used a mutable filter position. Recover the
            # stable upstream filter by exact label without changing its cursor.
            label = term['label'].casefold()
            options = {v['sourceId'] for v in adapter.vocabulary(http) if v['label'].casefold() == label}
            if len(options) != 1:
                raise SourceError('Сохранённый фильтр больше не совпадает со справочником источника.')
            tag = options.pop()
        rows, more = adapter.catalogue(http, page=page, tag=tag)
        if page == 1 and not rows and not term:
            raise SourceError('Адаптер вернул пустую первую страницу каталога')
        details = []
        for row in rows:
            if term:
                field = 'genres' if term['category'] == 'genre' else 'tags'
                row[field] = [term['label']]
            details.append({
                **{key: value for key, value in spec.items() if key != 'term'},
                'type': 'bridge-detail', 'url': row['url'], 'row': row,
            })
        return {'rows': rows, 'next': {'page': page + 1} if more else None, 'details': details}
    finally:
        http.close()


def saved_reader_url(adapter, client, source, canonical, manga, chapter):
    root = source.get('baseUrl') or adapter.ROOT
    title = adapter.site_link(canonical, root)
    title_path = adapter.TITLE_PATH.fullmatch(urlsplit(title).path)
    if not title_path or for_url(root) is not adapter:
        return None
    if chapter is None:
        return title
    chapters = client.get(f'/manga/{manga}/chapters', {'onlineFetch': 'false'}, timeout=8)
    for row in chapters:
        if row.get('index') == chapter:
            target = adapter.saved_chapter_url(row.get('realUrl') or row.get('url'), title_path[1], root)
            path = adapter.CHAPTER_PATH.fullmatch(urlsplit(target).path)
            if path and path[1] == title_path[1]:
                return target
            break
    raise SourceError('Не удалось сопоставить сохранённую главу с исходной читалкой.')


def legacy_links_path():
    return Path(os.getenv('DATA_DIR', '/data')) / 'manga-native-links.sqlite'


def recorded_reader_url(manga, chapter):
    path = legacy_links_path()
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            row = db.execute('SELECT source, url FROM links WHERE manga=? AND chapter=?', (manga, chapter or 0)).fetchone()
    except (OSError, ValueError, sqlite3.Error):
        return None
    if row:
        adapter = ADAPTERS.get(row[0])
        if adapter is not None and adapter is for_url(row[1]):
            pattern = adapter.CHAPTER_PATH if chapter is not None else adapter.TITLE_PATH
            if pattern.fullmatch(urlsplit(row[1]).path):
                return adapter.site_link(row[1])
    return None


def record_reader_url(manga, chapter, adapter, target):
    # Source and chapter were resolved by the old bridge and the direct reader
    # opened them successfully. Keep that mapping even if the JVM is offline.
    path = legacy_links_path()
    try:
        with closing(sqlite3.connect(path, timeout=1)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS links (manga INTEGER, chapter INTEGER, source TEXT NOT NULL, url TEXT NOT NULL, PRIMARY KEY(manga,chapter))')
            db.execute('INSERT OR IGNORE INTO links VALUES (?,?,?,?)', (manga, chapter or 0, adapter.SOURCE_ID, target))
        path.chmod(0o600)
    except (OSError, sqlite3.Error):
        # An unavailable migration cache must not interrupt a working reader.
        pass
