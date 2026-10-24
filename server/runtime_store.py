"""Private persistent queue. Job inputs and long-lived secrets are AES-GCM encrypted."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import contextmanager
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        key_path = self.directory / "master.key"
        try:
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(32))
        except FileExistsError:
            pass
        if key_path.stat().st_mode & 0o077:
            raise RuntimeError("master.key permissions must be 0600")
        self.cipher = AESGCM(key_path.read_bytes())
        self.path = self.directory / "queue.sqlite3"
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS secrets (name TEXT PRIMARY KEY, value BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, library TEXT NOT NULL,
                  status TEXT NOT NULL, payload BLOB, progress TEXT NOT NULL DEFAULT '{}',
                  result TEXT, label BLOB, created REAL NOT NULL, updated REAL NOT NULL, cancel INTEGER NOT NULL DEFAULT 0);
            ''')
            if 'label' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN label BLOB')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seal(self, name, value):
        nonce = os.urandom(12)
        return nonce + self.cipher.encrypt(nonce, json.dumps(value).encode(), name.encode())

    def open(self, name, value):
        return json.loads(self.cipher.decrypt(value[:12], value[12:], name.encode()))

    def secret(self, name):
        with self.connect() as db:
            row = db.execute("SELECT value FROM secrets WHERE name=?", (name,)).fetchone()
        return self.open(name, row[0]) if row else None

    def put_secret(self, name, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO secrets VALUES (?, ?)", (name, self.seal(name, value)))

    def delete_secret(self, name):
        with self.connect() as db:
            db.execute("DELETE FROM secrets WHERE name=?", (name,))

    def enqueue(self, job, request_id):
        identifier, now = uuid.uuid4().hex, time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT id FROM jobs WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                return previous[0]
            count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= 20:
                raise ValueError("В очереди уже 20 заданий. Дождись завершения.")
            db.execute("INSERT INTO jobs(id,request_id,library,status,payload,label,created,updated) VALUES (?,?,?,'queued',?,?,?,?)",
                       (identifier, request_id, job['library_id'], self.seal(identifier, job), self.seal('label:' + identifier, {'title': job.get('collection', ''), 'season': job.get('season', 1)}), now, now))
        return identifier

    def recover(self):
        # Called only by the single worker while holding its process lock.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")

    def take(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row['id']))
        return row['id'], self.open(row['id'], row['payload'])

    def update(self, identifier, *, progress=None, status=None, result=None):
        with self.connect() as db:
            if progress is not None:
                db.execute("UPDATE jobs SET progress=?,updated=? WHERE id=?", (json.dumps(progress), time.time(), identifier))
            if status:
                # Finished inputs (source URLs and collection names) no longer need storage.
                db.execute("UPDATE jobs SET status=?,result=?,payload=NULL,updated=? WHERE id=?",
                           (status, json.dumps(result), time.time(), identifier))

    def jobs(self, library):
        with self.connect() as db:
            rows = db.execute("SELECT id,status,progress,result,label,created,updated,cancel FROM jobs WHERE library=? ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END, created DESC LIMIT 70", (library,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            label = item.pop('label')
            item.update(self.open('label:' + item['id'], label) if label else {})
            item['progress'] = json.loads(item['progress'])
            item['result'] = json.loads(item['result']) if item['result'] else None
            result.append(item)
        return result

    def cancel(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()
            if not row:
                return False
            db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (identifier,))
            if row[0] == 'queued':
                db.execute("UPDATE jobs SET status='cancelled',payload=NULL,updated=? WHERE id=?", (time.time(), identifier))
        return True

    def cancelled(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT cancel FROM jobs WHERE id=?", (identifier,)).fetchone()
        return not row or bool(row[0])
