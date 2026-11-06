"""HentaiChan search, episode selection and verified MP4 routing."""
from pathlib import Path
import sys
from unittest import TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from hentaichan_video import CATALOG, ROOT, open_media, refresh_catalog, search
from manga_sources import site_for as manga_site_for
from site_adapters import inspect_source, search_site, site_for
from source_discovery import discover
from source_parser import Resolver, SourceAccessError, SourceError, SourceTemporaryError

TITLE = ROOT + '/video/123-neutral.html'
EPISODE = ROOT + '/video/online/123-neutral.html?episode=3'
MEDIA = ROOT + '/uploads/files/video/test.mp4'
CATALOG_HTML = '<div class="content_row"><a class="title_link" href="/video/123-neutral.html">Neutral Series</a></div><div class="content_row"><a class="title_link" href="/manga/123-neutral.html">Neutral Manga</a></div>'
DETAIL = '<h1>Neutral Series</h1><a href="/video/online/123-neutral.html?episode=3">Episode 3</a><a href="/video/online/456-other.html?episode=8">Other series</a>'
PLAYER = '<script>new Uppod({uid:"hplayer",file:"/uploads/files/video/test.mp4",poster:"/uploads/files/video/test.mp4.jpg"});</script>'


class Http:
    def __init__(self, player=PLAYER):
        self.pages = {ROOT+'/video/': CATALOG_HTML, TITLE: DETAIL, EPISODE: player}

    def document(self, url, **kwargs):
        return self.pages[url], url, {}

    def _open(self, url, *, headers, byte_range, timeout=None):
        assert (url, headers, byte_range) == (MEDIA, {'Referer': EPISODE}, 'bytes=0-1023')
        return mock.Mock(status_code=206, headers={'Content-Type': 'video/mp4', 'Content-Range': 'bytes 0-1023/9000'}), url

    def close(self):
        pass


class VideoTests(TestCase):
    def setUp(self):
        self.enterContext(mock.patch('hentaichan_video._unavailable_until', {}))

    def test_search_and_normal_playback_path(self):
        http = Http()
        with mock.patch('hentaichan_video._catalog_rows', ()):
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

    def test_catalog_indexes_older_published_pages(self):
        http = Http()
        url = ROOT + CATALOG
        http.pages[url] += ''.join(f'<a href="/video/new?offset={n}">Page</a>' for n in (20, 40, 60))
        for offset in (20, 40, 60):
            http.pages[f'{ROOT}/video/new?offset={offset}'] = CATALOG_HTML.replace('123-neutral.html', f'{offset}-older.html').replace('Neutral Series', f'Older Series {offset}')
        with mock.patch('hentaichan_video._catalog_rows', ()), mock.patch('hentaichan_video.PublicHttp', return_value=http):
            self.assertTrue(refresh_catalog(mock.Mock(wait=mock.Mock(return_value=False))))
            self.assertEqual([row['title'] for row in search('Older Series 60', http)], ['Older Series 60'])

    def test_known_card_opens_its_attached_source(self):
        with mock.patch('source_discovery.inspect_source', wraps=lambda url, **_: inspect_source(url, http=Http())) as inspect:
            result = discover({'title': 'Local catalogue alias', 'kind': 'anime',
                               'provider': 'hentaichan-video', 'sourceURL': TITLE})
        inspect.assert_called_once_with(TITLE, kind='anime')
        self.assertFalse(result['pending'])
        self.assertEqual(result['voices'][0]['variants'][0]['episodes'][0]['url'], EPISODE)

    def test_mirror_retry_preserves_episode_and_range(self):
        mirror = 'https://x3.h-chan.me'
        mirror_episode = EPISODE.replace(ROOT, mirror)
        http = Http()
        http.document = mock.Mock(side_effect=[SourceTemporaryError('timeout'), (PLAYER, mirror_episode, {})])
        result = inspect_source(EPISODE, http=http)
        self.assertEqual(result['episodes'][0]['url'], mirror_episode)
        self.assertEqual(result['url'], result['dubs'][0]['url'])
        self.assertEqual(http.document.call_args.args[0], mirror_episode)

        media_mirror = MEDIA.replace(ROOT, mirror)
        response = mock.Mock(status_code=206, headers={'Content-Type': 'video/mp4', 'Content-Range': 'bytes 16-31/9000'})
        http._open = mock.Mock(side_effect=[SourceTemporaryError('timeout'), (response, media_mirror)])
        headers = {'Referer': EPISODE}
        self.assertEqual(open_media(http, MEDIA, headers=headers, byte_range='bytes=16-31'), (response, media_mirror))
        self.assertEqual(http._open.call_args, mock.call(media_mirror, headers=headers, byte_range='bytes=16-31', timeout=(3, 7)))
        http._open = mock.Mock(return_value=(response, media_mirror))
        open_media(http, MEDIA, headers=headers, byte_range='bytes=16-31')
        http._open.assert_called_once_with(media_mirror, headers=headers, byte_range='bytes=16-31', timeout=(3, 4))

    def test_access_denial_and_wrong_episode_are_not_accepted(self):
        http = Http()
        http.document = mock.Mock(side_effect=SourceAccessError('forbidden'))
        with self.assertRaises(SourceAccessError):
            inspect_source(EPISODE, http=http)
        http.document.assert_called_once()
        http.document = mock.Mock(return_value=(PLAYER, EPISODE.replace('episode=3', 'episode=1'), {}))
        with self.assertRaisesRegex(SourceError, 'другой эпизод'):
            Resolver(http).resolve(EPISODE)
