"""Where a profile stopped reading or watching, shared between its devices.

Each profile keeps a small set of places (a ranobe paragraph, a manga page, an
online episode and its second, the viewing history rows that name «глава 12»).
A device sends the places it changed and receives what other devices changed
since its last visit. The newest change of a place wins; a removed place stays
as a short tombstone so another device does not bring it back.

Rows live in their own SQLite file next to the task store, so frequent saves
never touch the settings table the deploy preservation check hashes. The
profile and the place name are stored only as keyed hashes; the place name and
value are sealed with the server key.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

KEY_PATTERN = r'^[hrmpw]:[^\x00-\x1f]{1,600}$'
MAX_VALUE = 4096
MAX_ROWS = 4000
PAGE = 800
# Clocks of phones and computers drift; a place from the future is clamped.
FUTURE = 10 * 60 * 1000


class Place(BaseModel):
    model_config = ConfigDict(extra='forbid')
    k: str = Field(pattern=KEY_PATTERN, max_length=602)
    at: int = Field(ge=0)
    v: dict | list | None = None


class PlaceSync(BaseModel):
    model_config = ConfigDict(extra='forbid')
    since: int = Field(default=0, ge=0)
    entries: list[Place] = Field(default_factory=list, max_length=PAGE)


class PlaceStore:
    def __init__(self, directory, key, seal, unseal):
        self.key, self.seal, self.unseal = key, seal, unseal
        self.lock = threading.RLock()
        path = Path(directory) / 'places.sqlite'
        self.database = sqlite3.connect(path, check_same_thread=False)
        with self.database:
            self.database.executescript("""
                CREATE TABLE IF NOT EXISTS places (
                    owner TEXT NOT NULL, place TEXT NOT NULL, at INTEGER NOT NULL,
                    seen INTEGER NOT NULL, value BLOB NOT NULL, PRIMARY KEY(owner, place));
                CREATE INDEX IF NOT EXISTS places_seen ON places(owner, seen);
            """)
        path.chmod(0o600)
        self.last = self.database.execute('SELECT coalesce(max(seen),0) FROM places').fetchone()[0]

    def digest(self, *parts):
        return hmac.new(self.key, '\n'.join(('places',) + parts).encode(), hashlib.sha256).hexdigest()

    def tick(self):
        # A strictly increasing server clock: a device asks for rows seen after it.
        self.last = max(self.last + 1, time.time_ns() // 1000)
        return self.last

    def sync(self, subject, since, entries, now=None):
        owner = self.digest(str(subject))
        limit = int((now if now is not None else time.time()) * 1000) + FUTURE
        with self.lock, self.database:
            if since > self.last:
                since = 0  # the server was restored from an older backup: send everything
            for entry in entries:
                if entry.v is not None and len(json.dumps(entry.v, ensure_ascii=False, separators=(',', ':'))) > MAX_VALUE:
                    continue
                place, at = self.digest(str(subject), entry.k), min(entry.at, limit)
                row = self.database.execute('SELECT at FROM places WHERE owner=? AND place=?', (owner, place)).fetchone()
                if row and row[0] >= at:
                    continue
                sealed = self.seal({'k': entry.k, 'v': entry.v}, owner + place)
                self.database.execute('INSERT OR REPLACE INTO places VALUES (?,?,?,?,?)', (owner, place, at, self.tick(), sealed))
            extra = self.database.execute('SELECT count(*) FROM places WHERE owner=?', (owner,)).fetchone()[0] - MAX_ROWS
            if extra > 0:
                # The places nobody touched for longest make room.
                self.database.execute('DELETE FROM places WHERE rowid IN (SELECT rowid FROM places WHERE owner=? ORDER BY at LIMIT ?)', (owner, extra))
            rows = self.database.execute('SELECT place, at, seen, value FROM places WHERE owner=? AND seen>? ORDER BY seen LIMIT ?', (owner, since, PAGE + 1)).fetchall()
            more = len(rows) > PAGE
            rows = rows[:PAGE]
            # Caught up: the device continues from the server clock; otherwise
            # from the last row it received, and asks again.
            clock = rows[-1][2] if more else max(self.last, since)
        out = []
        for place, at, seen, value in rows:
            try:
                opened = self.unseal(value, owner + place)
            except Exception:
                continue
            out.append({'k': opened['k'], 'at': at, 'v': opened['v']})
        return {'clock': clock, 'entries': out, 'more': more}

    def close(self):
        with self.lock:
            self.database.close()


def install(app, viewer, store_getter, directory_getter):
    state = {'store': None}

    def places():
        task_store = store_getter()
        if task_store is None:
            raise HTTPException(503, 'Сервер ещё запускается.')
        current = state['store']
        if current is None or current.owner_store is not task_store:
            if current is not None:
                current.close()
            current = PlaceStore(directory_getter(), task_store.key, task_store.seal, task_store.open)
            current.owner_store = task_store
            state['store'] = current
        return current

    @app.post('/places')
    def sync_places(body: PlaceSync, subject=Depends(viewer)):
        if not subject or str(subject).startswith('share:'):
            raise HTTPException(403, 'Место чтения хранится только для профиля.')
        return places().sync(subject, body.since, body.entries)

    app.state.reading_places = places
