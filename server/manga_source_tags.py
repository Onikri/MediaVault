"""Conservative source-provided tag extraction.

Keep source labels intact (including adult classifications) and never infer
tags from artwork or a title. Empty means 'not provided', not 'no tags'.
"""
import re
import unicodedata

from bs4 import BeautifulSoup

MAX_LABELS = 120
MAX_LENGTH = 120
_TAG_LINK = re.compile(r'/(?:tags?|genres?|categories?)/|[?&](?:tag|genre|category)=', re.I)


def clean_label(value):
    if not isinstance(value, str):
        return ''
    value = unicodedata.normalize('NFKC', value)
    value = ' '.join(value.split()).strip(' ,;|')
    # Keep structurally valid source facts even when their public projection is
    # hidden. The owner can restore or remap them later without another scrape.
    return value[:MAX_LENGTH] if 1 <= len(value) <= MAX_LENGTH else ''


def unique(values):
    found = {}
    for value in values:
        label = clean_label(value)
        if label:
            found.setdefault(label.casefold(), label)
        if len(found) >= MAX_LABELS:
            break
    return list(found.values())


def labels(value):
    """Extract label text from an API's explicit tag/genre array only."""
    if isinstance(value, str):
        return unique([value])
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value[:MAX_LABELS]:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            item=item.get('attributes') if isinstance(item.get('attributes'),dict) else item
            raw = item.get('name') or item.get('label') or item.get('title')
            if isinstance(raw, str):
                result.append(raw)
            elif isinstance(raw, dict):
                # Retain both source-provided locales; the index normalizes.
                for lang in ('ru', 'en', 'ja', 'ko', 'uk'):
                    if isinstance(raw.get(lang), str):
                        result.append(raw[lang])
    return unique(result)


def from_api(payload):
    if not isinstance(payload, dict):
        return {'tags': [], 'genres': []}
    fields = payload.get('attributes') if isinstance(payload.get('attributes'), dict) else payload
    entries=fields.get('tags') or []
    grouped={'tags':[],'genres':[]}
    if isinstance(entries,list):
        for entry in entries:
            raw=entry.get('attributes',entry) if isinstance(entry,dict) else entry
            grouped['genres' if isinstance(raw,dict) and raw.get('group')=='genre' else 'tags'].append(raw)
    else:grouped['tags']=entries
    tags = labels(grouped['tags'])
    genres = labels(fields.get('genres') if fields.get('genres') is not None else fields.get('genre'))
    return {'tags': tags, 'genres': unique([*genres,*labels(grouped['genres'])])}


def from_html(source):
    soup = source if isinstance(source, BeautifulSoup) else BeautifulSoup(source, 'html.parser')
    tags, genres = [], []
    selectors = (
        '.tags a[href]', '.tag-list a[href]', '.manga-tags a[href]',
        '.genres a[href]', '.genre-list a[href]', '.manga-genres a[href]',
        '.post-content_item a[rel="tag"]', 'a[rel="tag"]',
        '.manga_row3 a[href]', '.post-content_item a[href]',
    )
    for link in soup.select(','.join(selectors))[:300]:
        href = str(link.get('href') or '')
        parent_classes = ' '.join(link.parent.get('class', [])) if link.parent else ''
        context = ((link.get('rel') or [''])[0] if link.get('rel') else '') + ' ' + parent_classes
        if not _TAG_LINK.search(href) and not re.search(r'\b(?:tags?|genres?)\b', context, re.I):
            continue
        label = clean_label(link.get_text(' ', strip=True))
        if not label:
            continue
        genre = '/genre' in href.casefold() or 'genre' in parent_classes.casefold()
        (genres if genre else tags).append(label)
    return {'tags': unique(tags), 'genres': unique(genres)}
