"""HentaiChan search, episode selection and verified MP4 routing."""
from pathlib import Path
import sys
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from hentaichan_video import ROOT
from manga_sources import site_for as manga_site_for
from site_adapters import inspect_source, search_site, site_for
from source_parser import Resolver, SourceError

TITLE = ROOT + '/video/123-neutral.html'
EPISODE = ROOT + '/video/online/123-neutral.html?episode=3'
MEDIA = ROOT + '/uploads/files/video/test.mp4'
CATALOG = '<div class="content_row"><a class="title_link" href="/video/123-neutral.html">Neutral Series</a></div><div class="content_row"><a class="title_link" href="/manga/123-neutral.html">Neutral Manga</a></div>'
DETAIL = '<h1>Neutral Series</h1><a href="/video/online/123-neutral.html?episode=3">Episode 3</a><a href="/video/online/456-other.html?episode=8">Other series</a>'
PLAYER = '<script>new Uppod({uid:"hplayer",file:"/uploads/files/video/test.mp4",poster:"/uploads/files/video/test.mp4.jpg"});</script>'


class Http:
    def __init__(self, player=PLAYER):
        self.pages = {ROOT+'/video': CATALOG, TITLE: DETAIL, EPISODE: player}

    def document(self, url, **kwargs):
        return self.pages[url], url, {}

    def _open(self, url, *, headers, byte_range):
        assert (url, headers, byte_range) == (MEDIA, {'Referer': EPISODE}, 'bytes=0-1023')
        return mock.Mock(status_code=206, headers={'Content-Type': 'video/mp4', 'Content-Range': 'bytes 0-1023/9000'}), url


class VideoTests(TestCase):
    def test_search_and_normal_playback_path(self):
        http = Http()
        with mock.patch('hentaichan_video._cache', (0, ())):
            rows = search_site(site_for(TITLE), 'Neutral Series', http=http)['results']
        self.assertEqual([(row['url'], row['age']) for row in rows], [(TITLE, 18)])
        self.assertIsNone(manga_site_for(TITLE))
        result = inspect_source(rows[0]['url'], http=http)
        self.assertEqual([(e['number'], e['url']) for e in result['episodes']], [(3, EPISODE)])
        self.assertEqual(Resolver(http).resolve(EPISODE).streams[0]['url'], MEDIA)
        self.assertEqual(Resolver(http).resolve(TITLE).streams[0]['url'], MEDIA)

    def test_untrusted_stream_is_rejected(self):
        with self.assertRaises(SourceError):
            Resolver(Http(PLAYER.replace('/uploads/files/video/test.mp4', 'https://other.example/video.mp4'))).resolve(EPISODE)
