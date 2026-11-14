"""Private, disk-backed VOD bundles. Never evict a playing or paused viewer.

One bundle identifies the owner, exact episode/dub URL, referer and requested
quality. Signed CDN URLs stay in private files, never in a public catalogue.
The original Alloha transport still fetches every upstream byte.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import threading
import time


def identity(owner, url, quality, referer=''):
    return hashlib.sha256(json.dumps([2, owner, url, str(quality), referer or ''],
                                    separators=(',', ':')).encode()).hexdigest()


class VodCache:
    def __init__(self, directory, *, retention=1200, maximum=60*1024**3,
                 reserve=8*1024**3, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.retention, self.maximum, self.reserve, self.clock = retention, maximum, reserve, clock
        self.pins, self.lock = Counter(), threading.RLock()
        self.last_prune, self.used = 0, 0
        self.prune()

    def folder(self, key):
        if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid cache identity')
        return self.directory / key

    @staticmethod
    def name(url, byte_range=''):
        return hashlib.sha256((url+'\n'+byte_range).encode()).hexdigest()

    @staticmethod
    def atomic(path, data):
        pending = path.with_name(path.name+'.'+secrets.token_hex(8)+'.pending')
        try:
            with pending.open('xb') as output:
                os.chmod(pending, 0o600)
                output.write(data)
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)

    def touch(self, key):
        with self.lock:
            folder = self.folder(key)
            folder.mkdir(exist_ok=True, mode=0o700)
            stamp = folder/'lease'
            if not stamp.exists() or self.clock()-stamp.stat().st_mtime > 25:
                stamp.touch(mode=0o600)
                os.utime(stamp, (self.clock(), self.clock()))

    def pin(self, key):
        with self.lock:
            self.pins[key] += 1
            self.touch(key)

    def release(self, key):
        with self.lock:
            if self.pins[key] > 0:
                self.pins[key] -= 1
                self.touch(key)
                stamp = self.folder(key)/'lease'
                os.utime(stamp, (self.clock(), self.clock()))
            if not self.pins[key]:
                self.pins.pop(key, None)

    def prune(self):
        with self.lock:
            now = self.clock()
            used = 0
            for folder in self.directory.iterdir():
                if not folder.is_dir() or len(folder.name) != 64:
                    continue
                try:
                    stamp = folder/'lease'
                    if self.pins[folder.name]:
                        self.touch(folder.name)
                    last = stamp.stat().st_mtime if stamp.exists() else folder.stat().st_mtime
                    if not self.pins[folder.name] and now-last >= self.retention:
                        shutil.rmtree(folder)
                    else:
                        used += sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
                except FileNotFoundError:
                    pass
            self.used, self.last_prune = used, now

    def get(self, key, url, byte_range=''):
        with self.lock:
            folder = self.folder(key)
            name = self.name(url, byte_range)
            try:
                meta = json.loads((folder/(name+'.json')).read_text())
                raw = (folder/name).read_bytes()
                if len(raw) != meta['size'] or hashlib.sha256(raw).hexdigest() != meta['sha256']:
                    (folder/'complete.json').unlink(missing_ok=True)
                    return None
                return raw, meta['headers'], meta['status'], meta['final']
            except (OSError, ValueError, KeyError):
                if byte_range.startswith('bytes='):
                    full = self.get(key, url)
                    if full and full[2] == 200:
                        raw, headers, _, final = full
                        try:
                            start, end = byte_range[6:].split('-')
                            begin = int(start) if start else max(0, len(raw)-int(end))
                            finish = min(len(raw)-1, int(end)) if start and end else len(raw)-1
                            if not 0 <= begin <= finish < len(raw):
                                return None
                            return raw[begin:finish+1], {**headers, 'content-range': f'bytes {begin}-{finish}/{len(raw)}',
                                'content-length': str(finish-begin+1), 'accept-ranges': 'bytes'}, 206, final
                        except ValueError:
                            pass
                return None

    def put(self, key, url, byte_range, value):
        raw, headers, status, final = value
        if not raw or status not in {200, 206}:
            return False
        with self.lock:
            if self.clock()-self.last_prune >= 30:
                self.prune()
            if self.used+len(raw)+4096 > self.maximum or shutil.disk_usage(self.directory).free < self.reserve+len(raw)+4096:
                return False  # Playback still streams normally when the cache is full.
            folder = self.folder(key)
            folder.mkdir(exist_ok=True, mode=0o700)
            name = self.name(url, byte_range)
            target = folder/name
            previous = target.stat().st_size if target.exists() else 0
            self.atomic(target, raw)
            self.atomic(folder/(name+'.json'), json.dumps({'size': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'headers': headers,
                'status': status, 'final': final}).encode())
            self.used += len(raw)-previous+512
            return True

    def complete(self, key, record):
        with self.lock:
            if not record['resources'] or any(self.get(key, url, interval) is None for url, interval in record['resources']):
                return False
            self.atomic(self.folder(key)/'complete.json', json.dumps(record).encode())
            return True

    def load(self, key):
        with self.lock:
            try:
                record = json.loads((self.folder(key)/'complete.json').read_text())
                # Content hashes are checked when each fragment is served and on
                # Drive restoration. Opening a film doesn't read the entire film.
                for url, interval in record['resources']:
                    name = self.name(url, interval)
                    meta = json.loads((self.folder(key)/(name+'.json')).read_text())
                    if (self.folder(key)/name).stat().st_size != meta['size']:
                        return None
                return record
            except (OSError, ValueError, KeyError):
                return None
