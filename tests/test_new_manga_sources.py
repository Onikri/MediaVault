"""Regression coverage for the two native manga adapters."""
from pathlib import Path
import json
import struct
import sys
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

import manga_hentaichan_cc as chan
import manga_hitomi as hitomi
from artwork import hitomi_cover
from manga_download import image_extension
from manga_sources import inspect
from source_parser import SourceError


class NativeMangaTests(TestCase):
    def test_chan_search_and_reader_use_public_cdn(self):
        http = mock.Mock()
        cover = 'https://cdn.hentaichan.cc/sample.webp'
        data = {'data': [{'name': 'Sample', 'slug': 'sample', 'src': cover}]}
        http.document.return_value = ('1:' + json.dumps(data), chan.ROOT + '/', {})
        row, = chan.search('Sample', http)
        self.assertEqual((row['cover'], row['url']), (cover, chan.ROOT + '/manga/sample'))
        chapter = chan.ROOT + '/read/sample-glava-2'
        detail = '<title>Read Sample online</title><h1>Sample</h1><a href="/read/sample-glava-2">Read</a>'
        http.document.return_value = (detail, row['url'], {})
        info = inspect(row['url'], http)
        self.assertEqual((info['title'], info['episodes'][0]['url']), (row['title'], chapter))
        bootstrap = 'setup();$_TSR.router={pages:$R[1]=[{originalSrc:"'+cover+'"}],ssr:"data-only"}'
        http.document.return_value = ('<script>'+bootstrap+'</script>', chapter, {})
        self.assertEqual(inspect(chapter, http)['pages'], [cover])
        http.document.return_value = ('<script>'+bootstrap.replace(chan.CDN, 'other.example')+'</script>', chapter, {})
        with self.assertRaises(SourceError):
            inspect(chapter, http)

    def test_hitomi_index_and_cover_paths(self):
        key = b'1234'
        node = struct.pack('>II4sIQI17Q', 1, 4, key, 1, 123, 8, *[0]*17)
        self.assertEqual(hitomi.decode_node(node)[:2], ([key], [(123, 8)]))
        with self.assertRaises(SourceError):
            hitomi.decode_node(node[:-1])
        page = {'hash': '0'*61+'12a', 'hasavif': 1}
        table = ('12345', 0, 1, {0xa12})
        thumb = hitomi.image(page, table, thumbnail=True)
        self.assertTrue(hitomi_cover(thumb))
        self.assertFalse(hitomi_cover(thumb.replace('/webpbigtn/', '/other/')))
        self.assertIn('/12345/2578/', hitomi.image(page, table))

    def test_hitomi_route_table_accepts_either_polarity(self):
        # gg.js as served in November 2026: listed shards use server 0, all others 1.
        flipped = ("gg = { m: function(g) {\nvar o = 1;\nswitch (g) {\ncase 2578:\ncase 6:\no = 0; break;\n}\nreturn o;\n},\n"
                   "s: function(h) { var m = /(..)(.)$/.exec(h); return parseInt(m[2]+m[1], 16).toString(10); },\nb: '1793973601/'\n};")
        table = hitomi.route_table(flipped)
        self.assertEqual(table, ('1793973601', 1, 0, frozenset({2578, 6})))
        listed = {'hash': '0'*61+'12a', 'hasavif': 1}
        other = {'hash': '0'*61+'13a'}
        self.assertTrue(hitomi.image(listed, table).startswith('https://a1.gold-usergeneratedcontent.net/1793973601/2578/'))
        self.assertTrue(hitomi.image(other, table).startswith('https://w2.gold-usergeneratedcontent.net/1793973601/2579/'))
        self.assertTrue(hitomi.image(other, table, thumbnail=True).startswith('https://btn.'))
        older = flipped.replace('var o = 1;', 'var o = 0;').replace('o = 0; break;', 'o = 1; break;')
        self.assertEqual(hitomi.route_table(older)[1:3], (0, 1))
        with self.assertRaises(SourceError):
            hitomi.route_table(flipped.replace('var o = 1;', 'var o = 2;'))
        self.assertEqual(image_extension(bytearray(b'\x00\x00\x00\x20ftypavif')), 'avif')
