import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import run_import  # noqa: E402
from source_parser import SourceError  # noqa: E402


class RanobeDriveTextTests(unittest.TestCase):
    """The VM writes ranobe chapters through the reader's own adapters."""

    def with_chapter(self, chapter):
        module = types.ModuleType('ranobe_sources')
        module.chapter = chapter
        previous = sys.modules.get('ranobe_sources')
        sys.modules['ranobe_sources'] = module
        self.addCleanup(lambda: sys.modules.__setitem__('ranobe_sources', previous) if previous else sys.modules.pop('ranobe_sources', None))

    def test_adapter_paragraphs_become_the_chapter_file(self):
        self.with_chapter(lambda url: {'title': 'Глава 3. Ночь', 'paragraphs': ['Первый абзац.', {'text': 'Второй абзац.'}, '']})
        with tempfile.TemporaryDirectory() as folder:
            path = run_import.download_text('https://ranobehub.org/ranobe/1/1/3', folder, http=None)
            self.assertEqual(path.read_text(encoding='utf-8'), 'Глава 3. Ночь\n\nПервый абзац.\n\nВторой абзац.')

    def test_chapter_of_another_book_is_refused_not_replaced(self):
        def wrong(url):
            raise SourceError('Глава относится к другой книге.')
        self.with_chapter(wrong)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(SourceError):
            run_import.download_text('https://ranobehub.org/ranobe/1/1/3', folder, http=None)

    def test_unknown_page_falls_back_to_article_text(self):
        def unknown(url):
            raise SourceError('Неизвестный источник ранобэ.')
        self.with_chapter(unknown)
        article = '<html><body><article>' + 'Текст главы. ' * 20 + '</article></body></html>'
        http = types.SimpleNamespace(document=lambda url: (article, None, None))
        with tempfile.TemporaryDirectory() as folder:
            path = run_import.download_text('https://example.org/chapter', folder, http)
            self.assertTrue(path.read_text(encoding='utf-8').startswith('Текст главы.'))


if __name__ == '__main__':
    unittest.main()
