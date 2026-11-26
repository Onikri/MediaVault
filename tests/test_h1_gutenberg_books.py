"""H1: Open Library cards open full texts (Gutenberg index, exact ids, Standard Ebooks, public scans); no network.

The CSV rows follow pg_catalog.csv (Text#, Type, Issued, Title, Language,
Authors, Subjects, LoCC, Bookshelves): multi-line titles, author life dates and
roles, audio entries. The Standard Ebooks page reproduces the single-page
XHTML layout (title page, imprint, hgroup headings, noterefs, colophon).
"""
import json, os, sqlite3, sys, tempfile, threading, time, unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import book_sources as bs
import catalogue_gutenberg as pg
import content_catalog
import content_names
from source_parser import SourceError, SourceRateLimitError

POLICY = {'schemaVersion': 1, 'tags': [], 'includeDiscovered': True, 'excludedTerms': [], 'excludedPrefixes': [], 'hiddenTags': []}
CSV = ('﻿Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves\r\n'
       '1342,Text,1998-06-01,Pride and Prejudice,en,"Austen, Jane, 1775-1817","Courtship -- Fiction; England -- Fiction; Love stories",PR,Best Books Ever Listings\r\n'
       '84,Text,1993-10-01,"Frankenstein; Or, The Modern Prometheus",en,"Shelley, Mary Wollstonecraft, 1797-1851","Science fiction; Monsters -- Fiction",PR,Gothic Fiction\r\n'
       '19033,Sound,2006-08-15,Pride and Prejudice,en,"Austen, Jane, 1775-1817",,,\r\n'
       '2600,Text,2001-04-01,"War and Peace\nBook One",en,"Tolstoy, Leo, graf, 1828-1910; Maude, Louise, 1855-1939 [Translator]",Napoleonic Wars -- Fiction,PG,\r\n'
       '43,Text,1992-11-01,Pride and Prejudice,en,"Smith, Adam, 1900-1980",,,\r\n'
       '120,Text,1994-02-01,Ulysses,en,"Joyce, James, 1882-1941",,,\r\n')
STANDARD_PAGE = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en-GB"><head><title>Pride and Prejudice - Standard Ebooks</title></head>
<body><section id="titlepage" epub:type="titlepage"><h1 epub:type="title">Pride and Prejudice</h1><p>By <b epub:type="z3998:author">Jane Austen</b>.</p></section>
<section id="imprint" epub:type="imprint"><p>This ebook is the product of many hours of hard work by volunteers for Standard Ebooks.</p></section>
<nav id="toc" epub:type="toc"><ol><li><a href="#chapter-1">I</a></li></ol></nav>
<section id="chapter-1" epub:type="chapter"><hgroup><h2 epub:type="ordinal z3998:roman">I</h2><p epub:type="title">In Which a Truth Is Acknowledged</p></hgroup>
<p>It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife.<a href="#note-1" id="noteref-1" epub:type="noteref">1</a></p></section>
<section id="chapter-2" epub:type="chapter"><h2 epub:type="ordinal z3998:roman">II</h2><p>Mr. Bennet was among the earliest of those who waited on Mr. Bingley.</p></section>
<section id="endnotes" epub:type="endnotes"><ol><li id="note-1"><p>An endnote.</p></li></ol></section>
<section id="colophon" epub:type="colophon"><p>Pride and Prejudice was published in 1813.</p></section></body></html>"""
SCAN = """PRIDE AND PREJUDICE

CHAPTER I.

It is a truth universally acknowledged, that a single man in pos-
session of a good fortune must be in want of a wife.

12

However little known the feelings or views
of such a man may be.

CHAPTER II.

Mr. Bennet was among the earliest of those who waited on Mr. Bingley.
"""


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status_code, self.headers = body.encode('utf-8'), status, headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]


class Feed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'pg_catalog.csv'
        self.path.write_bytes(CSV.encode('utf-8'))

    def test_csv_rows_become_book_rows_and_only_texts_are_kept(self):
        rows, offset = pg.read(self.path, 0)
        self.assertIsNone(offset)
        self.assertEqual([r['providerId'] for r in rows], ['1342', '84', '2600', '43', '120'])
        pride = rows[0]
        self.assertEqual({k: pride[k] for k in ('id', 'provider', 'kind', 'title', 'authors', 'language', 'ids', 'sourceUrl')},
                         {'id': 'gutenberg:1342', 'provider': 'gutenberg', 'kind': 'book', 'title': 'Pride and Prejudice', 'authors': ['Jane Austen'],
                          'language': 'en', 'ids': {'gutenberg': '1342'}, 'sourceUrl': 'https://www.gutenberg.org/ebooks/1342'})
        self.assertEqual(pride['genres'], ['Courtship -- Fiction', 'England -- Fiction', 'Love stories'])
        self.assertEqual(rows[1]['aliases'], ['Frankenstein'])
        # A translator is not the writer; a two-line title is one title.
        self.assertEqual((rows[2]['title'], rows[2]['authors'], rows[2]['aliases']), ('War and Peace Book One', ['Leo Tolstoy'], ['War and Peace']))

    def test_pages_continue_at_the_saved_offset(self):
        first, offset = pg.read(self.path, 0, limit=2)
        second, end = pg.read(self.path, offset, limit=2)
        third, last = pg.read(self.path, end, limit=2)
        self.assertEqual([r['providerId'] for r in first + second + third], ['1342', '84', '2600', '43', '120'])
        self.assertIsNone(last)

    def test_weekly_run_downloads_once_and_walks_the_saved_file(self):
        calls = []
        def get(url, **kw):
            calls.append(url)
            return Response(CSV)
        with patch.dict(os.environ, {'DATA_DIR': self.tmp.name}), patch.object(pg, 'PAGE', 2):
            page = pg.catalogue({}, {'page': 1}, get=get)
            self.assertEqual(page['total'], 5)
            pages = [page]
            while pages[-1]['next']:
                pages.append(pg.catalogue({}, pages[-1]['next'], get=get))
        self.assertEqual(calls, [pg.FEED])
        self.assertEqual([r['providerId'] for p in pages for r in p['rows']], ['1342', '84', '2600', '43', '120'])

    def test_maintenance_page_or_busy_answer_is_never_indexed(self):
        target = Path(self.tmp.name) / 'feeds' / 'pg_catalog.csv'
        with self.assertRaises(SourceError):
            pg.download(target, lambda url, **kw: Response('<!DOCTYPE html><title>Temporarily Down for Maintenance</title>'))
        with self.assertRaises(SourceRateLimitError):
            pg.download(target, lambda url, **kw: Response('down', 503, {'Retry-After': '21600'}))
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix('.part').exists())

    def test_two_weekly_runs_of_the_indexer_job_keep_one_row_per_book(self):
        import catalogue_indexer
        from manga_catalog_index import initialize
        db = sqlite3.connect(':memory:', check_same_thread=False); initialize(db); db.commit()
        self.addCleanup(db.close)
        policy = Path(self.tmp.name) / 'policy.json'; policy.write_text(json.dumps(POLICY), encoding='utf-8')
        clock, calls = [1000.0], []
        def get(url, **kw):
            calls.append(url)
            return Response(CSV)
        spec = {'type': 'gutenberg', 'kind': 'book', 'domain': 'www.gutenberg.org', 'name': 'Книги · Project Gutenberg'}
        with patch.dict(os.environ, {'DATA_DIR': self.tmp.name, 'MANGA_TAG_POLICY_FILE': str(policy), 'MEDIA_VAULT_DISABLE_WORKER': '1'}), patch.object(pg, 'PAGE', 2):
            worker = catalogue_indexer.Indexer(SimpleNamespace(db=db, lock=threading.RLock()), lambda s, c: pg.catalogue(s, c, get=get), lambda: clock[0], interval=0)
            with db:
                key = worker.enqueue(spec)
            for week in range(2):
                for _ in range(10):
                    clock[0] += 3
                    worker.run_once()
                    if db.execute('SELECT state FROM catalogue_jobs WHERE id=?', (key,)).fetchone()[0] == 'done':
                        break
                self.assertEqual(db.execute('SELECT state,records,expected FROM catalogue_jobs WHERE id=?', (key,)).fetchone(), ('done', 5, 5))
                clock[0] += 7 * 86400 + 1
        self.assertEqual(len(calls), 2)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM content_titles WHERE json_extract(raw,'$.provider')='gutenberg'").fetchone()[0], 5)

    def test_indexer_lists_the_weekly_gutenberg_job(self):
        import catalogue_indexer, catalogue_sources
        self.assertEqual(catalogue_indexer.refresh_interval({'type': 'gutenberg'}), 7 * 86400)
        with patch('catalogue_gutenberg.catalogue', return_value={'rows': [], 'next': None}) as run:
            catalogue_sources.fetch({'type': 'gutenberg', 'kind': 'book', 'domain': 'www.gutenberg.org'}, {'page': 1})
        run.assert_called_once()


class Index(unittest.TestCase):
    """content_titles in a temporary SQLite database, read through the catalogue reader."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        policy = Path(self.tmp.name) / 'policy.json'; policy.write_text(json.dumps(POLICY), encoding='utf-8')
        env = patch.dict(os.environ, {'MANGA_TAG_POLICY_FILE': str(policy), 'DATA_DIR': self.tmp.name}); env.start(); self.addCleanup(env.stop)
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        reader = contextmanager(lambda _store: (yield self.db))
        for guard in (patch('manga_discovery.manager'), patch('manga_discovery.catalogue_reader', reader)):
            guard.start(); self.addCleanup(guard.stop)
        path = Path(self.tmp.name) / 'pg_catalog.csv'; path.write_bytes(CSV.encode('utf-8'))
        self.rows, _ = pg.read(path, 0)
        self.ingest(self.rows)
        self.calls = []
        self.original = bs._get
        bs._cache.clear(); bs._running.clear()
        self.addCleanup(self.restore)

    def restore(self):
        bs._get = self.original
        bs._cache.clear()

    def ingest(self, rows):
        with self.db:
            return content_catalog.ingest(self.db, rows)

    def fake(self, answers):
        def get(url, *, params=None, accept=''):
            self.calls.append((url, params))
            for prefix, value in answers.items():
                if url.startswith(prefix):
                    if isinstance(value, Exception):
                        raise value
                    return value if isinstance(value, str) else json.dumps(value)
            raise SourceError('Библиотека сейчас недоступна.')
        bs._get = get

    def wait(self):
        deadline = time.monotonic() + 5
        while bs._running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(bs._running)

    def test_repeated_weekly_run_rewrites_the_same_rows(self):
        count = lambda: self.db.execute("SELECT COUNT(*) FROM content_titles WHERE json_extract(raw,'$.provider')='gutenberg'").fetchone()[0]
        self.assertEqual(count(), 5)
        self.assertEqual(self.ingest(self.rows), 5)
        self.assertEqual(count(), 5)
        names = self.db.execute("SELECT COUNT(*) FROM content_names WHERE kind='book'").fetchone()[0]
        self.ingest(self.rows)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM content_names WHERE kind='book'").fetchone()[0], names)
        stored = json.loads(self.db.execute("SELECT raw FROM content_titles WHERE json_extract(raw,'$.providerId')='1342'").fetchone()[0])
        self.assertEqual((stored['authors'], stored['ids'], stored['language']), (['Jane Austen'], {'gutenberg': '1342'}, 'en'))

    def test_existing_catalogue_fills_the_book_names_once(self):
        with self.db:
            self.db.execute("DELETE FROM content_names WHERE kind='book'")
            state = json.loads(self.db.execute("SELECT value FROM content_catalog_state WHERE name='content-names'").fetchone()[0])
            self.db.execute("UPDATE content_catalog_state SET value=? WHERE name='content-names'", (json.dumps({**state, 'filled': ['anime', 'ranobe']}),))
        self.assertEqual(content_names.pending(self.db), ['book'])
        store = SimpleNamespace(lock=threading.RLock(), db=self.db)
        while content_names.step(store):
            pass
        self.assertEqual(sorted(r['providerId'] for r in content_names.lookup(self.db, 'book', ['Pride and Prejudice'])), ['1342', '43'])

    def test_open_library_card_with_a_gutenberg_id_gets_the_book_without_a_title_search(self):
        self.fake({bs.OPENLIBRARY_SEARCH: {'docs': [{'key': '/works/OL66554W', 'title': 'Pride and Prejudice', 'author_name': ['Jane Austen'],
                                                     'id_project_gutenberg': ['1342', '42671'], 'ebook_access': 'public', 'ia': ['prideprejudice00aust']}]}})
        card = {'id': 'openlibrary:OL66554W', 'kind': 'book', 'title': 'Гордость и предубеждение', 'ids': {'openlibrary': 'OL66554W'}, 'year': 1813}
        started = time.monotonic()
        first = bs.search(card, 'ru')
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(first['pending'])
        self.assertEqual(first['fallback'], 'all')
        self.assertEqual([(r['url'], r['matchEvidence'], r['language']) for r in first['results']],
                         [('https://www.gutenberg.org/ebooks/1342', 'external_id', 'en'), ('https://www.gutenberg.org/ebooks/42671', 'external_id', 'und')])
        self.assertEqual(self.calls[0][1]['q'], 'key:/works/OL66554W')
        self.assertIn('id_project_gutenberg', self.calls[0][1]['fields'])
        self.wait()
        # The live search asked Wikisource, never Gutenberg's title search.
        self.assertFalse([u for u, _ in self.calls if 'gutenberg.org' in u])
        self.assertFalse([u for u, _ in self.calls if 'archive.org' in u])
        final = bs.search(card, 'ru')
        self.assertEqual(set(final), {'results', 'providers', 'language', 'checkedAt', 'fallback'})
        self.assertEqual(final['results'][0]['url'], 'https://www.gutenberg.org/ebooks/1342')
        self.assertEqual({p['provider']: p['status'] for p in final['providers']}['gutenberg'], 'ok')

    def test_index_matches_title_and_author_but_not_the_same_title_by_another_writer(self):
        self.fake({})
        card = {'id': 'openlibrary:OL1W', 'kind': 'book', 'title': 'Pride and Prejudice', 'authors': ['Jane Austen'], 'year': 1813}
        found = bs._fast(card, {})
        self.assertEqual([(r['url'], r['matchEvidence']) for r in found], [('https://www.gutenberg.org/ebooks/1342', 'exact_title')])
        self.assertEqual(bs._fast({**card, 'authors': ['Helen Jerome']}, {}), [])
        # Without an author there is no index match at all.
        self.assertEqual(bs._fast({**card, 'authors': []}, {}), [])
        # A spelling of the same surname; a subtitle-less name.
        self.assertEqual([r['url'] for r in bs._fast({'title': 'War and Peace', 'authors': ['Lev Tolstoi'], 'kind': 'book'}, {})],
                         ['https://www.gutenberg.org/ebooks/2600'])
        self.assertEqual([r['url'] for r in bs._fast({'title': 'Frankenstein', 'authors': ['Mary Shelley'], 'kind': 'book'}, {})],
                         ['https://www.gutenberg.org/ebooks/84'])

    def test_card_without_any_known_book_answers_with_the_live_search_as_before(self):
        self.fake({'https://www.gutenberg.org/ebooks/search.opds/': '<feed></feed>', 'https://en.wikisource.org/': {'query': {'search': []}}})
        value = bs.search({'title': 'Unknown Book', 'authors': ['Nobody Known'], 'kind': 'book'}, 'en')
        self.assertEqual(set(value), {'results', 'providers', 'language', 'checkedAt'})
        self.assertEqual([p['provider'] for p in value['providers']], ['gutenberg', 'wikisource-en'])

    def test_ranobe_endpoint_keeps_its_answer_form_for_books(self):
        import ranobe_sources
        self.fake({bs.OPENLIBRARY_SEARCH: {'docs': [{'key': '/works/OL2W', 'id_project_gutenberg': ['120'], 'author_name': ['James Joyce']}]}})
        first = ranobe_sources.search({'title': 'Ulysses', 'ids': {'openlibrary': 'OL2W'}, 'kind': 'book'}, 'all')
        self.assertEqual(set(first), {'results', 'providers', 'language', 'checkedAt', 'pending'})
        self.assertEqual({k for r in first['results'] for k in r} >= {'provider', 'providerName', 'title', 'translator', 'url', 'language', 'kind'}, True)
        self.wait()
        self.assertEqual(set(ranobe_sources.search({'title': 'Ulysses', 'ids': {'openlibrary': 'OL2W'}, 'kind': 'book'}, 'all')),
                         {'results', 'providers', 'language', 'checkedAt'})


class StandardEbooks(unittest.TestCase):
    def setUp(self):
        self.original = bs._get; bs._cache.clear()
        self.addCleanup(lambda: (setattr(bs, '_get', self.original), bs._cache.clear()))

    def test_single_page_becomes_chapters_without_front_and_back_matter(self):
        calls = []
        bs._get = lambda url, **_: calls.append(url) or STANDARD_PAGE
        book = bs.inspect('https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice')
        self.assertEqual(calls, ['https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice/text/single-page'])
        self.assertEqual((book['provider'], book['providerName'], book['title'], book['authors'], book['language']),
                         ('standard-ebooks', 'Standard Ebooks', 'Pride and Prejudice', ['Jane Austen'], 'en'))
        self.assertEqual([e['title'] for e in book['episodes']], ['I · In Which a Truth Is Acknowledged', 'II'])
        text = bs.chapter(book['episodes'][0]['url'])
        self.assertEqual(text['paragraphs'], ['It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife.'])
        whole = ' '.join(p for i in range(2) for p in bs.chapter(book['episodes'][i]['url'])['paragraphs'])
        for frame in ('Standard Ebooks', 'endnote', 'published in 1813'):
            self.assertNotIn(frame, whole)

    def test_routes_accept_book_pages_only(self):
        self.assertEqual(bs.route('https://standardebooks.org/ebooks/leo-tolstoy/war-and-peace/louise-maude_aylmer-maude'),
                         ('standard-ebooks', 'leo-tolstoy/war-and-peace/louise-maude_aylmer-maude', ''))
        self.assertIsNone(bs.route('https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice/text/single-page'))
        self.assertIsNone(bs.route('https://standardebooks.org/feeds/opds'))
        self.assertEqual(bs.route('https://archive.org/details/prideprejudice00aust'), ('internet-archive', 'prideprejudice00aust', ''))


class InternetArchive(unittest.TestCase):
    def setUp(self):
        self.original = bs._get; bs._cache.clear(); self.calls = []
        self.addCleanup(lambda: (setattr(bs, '_get', self.original), bs._cache.clear()))

    def serve(self, restricted=False):
        def get(url, **_):
            self.calls.append(url)
            if url.endswith('/metadata'):
                return json.dumps({'result': {'title': 'Pride and prejudice', 'creator': 'Austen, Jane', 'language': 'eng', 'mediatype': 'texts',
                                              **({'access-restricted-item': 'true'} if restricted else {})}})
            if url.endswith('_djvu.txt'):
                return SCAN
            raise SourceError('Библиотека сейчас недоступна.')
        bs._get = get

    def test_public_scan_is_read_as_paragraphs_and_marked(self):
        self.serve()
        found = bs._fast({'title': 'Pride and Prejudice', 'kind': 'book'}, {'ia': ['prideprejudice00aust']})
        self.assertEqual([(r['provider'], r['url'], r['scan']) for r in found], [('internet-archive', 'https://archive.org/details/prideprejudice00aust', True)])
        book = bs.inspect(found[0]['url'])
        self.assertTrue(book['scan'])
        self.assertEqual(book['providerName'], 'Internet Archive · скан')
        # The title page of a scan stays a first part of its own.
        self.assertEqual([e['title'] for e in book['episodes']], ['Начало', 'CHAPTER I.', 'CHAPTER II.'])
        self.assertEqual(bs.chapter(book['episodes'][1]['url'])['paragraphs'],
                         ['It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife.',
                          'However little known the feelings or views of such a man may be.'])
        self.assertIn('https://archive.org/download/prideprejudice00aust/prideprejudice00aust_djvu.txt', self.calls)

    def test_lent_books_are_never_opened(self):
        self.serve(restricted=True)
        self.assertEqual(bs._fast({'title': 'Pride and Prejudice', 'kind': 'book'}, {'ia': ['prideprejudice00aust']}), [])
        with self.assertRaises(SourceError):
            bs.inspect('https://archive.org/details/prideprejudice00aust')
        self.assertFalse([u for u in self.calls if u.endswith('_djvu.txt')])
        # Open Library's borrowable work gives no item at all.
        bs._get = lambda url, **_: json.dumps({'docs': [{'key': '/works/OL3W', 'ia': ['lentbook00'], 'ebook_access': 'borrowable'}]})
        self.assertEqual(bs._catalogue_ids({'ids': {'openlibrary': 'OL3W'}})['ia'], [])

    def test_archive_storage_redirect_is_the_only_extra_host(self):
        self.assertTrue(bs.ARCHIVE_STORAGE.fullmatch('ia800300.us.archive.org'))
        self.assertTrue(bs.ARCHIVE_STORAGE.fullmatch('dn720003.ca.archive.org'))
        self.assertFalse(bs.ARCHIVE_STORAGE.fullmatch('archive.org.example.com'))
        with self.assertRaises(SourceError):
            self.original('https://ia800300.us.archive.org/1/items/x/x_djvu.txt')


if __name__ == '__main__':
    unittest.main()
