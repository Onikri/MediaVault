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
        table = ('12345', {0xa12})
        thumb = hitomi.image(page, table, thumbnail=True)
        self.assertTrue(hitomi_cover(thumb))
        self.assertFalse(hitomi_cover(thumb.replace('/webpbigtn/', '/other/')))
        self.assertIn('/12345/2578/', hitomi.image(page, table))
        self.assertEqual(image_extension(bytearray(b'\x00\x00\x00\x20ftypavif')), 'avif')
