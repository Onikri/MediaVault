"""Project Gutenberg's own catalogue feed as book rows of the index.

Gutenberg asks machines to read its feeds instead of walking its pages, and
publishes the whole catalogue as one CSV file (pg_catalog.csv: Text#, Type,
Issued, Title, Language, Authors, Subjects, LoCC, Bookshelves). The first
page of a run downloads that file once into DATA_DIR; every later page reads
the next rows of the saved copy, so a weekly walk is one request to the site.
The cursor keeps the byte offset of the next record and the saved file's
stamp: a run that finds another file (or none) starts over from its first row.

Only "Text" entries become rows (no audio books, no sheet music). A row is a
book card of the catalogue (kind book, provider gutenberg) whose page is the
book our reader opens: https://www.gutenberg.org/ebooks/{id}. Its subjects go
through the ordinary tag path of ingest as genres, like Open Library's.
The row identity is the Gutenberg number, so a repeated run rewrites the same
rows and never adds a second copy.
"""
import csv
import os
import re
from pathlib import Path

import requests

from source_parser import SourceError, SourceRateLimitError, SourceTemporaryError

DOMAIN = 'www.gutenberg.org'
FEED = 'https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv'
USER_AGENT = 'MediaVault/5.1 (https://github.com/Onikri/MediaVault; personal catalogue)'
COLUMNS = ('Text#', 'Type', 'Title', 'Language', 'Authors')
# The feed was ~15 MB in 2026; a far larger answer is not the catalogue.
MAX_FEED = 200 * 1024 * 1024
# content_catalog.ingest writes at most 100 rows of one page.
PAGE = 100
MAX_AUTHORS = 6
MAX_SUBJECTS = 12
ROLE = re.compile(r'\s*\[([^\]]*)\]\s*$')
LIFE = re.compile(r',\s*(?:(?:approximately|active|ca\.)\s*)?(?:\d{1,4}\??\s*(?:BCE?|AD)?\s*-\s*(?:\d{1,4}\??\s*(?:BCE?|AD)?)?|-\s*\d{1,4}\??|\d{1,4}\??\s*(?:BCE?)?|\d{1,2}(?:st|nd|rd|th) cent(?:ury)?\.?(?:\s*BCE?)?)\s*$', re.I)
TITLES = {'sir', 'dame', 'lord', 'lady', 'graf', 'gräfin', 'count', 'countess', 'baron', 'baroness', 'freiherr', 'marquis',
          'duke', 'duchess', 'prince', 'princess', 'viscount', 'earl', 'saint', 'st', 'mrs', 'mr', 'miss'}
COMPLETE = re.compile(r'(?:\s*[,—–-]\s*|\s+)\(?complete\)?\.?$', re.I)


def feed_path():
    return Path(os.getenv('DATA_DIR', '/data')) / 'catalogue-feeds' / 'pg_catalog.csv'


def stamp(path):
    info = path.stat()
    return f'{info.st_size}-{int(info.st_mtime)}'


def download(path, get=requests.get):
    """Save the feed next to the index (the previous copy stays until the new one is whole)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part')
    try:
        with get(FEED, headers={'User-Agent': USER_AGENT, 'Accept': 'text/csv'}, timeout=(10, 60), stream=True, allow_redirects=False) as response:
            if response.status_code in {429, 503} and response.headers.get('Retry-After'):
                raise SourceRateLimitError(response.headers['Retry-After'], http_status=response.status_code)
            if response.status_code != 200:
                raise SourceTemporaryError(f'Источник вернул HTTP {response.status_code}.')
            size = 0
            with open(part, 'wb') as handle:
                for block in response.iter_content(1 << 20):
                    size += len(block)
                    if size > MAX_FEED:
                        raise SourceError('Каталог Project Gutenberg слишком велик.')
                    handle.write(block)
    except requests.RequestException:
        part.unlink(missing_ok=True)
        raise SourceTemporaryError('Project Gutenberg сейчас недоступен.') from None
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    with open(part, 'rb') as handle:
        header = handle.readline().decode('utf-8-sig', errors='replace')
    if not all(column in next(csv.reader([header]), []) for column in COLUMNS):
        part.unlink(missing_ok=True)
        # A maintenance page answers 200 with HTML: never index it.
        raise SourceTemporaryError('Project Gutenberg прислал не каталог.')
    os.replace(part, path)


def _lines(handle, position):
    """Decoded lines of a binary file; position[0] is the offset after the last line read."""
    while True:
        line = handle.readline()
        if not line:
            return
        position[0] = handle.tell()
        yield line.decode('utf-8', errors='replace')


def _clean(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def author_name(value):
    """'Wells, H. G. (Herbert George), 1866-1946' -> 'H. G. Wells'."""
    name = re.sub(r',\s*(?:active\b|fl\.|flourished\b).*$', '', _clean(value, 300), flags=re.I)
    name = LIFE.sub('', name).strip(' ,')
    name = re.sub(r'\s*\([^()]*\)', '', name).strip(' ,')
    parts = [part.strip() for part in name.split(',') if part.strip()]
    # 'Tolstoy, Leo, graf' and 'Doyle, Arthur Conan, Sir': a rank is not a name.
    parts = parts[:2] + [part for part in parts[2:] if part.casefold().rstrip('.') not in TITLES]
    suffix = [parts.pop()] if len(parts) >= 3 and re.fullmatch(r'(?:jr|sr|[ivx]+)\.?', parts[-1], re.I) else []
    parts = parts[:2]
    if len(parts) >= 2:
        name = ' '.join([*parts[1:], parts[0], *suffix])
    else:
        name = ' '.join([*parts, *suffix])
    return _clean(name, 120)


def authors(value):
    """Writers of the book; editors, translators and illustrators only when no writer is named."""
    writers, others = [], []
    for entry in str(value or '').split(';'):
        role = ROLE.search(entry)
        name = author_name(ROLE.sub('', entry))
        if not name or name.casefold() in {'anonymous', 'unknown', 'various'}:
            continue
        (writers if not role or role[1].strip().casefold() in {'author', 'creator'} else others).append(name)
    return list(dict.fromkeys(writers or others))[:MAX_AUTHORS]


def titles(value):
    """The full title and the names a reader knows the book by."""
    lines = [_clean(line, 300) for line in str(value or '').replace('\r', '\n').split('\n') if line.strip()]
    title = _clean(' '.join(lines), 300)
    names = [title]
    head = re.split(r'\s*[;:]\s+|\s*;\s*', lines[0] if lines else '', maxsplit=1)[0].strip(' .,')
    for name in (lines[0] if lines else '', head):
        name = COMPLETE.sub('', name).strip(' .,')
        if len(name) >= 2:
            names.append(name)
    return title, list(dict.fromkeys(names))


def book_row(record):
    """One CSV record as a content_titles row, or None for anything but a text."""
    number = str(record.get('Text#') or '').strip()
    if record.get('Type', '').strip() != 'Text' or not re.fullmatch(r'\d{1,7}', number):
        return None
    title, names = titles(record.get('Title'))
    if not title:
        return None
    language = [code.strip().lower() for code in str(record.get('Language') or '').split(';') if re.fullmatch(r'\s*[a-zA-Z]{2,3}\s*', code)]
    subjects = [_clean(s, 120) for s in str(record.get('Subjects') or '').split(';')]
    return {'id': 'gutenberg:' + number, 'provider': 'gutenberg', 'providerId': number, 'kind': 'book', 'title': title,
            'aliases': names[1:], 'authors': authors(record.get('Authors')), 'language': language[0] if language else 'und',
            'genres': list(dict.fromkeys(s for s in subjects if s))[:MAX_SUBJECTS], 'tags': [], 'ids': {'gutenberg': number},
            'sourceUrl': 'https://www.gutenberg.org/ebooks/' + number,
            # Gutenberg's own cover of every ebook; the client loads it only when the card is shown.
            'cover': f'https://www.gutenberg.org/cache/epub/{number}/pg{number}.cover.medium.jpg'}


def read(path, offset=0, limit=PAGE):
    """Up to `limit` text rows from the byte offset; (rows, next offset or None at the end)."""
    with open(path, 'rb') as handle:
        header = next(csv.reader([handle.readline().decode('utf-8-sig', errors='replace')]), [])
        if not all(column in header for column in COLUMNS):
            raise SourceError('Каталог Project Gutenberg изменил формат.')
        start = max(offset, handle.tell())
        handle.seek(start)
        position = [start]
        rows = []
        for values in csv.reader(_lines(handle, position)):
            row = book_row(dict(zip(header, values)))
            if row:
                rows.append(row)
                if len(rows) >= limit:
                    return rows, position[0]
        return rows, None


def count(path):
    """Text rows of the saved feed (the run's expected total)."""
    with open(path, encoding='utf-8-sig', errors='replace', newline='') as handle:
        return sum(1 for record in csv.DictReader(handle) if record.get('Type', '').strip() == 'Text')


def catalogue(spec, cursor, *, get=requests.get):
    page = int(cursor.get('page', 1))
    path = feed_path()
    total = None
    if page == 1 or not path.exists() or cursor.get('stamp') != stamp(path):
        if page == 1 or not path.exists():
            download(path, get)
            total = count(path)
        cursor = {'offset': 0}
    rows, offset = read(path, int(cursor.get('offset') or 0))
    return {'rows': rows, 'next': {'page': page + 1, 'offset': offset, 'stamp': stamp(path)} if offset is not None else None,
            'total': total}
