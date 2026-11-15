"""Bounded, GET-only publisher routes plus the NamiComi access-check request."""

import json
from urllib.parse import urlencode

from source_parser import PublicHttp, SourceError, public_url


def document(http, host, endpoint, params=(), body=None, action=None):
    target = host + endpoint + ('?' + urlencode(params) if params else '')

    def validate(value):
        if value != target:
            raise SourceError('Издатель перенаправил запрос на другой маршрут.')
        return public_url(value, allow_api=True)

    upstream = PublicHttp(validate=validate, timeout=http.timeout, deadline=http.deadline)
    try:
        kwargs = {'method': 'POST', 'data': body} if body is not None else {}
        raw, final, _ = upstream.document(target, headers={'Referer': host + '/'}, action=action, **kwargs)
        if final != target:
            raise SourceError('Издатель перенаправил запрос на другой маршрут.')
        return raw
    finally:
        upstream.close()


def json_data(raw):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise SourceError('Издатель вернул страницу вместо данных API.') from None


def mapping(value):
    if not isinstance(value, dict):
        raise SourceError('Издатель не предоставил ожидаемую запись API.')
    return value


def records(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise SourceError('Издатель не предоставил ожидаемый список API.')
    return value
