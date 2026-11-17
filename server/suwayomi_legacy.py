"""Suwayomi's local numeric IDs, kept as stable source identities after it is gone.

Old MediaVault links name a title as ``/__manga/suwayomi/m/<manga>`` and a
chapter as ``.../c/<index>``: Suwayomi's own database row and the chapter's
source order. Both numbers mean nothing outside that database. An export of it
(``deploy/oracle/export-suwayomi-legacy-map.sh``) keeps, for every title and
chapter Suwayomi ever stored, its source ID, the source's own title/chapter key
and public URL in ``/data/suwayomi-legacy-map.sqlite``.

``resolve`` turns such an old reference into the same title or chapter on
MediaVault's direct reader. It answers the bridge's REST calls from that map
(``MapClient``) and reuses the bridge's own matching rules
(``suwayomi_bridge.native_reader_url``), so a link resolves offline exactly as
it did through the running Suwayomi. A source whose direct adapter is not live
yet keeps its rows in the map and resolves once that adapter is activated.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

from source_parser import SourceError

MAP_NAME = 'suwayomi-legacy-map.sqlite'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, name TEXT NOT NULL, lang TEXT NOT NULL,
  base_url TEXT NOT NULL DEFAULT '', nsfw INTEGER NOT NULL DEFAULT 0, package TEXT NOT NULL DEFAULT '',
  extension TEXT NOT NULL DEFAULT '', exported REAL NOT NULL);
CREATE TABLE IF NOT EXISTS manga(id INTEGER PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL,
  real_url TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', thumbnail_url TEXT NOT NULL DEFAULT '',
  exported REAL NOT NULL);
CREATE INDEX IF NOT EXISTS manga_source ON manga(source);
CREATE TABLE IF NOT EXISTS chapters(manga INTEGER NOT NULL, idx INTEGER NOT NULL, id INTEGER NOT NULL,
  url TEXT NOT NULL, real_url TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', number REAL,
  scanlator TEXT NOT NULL DEFAULT '', page_count INTEGER, exported REAL NOT NULL, PRIMARY KEY(manga, idx));
'''
REFERENCE = re.compile(r'/__manga/suwayomi/m/([1-9]\d{0,9})(?:/c/([1-9]\d{0,6}))?(?:/p/(\d{1,4}))?$')
_cache = {}
_lock = threading.Lock()
CACHE_SIZE = 4096


def map_path():
    return Path(os.getenv('DATA_DIR', '/data')) / MAP_NAME


def _open(path=None):
    path = Path(path or map_path())
    if not path.is_file():
        return None
    try:
        return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    except (OSError, ValueError, sqlite3.Error):
        return None


def _empty(value):
    return None if value in (None, '') else value


def build(export_dir, sources_json=None, path=None, now=None):
    """Merge one H2 CSV export into the map. Rows are only added or refreshed.

    A title or chapter that a later Suwayomi export no longer has keeps its row:
    an old link to it stays resolvable.
    """
    export_dir = Path(export_dir)
    path = Path(path or map_path())
    now = time.time() if now is None else now
    csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)
    online = {}
    if sources_json:
        for row in json.loads(Path(sources_json).read_text(encoding='utf-8')):
            online[str(row['id'])] = row
    counts = {}
    with closing(sqlite3.connect(path, timeout=30)) as db:
        db.executescript(SCHEMA)
        with db:
            n = 0
            with open(export_dir / 'source.csv', encoding='utf-8', newline='') as handle:
                for row in csv.DictReader(handle):
                    sid = row['ID']
                    if sid == '0':
                        continue
                    live = online.get(sid, {})
                    db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?)', (
                        sid, row['NAME'] or live.get('name') or '', row['LANG'] or live.get('lang') or '',
                        live.get('baseUrl') or '', int(bool(live.get('isNsfw'))), row.get('PKG_NAME') or '',
                        row.get('EXT_NAME') or '', now))
                    n += 1
            counts['sources'] = n
            n = 0
            with open(export_dir / 'manga.csv', encoding='utf-8', newline='') as handle:
                for row in csv.DictReader(handle):
                    db.execute('INSERT OR REPLACE INTO manga VALUES (?,?,?,?,?,?,?)', (
                        int(row['ID']), row['SOURCE'], row['URL'] or '', row['REAL_URL'] or '', row['TITLE'] or '',
                        row['THUMBNAIL_URL'] or '', now))
                    n += 1
            counts['manga'] = n
            n = 0
            with open(export_dir / 'chapter.csv', encoding='utf-8', newline='') as handle:
                for row in csv.DictReader(handle):
                    number = _empty(row['CHAPTER_NUMBER'])
                    pages = _empty(row['PAGE_COUNT'])
                    db.execute('INSERT OR REPLACE INTO chapters VALUES (?,?,?,?,?,?,?,?,?,?)', (
                        int(row['MANGA']), int(row['SOURCE_ORDER']), int(row['ID']), row['URL'] or '',
                        row['REAL_URL'] or '', row['NAME'] or '', float(number) if number is not None else None,
                        row['SCANLATOR'] or '', int(pages) if pages is not None else None, now))
                    n += 1
            counts['chapters'] = n
            exports = json.loads((db.execute("SELECT value FROM meta WHERE key='exports'").fetchone() or ['[]'])[0])
            exports.append({'at': now, **counts})
            db.execute("INSERT OR REPLACE INTO meta VALUES ('exports', ?)", (json.dumps(exports),))
            for table in ('sources', 'manga', 'chapters'):
                counts['total_' + table] = db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    path.chmod(0o600)
    return counts


class MapClient:
    """Answers the bridge's read-only REST calls from the exported map."""

    def __init__(self, db):
        self.db = db

    def close(self):
        pass

    def source(self, sid):
        row = self.db.execute('SELECT id,name,lang,base_url,nsfw FROM sources WHERE id=?', (str(sid),)).fetchone()
        if not row:
            raise SourceError('Источник этой сохранённой ссылки неизвестен.')
        return {'id': row[0], 'name': row[1], 'lang': row[2], 'baseUrl': row[3] or None, 'isNsfw': bool(row[4])}

    def manga(self, manga):
        row = self.db.execute('SELECT id,source,url,real_url,title,thumbnail_url FROM manga WHERE id=?', (manga,)).fetchone()
        if not row:
            raise SourceError('Сохранённый тайтл отсутствует в карте старых ссылок.')
        return {'id': row[0], 'sourceId': row[1], 'url': row[2], 'realUrl': row[3] or None, 'title': row[4],
                'thumbnailUrl': row[5] or None, 'source': self.source(row[1])}

    def chapters(self, manga):
        return [{'index': idx, 'id': cid, 'url': url, 'realUrl': real or None, 'name': name, 'chapterNumber': number,
                 'scanlator': scanlator or None, 'pageCount': pages}
                for idx, cid, url, real, name, number, scanlator, pages in self.db.execute(
                    'SELECT idx,id,url,real_url,name,number,scanlator,page_count FROM chapters WHERE manga=? ORDER BY idx DESC',
                    (manga,))]

    def get(self, path, params=None, timeout=None, image=False, body=None):
        if image or body is not None:
            raise SourceError('Старая ссылка открывается только через прямой источник.')
        if match := re.fullmatch(r'/manga/(\d+)', path):
            return self.manga(int(match[1]))
        if match := re.fullmatch(r'/manga/(\d+)/chapters', path):
            return self.chapters(int(match[1]))
        if match := re.fullmatch(r'/source/(\d+)', path):
            return self.source(match[1])
        raise SourceError('Старая ссылка открывается только через прямой источник.')


def lookup(manga, chapter=None, path=None):
    """(title, chapter row or None) of an old reference, or None when unknown."""
    db = _open(path)
    if db is None:
        return None
    with closing(db):
        client = MapClient(db)
        try:
            data = client.manga(int(manga))
        except (SourceError, sqlite3.Error):
            return None
        row = None
        if chapter is not None:
            row = db.execute('SELECT idx,id,url,real_url,name,number FROM chapters WHERE manga=? AND idx=?',
                             (int(manga), int(chapter))).fetchone()
            if row is None:
                return None
        return data, row


def known(manga, chapter=None):
    return lookup(manga, chapter) is not None


def explain(manga, chapter=None, path=None):
    """(direct reader URL or None, reason). Reasons: ok, unknown-title,
    unknown-chapter, no-direct-reader, unmatched."""
    db = _open(path)
    if db is None:
        return None, 'no-map'
    with closing(db):
        client = MapClient(db)
        try:
            data = client.manga(int(manga))
        except SourceError:
            return None, 'unknown-title'
        if chapter is not None and not db.execute('SELECT 1 FROM chapters WHERE manga=? AND idx=?',
                                                  (int(manga), int(chapter))).fetchone():
            return None, 'unknown-chapter'
        from suwayomi_bridge import native_reader_url
        try:
            target = native_reader_url(client, data, data['source'], int(manga), chapter)
        except SourceError:
            return None, 'unmatched'
        if not target:
            return None, 'no-direct-reader'
        from manga_sources import site_for
        site = site_for(target)
        if site is None or site.family == 'suwayomi':
            return None, 'no-direct-reader'
        return target, 'ok'


def _comparable(url):
    from urllib.parse import parse_qsl, urlencode, urlsplit

    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k == 'mv_manga_source']
    path = re.sub(r'(?<=\d)\.0+(?=$|/)', '', parts.path.rstrip('/'))
    return (parts.hostname or '', path, urlencode(query))


def episode_url(target, episodes, number=None):
    """The direct reader's own episode URL for a resolved chapter.

    Reading progress is keyed by the exact episode URL the reader lists; the
    stored chapter link can differ in a trailing slash, a ``.0`` or tracking
    parameters (``cid``, ``mv_chapter``) the reader adds. Only a single,
    unambiguous episode is accepted.
    """
    urls = [e.get('url') for e in episodes if isinstance(e, dict) and isinstance(e.get('url'), str)]
    if target in urls:
        return target
    wanted = _comparable(target)
    same = [u for u in urls if _comparable(u) == wanted]
    if len(same) == 1:
        return same[0]
    if number is not None and number >= 0:
        numbered = [e['url'] for e in episodes if isinstance(e, dict) and e.get('number') == number
                    and _comparable(e.get('url', ''))[0] == wanted[0]]
        if len(numbered) == 1:
            return numbered[0]
    return None


def resolve(manga, chapter=None):
    """Direct reader URL of an old Suwayomi title/chapter reference, or None."""
    key = (int(manga), None if chapter is None else int(chapter))
    path = map_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    target, reason = explain(*key, path=path)
    if reason == 'unmatched':
        return None  # may be a passing network failure: try again next time
    with _lock:
        if len(_cache) >= CACHE_SIZE:
            _cache.clear()
        _cache[key] = (stamp, target)
    return target


def parse(value, root=None):
    """(manga, chapter, page) of an old reference on this MediaVault, or None."""
    from urllib.parse import urlsplit

    root = urlsplit(root if root is not None else os.getenv('PUBLIC_URL', ''))
    try:
        url = urlsplit(value)
    except (TypeError, ValueError):
        return None
    if (url.scheme, url.netloc) != (root.scheme, root.netloc) or not root.netloc or url.query or url.fragment:
        return None
    prefix = root.path.rstrip('/')
    if not url.path.startswith(prefix + '/__manga/suwayomi/'):
        return None
    match = REFERENCE.fullmatch(url.path[len(prefix):])
    if not match:
        return None
    return tuple(int(v) if v is not None else None for v in match.groups())


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description='Build the Suwayomi legacy ID map from an H2 CSV export.')
    parser.add_argument('command', choices=['build', 'stats', 'resolve'])
    parser.add_argument('--export', help='directory with manga.csv, chapter.csv and source.csv')
    parser.add_argument('--sources', help='JSON of /source/list (base URLs)')
    parser.add_argument('--map', help='map path (default $DATA_DIR/' + MAP_NAME + ')')
    parser.add_argument('reference', nargs='*')
    args = parser.parse_args(argv)
    if args.command == 'build':
        print(json.dumps(build(args.export, args.sources, args.map), ensure_ascii=False))
    elif args.command == 'stats':
        with closing(sqlite3.connect(Path(args.map or map_path()).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            print(json.dumps({t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('sources', 'manga', 'chapters')}
                             | {'exports': json.loads(db.execute("SELECT value FROM meta WHERE key='exports'").fetchone()[0])}))
    else:
        for value in args.reference:
            ids = parse(value) or tuple(int(v) for v in value.split('/'))
            print(value, *explain(ids[0], ids[1] if len(ids) > 1 else None, path=args.map))


if __name__ == '__main__':
    main()
