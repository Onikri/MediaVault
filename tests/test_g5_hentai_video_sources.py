"""G5: HentaiHaven and MioHentai in our player, from recorded answers; no network.

Fixtures are the sites' live public answers of 2026-11-26 (G5 recon), trimmed:
hentaihaven-search.json (cms.hentaihaven.xxx wp-manga search «overflow», the
fields the adapter asks for; the first entry «Overflow» is synthetic — that
answer stopped at 5 results), -releases.json, -chapters.json (the 8 episodes of
«Overflow»), -master.m3u8 (one episode's HLS master); miohentai-series.json
(series search «kuchibiru») and miohentai-post.html (the episode page's player
tag; the «up next» decoy is synthetic). The MioHentai post list is synthetic in
the shape of its REST answer.
"""
import json, sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import catalogue_hentaihaven, content_names, hentai_video_sites as sites, online_sessions, source_discovery
from dynamic_video_sources import catalogued_source, provider_for, resolve_dynamic
from site_adapters import BY_ID
from source_parser import SourceError, SourceListingEnd
from title_identity import match_title

FIXTURES = Path(__file__).parent / 'fixtures'
read = lambda name: (FIXTURES / name).read_text(encoding='utf-8')
CMS = 'https://cms.hentaihaven.xxx/wp-json/'
HH_SEARCH = CMS + 'wp/v2/wp-manga?search='
HH_YEARS = CMS + 'wp/v2/wp-manga-release?'
HH_CHAPTERS = CMS + 'hhaven/v1/manga/by-slug/overflow/chapters'
MASTER = 'https://octopusmanifest.org/70c8dbd7-3d5e-40f1-b83a-90ef7ffb0a0c/playlist.m3u8'
MIO_SERIES = 'https://miohentai.com/wp-json/wp/v2/series?'
MIO_POSTS = 'https://miohentai.com/wp-json/wp/v2/posts?'
POSTS = json.dumps([{'id': 274, 'date': '2023-01-29T16:09:04', 'title': {'rendered': 'Furueru Kuchibiru &#8211; Episode 1'}},
                    {'id': 8807, 'date': '2023-02-15T10:00:00', 'title': {'rendered': 'Furueru Kuchibiru &#8211; Episode 2'}}])
OVERFLOW = {'id': 'anilist:110209', 'kind': 'anime', 'year': 2020, 'format': 'ONA', 'title': 'Overflow',
            'titles': {'en': 'Overflow', 'native': 'オーバーフロー'}, 'aliases': ['Overflow', 'オーバーフロー'], 'adult': True}
KUCHIBIRU = {'id': 'anilist:20000', 'kind': 'anime', 'year': 2014, 'format': 'OVA', 'title': 'Furueru Kuchibiru',
             'aliases': ['Furueru Kuchibiru', 'ふるえるくちびる'], 'adult': True}


class Http:
    """Answers by URL prefix (longest first); records every request."""
    def __init__(self, pages):
        self.pages = pages; self.calls = []; self.deadline = None
    def document(self, url, headers=None, **_):
        self.calls.append(url)
        for prefix in sorted(self.pages, key=len, reverse=True):
            if url.startswith(prefix):
                value = self.pages[prefix]
                if isinstance(value, Exception):
                    raise value
                text, extra = value if isinstance(value, tuple) else (value, {})
                return text, url, extra
        error = SourceError('Источник вернул HTTP 404.'); error.http_status = 404
        raise error
    def close(self):
        pass


def pages(**extra):
    return {HH_SEARCH: read('hentaihaven-search.json'), HH_YEARS: read('hentaihaven-releases.json'),
            HH_CHAPTERS: read('hentaihaven-chapters.json'), MASTER: read('hentaihaven-master.m3u8'),
            MIO_SERIES: read('miohentai-series.json'), MIO_POSTS: POSTS,
            'https://miohentai.com/?p=274': read('miohentai-post.html'), **extra}


class Fresh(unittest.TestCase):
    def setUp(self):
        sites._haven_years.update(at=0.0, years={}); sites._haven_titles.clear(); sites._mio_series.clear()


class HentaiHaven(Fresh):
    def test_search_candidates_years_and_titles(self):
        http = Http(pages())
        rows = sites.search('hentaihaven', 'overflow', http)
        self.assertEqual(http.calls[0], HH_SEARCH + 'overflow&per_page=12&_fields=id%2Cslug%2Ctype%2Ctitle%2Clink%2Cwp-manga-release')
        named = {r['title']: r for r in rows}
        self.assertEqual(named['Overflow']['url'], 'https://hentaihaven.xxx/watch/overflow/')
        self.assertEqual(named['Overflow']['year'], 2020)
        # Tagged «Released 2020» and «2025»: dated by the first release.
        self.assertEqual(named['Overflow Hentai']['year'], 2020)
        self.assertEqual(named['Kenki Virgo']['year'], 2026)
        self.assertTrue(all(sites.provider_for(r['url'])[0] == 'hentaihaven' and r['providerName'] == 'HentaiHaven · EN' for r in rows))
        # The year dictionary is read once a day, not per search.
        sites.search('hentaihaven', 'overflow', http)
        self.assertEqual(sum(c.startswith(HH_YEARS) for c in http.calls), 1)

    def test_only_watch_series_pages(self):
        posts = [{'id': 1, 'slug': 'clip', 'type': 'rule34-video', 'title': {'rendered': 'Clip'}, 'link': 'https://cms.hentaihaven.xxx/rule34/video/clip/'},
                 {'id': 2, 'slug': 'other', 'type': 'wp-manga', 'title': {'rendered': 'Other'}, 'link': 'https://cms.hentaihaven.xxx/channels/other/'},
                 {'id': 3, 'slug': 'kept', 'type': 'wp-manga', 'title': {'rendered': 'Kept &amp; Sound'}, 'link': 'https://cms.hentaihaven.xxx/watch/kept/'}]
        self.assertEqual([r['title'] for r in sites.haven_rows(posts, {})], ['Kept & Sound'])
        # A Rule 34 clip is its own provider (G8), never a HentaiHaven series.
        self.assertEqual(sites.provider_for('https://hentaihaven.xxx/rule34/video/some-clip/')[0], 'hentaihaven-rule34')
        for url in ('https://hentaihaven.xxx/channels/x/', 'https://hentaihaven.xxx/series/uncensored/',
                    'https://hentaihaven.xxx/watch/', 'https://hentaihaven.xxx/watch/a/b/c/', 'https://hentaihaven.xxx/watch/overflow/?x=1',
                    'https://evil.example/watch/overflow/', 'https://hentaihaven.xxx/ru/watch/overflow/'):
            self.assertIsNone(sites.provider_for(url), url)
        self.assertEqual(provider_for('https://hentaihaven.xxx/watch/overflow/episode-8/'), ('hentaihaven', 'HentaiHaven · EN'))

    def test_episodes_and_stream(self):
        http = Http(pages())
        sites.search('hentaihaven', 'overflow', http)
        title, episodes = sites.episodes('hentaihaven', 'https://hentaihaven.xxx/watch/overflow/', http)
        self.assertEqual(title, 'Overflow')
        self.assertEqual([e['number'] for e in episodes], list(range(1, 9)))
        self.assertEqual(episodes[7]['url'], 'https://hentaihaven.xxx/watch/overflow/episode-8/')
        streams = sites.streams('hentaihaven', episodes[7]['url'], http)
        self.assertEqual(len(streams), 1)
        stream = streams[0]
        self.assertEqual((stream['url'], stream['type'], stream['quality']), (MASTER, 'hls', None))
        self.assertEqual(stream['headers']['Referer'], 'https://hentaihaven.xxx/')
        self.assertEqual([(s['language'], s['url']) for s in stream['subtitles']],
                         [(language, 'https://octopusmanifest.org/70c8dbd7-3d5e-40f1-b83a-90ef7ffb0a0c/s/' + language + '.vtt')
                          for language in ('ru', 'uk', 'en')])
        with self.assertRaises(SourceError):
            sites.streams('hentaihaven', 'https://hentaihaven.xxx/watch/overflow/', http)

    def test_player_page_keeps_our_player(self):
        http = Http(pages())
        page = resolve_dynamic(http, 'https://hentaihaven.xxx/watch/overflow/episode-8/', None, 'Overflow', 'hentaihaven')
        self.assertEqual([(s['url'], s['type']) for s in page.streams], [(MASTER, 'hls')])
        self.assertNotIn('subtitles', page.streams[0])
        self.assertEqual([s['language'] for s in page.subtitles], ['ru', 'uk', 'en'])
        # A chapter whose master is not an https playlist is not offered.
        broken = json.loads(read('hentaihaven-chapters.json'))
        for chapter in broken:
            chapter['chapter_content'] = chapter['indexable_content_url'] = 'http://octopusmanifest.org/x/playlist.m3u8'
        with self.assertRaises(SourceError):
            sites.episodes('hentaihaven', 'https://hentaihaven.xxx/watch/overflow/', Http({HH_CHAPTERS: json.dumps(broken)}))


class MioHentai(Fresh):
    def test_search_episodes_stream(self):
        http = Http(pages())
        rows = sites.search('miohentai', 'kuchibiru', http)
        self.assertEqual([(r['title'], r['url'], r['year']) for r in rows],
                         [('Furueru Kuchibiru', 'https://miohentai.com/series/furueru-kuchibiru/', None)])
        title, episodes, about = sites.episodes('miohentai', rows[0]['url'], http)
        self.assertEqual((title, about), ('Furueru Kuchibiru', {'uploadYear': 2023}))
        self.assertEqual([(e['number'], e['url']) for e in episodes], [(1, 'https://miohentai.com/?p=274'), (2, 'https://miohentai.com/?p=8807')])
        self.assertIn('series=178', next(c for c in http.calls if c.startswith(MIO_POSTS)))
        streams = sites.streams('miohentai', episodes[0]['url'], http)
        self.assertEqual(len(streams), 1)
        self.assertRegex(streams[0]['url'], r'^https://cdn\.miohentai\.com/index\.php\?data=[0-9a-f]{64,}$')
        self.assertEqual(streams[0]['type'], 'mp4')

    def test_strict_addresses(self):
        for url in ('https://miohentai.com/tags/', 'https://miohentai.com/?p=1&x=2', 'https://miohentai.com/series/a/b/', 'https://miohentai.com/contact/'):
            self.assertIsNone(sites.provider_for(url), url)
        self.assertEqual(sites.mio_media('https://evil.example/index.php?data=' + 'ab' * 20, 'https://miohentai.com/'), '')
        self.assertEqual(sites.mio_media('https://cdn.miohentai.com/index.php?data=zz', 'https://miohentai.com/'), '')
        self.assertEqual(sites.mio_media('https://cdn.miohentai.com/other.php?data=' + 'ab' * 20, 'https://miohentai.com/'), '')
        page = read('miohentai-post.html').replace('cdn.miohentai.com/index.php', 'cdn.example.net/index.php')
        self.assertEqual(sites.mio_streams('https://miohentai.com/?p=274', Http({'https://miohentai.com/?p=274': page})), [])


class Matching(Fresh):
    def test_names_pairs(self):
        same = lambda card, name, year=None: match_title(card, {'aliases': [name], 'year': year}, year_slack=1)
        sagurare = {'kind': 'anime', 'year': 2017, 'title': 'Sagurare Otome THE ANIMATION', 'aliases': ['Sagurare Otome THE ANIMATION']}
        self.assertEqual(same(sagurare, 'Sagurare Otome', 2017), (True, 'title_without_animation'))
        self.assertEqual(same(sagurare, 'Sagurare Otome', 2016), (False, 'different_year'))
        iribitari = {'kind': 'anime', 'year': 2024, 'title': 'Iribitari Gal ni Manko Tsukawasete Morau Hanashi Animation', 'aliases': []}
        self.assertTrue(same(iribitari, 'Iribitari Gal ni Manko Tsukawasete Morau Hanashi', 2024)[0])
        pandra = {'kind': 'anime', 'year': 2022, 'title': 'Raikou Shinki Igis Magia: PANDRA saga 3rd ignition - The Animation', 'aliases': []}
        self.assertTrue(same(pandra, 'Raikou Shinki Igis Magia Pandra Saga 3rd Ignition', 2022)[0])
        # One name, different works: a numbered sequel, a compilation, another part, another year.
        yayoi = {'kind': 'anime', 'year': 2016, 'title': 'Boku no Yayoi-san 2 The Animation', 'aliases': []}
        self.assertFalse(same(yayoi, 'Boku no Yayoi-san The Animation', 2016)[0])
        self.assertFalse(same(OVERFLOW, 'Overflow Hentai', 2020)[0])
        self.assertFalse(same({'kind': 'anime', 'year': 2025, 'title': 'Kegareboshi Ao'}, 'Kegareboshi', 2025)[0])
        self.assertFalse(same(OVERFLOW, 'Overflow', 2017)[0])
        self.assertFalse(same({'kind': 'anime', 'year': 2014, 'title': 'Animation'}, 'The Animation', 2014)[0])

    def test_index_anchor_uses_the_live_year_rule(self):
        row = {'provider': 'hanime', 'kind': 'anime', 'title': 'Youjuu Kyoushitsu', 'aliases': ['Youjuu Kyoushitsu'], 'year': 1991}
        card = {'kind': 'anime', 'year': 1990, 'title': 'Demon Beast Invasion', 'aliases': ['Demon Beast Invasion', 'Youjuu Kyoushitsu']}
        self.assertEqual(content_names.same_work(card, row, year_required=True), (False, 'different_year'))
        self.assertEqual(content_names.same_work(card, row, year_required=True, year_slack=1), (True, 'exact_title_near_year'))
        self.assertFalse(content_names.same_work({**card, 'year': 1988}, row, year_required=True, year_slack=1)[0])
        with patch('content_names.matches', return_value=[]) as matches:
            source_discovery.index_anchors(card)
        self.assertEqual(matches.call_args.kwargs['year_slack'], 1)

    def test_index_lookup_names_without_animation(self):
        import contextlib
        card = {'kind': 'anime', 'year': 2024, 'title': 'Iribitari Gal ni Manko Tsukawasete Morau Hanashi Animation', 'aliases': []}
        row = {'provider': 'watchhentai', 'kind': 'anime', 'title': 'Iribitari Gal ni Manko Tsukawasete Morau Hanashi', 'year': 2024,
               'sourceUrl': 'https://watchhentai.net/series/iribitari-gal-ni-manko-tsukawasete-morau-hanashi-id-01/'}
        with patch('manga_discovery.manager', return_value=None), patch('manga_discovery.catalogue_reader', lambda store: contextlib.nullcontext(None)), \
             patch('content_names.lookup', return_value=[row]) as lookup:
            found = content_names.matches(card, 'anime', year_required=True, year_slack=1)
        self.assertIn('Iribitari Gal ni Manko Tsukawasete Morau Hanashi', lookup.call_args.args[2])
        self.assertEqual([r['matchEvidence'] for r in found], ['title_without_animation'])

    def test_undated_site_rule(self):
        value = {'uploadYear': 2023}
        self.assertTrue(source_discovery.undated_match('miohentai', KUCHIBIRU, value, 'exact_title'))
        self.assertFalse(source_discovery.undated_match('miohentai', {**KUCHIBIRU, 'year': 2025}, value, 'exact_title'))
        self.assertFalse(source_discovery.undated_match('miohentai', KUCHIBIRU, value, 'headline'))
        self.assertFalse(source_discovery.undated_match('miohentai', KUCHIBIRU, {}, 'exact_title'))
        self.assertFalse(source_discovery.undated_match('hentaihaven', KUCHIBIRU, value, 'exact_title'))


class Discover(Fresh):
    def run_discover(self, card, http):
        guards = [patch.object(source_discovery, 'SITES', (BY_ID['hentaihaven'], BY_ID['miohentai'])),
                  patch.object(source_discovery, 'PublicHttp', lambda **_: http),
                  patch('kinobox_source.discover', return_value={'provider': 'kinobox', 'name': 'Kinobox', 'status': 'empty', 'complete': True, 'sources': []}),
                  patch('source_index.save'), patch.dict(source_discovery._cache, {}, clear=True),
                  patch.object(source_discovery, 'index_anchors', lambda selected: {})]
        for guard in guards:
            guard.start()
        try:
            return source_discovery._discover(card, refresh=True)
        finally:
            for guard in reversed(guards):
                guard.stop()

    def test_response_shape_and_sources(self):
        http = Http(pages())
        result = self.run_discover(OVERFLOW, http)
        self.assertEqual(set(result), {'title', 'voices', 'sources', 'providers', 'progress', 'pending', 'complete', 'checkedAt'})
        self.assertEqual([(s['provider'], s['url'], s['matchEvidence']) for s in result['sources']],
                         [('hentaihaven', 'https://hentaihaven.xxx/watch/overflow/', 'exact_title')])
        source = result['sources'][0]
        self.assertEqual(source['providerName'], 'HentaiHaven · EN')
        self.assertEqual(len(source['episodes']), 8)
        self.assertEqual(source['dubs'][0]['player'], 'HentaiHaven · EN')
        statuses = {p['provider']: p['status'] for p in result['providers']}
        self.assertEqual(statuses['hentaihaven'], 'ok')
        self.assertTrue(result['voices'])

    def test_latin_name_is_asked_first(self):
        http = Http(pages())
        card = {**OVERFLOW, 'title': 'Переполнение', 'titles': {'ru': 'Переполнение', 'en': 'Overflow'}, 'aliases': ['Переполнение', 'Overflow']}
        self.run_discover(card, http)
        # The first request of each site asks the romaji name; the Russian one only comes after it.
        for prefix in (HH_SEARCH, MIO_SERIES + 'search'):
            first = next(c for c in http.calls if c.startswith(prefix))
            self.assertIn('search=Overflow&', first)

    def test_undated_site_and_false_merges(self):
        http = Http(pages())
        result = self.run_discover(KUCHIBIRU, http)
        self.assertEqual([(s['provider'], s['matchEvidence']) for s in result['sources']], [('miohentai', 'exact_title_undated')])
        # Released after the first upload: not the uploaded series.
        later = self.run_discover({**KUCHIBIRU, 'year': 2025}, Http(pages()))
        self.assertEqual(later['sources'], [])
        self.assertEqual({p['provider']: p['status'] for p in later['providers']}['miohentai'], 'unverified')
        # Same name three years off: another work.
        self.assertEqual(self.run_discover({**OVERFLOW, 'year': 2017}, Http(pages()))['sources'], [])


class Playback(unittest.TestCase):
    def test_master_without_vtt_renditions(self):
        text = online_sessions.drop_vtt_renditions(read('hentaihaven-master.m3u8'))
        self.assertNotIn('TYPE=SUBTITLES', text)
        self.assertNotIn('SUBTITLES=', text)
        self.assertIn('TYPE=AUDIO', text)
        self.assertIn('AUDIO="audio"', text)
        rewritten = online_sessions.rewrite_manifest(read('hentaihaven-master.m3u8'), MASTER, lambda v: '/online/t/' + v.rsplit('/', 2)[-2])
        self.assertEqual(rewritten.count('#EXT-X-STREAM-INF'), 2)
        playlist = '#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="s",URI="subs/en.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1,SUBTITLES="s"\nv.m3u8\n'
        self.assertEqual(online_sessions.drop_vtt_renditions(playlist), playlist)

    def test_mislabelled_fragments(self):
        self.assertEqual(online_sessions.media_sample(b'\x00\x00\x00\x18stypmsdh\x00\x00\x00\x00'), 'video/mp4')
        self.assertEqual(online_sessions.media_sample(b'\x00\x00\x00\x1cftypiso5\x00\x00\x02\x00'), 'video/mp4')
        self.assertEqual(online_sessions.media_sample(b'\x47' + b'\x00' * 187 + b'\x47'), 'video/mp2t')
        self.assertEqual(online_sessions.media_sample(b'#EXTM3U\n'), '')
        self.assertEqual(online_sessions.media_sample(b'<!doctype html>'), '')

        class Response:
            def __init__(self, mime, body):
                self.headers = {'Content-Type': mime}; self.body = body
            def iter_content(self, size):
                yield self.body
            def close(self):
                pass

        class Client:
            def __init__(self, mime, body):
                self.answer = Response(mime, body)
            def _open(self, url, **_):
                return self.answer, url

        variant = '#EXTM3U\n#EXT-X-MAP:URI="https://octy.vercomicspornox.com/s/x/7sop/i.mp4"\n#EXTINF:2.0,\nhttps://octy.vercomicspornox.com/s/x/7sop/ha1.html\n#EXT-X-ENDLIST\n'
        online_sessions._ready.clear()
        online_sessions.playable(variant, 'https://octopusmanifest.org/x/7sop/v.m3u8', {}, Client('application/x-mpegURL', b'\x00\x00\x00\x1cftypiso5'), None)
        online_sessions._ready.clear()
        with self.assertRaises(SourceError):
            online_sessions.playable(variant, 'https://octopusmanifest.org/x/7sop/v.m3u8', {}, Client('application/x-mpegURL', b'#EXTM3U\n'), None)


class Index(unittest.TestCase):
    def test_walk(self):
        years, genres = read('hentaihaven-releases.json'), json.dumps([{'id': 105, 'name': 'Harem'}, {'id': 815, 'name': 'Incest'}])
        posts = json.loads(read('hentaihaven-search.json'))
        posts[0]['wp-manga-genre'] = [105, 815, 999]
        posts[0]['meta'] = {'vraven_remote_thumbnail': 'images/hh/y/h/s_poster_8406.jpg'}
        # An older import: its episodes name a master-lengs.org playlist only (CDN answered 523).
        legacy = json.dumps([{'chapter_name': 'Episode 1', 'episode_slug': 'episode-1', 'is_deleted': False, 'chapter_content': '',
                              'indexable_content_url': 'https://master-lengs.org/api/v3/hh/kenki-virgo-episode-1/master.m3u8'}])
        chapters = CMS + 'hhaven/v1/manga/by-slug/'
        http = Http({CMS + 'wp/v2/wp-manga-release?': years, CMS + 'wp/v2/wp-manga-genre?': genres,
                     CMS + 'wp/v2/wp-manga?per_page=100&page=1&': (json.dumps(posts[:2]), {'X-WP-TotalPages': '2'}),
                     CMS + 'wp/v2/wp-manga?per_page=100&page=2&': (json.dumps(posts[3:4]), {'X-WP-TotalPages': '2'}),
                     chapters + 'overflow/chapters': read('hentaihaven-chapters.json'), chapters + 'kenki-virgo/chapters': legacy,
                     chapters + 'overflow-hentai/chapters': '[]'})
        spec = {'type': 'hentaihaven', 'kind': 'anime', 'domain': 'hentaihaven.xxx', 'name': 'Хентай · HentaiHaven'}
        step = catalogue_hentaihaven.catalogue(spec, {}, http)
        self.assertEqual((step['rows'], step['next']['step']), ([], 'genres'))
        step = catalogue_hentaihaven.catalogue(spec, step['next'], http)
        self.assertEqual(step['vocabulary'], [{'category': 'genre', 'label': 'Harem'}, {'category': 'genre', 'label': 'Incest'}])
        rows, calls = [], 0
        while step['next'] and calls < 10:
            step = catalogue_hentaihaven.catalogue(spec, json.loads(json.dumps(step['next'])), http)
            rows.extend(step['rows']); calls += 1
        # 2 list pages + 3 series = 5 requests; the legacy and the empty series give no row.
        self.assertEqual(calls, 5)
        self.assertIsNone(step['next'])
        self.assertEqual([r['title'] for r in rows], ['Overflow'])
        row = rows[0]
        self.assertEqual({k: row[k] for k in ('id', 'provider', 'kind', 'title', 'url', 'sourceUrl', 'year', 'genres', 'cover', 'age', 'episodes')},
                         {'id': 'hentaihaven:https://hentaihaven.xxx/watch/overflow/', 'provider': 'hentaihaven', 'kind': 'anime',
                          'title': 'Overflow', 'url': 'https://hentaihaven.xxx/watch/overflow/', 'sourceUrl': 'https://hentaihaven.xxx/watch/overflow/',
                          'year': 2020, 'genres': ['Harem', 'Incest'], 'cover': 'https://img.hentaihaven.xxx/images/hh/y/h/s_poster_8406.jpg', 'age': 18,
                          'episodes': 8})
        self.assertTrue(content_names.playable(row))
        self.assertEqual(catalogued_source('hentaihaven', row['url']), row['url'])
        self.assertEqual(catalogued_source('hentaihaven', 'https://hentaihaven.xxx/rule34/video/clip/'), '')
        gone = SourceError('Источник вернул HTTP 400.'); gone.http_status = 400
        with self.assertRaises(SourceListingEnd):
            catalogue_hentaihaven.catalogue(spec, {'step': 'series', 'page': 3}, Http({CMS + 'wp/v2/wp-manga?': gone}))
        # A series removed since it was listed is skipped.
        skipped = catalogue_hentaihaven.catalogue(spec, {'step': 'series', 'page': 2, 'last': 2, 'queue': [['gone', 'Gone', None, [], '']]}, Http({}))
        self.assertEqual((skipped['rows'], skipped['next']['page']), ([], 2))
        # The card of an index row opens the series page directly.
        sel = {'title': 'Overflow', 'provider': 'hentaihaven', 'sourceURL': row['url']}
        self.assertEqual(source_discovery.indexed_sources(sel), {'hentaihaven': [row['url']]})


if __name__ == '__main__':
    unittest.main()
