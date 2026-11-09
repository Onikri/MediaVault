import json
import unittest
from urllib.parse import parse_qs, urlsplit

import ranobe_jp
from ranobe_sources import html_paragraphs
from source_parser import SourceError, public_url


class NarouSource(unittest.TestCase):
    def test_search_and_read_edition(self):
        class Http:
            def document(self, url, **options):
                if url.startswith(ranobe_jp.API):
                    row = {'title': '無職転生 - 異世界行ったら本気だす -', 'ncode': 'N9669BK',
                           'general_all_no': 286, 'noveltype': 1}
                    query = parse_qs(urlsplit(url).query)
                    if 'word' in query:
                        self.query = query
                    data = [{'allcount': 2}, row, {**row, 'title': '無職転生の別作品', 'ncode': 'N0123AA'}]
                    return json.dumps(data), url, 'application/json'
                text = '<h1 class="p-novel__title">始まり</h1><div class="p-novel__body"><div class="p-novel__text"><p><ruby>漢字<rt>かんじ</rt></ruby>の本文。</p></div></div>'
                return text, url, 'text/html'

        http = Http()
        matches = ranobe_jp.search({'title': 'Mushoku Tensei', 'titles': {'native': '無職転生'}}, http)
        self.assertEqual(http.query['order'], ['favnovelcnt'])
        self.assertEqual([row['url'] for row in matches], ['https://ncode.syosetu.com/n9669bk/'])
        book = ranobe_jp.inspect(matches[0]['url'], http)
        self.assertEqual(len(book['episodes']), 286)
        chapter = ranobe_jp.chapter(book['episodes'][0]['url'], http, html_paragraphs)
        self.assertEqual(chapter['paragraphs'], ['漢字の本文。'])

    def test_routes_only_open_public_works_and_specific_api(self):
        self.assertIsNone(ranobe_jp.route('https://novel18.syosetu.com/n9669bk/1/'))
        self.assertIsNone(ranobe_jp.route('https://ncode.syosetu.com.evil.test/n9669bk/1/'))
        self.assertEqual(public_url(ranobe_jp.API, resolve_dns=False), ranobe_jp.API)
        with self.assertRaises(SourceError):
            public_url('https://api.syosetu.com/private/api/', resolve_dns=False)
