"""HentaiChan's served listing, deep pages past 2000 and a site's pagination end.

Neutral HTML/JSON fixtures only: no network, no artwork, no ML inference.
"""
import json,os,sys,tempfile,threading,sqlite3,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import requests
import catalogue_sources
from catalogue_html import catalogue,listing_url
from catalogue_indexer import Indexer,REFRESH_BASE,listing_end
from manga_catalog_index import initialize
from manga_series_port import SeriesPort
from source_parser import CATALOGUE_PAGE_LIMIT,SourceError,SourceListingEnd,SourceTemporaryError

ROOT='https://x17.h-chan.me'
SPEC={'type':'html','domain':'hentaichan.live','name':'HentaiChan','url':ROOT+'/manga/newest?offset=0','hosts':['x17.h-chan.me','xxl.hentaichan.live']}

def card(n):
 return ('<div class="content_row" title="Work %d"><div class="manga_images"><img src="https://img.example/%d.jpg"></div>'
         '<div class="manga_row1"><h2><a class="title_link" href="%s/manga/%d-work-%d.html">Work %d</a></h2></div>'
         '<div class="manga_row3"><div class="item">Тэги</div><div class="genre"><a href="%s/tags/3DCG/">3DCG</a>, '
         '<a href="%s/tags/%%D1%%8E%%D0%%BC%%D0%%BE%%D1%%80/">юмор</a></div></div></div>')%(n,n,ROOT,n,n,n,ROOT,ROOT)

def dle_page(page,last=1657,count=20):
 numbers=[n for n in (page-1,page+1,last) if 1<=n<=last and n!=page]
 links=''.join('<a href="%s/manga/page/%d/">%d</a>'%(ROOT,n,n) for n in numbers)
 return '<html><body><div id="dle-content">'+''.join(card(page*100+i) for i in range(count))+'<div class="navigation">'+links+'</div></div></body></html>'

def memory_store():
 db=sqlite3.connect(':memory:',check_same_thread=False);initialize(db);db.commit()
 return db,SimpleNamespace(db=db,lock=threading.RLock())

class HentaiChanListingTests(unittest.TestCase):
 def test_the_stored_offset_cursor_continues_on_the_served_category_page(self):
  self.assertEqual(listing_url(ROOT+'/manga/newest?offset=200',11),ROOT+'/manga/page/11/')
  self.assertEqual(listing_url(ROOT+'/manga/newest?offset=0',1),ROOT+'/manga/')
  # Tag routes keep their own address.
  self.assertEqual(listing_url(ROOT+'/tags/x?offset=20',2),ROOT+'/tags/x?offset=20')

 def test_cards_after_offset_200_keep_tags_native_source_and_catalogue_size(self):
  result=catalogue(dle_page(11),ROOT+'/manga/page/11/',SPEC,11)
  self.assertEqual(len(result['rows']),20)
  row=result['rows'][0]
  self.assertEqual((row['provider'],row['sourceId'],row['url']),('hentaichan','990000000000000001',ROOT+'/manga/1100-work-1100.html'))
  self.assertEqual(row['genres'],['3DCG','юмор'])
  self.assertEqual(result['next'],{'page':12,'url':ROOT+'/manga/page/12/'})
  self.assertEqual(result['total'],1657*20)
  last=catalogue(dle_page(1657,count=7),ROOT+'/manga/page/1657/',SPEC,1657)
  self.assertEqual((last['next'],last['total']),(None,1656*20+7))

 def test_a_skipped_or_different_page_is_still_an_error(self):
  with self.assertRaises(SourceError):catalogue(dle_page(11),ROOT+'/manga/page/12/',SPEC,11)
  skipped=dle_page(11).replace('/manga/page/12/','/manga/page/13/')
  with self.assertRaises(SourceError):catalogue(skipped,ROOT+'/manga/page/11/',SPEC,11)

 def test_the_maintenance_stub_is_a_temporary_failure_not_a_parse_error(self):
  with self.assertRaises(SourceTemporaryError):catalogue('﻿technical maintenance.',ROOT+'/tags/x?offset=20',{**SPEC,'term':{'label':'x'}},2)

 def test_fetch_asks_the_category_page_for_an_offset_cursor(self):
  asked=[]
  def get(session,url,hosts,timeout=10):
   asked.append(url);return dle_page(11).encode(),url
  with patch.object(catalogue_sources,'checked_get',get),patch.object(catalogue_sources,'permitted',lambda *a,**k:True):
   result=catalogue_sources.fetch(SPEC,{'page':11,'url':ROOT+'/manga/newest?offset=200'})
  self.assertEqual(asked,[ROOT+'/manga/page/11/'])
  self.assertEqual((len(result['rows']),result['next']['page']),(20,12))

 def test_mirror_duplicate_and_parked_domains_finish_without_a_listing(self):
  def forbidden(*a,**k):raise AssertionError('no request expected')
  with patch.object(catalogue_sources,'checked_get',forbidden):
   mirror=catalogue_sources.fetch({'type':'html','domain':'y.hentaichan.live','name':'Y','url':'https://y.hentaichan.live/','hosts':['y.hentaichan.live']},{'page':1})
   duplicate=catalogue_sources.fetch({**SPEC,'source':{'id':'5504588601186153612'}},{'page':11,'url':ROOT+'/manga/newest?offset=200'})
  for result in (mirror,duplicate):self.assertEqual((result['rows'],result['next'],result['state'],result['noListing']),([],None,'done',True))
  parked='<html><head><meta name="description" content="This domain may be for sale."><script src="https://assets.abovedomains.com/x.js"></script></head><body><h1>henchan.pro</h1></body></html>'
  with patch.object(catalogue_sources,'checked_get',lambda *a,**k:(parked.encode(),'https://henchan.pro/')),patch.object(catalogue_sources,'permitted',lambda *a,**k:True):
   result=catalogue_sources.fetch({'type':'html','domain':'henchan.pro','name':'HenChan','url':'https://henchan.pro/','hosts':['henchan.pro']},{'page':1})
  self.assertEqual((result['state'],result['noListing']),('done',True))
  self.assertIn('припаркован',result['reason'])
  # The indexer accepts such an answer as finished, not as an empty first page.
  db,store=memory_store()
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'DATA_DIR':d,'MEDIA_VAULT_DISABLE_WORKER':'1'}):
   worker=Indexer(store,lambda s,c:result,lambda:1000,interval=0)
   with db:key=worker.enqueue({'type':'html','domain':'henchan.pro','name':'HenChan','url':'https://henchan.pro/','hosts':['henchan.pro']})
   worker.run_once()
  self.assertEqual(db.execute('SELECT state,error FROM catalogue_jobs WHERE id=?',(key,)).fetchone()[0],'done')

 def test_new_hentaichan_jobs_do_not_carry_the_henchan_bridge_id(self):
  installed=[{'id':'5504588601186153612','name':'HenChan','lang':'ru','baseUrl':'https://xxl.hentaichan.live'}]
  job=next(j for j in catalogue_sources.base_sources(installed) if j['domain']=='hentaichan.live')
  self.assertEqual((job['type'],'source' in job),('html',False))

class DeepListingTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db,self.store=memory_store();self.clock=[1000.0]
 def tearDown(self):
  self.env.stop();self.temp.cleanup();self.db.close()

 def job(self,fetch,cursor,pages,spec=None):
  worker=Indexer(self.store,fetch,lambda:self.clock[0],interval=0)
  spec=spec or {'type':'bridge','domain':'gallery.example','name':'Gallery · all','source':{'id':'42','lang':'all'}}
  with self.db:
   key=worker.enqueue(spec)
   self.db.execute("UPDATE catalogue_jobs SET cursor=?,pages=?,records=?,state='retry',attempts=11 WHERE id=?",(json.dumps(cursor),pages,pages*20,key))
  return worker,key

 def row(self,key):
  return self.db.execute('SELECT state,cursor,pages,attempts,reason FROM catalogue_jobs WHERE id=?',(key,)).fetchone()

 def test_our_bound_no_longer_stops_at_page_2000(self):
  self.assertEqual(SeriesPort.catalogue_params(None,2001,'',''),'')
  with self.assertRaises(SourceListingEnd):SeriesPort.catalogue_params(None,CATALOGUE_PAGE_LIMIT+1,'','')
  with self.assertRaises(SourceError):SeriesPort.catalogue_params(None,0,'','')
  from manga_hentaihand import HOSTS,public_api
  host=sorted(HOSTS)[0]
  self.assertTrue(public_api(host,'/api/comics','page=2001&sort=popularity&order=desc&duration=all'))

 def test_a_job_at_page_2001_continues_from_its_cursor(self):
  seen=[]
  def fetch(spec,cursor):
   seen.append(dict(cursor));return {'rows':[{'kind':'manga','provider':'fixture','title':'Deep','sourceUrl':'https://gallery.example/g/2001'}],'next':{'page':cursor['page']+1}}
  worker,key=self.job(fetch,{'page':2001},2000)
  worker.run_once()
  self.assertEqual(seen,[{'page':2001}])
  state,cursor,pages,attempts,_=self.row(key)
  self.assertEqual((state,json.loads(cursor),pages,attempts),('queued',{'page':2002},2001,0))

 def test_gone_page_after_served_pages_finishes_the_listing_as_done(self):
  def gone(spec,cursor):
   response=requests.Response();response.status_code=410
   raise requests.HTTPError('410 Client Error: Gone',response=response)
  spec={'type':'html','domain':'moody.example','name':'Moody','url':'https://moody.example/','hosts':['moody.example']}
  worker,key=self.job(gone,{'page':100,'url':'https://moody.example/page/100/'},99,spec)
  worker.run_once()
  state,cursor,pages,attempts,reason=self.row(key)
  self.assertEqual((state,json.loads(cursor),pages,attempts),('done',{'page':1},99,0))
  self.assertIn('Дочитано до предела сайта',reason);self.assertIn('410',reason);self.assertIn('частичный охват',reason)
  self.assertEqual(self.db.execute('SELECT records FROM catalogue_jobs WHERE id=?',(key,)).fetchone()[0],99*20)
  # It is not retried in a loop: the next turn waits for the normal refresh.
  self.clock[0]+=3600;self.assertFalse(worker.run_once())
  self.assertEqual(self.row(key)[0],'done')

 def test_public_http_404_past_the_last_page_is_an_end_but_a_first_page_404_is_not(self):
  def missing(spec,cursor):
   error=SourceError('Источник вернул HTTP 404.');error.http_status=404;raise error
  worker,key=self.job(missing,{'page':48},47)
  worker.run_once();self.assertEqual(self.row(key)[0],'done')
  first,first_key=self.job(missing,{'page':1},0,{'type':'bridge','domain':'other.example','name':'Other','source':{'id':'43','lang':'en'}})
  first.run_once();self.assertEqual(self.row(first_key)[0],'retry')
  self.assertFalse(listing_end({'cursor':{'page':5},'pages':4},{'type':'bridge-detail'},SourceError('x'),404))

 def test_our_own_page_bound_ends_the_walk_as_done(self):
  def bound(spec,cursor):raise SourceListingEnd('Дочитано до предела обхода: 100000 страниц каталога.')
  worker,key=self.job(bound,{'page':CATALOGUE_PAGE_LIMIT+1},CATALOGUE_PAGE_LIMIT)
  worker.run_once()
  state,cursor,_,_,reason=self.row(key)
  self.assertEqual((state,json.loads(cursor)),('done',{'page':1}));self.assertIn('предела обхода',reason)
  def last(spec,cursor):return {'rows':[{'kind':'manga','provider':'fixture','title':'Last','sourceUrl':'https://gallery.example/g/last'}],'next':{'page':CATALOGUE_PAGE_LIMIT+1}}
  worker,key=self.job(last,{'page':CATALOGUE_PAGE_LIMIT},CATALOGUE_PAGE_LIMIT-1,{'type':'bridge','domain':'b.example','name':'B','source':{'id':'44','lang':'en'}})
  worker.run_once();state,cursor,_,_,reason=self.row(key)
  self.assertEqual((state,json.loads(cursor)),('done',{'page':1}));self.assertIn('предела обхода',reason)

 def test_seed_gives_a_stalled_site_end_its_turn_now(self):
  worker,key=self.job(lambda s,c:{},{'page':100},99,{'type':'html','domain':'moody.example','name':'Moody','url':'https://moody.example/','hosts':['moody.example']})
  with self.db:self.db.execute("UPDATE catalogue_jobs SET state='stalled',due=?,error=? WHERE id=?",(self.clock[0]+7*86400,'HTTPError: 410 Client Error: Gone for url: https://moody.example/page/100/',key))
  with patch.object(catalogue_sources,'base_sources',lambda installed:[]):worker.seed([])
  self.assertLessEqual(self.db.execute('SELECT due FROM catalogue_jobs WHERE id=?',(key,)).fetchone()[0],self.clock[0])

if __name__=='__main__':unittest.main()
