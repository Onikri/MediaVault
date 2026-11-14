"""One encrypted Drive object per complete VOD, restored once onto VM disk.

This is a private playback cache, separate from the user's encrypted library.
The service encryption key must be backed up along with tasks.sqlite. Uploads
are bounded-memory, resumable and never publish partial or unverified bundles.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import threading
import time
import zipfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from vault_drive import GoogleDriveAdapter

CHUNK = 16*1024**2
LIMIT = 16*1024**3


class DriveArchive:
    def __init__(self, cache, get_store, credentials):
        self.cache, self.get_store, self.credentials = cache, get_store, credentials
        self.slots = threading.BoundedSemaphore(1)
        self.range_slots = threading.BoundedSemaphore(2)
        self.unavailable = {}

    def setting(self, owner, key):
        return 'alloha-archive:'+hashlib.sha256(owner.encode()).hexdigest()+':'+key

    def key(self, owner, key):
        return hmac.digest(self.get_store().key, ('alloha-vod-v1:'+owner+':'+key).encode(), 'sha256')

    def seal(self, owner, key, source, target):
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(self.key(owner, key)), modes.GCM(nonce)).encryptor()
        cipher.authenticate_additional_data(key.encode())
        with source.open('rb') as src, target.open('wb') as dst:
            os.chmod(target, 0o600)
            dst.write(b'MVVOD1'+nonce+b'\0'*16)
            while raw := src.read(CHUNK):
                dst.write(cipher.update(raw))
            dst.write(cipher.finalize())
            dst.seek(18)
            dst.write(cipher.tag)

    def unseal(self, owner, key, source, target):
        with source.open('rb') as src, target.open('wb') as dst:
            os.chmod(target, 0o600)
            if src.read(6) != b'MVVOD1':
                raise ValueError('Invalid playback archive')
            cipher = Cipher(algorithms.AES(self.key(owner, key)), modes.GCM(src.read(12), src.read(16))).decryptor()
            cipher.authenticate_additional_data(key.encode())
            while raw := src.read(CHUNK):
                dst.write(cipher.update(raw))
            dst.write(cipher.finalize())

    def upload(self, owner, key, path):
        from googleapiclient.http import MediaFileUpload
        drive = GoogleDriveAdapter.from_adc(self.credentials(owner))
        folders = drive.list_children('root', name='.MediaVault playback cache', mime_type='application/vnd.google-apps.folder')
        if folders:
            parent = folders[0]['id']
        else:
            parent = drive.allocate_id()
            drive.create_folder(parent, '.MediaVault playback cache')
        # Reuse an opaque deterministic name after an interrupted settings write.
        existing = drive.list_children(parent, name=key+'.mvv')
        media = MediaFileUpload(str(path), mimetype='application/octet-stream', chunksize=CHUNK, resumable=True)
        if existing:
            file_id = existing[0]['id']
            # Encryption uses a fresh nonce. Never index the new ciphertext's
            # hash against an older object left by an interrupted settings write.
            request = drive.service.files().update(fileId=file_id, media_body=media, fields='id,size,md5Checksum')
        else:
            file_id = drive.allocate_id()
            request = drive.service.files().create(body={'id': file_id, 'name': key+'.mvv',
                'parents': [parent], 'mimeType': 'application/octet-stream'}, media_body=media, fields='id,size,md5Checksum')
        result = None
        while result is None:
            _, result = request.next_chunk(num_retries=2)
        if int(result.get('size', -1)) != path.stat().st_size:
            raise ValueError('Drive archive size mismatch')
        digest = hashlib.md5()
        with path.open('rb') as source:
            while raw := source.read(CHUNK):
                digest.update(raw)
        if result.get('md5Checksum') != digest.hexdigest():
            raise ValueError('Drive archive checksum mismatch')
        return file_id

    def download(self, owner, file_id, path, size):
        from googleapiclient.http import MediaIoBaseDownload
        drive = GoogleDriveAdapter.from_adc(self.credentials(owner))
        with path.open('wb') as output:
            os.chmod(path, 0o600)
            reader = MediaIoBaseDownload(output, drive.service.files().get_media(fileId=file_id), chunksize=CHUNK)
            done = False
            while not done:
                _, done = reader.next_chunk(num_retries=2)
                if output.tell() > min(LIMIT, size):
                    raise ValueError('Drive archive exceeds expected size')
        if path.stat().st_size != size:
            raise ValueError('Incomplete Drive archive')

    def save_legacy(self, owner, key):
        store = self.get_store()
        if not store or owner.startswith(('guest:', 'share:')) or not store.setting('google:'+owner):
            return False
        with self.slots:
            if store.setting(self.setting(owner, key)):
                return True
            record = self.cache.load(key)
            if record is None:
                return False
            folder = self.cache.folder(key)
            names = {'complete.json'}
            for url, interval in record['resources']:
                name = self.cache.name(url, interval)
                names.update((name, name+'.json'))
            size = sum((folder/name).stat().st_size for name in names)
            if size > LIMIT or shutil.disk_usage(folder).free < 2*size+self.cache.reserve:
                return False
            token = secrets.token_hex(12)
            plain, sealed = folder/(token+'.zip.pending'), folder/(token+'.sealed.pending')
            try:
                with zipfile.ZipFile(plain, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                    os.chmod(plain, 0o600)
                    for name in sorted(names):
                        archive.write(folder/name, name)
                self.seal(owner, key, plain, sealed)
                file_id = self.upload(owner, key, sealed)
                store.setting(self.setting(owner, key), {'file': file_id, 'size': sealed.stat().st_size,
                    'sha256': self.digest(sealed), 'version': 1})
                return True
            finally:
                plain.unlink(missing_ok=True)
                sealed.unlink(missing_ok=True)

    @staticmethod
    def digest(path):
        digest = hashlib.sha256()
        with path.open('rb') as source:
            while raw := source.read(CHUNK):
                digest.update(raw)
        return digest.hexdigest()

    def restore_legacy(self, owner, key):
        store = self.get_store()
        info = store.setting(self.setting(owner, key)) if store else None
        if not info:
            return False
        with self.slots:
            if self.cache.load(key):
                return True
            size = int(info['size'])
            if not 0 < size <= LIMIT or shutil.disk_usage(self.cache.directory).free < 3*size+self.cache.reserve or self.cache.used+size > self.cache.maximum:
                return False
            folder = self.cache.folder(key)
            token = secrets.token_hex(12)
            plain, sealed = folder/(token+'.zip.pending'), folder/(token+'.sealed.pending')
            staging = folder/(token+'.restore')
            staging.mkdir(mode=0o700)
            try:
                self.download(owner, info['file'], sealed, size)
                if self.digest(sealed) != info['sha256']:
                    raise ValueError('Damaged Drive archive')
                self.unseal(owner, key, sealed, plain)
                with zipfile.ZipFile(plain) as archive:
                    record = json.loads(archive.read('complete.json'))
                    expected = {'complete.json'}
                    for url, interval in record['resources']:
                        name = self.cache.name(url, interval)
                        expected.update((name, name+'.json'))
                    if set(archive.namelist()) != expected or len(expected) > 40002 or sum(i.file_size for i in archive.infolist()) > LIMIT:
                        raise ValueError('Unexpected playback archive members')
                    for name in expected:
                        with archive.open(name) as source, (staging/name).open('wb') as target:
                            os.chmod(staging/name, 0o600)
                            shutil.copyfileobj(source, target, CHUNK)
                    for url, interval in record['resources']:
                        name = self.cache.name(url, interval)
                        meta = json.loads((staging/(name+'.json')).read_text())
                        if (staging/name).stat().st_size != meta['size'] or self.digest(staging/name) != meta['sha256']:
                            raise ValueError('Damaged archived fragment')
                    # Publish completeness last, after GCM, ZIP CRC and SHA checks.
                    for item in staging.iterdir():
                        if item.name != 'complete.json':
                            item.replace(folder/item.name)
                    (staging/'complete.json').replace(folder/'complete.json')
                self.cache.prune()
                return True
            finally:
                plain.unlink(missing_ok=True)
                sealed.unlink(missing_ok=True)
                shutil.rmtree(staging)

    def lookup(self, owner, key):
        if self.unavailable.get((owner, key), 0) > time.monotonic():
            return None
        store = self.get_store()
        info = store.setting(self.setting(owner, key)) if store else None
        return info if info and info.get('version') == 2 else None

    def suspend(self, owner, key):
        now = time.monotonic()
        self.unavailable = {k: v for k, v in self.unavailable.items() if v > now}
        self.unavailable[(owner, key)] = now+60

    def save(self, owner, key):
        """Independently authenticated fragments in one resumable Drive object.

        The private encrypted index permits immediate playback without waiting
        for a multi-gigabyte archive to download or trusting partial GCM data.
        """
        store = self.get_store()
        if not store or owner.startswith(('guest:', 'share:')) or not store.setting('google:'+owner):
            return False
        with self.slots:
            if store.setting(self.setting(owner, key)):
                return True
            record = self.cache.load(key)
            if record is None:
                return False
            folder = self.cache.folder(key)
            entries, offset = [], 0
            for url, interval in record['resources']:
                name = self.cache.name(url, interval)
                meta = json.loads((folder/(name+'.json')).read_text())
                entries.append({'url': url, 'range': interval, 'name': name, 'meta': meta,
                                'offset': offset, 'length': meta['size']+28})
                offset += meta['size']+28
            if offset > LIMIT or shutil.disk_usage(folder).free < offset+self.cache.reserve:
                return False
            index = {'record': record, 'entries': entries}
            cipher = AESGCM(self.key(owner, key))
            raw_index = json.dumps(index, separators=(',', ':')).encode()
            if len(raw_index) > 16*1024**2:
                return False
            nonce = os.urandom(12)
            header = nonce+cipher.encrypt(nonce, raw_index, (key+':index').encode())
            if offset+10+len(header) > LIMIT:
                return False
            index['body'] = 10+len(header)
            target = folder/(secrets.token_hex(12)+'.sealed.pending')
            try:
                with target.open('wb') as output:
                    os.chmod(target, 0o600)
                    output.write(b'MVVOD2'+len(header).to_bytes(4, 'big')+header)
                    for entry in entries:
                        raw = (folder/entry['name']).read_bytes()
                        if len(raw) != entry['meta']['size'] or hashlib.sha256(raw).hexdigest() != entry['meta']['sha256']:
                            raise ValueError('Fragment changed before archiving')
                        nonce = os.urandom(12)
                        output.write(nonce+cipher.encrypt(nonce, raw, (key+':'+entry['name']).encode()))
                file_id = self.upload(owner, key, target)
                store.setting(self.setting(owner, key), {'file': file_id, 'size': target.stat().st_size,
                    'sha256': self.digest(target), 'version': 2, 'index': index})
                return True
            finally:
                target.unlink(missing_ok=True)

    def download_range(self, owner, file_id, start, end):
        drive = GoogleDriveAdapter.from_adc(self.credentials(owner))
        request = drive.service.files().get_media(fileId=file_id)
        request.headers['Range'] = f'bytes={start}-{end}'
        return drive._execute(request)

    def decode_entry(self, owner, key, entry, blob):
        if len(blob) != entry['length'] or len(blob) > 32*1024**2+28:
            raise ValueError('Invalid archived fragment size')
        raw = AESGCM(self.key(owner, key)).decrypt(blob[:12], blob[12:], (key+':'+entry['name']).encode())
        meta = entry['meta']
        if len(raw) != meta['size'] or hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise ValueError('Invalid archived fragment checksum')
        return raw, meta['headers'], meta['status'], meta['final']

    def fetch(self, owner, key, url, byte_range=''):
        """Only cold misses touch Drive; foreground duplicates join in delivery."""
        info = self.lookup(owner, key)
        if not info:
            raise ValueError('Archive is not indexed')
        with self.range_slots:
            cached = self.cache.get(key, url, byte_range)
            if cached:
                return cached
            entry = next((e for e in info['index']['entries'] if e['url'] == url and e['range'] == byte_range), None)
            if entry is None:
                entry = next((e for e in info['index']['entries'] if e['url'] == url and not e['range']), None)
            if entry is None:
                raise ValueError('Resource is not in the archived variant')
            start = info['index']['body']+entry['offset']
            blob = self.download_range(owner, info['file'], start, start+entry['length']-1)
            value = self.decode_entry(owner, key, entry, blob)
            self.cache.put(key, entry['url'], entry['range'], value)
            if byte_range == entry['range']:
                return value
            value = self.cache.get(key, url, byte_range)
            if value is None:
                raise ValueError('Requested archived range is not available')
            return value

    def restore(self, owner, key):
        info = self.lookup(owner, key)
        if not info:
            if self.unavailable.get((owner, key), 0) > time.monotonic():
                return False
            return self.restore_legacy(owner, key)
        with self.slots:
            if self.cache.load(key):
                return True
            size = int(info['size'])
            if not 0 < size <= LIMIT or shutil.disk_usage(self.cache.directory).free < 2*size+self.cache.reserve or self.cache.used+size > self.cache.maximum:
                return False
            folder = self.cache.folder(key)
            folder.mkdir(exist_ok=True, mode=0o700)
            sealed = folder/(secrets.token_hex(12)+'.sealed.pending')
            try:
                self.download(owner, info['file'], sealed, size)
                if self.digest(sealed) != info['sha256']:
                    raise ValueError('Damaged Drive archive')
                with sealed.open('rb') as source:
                    if source.read(6) != b'MVVOD2':
                        raise ValueError('Invalid playback archive')
                    length = int.from_bytes(source.read(4), 'big')
                    if not 28 <= length <= 16*1024**2+28:
                        raise ValueError('Invalid encrypted archive index')
                    blob = source.read(length)
                    index = json.loads(AESGCM(self.key(owner, key)).decrypt(blob[:12], blob[12:], (key+':index').encode()))
                    expected = {k: v for k, v in info['index'].items() if k != 'body'}
                    if index != expected or source.tell() != info['index']['body']:
                        raise ValueError('Archive index mismatch')
                    for entry in index['entries']:
                        source.seek(info['index']['body']+entry['offset'])
                        value = self.decode_entry(owner, key, entry, source.read(entry['length']))
                        if not self.cache.put(key, entry['url'], entry['range'], value):
                            return False
                return self.cache.complete(key, index['record'])
            finally:
                sealed.unlink(missing_ok=True)
