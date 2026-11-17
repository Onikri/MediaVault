"""Discrepancies found by the both-path pilot (agent E): mirrors, paid chapters, page format."""

from io import BytesIO
from unittest import TestCase

from PIL import Image

import manga_ciaoplus
import manga_html_families
import manga_japan_routed
from manga_direct_payloads import JsonSeries
from source_parser import SourceAccessError, SourcePaidError


class Listed(JsonSeries):
    def __init__(self):
        super().__init__(('1', 'Listed', 'en', 'https://example.com', False), r'/t/(\w+)', r'/t/(\w+)/c/\w+')
        self.fetched = []

    def title_for(self, url):
        return 'https://example.com/t/' + self.chapter_key(url)

    def chapter_identity(self, url):
        return url.split('?')[0]

    def series(self, http, url):
        row = self.record('https://example.com/t/a', 'A')
        return row, [{**self.chapter('https://example.com/t/a/c/1', 'One', 1.0), 'locked': True},
                     {**self.chapter('https://example.com/t/a/c/2', 'Two', 2.0), 'locked': False}]

    def pages(self, http, url):
        self.fetched.append(url)
        return ['https://example.com/p.jpg']


class PilotDiscrepancyTests(TestCase):
    def test_manganato_accepts_the_manganami_mirror(self):
        adapter = next(a for a in manga_html_families.SOURCES if a.SOURCE_ID == '1024627298672457456')
        for url in ('https://www.manganami.com/manga/one-piece', 'https://www.manganami.com/search/story/one_piece'):
            self.assertTrue(adapter.site_link(url), url)
        self.assertTrue(adapter.is_title(adapter.site_link('https://www.manganami.com/manga/one-piece')))
        self.assertTrue(manga_html_families.public_api('www.manganami.com', '/api/manga/one-piece/chapters', 'limit=-1'))

    def test_paid_chapters_stay_listed_and_are_reported_not_fetched(self):
        adapter = Listed()
        detail = adapter.inspect('https://example.com/t/a', None)
        self.assertEqual([c['locked'] for c in detail['episodes']], [True, False])
        with self.assertRaises(SourcePaidError) as caught:
            adapter.inspect('https://example.com/t/a/c/1', None)
        self.assertIsInstance(caught.exception, SourceAccessError)
        self.assertEqual(adapter.fetched, [])
        self.assertEqual(adapter.inspect('https://example.com/t/a/c/2', None)['pages'], ['https://example.com/p.jpg'])

    def test_line_and_sokuyomi_keep_the_lock_rules(self):
        self.assertTrue(manga_japan_routed.line_locked({'selling_buy_price': 50}))
        self.assertFalse(manga_japan_routed.line_locked({'selling_buy_price': 0}))
        self.assertTrue(manga_japan_routed.soku_locked({'consumption_coin': 30}, 'coin'))
        self.assertFalse(manga_japan_routed.soku_locked({'consumption_coin': 0}, 'coin'))

    def test_ciao_plus_pages_are_jpeg(self):
        raw = BytesIO()
        Image.new('RGB', (64, 64), (200, 10, 10)).save(raw, 'PNG')
        page = manga_ciaoplus.CiaoPage(7, 2).decode(raw.getvalue())
        self.assertEqual(page[:3], b'\xff\xd8\xff')
