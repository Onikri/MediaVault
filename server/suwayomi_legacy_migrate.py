"""Rewrite stored Suwayomi references to MediaVault's direct readers.

Run against a DATA_DIR (a copy first, then the live one):

    python suwayomi_legacy_migrate.py --data /data            # dry run, report only
    python suwayomi_legacy_migrate.py --data /data --apply    # write

What it changes, idempotently:
* manga catalogue rows (``catalog_titles`` and the search ``titles`` cache in
  manga-discovery.sqlite): an old ``/__manga/suwayomi/m/<id>`` reader link in
  their metadata becomes the same title's direct reader URL. Row IDs, the
  stable ``provider``/``source_url`` key, tags and everything else stay.
* reading places (places.sqlite): a place keyed by an old chapter link gets a
  twin under the direct chapter's key with the same position and time. The old
  place stays, so a device that still has it loses nothing.

What it only reports: import tasks and title shares (sealed in tasks.sqlite;
tasks change only through the running service) and the catalogue indexer's
queued detail jobs. Their old links keep opening through ``suwayomi_legacy``.

A reference whose source has no live direct reader yet stays as it is and is
listed with its reason; a later run converts it once that reader is activated.
Resolution never touches the network: the map and the adapters' URL rules only.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

LINK = r'/__manga/suwayomi/m/[1-9]\d{0,9}(?:/c/[1-9]\d{0,6})?(?:/p/\d{1,4})?'
JS_SAFE = "-_.!~*'()"  # encodeURIComponent keeps these


class Offline(Exception):
    pass


@contextmanager
def offline(report):
    """Adapters may look a title up online; a migration never does."""
    import socket

    import requests
    from source_parser import SourceError

    original, lookup = requests.Session.request, socket.getaddrinfo

    def refuse(*_args, **_kwargs):
        report['network_refused'] = report.get('network_refused', 0) + 1
        raise SourceError('offline migration')

    def unresolvable(*_args, **_kwargs):
        report['network_refused'] = report.get('network_refused', 0) + 1
        raise socket.gaierror('offline migration')

    requests.Session.request, socket.getaddrinfo = refuse, unresolvable
    try:
        yield
    finally:
        requests.Session.request, socket.getaddrinfo = original, lookup


class Resolver:
    def __init__(self, map_path, root, report=None):
        import suwayomi_legacy

        self.legacy = suwayomi_legacy
        self.report = report if report is not None else {}
        self.map_path = map_path
        self.root = root.rstrip('/')
        self.pattern = re.compile(re.escape(self.root) + LINK)
        self.memo = {}
        self.reasons = collections.Counter()
        self.unresolved = collections.Counter()  # (reason, source name)

    def source_name(self, manga):
        found = self.legacy.lookup(manga, path=self.map_path)
        if not found:
            return '?'
        source = found[0]['source']
        return f"{source['name']} ({source['lang']}, {source['id']})"

    def target(self, link):
        """Direct URL for one old link, or (None, reason)."""
        if link in self.memo:
            return self.memo[link]
        ids = self.legacy.parse(link, self.root)
        if not ids:
            result = (None, 'not-a-reference')
        elif ids[2] is not None:
            result = (None, 'page-link')
        else:
            tried = self.report.get('network_refused', 0)
            result = self.legacy.explain(ids[0], ids[1], path=self.map_path)
            if result[0] is None and self.report.get('network_refused', 0) > tried:
                # e.g. a Madara post ID without a stored URL: the reader looks
                # its slug up when the link is opened; a migration does not.
                result = (None, 'needs-online-lookup')
        self.memo[link] = result
        self.reasons[result[1]] += 1
        if result[0] is None and ids:
            self.unresolved[(result[1], self.source_name(ids[0]))] += 1
        return result

    def links(self, text):
        return self.pattern.findall(text)

    def rewrite(self, value):
        """(new value, changed, unresolved reasons) for a JSON value."""
        missing = []
        changed = False

        def walk(item):
            nonlocal changed
            if isinstance(item, str):
                def swap(match):
                    nonlocal changed
                    target, reason = self.target(match[0])
                    if target is None:
                        missing.append(reason)
                        return match[0]
                    changed = True
                    return target
                return self.pattern.sub(swap, item)
            if isinstance(item, list):
                return [walk(v) for v in item]
            if isinstance(item, dict):
                return {k: walk(v) for k, v in item.items()}
            return item

        return walk(value), changed, missing


def bridge_rows(db, table):
    return db.execute(f"SELECT rowid, id, metadata FROM {table} WHERE metadata LIKE '%/\\_\\_manga/suwayomi/m/%' ESCAPE '\\'").fetchall()


def migrate_catalogue(data, resolver, apply, report):
    path = Path(data) / 'manga-discovery.sqlite'
    if not path.is_file():
        report['catalogue'] = {'missing': True}
        return
    with closing(sqlite3.connect(path, timeout=60)) as db:
        for table in ('catalog_titles', 'titles'):
            entry = report.setdefault(table, {})
            entry['rows'] = db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            rows = bridge_rows(db, table)
            entry['with_old_links_before'] = len(rows)
            pending, rewritten, kept = [], 0, collections.Counter()
            for rowid, _identity, raw in rows:
                value = json.loads(raw)
                new, changed, missing = resolver.rewrite(value)
                for reason in missing:
                    kept[reason] += 1
                if changed:
                    rewritten += 1
                    pending.append((json.dumps(new, ensure_ascii=False), rowid))
                if apply and len(pending) >= 400:
                    with db:
                        db.executemany(f'UPDATE {table} SET metadata=? WHERE rowid=?', pending)
                    pending.clear()
            if apply and pending:
                with db:
                    db.executemany(f'UPDATE {table} SET metadata=? WHERE rowid=?', pending)
            entry['rewritten'] = rewritten
            entry['kept_old_links'] = dict(kept)
            entry['rows_after'] = db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            entry['with_old_links_after'] = len(bridge_rows(db, table)) if apply else None
        jobs = report.setdefault('catalogue_jobs', {})
        try:
            from manga_native_sources import for_source
            states = collections.Counter()
            for state, spec in db.execute("SELECT state, spec FROM catalogue_jobs WHERE spec LIKE '%\"manga\":%'"):
                value = json.loads(spec)
                if value.get('type') != 'bridge-detail' or 'manga' not in value:
                    continue
                direct = bool(for_source(value.get('source') or {})) and value.get('route') != 'suwayomi'
                states[(state, 'direct' if direct else 'needs-suwayomi')] += 1
            jobs['bridge_detail'] = {f'{a}/{b}': n for (a, b), n in sorted(states.items())}
        except sqlite3.Error as error:
            jobs['error'] = str(error)
        work = db.execute("SELECT count(*) FROM work WHERE results LIKE '%/\\_\\_manga/suwayomi/m/%' ESCAPE '\\'").fetchone()[0]
        report['search_work_results_with_old_links'] = work


class Sealer:
    def __init__(self, key):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self.key, self.aes = key, AESGCM(key)

    def open(self, raw, aad):
        return json.loads(self.aes.decrypt(raw[:12], raw[12:], aad.encode()))

    def seal(self, value, aad):
        nonce = os.urandom(12)
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        return nonce + self.aes.encrypt(nonce, raw, aad.encode())

    def digest(self, *parts):
        # reading_places.PlaceStore.digest
        return hmac.new(self.key, '\n'.join(('places',) + parts).encode(), hashlib.sha256).hexdigest()


def subjects(data, sealer, extra=()):
    """Profiles known to this server, by their places owner digest."""
    names = set(extra)
    tasks = Path(data) / 'tasks.sqlite'
    if tasks.is_file():
        with closing(sqlite3.connect(tasks.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
            for (name,) in db.execute('SELECT name FROM settings'):
                head, _, rest = name.partition(':')
                names.update({name, rest, 'guest:' + rest})
                if head == 'guest':
                    try:
                        record = sealer.open(db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()[0], name)
                        if isinstance(record, dict) and record.get('id'):
                            names.update({str(record['id']), 'guest:' + str(record['id'])})
                    except Exception:
                        pass
    return {sealer.digest(name): name for name in names if name}


class Episodes:
    """The direct reader's episode list per title, fetched once (online only)."""

    def __init__(self, online):
        self.online = online
        self.titles = {}

    def chapter(self, resolver, link):
        """(exact episode URL, None) or (None, reason) for an old chapter link."""
        ids = resolver.legacy.parse(link, resolver.root)
        target, reason = resolver.target(link)
        if target is None:
            return None, reason
        if ids[1] is None:
            return target, None
        if not self.online:
            return None, 'needs-online-match'
        title, reason = resolver.legacy.explain(ids[0], path=resolver.map_path)
        if title is None:
            return None, reason
        if title not in self.titles:
            from manga_sources import inspect
            from source_parser import SourceError
            try:
                self.titles[title] = inspect(title).get('episodes') or []
            except SourceError:
                self.titles[title] = None
            time.sleep(0.5)
        episodes = self.titles[title]
        if episodes is None:
            return None, 'title-unavailable-now'
        found = resolver.legacy.lookup(ids[0], ids[1], path=resolver.map_path)
        number = found[1][5] if found and found[1] else None
        exact = resolver.legacy.episode_url(target, episodes, number)
        return (exact, None) if exact else (None, 'no-matching-episode')


def place_twin(resolver, episodes, key, value):
    """(new key, new value) of a place keyed by an old chapter link, or (None, reason)."""
    family, _, encoded = key.partition(':')
    if family not in {'m', 'p', 'r', 'w'}:
        return None, 'old-link-only-in-value'
    decoded = unquote(encoded)
    if quote(decoded, safe=JS_SAFE) != encoded:
        return None, 'unexpected-encoding'
    links = resolver.links(decoded)
    if not links:
        return None, 'old-link-only-in-value'
    swap = {}
    for link in dict.fromkeys(links):
        exact, reason = episodes.chapter(resolver, link)
        if exact is None:
            return None, reason
        swap[link] = exact

    def replace(item):
        if isinstance(item, str):
            return resolver.pattern.sub(lambda m: swap.get(m[0], m[0]), item)
        if isinstance(item, list):
            return [replace(v) for v in item]
        if isinstance(item, dict):
            return {k: replace(v) for k, v in item.items()}
        return item

    new_value = replace(value)
    if resolver.links(json.dumps(new_value, ensure_ascii=False)):
        return None, 'value-has-other-old-links'
    return (family + ':' + quote(replace(decoded), safe=JS_SAFE), new_value), None


def migrate_places(data, resolver, sealer, apply, report, online=False):
    path = Path(data) / 'places.sqlite'
    entry = report.setdefault('places', {})
    if not path.is_file():
        entry['missing'] = True
        return
    with closing(sqlite3.connect(path, timeout=30)) as db:
        rows = db.execute('SELECT owner, place, at, value FROM places').fetchall()
        entry['rows_before'] = len(rows)
        history_ids = set()
        opened = []
        for owner, place, at, raw in rows:
            try:
                value = sealer.open(raw, owner + place)
            except Exception:
                entry['undecryptable'] = entry.get('undecryptable', 0) + 1
                continue
            opened.append((owner, place, at, value))
            if value['k'].startswith('h:') and isinstance(value.get('v'), dict):
                parts = value['v'].get('id', '').split(':')
                if len(parts) > 1:
                    history_ids.add(parts[1])
        profiles = subjects(data, sealer, history_ids)
        counts = collections.Counter()
        writes = []
        existing = {(o, p): a for o, p, a, _ in rows}
        episodes = Episodes(online)
        for owner, place, at, value in opened:
            key = value['k']
            text = json.dumps(value, ensure_ascii=False)
            if not resolver.links(text):
                if re.search(r'suwayomi:-?\d+:\d+(?![\w:])', text):
                    counts['legacy-title-id-in-history'] += 1
                continue
            counts['with_old_links'] += 1
            twin, reason = place_twin(resolver, episodes, key, value.get('v'))
            if twin is None:
                # A history row names its title by an opaque ID; its route opens
                # through the title snapshot and the bridge resolver.
                counts[reason if reason == 'old-link-only-in-value' else 'kept:' + reason] += 1
                continue
            new_key, new_value = twin
            subject = profiles.get(owner)
            if subject is None:
                counts['kept:unknown-profile'] += 1
                continue
            new_place = sealer.digest(subject, new_key)
            if existing.get((owner, new_place), -1) >= at:
                counts['already-migrated'] += 1
                continue
            writes.append((owner, new_place, at, {'k': new_key, 'v': new_value}))
            counts['added'] += 1
        if apply and writes:
            with db:
                clock = db.execute('SELECT coalesce(max(seen),0) FROM places').fetchone()[0]
                for owner, new_place, at, value in writes:
                    # Re-check inside the write: a device may have synced since.
                    row = db.execute('SELECT at FROM places WHERE owner=? AND place=?', (owner, new_place)).fetchone()
                    if row and row[0] >= at:
                        continue
                    clock = max(clock + 1, time.time_ns() // 1000)
                    db.execute('INSERT OR REPLACE INTO places VALUES (?,?,?,?,?)',
                               (owner, new_place, at, clock, sealer.seal(value, owner + new_place)))
        entry.update(counts)
        entry['profiles_known'] = len({profiles.get(o) for o, *_ in rows if profiles.get(o)})
        entry['rows_after'] = db.execute('SELECT count(*) FROM places').fetchone()[0]


def report_sealed(data, resolver, sealer, report):
    """Import tasks and title shares: counted, resolved, never written here."""
    path = Path(data) / 'tasks.sqlite'
    if not path.is_file():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        tasks = collections.Counter()
        for tid, status, raw in db.execute('SELECT id, status, data FROM tasks'):
            try:
                text = json.dumps(sealer.open(raw, tid), ensure_ascii=False)
            except Exception:
                continue
            links = resolver.links(text)
            if links:
                ok = all(resolver.target(link)[0] for link in links if not re.search(r'/p/\d+$', link))
                tasks[f"{status}/{'resolves' if ok else 'not-yet-direct'}"] += 1
        report['tasks'] = dict(tasks)
        shares = collections.Counter()
        for name, raw in db.execute('SELECT name, value FROM settings'):
            try:
                text = json.dumps(sealer.open(raw, name), ensure_ascii=False)
            except Exception:
                continue
            links = resolver.links(text)
            if links:
                kind = name.split(':', 1)[0]
                shares[kind + ':links'] += len(links)
                shares[kind + ':resolves'] += sum(1 for link in links if resolver.target(link)[0])
        report['settings'] = dict(shares)


def run(data, apply=False, root=None, map_path=None, only=None, online=False):
    data = Path(data)
    root = root or os.getenv('PUBLIC_URL', '')
    if not root.startswith('https://'):
        raise SystemExit('PUBLIC_URL (https://…) is required to recognise old links.')
    map_path = Path(map_path or data / 'suwayomi-legacy-map.sqlite')
    if not map_path.is_file():
        raise SystemExit(f'Legacy ID map not found: {map_path}')
    os.environ['DATA_DIR'] = str(data)
    report = {'apply': apply, 'data': str(data), 'started': time.time()}
    resolver = Resolver(map_path, root, report)
    sealer = Sealer((data / 'service.key').read_bytes())
    parts = set(only or ('catalogue', 'places', 'sealed'))
    with offline(report):
        if 'catalogue' in parts:
            migrate_catalogue(data, resolver, apply, report)
        if 'sealed' in parts:
            report_sealed(data, resolver, sealer, report)
    if 'places' in parts:
        # A chapter's progress key is the reader's exact episode URL: with
        # --online each title's episode list is read once to find it.
        resolver.memo.clear()
        migrate_places(data, resolver, sealer, apply, report, online)
    report['references'] = dict(resolver.reasons)
    report['unresolved_by_source'] = sorted(
        ({'reason': reason, 'source': source, 'links': n} for (reason, source), n in resolver.unresolved.items()),
        key=lambda row: -row['links'])
    report['finished'] = time.time()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--data', default=os.getenv('DATA_DIR', '/data'))
    parser.add_argument('--map')
    parser.add_argument('--root', help='PUBLIC_URL the old links were issued under')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--only', nargs='*', choices=['catalogue', 'places', 'sealed'])
    parser.add_argument('--online', action='store_true', help='read episode lists to key reading places exactly')
    parser.add_argument('--report')
    args = parser.parse_args(argv)
    report = run(args.data, args.apply, args.root, args.map, args.only, args.online)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.report:
        Path(args.report).write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
