"""Narrow, same-source recovery for a known extension empty-result schema bug."""
import json
import time
from urllib.parse import urlencode, urlsplit

from source_parser import PublicHttp, SourceError


def rawuwu_empty(source, query, http_factory=PublicHttp):
    # The site's nonempty responses have pagi.button; its valid empty response
    # instead has {current,offset}. The extension's required Kotlin field throws
    # MissingFieldException and Suwayomi returns400. Never fabricate a success
    # for nonempty results, blocked HTML, malformed JSON, or another provider.
    if source.get('name') != 'Raw UwU' or urlsplit(source.get('baseUrl', '')).hostname != 'rawuwu.net':
        return False
    http = http_factory(timeout=(3, 5), deadline=time.monotonic() + 7)
    try:
        url = 'https://rawuwu.net/spa/search?' + urlencode({'query': query, 'page': 1})
        text, final, _ = http.document(url)
        if urlsplit(final).hostname != 'rawuwu.net' or len(text) > 65536:
            return False
        value = json.loads(text)
        return (isinstance(value, dict) and value.get('manga_list') == []
                and isinstance(value.get('pagi'), dict)
                and 'button' not in value['pagi']
                and value['pagi'].get('current') == 1 and value['pagi'].get('offset') == 0)
    except (SourceError, ValueError, TypeError):
        return False
    finally:
        http.close()
