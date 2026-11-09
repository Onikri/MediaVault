"""One real image per title before advertising it as a usable reader.

Shared short-lived results contain only booleans and fixed/public errors. No
image bytes are cached here. A good sample does not guarantee every chapter.
"""
import threading,time
from source_parser import PublicHttp,SourceError

_lock=threading.RLock();_cache={};_pending={};_slots=threading.BoundedSemaphore(4)

def verify(value,refresh=False):
    url=value['url'];now=time.monotonic()
    with _lock:
        hit=_cache.get(url)
        if not refresh and hit and hit[0]>now:return hit[1]
        pending=_pending.get(url)
        if pending is None:pending={'event':threading.Event()};_pending[url]=pending;leader=True
        else:leader=False
    if not leader:
        if not pending['event'].wait(65):raise SourceError('Проверка страниц ещё выполняется. Повтори позже.')
        if 'value' not in pending:raise SourceError('Не удалось завершить проверку страниц.')
        return pending['value']
    acquired=False
    try:
        acquired=_slots.acquire(timeout=4)
        if not acquired:raise SourceError('Проверяются другие читалки. Повтори через несколько секунд.')
        from manga_sources import inspect
        from suwayomi_bridge import parse_reference,page_image
        from manga_download import image_extension
        entries = value.get('episodes') or []
        targets = [value['url']] if value.get('pages') else list(dict.fromkeys(e['url'] for e in entries))[:3]
        result = {'readable': False, 'verifiedPages': 0,
                  'readabilityError': 'У этого тайтла нет открытых глав на выбранном языке.'}
        if targets:
            http = PublicHttp(timeout=(3, 8), deadline=time.monotonic()+35)
            try:
                for target in targets:
                    try:
                        chapter = value if value.get('pages') else inspect(target, http)
                        pages = chapter.get('pages') or []
                        if not pages:
                            raise SourceError('Источник не предоставил страницы открытой главы.')
                        if parse_reference(pages[0]):
                            raw = page_image(pages[0])[0]
                        else:
                            response, _ = http._open(pages[0], headers={'Referer': chapter['url']})
                            try:
                                raw = bytearray()
                                for block in response.iter_content(65536):
                                    raw.extend(block)
                                    if len(raw) > 30*1024*1024 or time.monotonic() > http.deadline:
                                        raise SourceError('Источник не успел загрузить страницу в пределах лимита.')
                            finally:
                                response.close()
                        if not image_extension(raw[:32]):
                            raise SourceError('Источник вернул заглушку вместо страницы.')
                        result = {'readable': True, 'verifiedPages': 1, 'readabilityError': '',
                                  'verifiedChapterUrl': target}
                        break
                    except Exception as error:
                        result['readabilityError'] = (str(error) if isinstance(error, SourceError)
                                                      else 'Не удалось загрузить страницу источника.')
                        if time.monotonic() >= http.deadline:
                            break
            finally:
                http.close()
        result['pagesCheckedAt']=int(time.time())
        with _lock:
            if len(_cache)>=256:_cache.pop(next(iter(_cache)))
            _cache[url]=(time.monotonic()+(300 if result['readable'] else 45),result);pending['value']=result
        return result
    finally:
        if acquired:_slots.release()
        with _lock:_pending.pop(url,None);pending['event'].set()
