"""HanimeTV catalogue indexing from a recorded feed fixture; no network."""
import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import catalogue_hanime,content_catalog,hanime_source
from catalogue_indexer import Indexer,REFRESH_BASE
from manga_catalog_index import initialize

FEED=json.loads((Path(__file__).parent/'fixtures'/'hanime-feed.json').read_text(encoding='utf-8'))['data']
VIDEO='https://hanime.tv/videos/hentai/'

class Response:
 def __init__(self,body):self.body=body
 def iter_content(self,size):
  for i in range(0,len(self.body),size):yield self.body[i:i+size]
 def close(self):pass

class Http:
 def __init__(self):self.calls=[]
 def _open(self,url,headers=None):self.calls.append(url);return Response(json.dumps({'data':FEED}).encode()),url
 def close(self):pass

class HanimeCatalogue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();policy=Path(self.tmp.name)/'policy.json'
  policy.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(policy),'DATA_DIR':self.tmp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.cache=patch.dict(hanime_source._cache,{'until':0.0,'rows':[]});self.cache.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db)
 def tearDown(self):self.db.close();self.cache.stop();self.env.stop();self.tmp.cleanup()

 def rows(self):return {row['title']:row for name,episodes in catalogue_hanime.series(FEED) for row in [catalogue_hanime.series_row(name,episodes)]}

 def test_episodes_group_into_series_with_the_feed_fields(self):
  rows=self.rows()
  self.assertEqual(sorted(rows),['Cafe Junkie','Ikusa Otome Suvia Bonus Video','Tropical Kiss','Yabai! Fukushuu Yami Site'])
  kiss=rows['Tropical Kiss']
  # The feed lists episode 3 first; the series opens at episode 1 and its year.
  self.assertEqual(kiss['url'],VIDEO+'tropical-kiss-ova-1');self.assertEqual(kiss['sourceUrl'],kiss['url'])
  self.assertEqual((kiss['kind'],kiss['provider'],kiss['id'],kiss['episodes'],kiss['year'],kiss['age']),('anime','hanime','hanime:'+kiss['url'],3,2012,18))
  self.assertEqual(kiss['cover'],next(v['cover_url'] for v in FEED if v['slug']=='tropical-kiss-ova-1'))
  self.assertEqual(kiss['tags'],list(dict.fromkeys(t for slug in ('tropical-kiss-ova-1','tropical-kiss-ova-2','tropical-kiss-ova-3') for v in FEED if v['slug']==slug for t in v['tags'])))
  self.assertEqual(kiss['genres'],[]);self.assertNotIn('providerId',kiss)
  for alias in ('トロピカルKISS','트로피컬 키스','Тропический поцелуй','トロピカルKISS♡'):self.assertIn(alias,kiss['aliases'])
  self.assertNotIn('Tropical Kiss',kiss['aliases'])
  yabai=rows['Yabai! Fukushuu Yami Site']['aliases']
  for alias in ('Dangerous! Revenge - Website of Darkness','ヤバい! -復讐・闇サイト-','위험해! -복수・암흑 Site-','危机！-复仇·暗黑网站'):self.assertIn(alias,yabai)
  self.assertEqual(rows['Ikusa Otome Suvia Bonus Video']['episodes'],1)

 def test_row_matches_the_live_search_result_that_opens_our_player(self):
  row=self.rows()['Tropical Kiss']
  with patch.object(hanime_source,'load_catalog',return_value=FEED):
   found=hanime_source.search('Tropical Kiss',None)[0];episodes=hanime_source.episodes_for(row['url'],None)
  # The client keys a source result as provider:url (use-source-titles.js).
  self.assertEqual(found['provider']+':'+found['url'],row['id'])
  self.assertEqual({k:found[k] for k in ('url','title','kind','year','cover','episodes')},{k:row[k] for k in ('url','title','kind','year','cover','episodes')})
  self.assertEqual([e['number'] for e in episodes],[1,2,3])

 def test_one_feed_request_serves_every_page(self):
  http=Http()
  with patch.object(catalogue_hanime,'PAGE',3):
   first=catalogue_hanime.catalogue({'page':1},http);second=catalogue_hanime.catalogue(first['next'],http)
  self.assertEqual(http.calls,[hanime_source.CATALOG])
  self.assertEqual((len(first['rows']),first['next'],first['total']),(3,{'page':2},4))
  self.assertEqual((len(second['rows']),second['next']),(1,None))
  self.assertEqual(len({r['id'] for r in first['rows']+second['rows']}),4)

 def test_hentai_genre_comes_from_the_host_rule_and_tags_are_facts(self):
  self.assertEqual(content_catalog.ingest(self.db,list(self.rows().values())),4)
  data=content_catalog.browse(self.db,kind='anime',genre='Хентай')
  self.assertEqual(data['total'],4);self.assertTrue(all('Хентай' in item['genres'] for item in data['items']))
  raw=[json.loads(r) for (r,) in self.db.execute('SELECT raw FROM content_titles')]
  self.assertTrue(all(r['genres']==[] for r in raw))
  facts=self.db.execute("SELECT DISTINCT source,category FROM content_tag_facts").fetchall()
  self.assertEqual(facts,[('hanime.tv','tags')])
  self.assertEqual(content_catalog.browse(self.db,kind='anime',tag='Tentacle',genre='Хентай')['total'],
                   sum('tentacle' in r['tags'] for r in self.rows().values()))
  self.assertEqual(content_catalog.browse(self.db,kind='anime',age='adult')['total'],4)

 def test_seeded_job_crawls_and_a_refresh_leaves_unchanged_rows_alone(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  worker=Indexer(store,fetch,lambda:now[0],interval=0)
  worker.seed([])
  job=self.db.execute("SELECT id,host,cursor,state,spec FROM catalogue_jobs WHERE kind='hanime'").fetchall()
  self.assertEqual(len(job),1);key,host,cursor,state,spec=job[0]
  self.assertEqual((host,cursor,state,json.loads(spec)['kind']),('hanime.tv','{"page":1}','queued','anime'))
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind!='hanime'",(now[0]+10**9,))
  http=Http()
  def crawl():
   with patch.object(catalogue_hanime,'PAGE',3),patch('source_parser.PublicHttp',lambda **_:http):
    for _ in range(2):self.assertTrue(worker.run_once());now[0]+=3
  crawl()
  state,due,records=self.db.execute('SELECT state,due,records FROM catalogue_jobs WHERE id=?',(key,)).fetchone()
  self.assertEqual((state,records),('done',4));self.assertAlmostEqual(due,now[0]-3+REFRESH_BASE)
  self.assertEqual(len(http.calls),1)
  before=self.db.execute('SELECT id,raw FROM content_titles ORDER BY id').fetchall();facts=self.db.execute('SELECT * FROM content_tag_facts ORDER BY 1,3,4,5').fetchall()
  self.assertEqual(len(before),4)
  now[0]=due+1;hanime_source._cache.update(until=0.0,rows=[])
  with patch.object(content_catalog,'_index',side_effect=AssertionError('unchanged row re-indexed')):crawl()
  self.assertEqual(len(http.calls),2)
  self.assertEqual(self.db.execute('SELECT id,raw FROM content_titles ORDER BY id').fetchall(),before)
  self.assertEqual(self.db.execute('SELECT * FROM content_tag_facts ORDER BY 1,3,4,5').fetchall(),facts)

if __name__=='__main__':unittest.main()
