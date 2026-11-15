"""Keep MediaVault source selection in reader URLs and off the upstream wire."""

import re
from urllib.parse import unquote_plus, urlsplit, urlunsplit


SOURCE_PARAM = 'mv_manga_source'
SOURCE_ID = re.compile(r'[1-9][0-9]{0,18}')


def split_reader_url(value):
    parts = urlsplit(value)
    selected = []
    remaining = []
    for field in parts.query.split('&') if parts.query else ():
        name, _, raw = field.partition('=')
        if unquote_plus(name) == SOURCE_PARAM:
            selected.append(unquote_plus(raw))
        else:
            remaining.append(field)
    if not selected:
        return None, value
    if len(selected) != 1 or not SOURCE_ID.fullmatch(selected[0]):
        raise ValueError('Invalid manga source selection')
    return selected[0], urlunsplit(parts._replace(query='&'.join(remaining)))


def reader_url(value, source_id):
    selected, upstream = split_reader_url(value)
    if not SOURCE_ID.fullmatch(source_id) or selected not in (None, source_id):
        raise ValueError('Invalid manga source selection')
    parts = urlsplit(upstream)
    query = '&'.join(filter(None, (parts.query, SOURCE_PARAM + '=' + source_id)))
    return urlunsplit(parts._replace(query=query))
