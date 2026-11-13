"""Neutral source metadata fixtures; no manga artwork or ML inference."""
import json,os,sys,tempfile,threading,sqlite3,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from catalogue_html import catalogue,metadata
from catalogue_sources import base_sources,fetch
from catalogue_indexer import Indexer
from manga_catalog_index import initialize
from source_parser import SourceError
from bs4 import BeautifulSoup

class CompletionTests(unittest.TestCase):
 def spec(self):return {'type':'html','domain':'manga-chan.me','name':'MangaChan','url':'https://im.manga-chan.me/catalog','hosts':['im.manga-chan.me'],'source':{'id':'7'}}
 def card(self):return '<div class="content_row"><h2><a class="title_link" href="/manga/1-garden.html">Garden</a></h2><div class="genre"><a href="/tags/ecology">Ecology</a><span hidden><a href="/tags/botany">Botany</a></span></div><img src="https://covers.example/garden.jpg"></div>'
 def test_collapsed_work_tags_survive_and_offset_navigation_is_followed(self):
  result=catalogue(self.card()+'<div id="page"><a href="?offset=20">Next</a><a href="?offset=120">Last</a></div><aside class="sidetag"><a href="/tags/foreign">Foreign</a></aside>',self.spec()['url'],self.spec(),1)
  self.assertEqual(result['rows'][0]['genres'],['Ecology','Botany']);self.assertEqual(result['rows'][0]['provider'],'suwayomi:7')
  self.assertEqual(result['next'],{'page':2,'url':'https://im.manga-chan.me/catalog?offset=20'})
  self.assertEqual(result['rows'][0]['cover'],'https://covers.example/garden.jpg')
 def test_missing_offset_and_parked_empty_pages_are_not_complete(self):
  with self.assertRaises(SourceError):catalogue(self.card(),self.spec()['url'],self.spec(),2)
  with self.assertRaises(SourceError):catalogue('<h1>Domain for sale</h1>',self.spec()['url'],self.spec(),1)
  with self.assertRaises(SourceError):catalogue(self.card()+'<a href="?offset=40">Next</a>',self.spec()['url'],self.spec(),1)
 def test_detail_scopes_full_work_tags_and_rejects_a_login_page(self):
  raw='<div id="info_wrap"></div><div class="sidetags"><ul><li><a href="/tags/ecology">Ecology</a></li></ul></div><aside class="sidetag"><a href="/tags/foreign">Foreign</a></aside>'
  self.assertEqual(metadata(BeautifulSoup(raw,'html.parser'),'manga-chan.me')['tags'],['Ecology'])
  with self.assertRaises(SourceError):metadata(BeautifulSoup('<h1>Log in</h1>','html.parser'),'manga-chan.me')
 def test_moody_new_cards_and_real_next_link(self):
  spec={'type':'html','domain':'online.hentaimoody.com','name':'HentaiMoody','hosts':['online.hentaimoody.com']}
  raw='<article class="manga-card"><a class="manga-card__link" href="/12-garden.html"><span class="manga-card__title">Garden</span><span class="manga-card__meta">Ecology<span>Botany</span></span></a></article><div class="pagination"><a href="/page/2/">2</a></div>'
  d=catalogue(raw,'https://online.hentaimoody.com/',spec,1);self.assertEqual(d['rows'][0]['genres'],['Ecology','Botany']);self.assertEqual(d['next']['page'],2)
  with self.assertRaises(SourceError):metadata(BeautifulSoup('<h1>Garden</h1><div class="system-message">Login</div>','html.parser'),spec['domain'])
  public='<div class="title-hero__body"><h1>Garden</h1></div><div class="title-hero__genres"><a href="/genre/ecology">Ecology</a><span hidden><a href="/genre/botany">Botany</a></span></div><div class="system-message">Reader requires login</div>'
  self.assertEqual(metadata(BeautifulSoup(public,'html.parser'),spec['domain'])['genres'],['Ecology','Botany'])
 def test_all_requested_sources_are_accounted_for_even_a_shared_extension(self):
  jobs=base_sources([{'id':'7','name':'MangaChan','lang':'ru','baseUrl':'https://im.manga-chan.me'},{'id':'8','name':'HenChan','lang':'ru','baseUrl':'https://xxl.hentaichan.live'}])
  from manga_source_coverage import SOURCES
  domains={j['domain'] for j in jobs};self.assertTrue({s[0] for s in SOURCES}<=domains)
  by={j['domain']:j for j in jobs};self.assertEqual(by['manga-chan.me']['type'],'html');self.assertEqual(by['h-chan.me']['type'],'mirror');self.assertEqual(by['henchan.pro']['type'],'html')
 def test_empty_extension_popular_page_cannot_claim_success(self):
  class Client:
   def get(self,*a,**k):return {'mangaList':[],'hasNextPage':False}
   def close(self):pass
  with patch('suwayomi_bridge.Client',Client),self.assertRaises(SourceError):fetch({'type':'bridge','domain':'fixture.example','source':{'id':'7'}},{'page':1})
 def test_slow_host_cannot_starve_a_different_source_and_base_pages_get_a_turn(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'DATA_DIR':d,'MEDIA_VAULT_DISABLE_WORKER':'1'}):
   db=sqlite3.connect(':memory:',check_same_thread=False);initialize(db);db.commit();store=SimpleNamespace(db=db,lock=threading.RLock());worker=Indexer(store,clock=lambda:1000,interval=0)
   with db:
    for i in range(120):worker.enqueue({'type':'lib-detail','domain':'mangalib.org','site':1,'slug':str(i)},100)
    worker.enqueue({'type':'bridge','domain':'fixture.example','name':'Fixture','source':{'id':'9'}},1)
   worker.inflight['api.cdnrulib.link']=2;job=worker.claim();self.assertEqual(job['spec']['domain'],'fixture.example');db.close()
 def test_robots_cache_is_path_specific_and_does_not_refetch_for_every_detail(self):
  import content_sources
  class Session:pass
  content_sources._robots.clear()
  with patch('content_sources.checked_get',return_value=(b'User-agent: *\nDisallow: /private/', 'https://fixture.example/robots.txt')) as get:
   self.assertTrue(content_sources.permitted(Session(),'https://fixture.example/manga/1',{'fixture.example'}))
   self.assertFalse(content_sources.permitted(Session(),'https://fixture.example/private/1',{'fixture.example'}))
   self.assertEqual(get.call_count,1)
  content_sources._robots.clear()

 def test_overlapping_listing_pages_count_unique_titles_and_refresh_resets_cycle(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'DATA_DIR':d,'MEDIA_VAULT_DISABLE_WORKER':'1'}):
   db=sqlite3.connect(':memory:',check_same_thread=False);initialize(db);db.commit();store=SimpleNamespace(db=db,lock=threading.RLock());now=[1000]
   def row(i):return {'kind':'manga','provider':'fixture','title':'Garden '+str(i),'sourceUrl':'https://fixture.example/manga/'+str(i)}
   def fetch_page(s,c):return {'rows':[row(1),row(c['page']+1)],'next':{'page':2} if c['page']==1 else None}
   worker=Indexer(store,fetch_page,lambda:now[0],interval=0)
   with db:worker.enqueue({'type':'lib','domain':'fixture.example','site':1,'name':'Fixture'},80)
   worker.run_once();now[0]+=3;worker.run_once();status=worker.status()['sources'][0]
   self.assertEqual(status['indexed'],3);self.assertEqual(status['pages'],2)
   self.assertEqual(db.execute('SELECT priority FROM catalogue_jobs').fetchone()[0],10)
   now[0]+=21601;worker.run_once();status=worker.status()['sources'][0]
   self.assertEqual(status['indexed'],2);self.assertEqual(status['pages'],1);db.close()

 def test_existing_private_lib_session_is_reused_only_for_detail_requests(self):
  import catalogue_lib_auth as auth
  from catalogue_sources import headers
  secret='fixture-session-credential';calls=[]
  class Client:
   def get(self,path,**kw):
    calls.append(path);return [{'props':{'key':'bearer_token','currentValue':secret if auth.SOURCES[4] in path else ''}}]
   def close(self):pass
  auth._cache.clear()
  with patch.object(auth,'configured',return_value=True),patch.object(auth,'Client',Client):
   self.assertEqual(auth.token(2),secret);self.assertEqual(auth.token(2),secret);self.assertEqual(len(calls),2)
   spec={'type':'lib-detail','site':2,'referer':'https://v2.shlib.life/'}
   self.assertEqual(headers(spec)['Authorization'],'Bearer '+secret)
   self.assertNotIn('Authorization',headers({**spec,'type':'lib'}));self.assertNotIn(secret,json.dumps(spec))
  auth._cache.clear()

 def test_missing_private_lib_session_preserves_anonymous_metadata_access(self):
  import catalogue_lib_auth as auth
  auth._cache.clear()
  with patch.object(auth,'configured',return_value=True),patch.object(auth,'Client',side_effect=RuntimeError('unavailable')):
   self.assertEqual(auth.token(4),'')
  auth._cache.clear()

 def test_published_tag_directory_seeds_each_source_listing_and_preserves_full_details(self):
  spec={'type':'html','domain':'hentaros.com','name':'HentaRos','hosts':['hentaros.com'],'url':'https://hentaros.com/tag'}
  card='<a class="card" href="/tag/ecology"><span class="t">Ecology</span></a>'
  d=catalogue(card+card,spec['url'],spec,1)
  self.assertEqual(len(d['catalogues']),1)
  self.assertEqual(d['catalogues'][0]['term']['label'],'Ecology');self.assertEqual(d['catalogues'][0]['url'],'https://hentaros.com/tag/ecology')
  self.assertEqual(d['state'],'partial')
  detail='<div class="post-head"><h1>Garden</h1></div><a class="chip" href="/tag/ecology">Ecology</a><a class="chip" href="/artist/smith">Smith</a>'
  self.assertEqual(metadata(BeautifulSoup(detail,'html.parser'),spec['domain'])['tags'],['Ecology'])
 def test_detail_identity_deduplicates_a_work_seen_under_many_source_tags(self):
  from catalogue_indexer import identity
  base={'type':'html-detail','domain':'fixture.example','url':'https://fixture.example/garden'}
  self.assertEqual(identity({**base,'term':{'label':'Ecology'}}),identity({**base,'term':{'label':'Botany'}}))
  self.assertNotEqual(identity({**base,'type':'html','term':{'label':'Ecology'}}),identity({**base,'type':'html','term':{'label':'Botany'}}))

 def test_tag_crawl_status_reports_stored_cards_even_without_a_base_title_listing(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'DATA_DIR':d,'MEDIA_VAULT_DISABLE_WORKER':'1'}):
   db=sqlite3.connect(':memory:',check_same_thread=False);initialize(db);db.commit();store=SimpleNamespace(db=db,lock=threading.RLock())
   row={'kind':'manga','provider':'fixture.example','title':'Garden','sourceUrl':'https://fixture.example/garden'}
   detail={'type':'html-detail','domain':'fixture.example','url':row['sourceUrl'],'row':row}
   worker=Indexer(store,lambda s,c:{'rows':[row],'next':None,'state':'partial','details':[detail]},lambda:1000,interval=0)
   with db:worker.enqueue({'type':'html','domain':'fixture.example','name':'Fixture','url':'https://fixture.example/catalog'})
   worker.run_once();status=worker.status()['sources'][0]
   self.assertEqual(status['storedTitles'],1);self.assertEqual(status['pendingDetails'],1);self.assertEqual(status['status'],'enriching');db.close()

 def test_remanga_uses_the_published_alternative_name_when_primary_name_is_empty(self):
  from manga_remanga import catalogue_page
  payload={'results':[{'id':12,'dir':'garden','main_name':'','secondary_name':'Garden','genres':[{'name':'Ecology'}]}],'next':'/api/v2/search/catalog/?page=2&count=30'}
  with patch('manga_remanga.api',return_value=payload):d=catalogue_page(1,None)
  self.assertEqual(d['rows'][0]['title'],'Garden');self.assertEqual(d['rows'][0]['genres'],['Ecology']);self.assertEqual(d['next'],{'page':2})

 def test_lib_unnamed_stub_is_retained_as_a_detail_job_without_stalling_the_page(self):
  spec={'type':'lib','domain':'mangalib.org','site':1,'referer':'https://mangalib.me/'}
  payload={'data':[{'id':1,'slug_url':'1-garden','rus_name':' ','eng_name':'Garden'},{'id':2,'slug_url':'2-pending','rus_name':'','eng_name':'','name':''}],'meta':{'has_next_page':True}}
  with patch('catalogue_sources.checked_get',return_value=(json.dumps(payload).encode(),'https://api.cdnrulib.link/api/manga')):d=fetch(spec,{'page':1})
  self.assertEqual([r['title'] for r in d['rows']],['Garden']);self.assertEqual(len(d['details']),2);self.assertEqual(d['next']['page'],2)
  detail=d['details'][1]
  with patch('catalogue_lib_auth.token',return_value=''),patch('catalogue_sources.checked_get',return_value=(json.dumps({'data':{'id':2,'slug_url':'2-pending','rus_name':'Botany','tags':[{'name':'Ecology'}]}}).encode(),'https://api.cdnrulib.link/api/manga/2-pending')):enriched=fetch(detail,{'page':1})
  self.assertEqual(enriched['rows'][0]['title'],'Botany');self.assertEqual(enriched['rows'][0]['tags'],['Ecology'])

 def test_lib_published_long_slugs_are_not_dropped_from_the_catalogue(self):
  from content_sources import lib_titles
  slug='123--'+'garden-'*70
  rows=lib_titles({'data':[{'slug_url':slug,'rus_name':'Garden'}]},1,'','tag')
  self.assertEqual(len(rows),1);self.assertTrue(rows[0]['sourceUrl'].endswith(slug))

if __name__=='__main__':unittest.main()
