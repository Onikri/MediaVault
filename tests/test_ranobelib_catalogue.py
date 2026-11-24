"""RanobeLib (LibGroup site 3) catalogue indexing from a recorded listing; no network."""
import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import catalogue_sources,content_catalog,ranobe_ru
from catalogue_indexer import Indexer,REFRESH_BASE,REFRESH_TAG,LIB_HOST,PACE,HOST_SLOTS,host_of,refresh_interval
from content_sources import ranobe_titles
from manga_catalog_index import initialize

LISTING=json.loads((Path(__file__).parent/'fixtures'/'ranobelib-listing.json').read_text(encoding='utf-8'))
BOOK='https://ranobelib.me/ru/book/'

class Client:
 """httpx.Client stand-in: records the constructor's headers and HTTP/2 flag."""
 made=[]
 def __init__(self,**options):self.options=options;Client.made.append(options)
 def __enter__(self):return self
 def __exit__(self,*_):return False

class Api:
 def __init__(self,pages):self.pages=pages;self.urls=[]
 def __call__(self,client,url,hosts,headers=None,timeout=10):
  self.urls.append(url);self.hosts=hosts
  return json.dumps(self.pages[min(len(self.urls),len(self.pages))-1],ensure_ascii=False).encode(),url

def page(more):return {**LISTING,'meta':{**LISTING['meta'],'has_next_page':more}}

class RanobeLibCatalogue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();policy=Path(self.tmp.name)/'policy.json'
  policy.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(policy),'DATA_DIR':self.tmp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db)
  Client.made.clear()
 def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()

 def spec(self):return next(s for s in catalogue_sources.base_sources([]) if s.get('site')==3)

 def fetch(self,spec,cursor,pages):
  api=Api(pages)
  with patch.object(catalogue_sources.httpx,'Client',Client),patch.object(catalogue_sources,'checked_get',api):
   return catalogue_sources.fetch(spec,cursor),api

 def test_job_is_a_lib_listing_of_site_3_with_its_own_headers(self):
  spec=self.spec()
  self.assertEqual({k:spec[k] for k in ('type','kind','site','domain','referer')},{'type':'lib','kind':'ranobe','site':3,'domain':'ranobelib.me','referer':'https://ranobelib.me/'})
  self.assertEqual(catalogue_sources.source_provider(spec),'ranobelib')
  result,api=self.fetch(spec,{'page':1},[page(True)])
  options=Client.made[0];sent={k.casefold():v for k,v in options['headers'].items()}
  self.assertTrue(options['http2']);self.assertEqual(sent['site-id'],'3')
  self.assertEqual((sent['referer'],sent['origin']),('https://ranobelib.me/','https://ranobelib.me'))
  self.assertEqual(api.urls,['https://api.cdnrulib.link/api/manga?site_id%5B%5D=3&page=1']);self.assertEqual(api.hosts,{LIB_HOST})
  self.assertEqual(result['next'],{'page':2,'seed':LISTING['meta']['seed']})
  # Ranobe rows are content rows: no manga catalog_titles detail fan-out.
  self.assertEqual(result['details'],[]);self.assertEqual(len(result['rows']),len(LISTING['data']))
  self.assertTrue(all(r['kind']=='ranobe' for r in result['rows']))
  # The manga listings keep their headers (no Origin) and site ids.
  manga=[s for s in catalogue_sources.base_sources([]) if s['type']=='lib' and s.get('site')!=3]
  self.assertEqual(sorted(s['site'] for s in manga),[1,2,4]);self.assertTrue(all('kind' not in s for s in manga))
  self.assertNotIn('Origin',catalogue_sources.headers(manga[0]))

 def test_listing_fields_become_ranobe_rows(self):
  rows={r['url']:r for r in ranobe_titles(LISTING,3,'','tag')}
  mech=rows[BOOK+'116379--i-devour-mechas']
  self.assertEqual((mech['id'],mech['provider'],mech['kind'],mech['sourceUrl'],mech['language']),('ranobelib:'+BOOK+'116379--i-devour-mechas','ranobelib','ranobe',mech['url'],'ru'))
  self.assertNotIn('providerId',mech)
  # "(Новелла)" only tells the book from its manga on LibGroup; the full name stays an alias.
  self.assertEqual(mech['title'],'Я пожираю мехов');self.assertEqual(mech['titles'],{'ru':'Я пожираю мехов','en':'I Devour Mechas'})
  for alias in ('Я пожираю мехов (Новелла)','I Devour Mechas (Novel)','I Devour Mechas'):self.assertIn(alias,mech['aliases'])
  self.assertEqual((mech['year'],mech['status'],mech['age']),(2021,'Онгоинг',6))
  self.assertEqual(mech['cover'],LISTING['data'][0]['cover']['default']);self.assertNotIn('format',mech)
  adult=rows[BOOK+'244658--obitel-ee-poslednego-zelaniia'];self.assertEqual(adult['age'],18)
  self.assertEqual(rows[BOOK+'226011--xiuxian-wo-cai-shi-nu-zhu']['age'],12)
  self.assertEqual(rows[BOOK+'184550--genius-blacksmiths-game']['format'],'web_novel')
  # Editions seen on page 1 of the live listing (light-novel 11/60, novel 1/60).
  for slug,expected in (('light-novel','light_novel'),('novel','novel')):
   payload={'data':[{**LISTING['data'][0],'edition':{'slug':slug}}]}
   self.assertEqual(ranobe_titles(payload,3,'','tag')[0]['format'],expected)
  self.assertEqual(ranobe_titles(LISTING,1,'','tag'),[])
  # A filtered tag/genre listing adds that label as a source fact.
  genre=ranobe_titles(LISTING,3,'Фэнтези','genre')[0];tag=ranobe_titles(LISTING,3,'Магия','tag')[0]
  self.assertEqual((genre['genres'],genre['tags'],tag['tags'],tag['genres']),(['Фэнтези'],[],['Магия'],[]))

 def test_row_identity_matches_the_reader_search_result(self):
  with patch.object(ranobe_ru,'_lib',return_value=LISTING):found=list(ranobe_ru.lib_search('мехов',None))
  rows=ranobe_titles(LISTING,3,'','tag')
  self.assertEqual([f['provider']+':'+f['url'] for f in found],[r['id'] for r in rows])
  self.assertEqual([(f['url'],f['cover']) for f in found],[(r['url'],r['cover']) for r in rows])
  self.assertTrue(all(set(f['aliases'])<=set(r['aliases']) for f,r in zip(found,rows)))
  # The reader resolves the indexed link as its own RanobeLib book.
  self.assertEqual(ranobe_ru.route(rows[0]['url'])[0],'ranobelib')

 def test_rows_are_ranobe_content_with_genre_tag_facts_and_filters(self):
  rows=ranobe_titles(LISTING,3,'Фэнтези','genre')
  self.assertEqual(content_catalog.ingest(self.db,rows),len(rows))
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog_titles').fetchone()[0],0)
  self.assertEqual(set(k for (k,) in self.db.execute('SELECT kind FROM content_titles')),{'ranobe'})
  self.assertEqual(self.db.execute("SELECT DISTINCT kind,source,category,original FROM content_tag_facts").fetchall(),[('ranobe','ranobelib.me','genres','Фэнтези')])
  self.assertEqual(content_catalog.browse(self.db,kind='ranobe',format='Веб-новелла')['total'],1)
  self.assertEqual(content_catalog.browse(self.db,kind='ranobe',age='adult')['total'],sum(r.get('age')==18 for r in rows))
  self.assertEqual(content_catalog.browse(self.db,kind='manga')['total'],0)
  card=content_catalog.title(self.db,'ranobe','ranobelib',rows[0]['url'])
  self.assertEqual((card['title'],card['url'],card['provider']),(rows[0]['title'],rows[0]['url'],'ranobelib'))

 def test_seeded_job_shares_the_libgroup_host_and_refreshes_like_base_listings(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  pages=[page(True),page(False)]
  api=Api(pages)
  def fetch(spec,cursor):
   with patch.object(catalogue_sources.httpx,'Client',Client),patch.object(catalogue_sources,'checked_get',api):return catalogue_sources.fetch(spec,cursor)
  worker=Indexer(store,fetch,lambda:now[0],interval=1.1)
  worker.seed([])
  jobs={json.loads(spec).get('kind','manga')+':'+kind:(key,host) for key,spec,kind,host in self.db.execute("SELECT id,spec,kind,host FROM catalogue_jobs WHERE kind IN ('lib','lib-vocabulary')")}
  self.assertIn('ranobe:lib',jobs);self.assertIn('ranobe:lib-vocabulary',jobs)
  # One host for MangaLib and RanobeLib: the same pause, pace and slots.
  self.assertEqual({host for _,host in jobs.values()},{LIB_HOST});self.assertEqual(host_of(self.spec()),LIB_HOST)
  self.assertEqual((PACE,HOST_SLOTS,worker.base_pace(LIB_HOST)),({LIB_HOST:0.6},2,0.6))
  key=jobs['ranobe:lib'][0]
  self.db.execute('UPDATE catalogue_jobs SET due=? WHERE id!=?',(now[0]+10**9,key))
  # The second page repeats the first's titles; mark it distinct for the walk.
  pages[1]={**pages[1],'data':[{**r,'slug_url':r['slug_url']+'-2'} for r in pages[1]['data']]}
  for _ in range(2):self.assertTrue(worker.run_once());now[0]+=3
  state,due,records=self.db.execute('SELECT state,due,records FROM catalogue_jobs WHERE id=?',(key,)).fetchone()
  self.assertEqual((state,records),('done',2*len(LISTING['data'])));self.assertAlmostEqual(due,now[0]-3+REFRESH_BASE)
  self.assertEqual(self.db.execute("SELECT COUNT(*) FROM content_titles WHERE kind='ranobe'").fetchone()[0],2*len(LISTING['data']))
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog_titles').fetchone()[0],0)
  self.assertEqual(len(api.urls),2);self.assertTrue(api.urls[1].endswith('page=2&seed='+LISTING['meta']['seed']))

 def test_vocabulary_is_ranobe_and_routes_back_to_site_3(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  terms=[{'label':'Фэнтези','category':'genre','sourceId':4},{'label':'Магия','category':'tag','sourceId':97}]
  worker=Indexer(store,lambda spec,cursor:{'rows':[],'next':None,'vocabulary':terms},lambda:now[0],interval=0)
  worker.seed([])
  key=next(k for k,s in self.db.execute("SELECT id,spec FROM catalogue_jobs WHERE kind='lib-vocabulary'") if json.loads(s).get('kind')=='ranobe')
  self.db.execute('UPDATE catalogue_jobs SET due=? WHERE id!=?',(now[0]+10**9,key))
  self.assertTrue(worker.run_once())
  self.assertEqual(sorted(self.db.execute("SELECT label,source,category,kind FROM catalog_vocabulary WHERE source='ranobelib.me'")),
                   [('Магия','ranobelib.me','tags','ranobe'),('Фэнтези','ranobelib.me','genres','ranobe')])
  targets=[json.loads(t) for (t,) in self.db.execute("SELECT target FROM catalogue_tag_targets WHERE source='ranobelib.me'")]
  self.assertEqual(sorted((t['type'],t['kind'],t['site'],t['term']['sourceId']) for t in targets),[('lib','ranobe',3,4),('lib','ranobe',3,97)])
  # Every route of the vocabulary is queued at once, low, on the shared host.
  routes="SELECT id,priority,host,state,cursor,json_extract(spec,'$.term.sourceId') FROM catalogue_jobs WHERE kind='lib' AND json_extract(spec,'$.term') IS NOT NULL ORDER BY 6"
  queued=self.db.execute(routes).fetchall()
  self.assertEqual([(p,h,s,c,t) for _,p,h,s,c,t in queued],[(5,LIB_HOST,'queued','{"page":1}',4),(5,LIB_HOST,'queued','{"page":1}',97)])
  self.assertTrue(all(json.loads(s)['kind']=='ranobe' for (s,) in self.db.execute("SELECT spec FROM catalogue_jobs WHERE kind='lib' AND json_extract(spec,'$.term') IS NOT NULL")))
  self.assertEqual(refresh_interval(json.loads(self.db.execute('SELECT spec FROM catalogue_jobs WHERE id=?',(queued[0][0],)).fetchone()[0])),REFRESH_TAG)
  # A route already walking is neither duplicated nor restarted by the next vocabulary run.
  self.db.execute("UPDATE catalogue_jobs SET state='queued',cursor='{\"page\":3}',due=? WHERE id=?",(now[0]+10**9,queued[0][0]))
  self.db.execute("UPDATE catalogue_jobs SET state='queued',due=? WHERE id=?",(now[0],key));self.db.execute("UPDATE catalogue_jobs SET due=? WHERE id=?",(now[0]+10**9,queued[1][0]))
  self.assertTrue(worker.run_once())
  again=self.db.execute(routes).fetchall()
  self.assertEqual(len(again),2);self.assertEqual(again[0][4],'{"page":3}');self.assertEqual([r[1] for r in again],[5,5])
  # Manga LibGroup vocabularies still only record targets for the owner's ask.
  manga=next(k for k,s in self.db.execute("SELECT id,spec FROM catalogue_jobs WHERE kind='lib-vocabulary'") if json.loads(s).get('site')==1)
  self.db.execute('UPDATE catalogue_jobs SET due=? WHERE id!=?',(now[0]+10**9,manga));self.db.execute('UPDATE catalogue_jobs SET due=? WHERE id=?',(now[0],manga))
  self.assertTrue(worker.run_once())
  self.assertEqual(len(self.db.execute(routes).fetchall()),2)

if __name__=='__main__':unittest.main()
