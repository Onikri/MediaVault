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
import zipfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from vault_drive import GoogleDriveAdapter

CHUNK = 16*1024**2
LIMIT = 16*1024**3


class DriveArchive:
    def __init__(self, cache, get_store, credentials):
        self.cache, self.get_store, self.credentials = cache, get_store, credentials
        self.slots = threading.BoundedSemaphore(1)

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

    def save(self, owner, key):
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

    def restore(self, owner, key):
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
