"""Published player shapes, identity, and exact selected-translation preservation."""
import json
import html
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_parser import Page, PublicHttp, Resolver, SourceError, parse_page, public_url
from player_catalog import animego_buttons, cvh_choices, group_voices, choice, inspect_catalog, relay_url
from title_identity import match_title
from release_calendar import parse_announcements
from run_import import validate_job, source_identity

class Http(PublicHttp):
    def __init__(self,pages):self.pages=pages;self.calls=[]
    def document(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if url not in self.pages:raise SourceError('Missing fixture')
        return self.pages[url],url,{}
    def close(self):pass

class IdentityTests(unittest.TestCase):
    def test_only_exact_title_season_year_and_consistent_ids(self):
        selected={'title':'Дандадан 2','aliases':['Dandadan 2nd Season'],'year':2025,'kind':'anime'}
        self.assertTrue(match_title(selected,{'title':'Dandadan 2nd Season','year':2025,'kind':'anime'})[0])
        for candidate in [{'title':'Дандадан'},{'title':'Дандадан 3'},{'title':'Лазарь'},{'title':'Ведьма Михаси'}, {'title':'Дандадан 2','year':2026},{'title':'Дандадан 2','kind':'manga'}]:
            self.assertFalse(match_title(selected,candidate)[0],candidate)
        self.assertFalse(match_title({'title':'Стальной алхимик','year':2003},{'title':'Стальной алхимик: Братство','year':2009})[0])
        self.assertFalse(match_title({'title':'Same','ids':{'mal':1}},{'title':'Same','ids':{'mal':2}})[0])
        self.assertTrue(match_title({'title':'Русское','ids':{'mal':1}},{'title':'English','ids':{'mal':'1'}})[0])

class PlayerCatalogTests(unittest.TestCase):
    def test_parser_retains_two_translations_of_one_episode(self):
        page=parse_page('<a href="/episode-1?translation=1">1 серия</a><a href="/episode-1?translation=2">1 серия</a>','https://example.com/show')
        self.assertEqual(len(page.episodes),2)

    def test_grouping_preserves_players_subtitles_and_languages(self):
        a=choice('Ani Dub','https://aniboom.one/embed/a',player='Aniboom',language='ru')
        b=choice('ani-dub','https://kodikplayer.com/serial/1/h/720p',player='Kodik',language='ru')
        sub={**b,'kind':'subtitles'};en={**b,'language':'en'}
        voices=group_voices([{'url':'https://site.example/show','dubs':[a,b,sub,en]}])
        self.assertEqual(len(voices),3)
        main=next(g for g in voices if g['kind']=='voice' and g['language']=='ru')
        self.assertEqual(len(main['variants']),2)
        self.assertEqual({v['player'] for v in main['variants']},{'Kodik','Aniboom'})

    def test_animego_selects_each_episodes_actual_button(self):
        root='https://animego.org/anime/show-70';relay='https://animego.org/player/70'
        def buttons(ep,studio='A'):
            return f'<div id="provider"><button data-player="//aniboom.one/embed/show?episode={ep}&amp;translation=30" data-provider-title="AniBoom" data-ptranslation="30" data-translation-title="{studio}"></button></div>'
        def envelope(value):return json.dumps({'data':{'content':html.escape(value)}})
        pages={root:'<title>Show</title>',relay:envelope(buttons(1)+'<button data-episode="101" data-episode-number="1"></button><button data-episode-number="3" data-episode="103"></button>'),
               'https://animego.org/player/videos/101':envelope(buttons(1)),'https://animego.org/player/videos/103':envelope(buttons(3))}
        http=Http(pages);found=inspect_catalog(root,pages[root],root,http,provider='animego')
        studio=found['dubs'][0]
        self.assertEqual([e['number'] for e in studio['episodes']],[1,3])
        selected=inspect_catalog(root,pages[root],root,http,provider='animego',dub_url=studio['url'])
        self.assertEqual([e['number'] for e in selected['episodes']],[1,3])
        resolver=Resolver(http=http);seen=[]
        def extract(url,referer=None):seen.append((url,referer));return Page(streams=[{'url':'https://cdn.example/3.mp4','type':'mp4'}])
        resolver.player=extract
        resolver.resolve(studio['episodes'][1]['url'])
        self.assertIn('episode=3',seen[0][0]);self.assertNotIn('episode=1',seen[0][0])
        self.assertEqual(seen[0][1],'https://animego.org/player/videos/103')
        pages['https://animego.org/player/videos/103']=envelope(buttons(3).replace('data-ptranslation="30"','data-ptranslation="31"'))
        with self.assertRaises(SourceError):resolver.resolve(studio['episodes'][1]['url'])

    def test_modern_animego_card_and_xhr_headers(self):
        from site_adapters import BY_ID,parse_search
        from requests import Session,Response
        import io
        text='<div class="ani-grid__item"><a class="ani-grid__item-body" href="/anime/show-70"><img src="/a.jpg"><div class="ani-grid__item-title">Дандадан 2</div><span class="ani-grid__item-genres__link">2025</span></a></div>'
        found=parse_search(BY_ID['animego'],text,'https://animego.me/search/anime?q=show')
        self.assertEqual((found[0]['title'],found[0]['year']),('Дандадан 2',2025))
        response=Response();response.status_code=200;response.raw=io.BytesIO(b'{"data":{"content":"<div>player</div>"}}')
        with Session() as session,patch.object(session,'request',return_value=response) as request:
            http=PublicHttp(session=session,validate=lambda value:value)
            http.document('https://animego.me/player/70',headers={'Authorization':'private-google-token','Cookie':'private-session'})
            headers=request.call_args.kwargs['headers']
            self.assertEqual(headers['X-Requested-With'],'XMLHttpRequest')
            self.assertNotIn('Authorization',headers);self.assertNotIn('Cookie',headers)

    def test_cvh_exposes_every_real_voice_episode_and_quality(self):
        playlist='https://plapi.cdnvideohub.com/api/v1/player/sv/playlist?pub=747&aggr=mali&id=42'
        video='https://plapi.cdnvideohub.com/api/v1/player/sv/video/103'
        rows=[{'cvhId':42,'vkId':103,'voiceStudio':'A','voiceType':'voice','season':2,'episode':3},
              {'cvhId':42,'vkId':109,'voiceStudio':'B','voiceType':'subtitles','season':2,'episode':9}]
        http=Http({playlist:json.dumps({'items':rows}),video:json.dumps({'sources':{'mpegHighUrl':'https://cdn.example/real.mp4'}})})
        values=cvh_choices('https://animego.org/cdn-iframe/42/2/3',http)
        self.assertEqual(len(values),2);self.assertEqual(values[1]['kind'],'subtitles')
        self.assertEqual(values[1]['episodes'][0]['number'],9)
        resolved=Resolver(http).resolve(video)
        self.assertEqual(resolved.streams[0]['quality'],720)
        self.assertEqual(resolved.streams[0]['url'],'https://cdn.example/real.mp4')
        for url in ['https://plapi.cdnvideohub.com/api/v1/player/sv/video/103','https://aniliberty.top/api/v1/anime/releases/show']:
            public_url(url,resolve_dns=False)
        for url in ['https://plapi.cdnvideohub.com/api/private','https://evil.example/api/private','https://api.anilibria.app/x']:
            with self.assertRaises(SourceError):public_url(url,resolve_dns=False)

    def test_v2_translation_is_preserved_and_does_not_admit_credentials(self):
        job={'version':2,'library_id':'catalog-123','sources':['https://example.com/show'],'collection':'Show','translation':{'name':'A','kind':'subtitles','language':'ru','player':'CVH','variantId':'one'}}
        self.assertEqual(validate_job(job)['translation'],job['translation'])
        with self.assertRaises(SourceError):validate_job({**job,'translation':{'refresh_token':'secret'}})
        self.assertNotEqual(source_identity('https://animego.org/player/70?mv_translation=30&mv_player=A'),source_identity('https://animego.org/player/70?mv_translation=31&mv_player=A'))

class CalendarTests(unittest.TestCase):
    def test_only_real_source_dates_and_no_doctype(self):
        html='<article><h2><a href="/show">Show — 3 серия</a></h2><time datetime="2026-10-25T18:00:00+03:00"></time></article><article><h2>Show — 4 серия, скоро</h2></article>'
        values=parse_announcements(html,'https://site.example/','Studio')
        self.assertEqual(len(values),1);self.assertEqual(values[0]['episode'],3);self.assertEqual(values[0]['kind'],'translation')
        self.assertEqual(values[0]['date'],'2026-10-25T18:00:00+03:00')
        rss='<rss><channel><item><title>Show</title><link>https://site.example/show</link><pubDate>Sun, 25 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(len(parse_announcements(rss,'https://site.example/','Studio')),1)
        self.assertEqual(parse_announcements('<!DOCTYPE rss>'+rss,'https://site.example/','Studio'),[])

class PosterTests(unittest.TestCase):
    def test_exact_ids_real_poster_and_retry_after_empty(self):
        import poster_assets
        poster_assets._cache.clear()
        with patch.object(poster_assets,'get_json',side_effect=[{'data':{'animes':[]}},{'data':{'animes':[{'id':'57277','russian':'Дандадан 2','poster':{'originalUrl':'https://desu.shikimori.io/uploads/poster/57277.jpg'}},{'id':'999','poster':{'originalUrl':'https://other.example/a.jpg'}}]}}]):
            self.assertEqual(poster_assets.posters(['57277']),{})
            value=poster_assets.posters(['57277']);self.assertEqual(set(value),{'57277'});self.assertIn('57277',value['57277']['cover'])
        self.assertFalse(poster_assets.usable('https://shikimori.io/assets/404/original.png'))

if __name__=='__main__':unittest.main()

class AggregationTests(unittest.TestCase):
    def test_discovery_groups_only_confirmed_exact_work_and_never_inspects_unrelated_hits(self):
        import source_discovery as discovery
        from site_adapters import BY_ID
        discovery._cache.clear()
        selected={'title':'Дандадан','aliases':['Dandadan'],'year':2024,'kind':'anime','ids':{'mal':'57334'}}
        visited=[]
        def search(site,query,**kwargs):
            return {'status':'ok','results':[{'title':'Дандадан','year':2024,'kind':'anime','url':site.root+'/dandadan','provider':site.id}, {'title':'Лазарь','year':2024,'kind':'anime','url':site.root+'/lazarus','provider':site.id}]}
        def inspect(url,**kwargs):
            visited.append(url)
            return {'url':url,'title':'Дандадан','ids':{'mal':'57334'},'year':2024,'provider':'fixture', 'dubs':[choice('Studio A','https://kodikplayer.com/serial/1/h/720p')], 'episodes':[{'number':1,'url':url}]}
        with patch.object(discovery,'SITES',[BY_ID['yummy'],BY_ID['animego']]),patch.object(discovery,'search_site',side_effect=search),patch.object(discovery,'inspect_source',side_effect=inspect):
            result=discovery.discover(selected)
        self.assertEqual(len(result['voices']),1)
        self.assertEqual(len(result['voices'][0]['variants']),2)
        self.assertTrue(all('dandadan' in url for url in visited))
        self.assertEqual(len(visited),2)

class MetadataRouteTests(unittest.TestCase):
    def test_static_poster_and_watch_order_routes_are_not_shadowed_by_provider_route(self):
        import os,tempfile
        from fastapi.testclient import TestClient
        import api
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory,'MEDIA_VAULT_DISABLE_WORKER':'1'}):
            with TestClient(api.app) as client,patch('poster_assets.posters',return_value={'57334':{'cover':'https://desu.shikimori.io/poster.jpg'}}),patch('watch_order.watch_order',return_value={'items':[{'id':'57334','current':True}]}),patch.object(api,'metadata',side_effect=AssertionError('Static route reached generic metadata handler')):
                self.assertEqual(client.get('/metadata/posters?ids=57334').json()['57334']['cover'],'https://desu.shikimori.io/poster.jpg')
                self.assertTrue(client.get('/metadata/watch-order?identity=57334').json()['items'][0]['current'])
                self.assertEqual(client.get('/metadata/watch-order?identity=bad').status_code,422)
