"""Single durable worker, separate from the HTTP process. No public listening port."""
import base64
import fcntl
import os
import shutil
import threading
import time
from pathlib import Path

from run_import import run_job
from runtime_api import open_vault, runtime_store
from source_parser import PublicHttp, Resolver, SourceError


class LimitedHttp(PublicHttp):
    def download(self, value, target, **options):
        limit = int(os.environ.get('MEDIAVAULT_MAX_FILE_BYTES', 2 * 1024**3))
        episode = next((str(path) for path in Path(target).parents if path.name.startswith('mediavault-episode-')), str(target))
        if getattr(self, '_episode', None) != episode:
            self._episode, self._downloaded = episode, 0
        remaining = limit - self._downloaded
        if remaining <= 0:
            raise SourceError('Серия превышает установленный на сервере лимит размера.')
        options['maximum'] = min(options.get('maximum', remaining), remaining)
        size = super().download(value, target, **options)
        self._downloaded += size
        return size


def process_one(store, *, vault_factory=None, runner=run_job):
    task = store.take()
    if not task:
        return False
    identifier, job = task
    vault = None
    resolver = None
    try:
        if store.cancelled(identifier):
            raise InterruptedError()
        if shutil.disk_usage(os.environ.get('TMPDIR', '/tmp')).free < 5 * 1024**3:
            raise RuntimeError('Insufficient temporary disk')
        key = store.secret('library:' + job['library_id'])
        if not key:
            raise RuntimeError('Library disconnected')
        vault = (vault_factory or (lambda: open_vault(store)))()
        vault.unlock_key(job['library_id'], base64.b64decode(key, validate=True))
        resolver = Resolver(http=LimitedHttp())
        result = runner(job, vault, resolver=resolver, log=lambda value: None,
                        event=lambda progress: store.update(identifier, progress=progress),
                        cancelled=lambda: store.cancelled(identifier))
        status = 'partial' if result.get('failed') else 'completed'
        store.update(identifier, status=status, result=result)
    except InterruptedError:
        store.update(identifier, status='cancelled', result={'message': 'Импорт остановлен. Сохранённые серии остаются в Drive.'})
    except Exception:
        store.update(identifier, status='failed', result={'message': 'Импорт остановлен. Проверь доступ Google, свободное место и источник. Повторный импорт пропустит сохранённые серии.'})
    finally:
        if vault:
            vault.close()
        if resolver:
            resolver.http.close()
    return True


def main():
    os.umask(0o077)
    store = runtime_store()
    # Prevent two workers on the same VM, including an accidental service restart overlap.
    with (store.directory / 'worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store.recover()
        def heartbeat():
            while True:
                store.put_secret('worker-heartbeat', time.time())
                time.sleep(20)
        threading.Thread(target=heartbeat, daemon=True).start()
        while True:
            if not process_one(store):
                time.sleep(2)


if __name__ == '__main__':
    main()
