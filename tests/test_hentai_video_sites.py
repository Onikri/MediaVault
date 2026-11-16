"""Native hentai video adapters on synthetic pages shaped like the sites' public HTML."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import hentai_video_sites as sites
from dynamic_video_sources import inspect, provider_for, resolve_dynamic
from source_parser import SourceError


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def document(self, url, *, headers=None, method='GET', data=None, **_):
        self.calls.append((method, url, data, headers))
        key = (method, url) if (method, url) in self.pages else url
        if key not in self.pages:
            raise SourceError('missing fixture ' + url)
        value = self.pages[key]
        return (value, url, {}) if isinstance(value, str) else (value[0], value[1], {})


def hanime1_card(v, title):
    return (f'<div class="horizontal-card"><a class="video-link" href="https://hanime1.me/watch?v={v}">'
            f'<div class="thumb-container"><img class="main-thumb" src="https://vdownload.hembed.com/image/{v}.jpg">'
            f'<div class="stats-container">07:10</div></div><div class="title">{title}</div></a></div>')


def playlist_card(v, title):
    return (f'<div class="playlist-video-card video-item-container"><div class="video-thumb-container horizontal-card">'
            f'<div class="thumb-container"><a href="https://hanime1.me/watch?v={v}"><img class="main-thumb" src="https://vdownload.hembed.com/t/{v}.jpg">'
            f'<div class="stats-container"><div class="stat-item">thumb_up 100%</div></div></a></div></div>'
            f'<div class="video-info-container"><h4 class="video-title"><a href="https://hanime1.me/watch?v={v}">{title}</a></h4></div></div>')


SPONSOR = ('<div class="horizontal-card"><a class="video-link" href="https://ads.example/s/1"><div class="title">Sponsor</div></a>'
           '<div class="subtitle"><a href="https://ads.example/s/1">AD</a></div></div>')
HANIME1_SEARCH = ('<div class="horizontal-row">' + SPONSOR + hanime1_card(30, 'Garden Story 庭園 2')
                  + hanime1_card(10, 'Garden Story 庭園 1') + hanime1_card(77, 'Other Tale 3') + '</div>')
HANIME1_WATCH = ('<h3 id="shareBtn-title">ガーデン【第02話】 [中文字幕]</h3>'
                 '<video><source size="720" src="https://vdownload-7.hembed.com/30-720p.mp4?token=a&amp;expires=9">'
                 '<source size="1080" src="https://vdownload-7.hembed.com/30-1080p.mp4?token=b&amp;expires=9">'
                 '<source size="480" src="http://insecure.example/30.mp4"></video>'
                 '<div id="playlist-scroll">' + playlist_card(30, 'Garden Story 庭園 2') + playlist_card(10, 'Garden Story 庭園 1')
                 + playlist_card(77, 'Other Tale 3') + '</div>')

MAMA_SEARCH = ('<div class="search-results"><div class="dt-series-cards">'
               '<article class="series-card"><div class="sc-left"><a href="https://hentaimama.io/tvshows/garden-story/">'
               '<img src="https://hentaimama.io/wp-content/uploads/garden.jpg"></a></div><h3>Garden Story</h3></article>'
               '<article class="series-card"><a href="https://elsewhere.example/tvshows/x/"></a><h3>Elsewhere</h3></article></div></div>')
MAMA_SERIES = ('<h1>Garden Story</h1><ul>'
               '<li><a href="https://hentaimama.io/episodes/garden-story-episode-2/">EP 2</a></li>'
               '<li><a href="https://hentaimama.io/episodes/garden-story-episode-1/">EP 1</a></li>'
               '<li><a href="#episodes">Episodes</a></li></ul>')
MAMA_EPISODE = ('<a href="https://hentaimama.io/tvshows/garden-story/">Garden Story</a>'
                "<script>$.post(\"https://hentaimama.io/wp-admin/admin-ajax.php\", {action: 'get_player_contents',a: '7360',i: n}, f)</script>")
MAMA_AJAX = json.dumps(['<iframe src="https://hentaimama.io/?dt_embed=rtmp&#038;p=Ry9nYXJkZW4tMS5tcDQ=&#038;ep=7360"></iframe>', '', ''])
MAMA_EMBED = 'jwplayer("p").setup({sources: [{"file":"https:\\/\\/gdvid.info\\/G\\/garden-1.mp4","type":"mp4"}],advertising:{}})'


def ua_card(slug, title):
    return (f'<article class="card horizontal hentai_video translate_type-sub"><a href="https://hentai.com.ua/hentai_video/{slug}/">'
            f'<img src="https://hentai.com.ua/wp-content/uploads/{slug}.webp"></a><div class="card-body">'
            f'<a class="text-body text-decoration-none" href="https://hentai.com.ua/hentai_video/{slug}/"><h2>{title}</h2></a></div></article>')


UA_SEARCH = (ua_card('sad-2', 'Сад історій Серія 2 / Garden Story Episode 2') + ua_card('sad-1', 'Сад історій Серія 1 / Garden Story Episode 1')
             + ua_card('inshe', 'Інша казка :: Other Tale'))
UA_EPISODE = ('<h1>Сад історій Серія 2 / Garden Story Episode 2</h1>'
              '<button class="hv-player__tab is-active" data-src="https://hentai.com.ua/wp-content/uploads/2026/09/a.mp4" data-premium="0">1</button>'
              '<button class="hv-player__tab" data-src="https://hentai.com.ua/wp-content/uploads/2026/09/premium.mp4" data-premium="1">2</button>')


class HentaiVideoSitesTests(unittest.TestCase):
    def test_provider_for_accepts_only_series_and_episode_pages(self):
        self.assertEqual(provider_for('https://hanime1.me/watch?v=4430')[0], 'hanime1')
        self.assertEqual(provider_for('https://hentaimama.io/tvshows/garden-story/')[0], 'hentaimama')
        self.assertEqual(provider_for('https://hentaimama.io/episodes/garden-story-episode-1/')[0], 'hentaimama')
        self.assertEqual(provider_for('https://hentai.com.ua/hentai_video/sad-1/')[0], 'hentaicomua')
        for other in ['https://hanime1.me/search?query=x', 'https://hanime1.me/watch?v=abc', 'https://hentaimama.io/wp-login.php',
                      'https://hentai.com.ua/hentai-video-playlis/sad/', 'https://evil.example/watch?v=1']:
            self.assertIsNone(provider_for(other), other)

    def test_hanime1_groups_episodes_skips_sponsors_and_orders_qualities(self):
        http = FakeHttp({'https://hanime1.me/search?query=garden': HANIME1_SEARCH, 'https://hanime1.me/watch?v=30': HANIME1_WATCH})
        rows = sites.search('hanime1', 'garden', http)
        self.assertEqual([(r['title'], r['url'], r['episodes']) for r in rows],
                         [('Garden Story 庭園', 'https://hanime1.me/watch?v=10', 2), ('Other Tale', 'https://hanime1.me/watch?v=77', 1)])
        self.assertIn('Garden Story 庭園', rows[0]['aliases'])
        title, episodes = sites.episodes('hanime1', 'https://hanime1.me/watch?v=30', http)
        self.assertEqual(title, 'Garden Story 庭園')
        self.assertEqual([(e['number'], e['url']) for e in episodes], [(1, 'https://hanime1.me/watch?v=10'), (2, 'https://hanime1.me/watch?v=30')])
        streams = sites.streams('hanime1', 'https://hanime1.me/watch?v=30', http)
        self.assertEqual([(s['quality'], s['url']) for s in streams],
                         [(1080, 'https://vdownload-7.hembed.com/30-1080p.mp4?token=b&expires=9'),
                          (720, 'https://vdownload-7.hembed.com/30-720p.mp4?token=a&expires=9')])
        self.assertEqual(streams[0]['headers']['Referer'], 'https://hanime1.me/')

    def test_hentaimama_series_episodes_and_player_ajax(self):
        http = FakeHttp({'https://hentaimama.io/?s=garden': MAMA_SEARCH,
                         'https://hentaimama.io/tvshows/garden-story/': MAMA_SERIES,
                         'https://hentaimama.io/episodes/garden-story-episode-1/': MAMA_EPISODE,
                         ('POST', 'https://hentaimama.io/wp-admin/admin-ajax.php'): MAMA_AJAX,
                         'https://hentaimama.io/?dt_embed=rtmp&p=Ry9nYXJkZW4tMS5tcDQ=&ep=7360': MAMA_EMBED})
        rows = sites.search('hentaimama', 'garden', http)
        self.assertEqual([(r['title'], r['url']) for r in rows], [('Garden Story', 'https://hentaimama.io/tvshows/garden-story/')])
        title, episodes = sites.episodes('hentaimama', 'https://hentaimama.io/episodes/garden-story-episode-1/', http)
        self.assertEqual((title, [e['number'] for e in episodes]), ('Garden Story', [1, 2]))
        streams = sites.streams('hentaimama', 'https://hentaimama.io/episodes/garden-story-episode-1/', http)
        self.assertEqual([s['url'] for s in streams], ['https://gdvid.info/G/garden-1.mp4'])
        post = next(call for call in http.calls if call[0] == 'POST')
        self.assertEqual(post[2], {'action': 'get_player_contents', 'a': '7360', 'i': '1'})

    def test_hentai_com_ua_groups_series_and_never_offers_premium_tracks(self):
        search = 'https://hentai.com.ua/?post_type=hentai_video&s='
        http = FakeHttp({search + 'garden': UA_SEARCH, search + 'Garden+Story': UA_SEARCH,
                         'https://hentai.com.ua/hentai_video/sad-2/': UA_EPISODE})
        rows = sites.search('hentaicomua', 'garden', http)
        self.assertEqual([(r['title'], r['url'], r['episodes']) for r in rows],
                         [('Сад історій', 'https://hentai.com.ua/hentai_video/sad-1/', 2), ('Інша казка', 'https://hentai.com.ua/hentai_video/inshe/', 1)])
        self.assertEqual(rows[0]['aliases'], ['Сад історій', 'Garden Story'])
        title, episodes = sites.episodes('hentaicomua', 'https://hentai.com.ua/hentai_video/sad-2/', http)
        self.assertEqual((title, [(e['number'], e['url']) for e in episodes]),
                         ('Сад історій', [(1, 'https://hentai.com.ua/hentai_video/sad-1/'), (2, 'https://hentai.com.ua/hentai_video/sad-2/')]))
        streams = sites.streams('hentaicomua', 'https://hentai.com.ua/hentai_video/sad-2/', http)
        self.assertEqual([s['url'] for s in streams], ['https://hentai.com.ua/wp-content/uploads/2026/09/a.mp4'])

    def test_only_the_hentaimama_player_form_may_be_posted(self):
        from source_parser import PublicHttp
        http = PublicHttp(validate=lambda url: url)  # no DNS: the form check alone must refuse
        try:
            for data in [{'action': 'get_player_contents', 'a': '1; drop', 'i': '1'}, {'action': 'other', 'a': '1', 'i': '1'},
                         {'action': 'get_player_contents', 'a': '1', 'i': '1', 'extra': 'x'}]:
                with self.assertRaisesRegex(SourceError, 'POST'):
                    http.document('https://hentaimama.io/wp-admin/admin-ajax.php', method='POST', data=data)
        finally:
            http.close()

    def test_no_open_video_is_an_error_not_an_empty_player(self):
        http = FakeHttp({'https://hentai.com.ua/hentai_video/x/': '<h1>X</h1><button class="hv-player__tab" data-src="https://hentai.com.ua/p.mp4" data-premium="1"></button>'})
        with self.assertRaisesRegex(SourceError, 'не опубликовал'):
            sites.streams('hentaicomua', 'https://hentai.com.ua/hentai_video/x/', http)

    def test_dynamic_routing_inspects_and_resolves_through_the_native_adapter(self):
        http = FakeHttp({'https://hanime1.me/watch?v=30': HANIME1_WATCH})
        info = inspect('https://hanime1.me/watch?v=30', provider_for('https://hanime1.me/watch?v=30'), http)
        self.assertEqual((info['provider'], len(info['episodes'])), ('hanime1', 2))
        checked = []
        def check(_, stream, **__):
            checked.append(stream['quality'])
            if stream['quality'] == 1080:
                raise SourceError('expired')
        with patch('dynamic_video_sources.check_mp4', side_effect=check):
            page = resolve_dynamic(http, 'https://hanime1.me/watch?v=30', None, 'Hanime1 · JA', 'hanime1')
        self.assertEqual(checked, [1080, 720])
        self.assertEqual([s['quality'] for s in page.streams], [720])

    def test_sites_are_searchable_and_marked_as_hentai(self):
        from site_adapters import SITES, search_site
        from catalog_taxonomy import hentai_origin
        site = next(s for s in SITES if s.id == 'hentaicomua')
        with patch.dict(sites.SEARCH, {'hentaicomua': lambda query, http: [{'title': 'Сад'}]}):
            self.assertEqual(search_site(site, 'сад', http=object())['results'], [{'title': 'Сад'}])
        for provider, url in [('hanime1', 'https://hanime1.me/watch?v=1'), ('hentaimama', 'https://hentaimama.io/tvshows/a/'),
                              ('hentaicomua', 'https://hentai.com.ua/hentai_video/a/')]:
            self.assertTrue(hentai_origin(provider, url, 'anime'))


if __name__ == '__main__':
    unittest.main()
