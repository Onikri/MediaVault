"""Public-domain book texts (Gutenberg, Wikisource): parsing and routing, offline.

The HTML snippets reproduce the markup seen live on 2026-11-08: Gutenberg's
illustrated headings with captions and page numbers, Wikisource chapters as
<center> numerals and <div role="heading">, and Gutenberg's OPDS search feed.
"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import book_sources as bs
from source_parser import SourceError

GUTENBERG_HTML = """<html lang="en"><head><title>Pride and Prejudice | Project Gutenberg</title>
<meta name="dc.title" content="Pride and Prejudice"><meta name="dc.creator" content="Austen, Jane, 1775-1817"><meta name="dc.language" content="en"></head>
<body><section class="pg-boilerplate" id="pg-header"><p>The Project Gutenberg eBook of Pride and Prejudice</p></section>
<h1>PRIDE AND PREJUDICE</h1><p class="toc"><a href="#CHAPTER_I">Chapter I.</a></p>
<h2><a id="CHAPTER_I"></a>Chapter I.</h2><p>It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife.</p>
<p><span class="pagenum"><a id="page_6">{6}</a></span></p>
<div class="figcenter"><img src="i.jpg"><div class="caption"><p>Mr. &amp; Mrs. Bennet</p></div></div>
<h2><a id="CHAPTER_II"></a><img src="h.jpg"><span class="caption">I hope Mr. Bingley will like it.</span><br><br>CHAPTER II.</h2>
<p>Mr. Bennet was among the earliest of those who waited on Mr. Bingley.</p><p>* * * * *</p>
<section class="pg-boilerplate" id="pg-footer"><p>End of the Project Gutenberg EBook</p></section></body></html>"""

WIKISOURCE_HTML = """<html><body><section><div class="ws-noexport">Шаблон заголовка</div>
<div role="heading" aria-level="3">ЧАСТЬ ПЕРВАЯ.</div><center>I.</center>
<p>— Eh bien, mon prince, — сказала Анна Павловна.</p><p>Так говорила в июле 1805 года известная Анна Павловна Шерер.</p>
<center>————</center><div role="heading" aria-level="3">II.</div>
<p>Гостиная Анны Павловны начала понемногу наполняться.<sup class="reference">[1]</sup></p>
<a rel="mw:WikiLink" href="./Война_и_мир_(Толстой)/Том_2">Том 2</a></section></body></html>"""

OPDS = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>https://www.gutenberg.org/ebooks/1342.opds</id><title>Pride and Prejudice</title><content type="text">Jane Austen</content></entry>
<entry><id>https://www.gutenberg.org/ebooks/37431.opds</id><title>Pride and Prejudice, a play</title><content type="text">Helen Jerome</content></entry>
<entry><id>https://www.gutenberg.org/ebooks/99.opds</id><title>Sense and Sensibility</title><content type="text">Jane Austen</content></entry>
</feed>"""


class Chapters(unittest.TestCase):
    def test_gutenberg_headings_drop_captions_page_numbers_and_boilerplate(self):
        chapters = bs._chapters_from_html(GUTENBERG_HTML)
        self.assertEqual([c['title'] for c in chapters], ['Chapter I.', 'CHAPTER II.'])
        self.assertEqual(chapters[0]['paragraphs'], ['It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife.'])
        text = ' '.join(p for c in chapters for p in c['paragraphs'])
        self.assertNotIn('Project Gutenberg', text)
        self.assertNotIn('Bennet</', text)
        self.assertNotIn('{6}', text)
        self.assertNotIn('* * *', text)

    def test_wikisource_center_numerals_and_role_headings_split_chapters(self):
        chapters = bs._chapters_from_html(WIKISOURCE_HTML)
        self.assertEqual([c['title'] for c in chapters], ['ЧАСТЬ ПЕРВАЯ. · I.', 'II.'])
        self.assertEqual(len(chapters[0]['paragraphs']), 2)
        self.assertEqual(chapters[1]['paragraphs'], ['Гостиная Анны Павловны начала понемногу наполняться.'])

    def test_long_text_without_headings_is_split_into_parts(self):
        html = '<body>' + ''.join(f'<p>Абзац номер {i}.</p>' for i in range(300)) + '</body>'
        chapters = bs._chapters_from_html(html)
        self.assertEqual(len(chapters), 3)
        self.assertTrue(chapters[0]['title'].endswith('часть 1'))
        self.assertEqual(sum(len(c['paragraphs']) for c in chapters), 300)

    def test_wikisource_subpages_are_found_in_order(self):
        self.assertEqual(bs._subpages(WIKISOURCE_HTML, 'Война_и_мир_(Толстой)'), [('Война_и_мир_(Толстой)/Том_2', 'Том 2')])


class Search(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.original = bs._get
        bs._cache.clear()

    def tearDown(self):
        bs._get = self.original
        bs._cache.clear()

    def test_gutenberg_opds_matches_title_and_author(self):
        def fake(url, *, params=None, accept=''):
            self.calls.append((url, params))
            return OPDS
        bs._get = fake
        found = bs._gutenberg_search({'title': 'Pride and Prejudice', 'aliases': ['Гордость и предубеждение'], 'authors': ['Jane Austen']}, ['ru', 'uk', 'en'])
        self.assertEqual([r['url'] for r in found], ['https://www.gutenberg.org/ebooks/1342'])
        self.assertEqual(self.calls[0][0], 'https://www.gutenberg.org/ebooks/search.opds/')
        bs._gutenberg_search({'title': 'Pride and Prejudice'}, ['ru'])
        self.assertTrue(self.calls[-1][1]['query'].endswith(' l.ru'))

    def test_wikisource_prefers_author_page_and_skips_subpages_and_old_spelling(self):
        rows = {'query': {'search': [{'title': 'Пиковая дама'}, {'title': 'Пиковая дама (Пушкин)'}, {'title': 'Пиковая дама (Пушкин)/ДО'},
                                     {'title': 'Пиковая дама (Пушкин)/Глава I'}, {'title': 'Пиковая дама (Чайковский)'}]}}
        bs._get = lambda url, **_: __import__('json').dumps(rows)
        found = bs._wikisource_search({'title': 'Пиковая дама', 'authors': ['Александр Пушкин']}, 'ru')
        self.assertEqual([r['title'] for r in found], ['Пиковая дама (Пушкин)'])

    def test_search_reports_unavailable_libraries_without_failing(self):
        def broken(url, **_):
            raise SourceError('Библиотека сейчас недоступна.')
        bs._get = broken
        value = bs.search({'title': 'Война и мир', 'kind': 'book'}, 'ru')
        self.assertEqual(value['results'], [])
        self.assertEqual({p['status'] for p in value['providers']}, {'unavailable'})
        self.assertEqual([p['provider'] for p in value['providers']], ['gutenberg', 'wikisource-ru'])

    def test_audio_only_entry_does_not_shadow_a_readable_edition(self):
        bs._get = lambda *args, **kwargs: OPDS.replace(
            '<content type="text">Jane Austen</content></entry>',
            '<content type="text">Jane Austen</content><link rel="http://opds-spec.org/acquisition" type="audio/mpeg"/></entry>',
            1)
        self.assertEqual(bs._gutenberg_search({'title': 'Pride and Prejudice', 'authors': ['Jane Austen']}, ['en']), [])

    def test_gutenberg_falls_back_to_readable_plain_text(self):
        def fake(url, **kwargs):
            if not url.endswith('.txt.utf-8'):
                raise bs.MissingBook('404')
            return 'Title: A Japanese book\nLanguage: Japanese\n*** START OF THE PROJECT GUTENBERG EBOOK BOOK ***\n\n第一章。\n\n本文。\n\n*** END OF THE PROJECT GUTENBERG EBOOK BOOK ***'
        bs._get = fake
        data = bs._gutenberg_book('123')
        self.assertEqual(data['language'], 'ja')
        self.assertEqual(data['chapters'][0]['paragraphs'], ['第一章。', '本文。'])


class Routing(unittest.TestCase):
    def test_routes_accept_only_book_pages(self):
        self.assertEqual(bs.route('https://www.gutenberg.org/ebooks/1342'), ('gutenberg', '1342', ''))
        self.assertEqual(bs.route('https://www.gutenberg.org/ebooks/1342?mv_chapter=3'), ('gutenberg', '1342', '3'))
        self.assertEqual(bs.route('https://uk.wikisource.org/wiki/%D0%9A%D0%BE%D0%B1%D0%B7%D0%B0%D1%80'), ('wikisource-uk', 'Кобзар', ''))
        self.assertIsNone(bs.route('https://ranobehub.org/ranobe/1'))
        self.assertIsNone(bs.route('http://www.gutenberg.org/ebooks/1342'))
        with self.assertRaises(SourceError):
            bs.route('https://ru.wikisource.org/wiki/Служебная:Поиск')
        with self.assertRaises(SourceError):
            bs.route('https://www.gutenberg.org/ebooks/1342?mv_chapter=x')

    def test_only_library_hosts_are_contacted(self):
        with self.assertRaises(SourceError):
            bs._get('https://example.com/book.html')

    def test_inspect_and_chapter_share_ranobe_endpoints(self):
        import ranobe_sources
        original = bs._get
        bs._cache.clear()
        bs._get = lambda url, **_: GUTENBERG_HTML
        try:
            book = ranobe_sources.inspect('https://www.gutenberg.org/ebooks/1342')
            self.assertEqual((book['title'], book['language'], book['kind']), ('Pride and Prejudice', 'en', 'book'))
            self.assertEqual([e['title'] for e in book['episodes']], ['Chapter I.', 'CHAPTER II.'])
            text = ranobe_sources.chapter(book['episodes'][1]['url'])
            self.assertEqual(text['paragraphs'], ['Mr. Bennet was among the earliest of those who waited on Mr. Bingley.'])
            with self.assertRaises(SourceError):
                ranobe_sources.chapter('https://www.gutenberg.org/ebooks/1342?mv_chapter=9')
        finally:
            bs._get = original
            bs._cache.clear()


if __name__ == '__main__':
    unittest.main()
