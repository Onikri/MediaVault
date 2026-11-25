"""hanime1.me listing indexing from recorded listing fixtures; no network."""
import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from bs4 import BeautifulSoup
import catalogue_hanime1,content_catalog,hentai_video_sites as sites
from catalogue_indexer import Indexer,REFRESH_BASE
from manga_catalog_index import initialize
from source_parser import SourceChallengeError

FIXTURES=Path(__file__).parent/'fixtures'
SEARCH=(FIXTURES/'hanime1-search.html').read_text(encoding='utf-8')
GENRE=(FIXTURES/'hanime1-genre.html').read_text(encoding='utf-8')
WATCH='https://hanime1.me/watch?v='
BASE={'type':'hanime1','kind':'anime','domain':'hanime1.me','name':'Хентай · Hanime1'}
HENTAI_GENRE={**BASE,'term':{'category':'genre','label':'裏番','sourceId':'裏番'}}

class Http:
 def __init__(self,pages):self.pages=pages;self.calls=[]
 def document(self,url,**_):
  self.calls.append(url)
  value=self.pages[url]
  if isinstance(value,Exception):raise value
  return value,url,{}
 def close(self):pass

def card(v,title):
 return f'<div class="horizontal-card"><a class="video-link" href="{WATCH}{v}"><img src="https://vdownload.hembed.com/image/thumbnail/{v}l.jpg"><div class="title">{title}</div></a></div>'

def page(cards,last):
 return '<div>'+''.join(card(v,t) for v,t in cards)+'</div>'+''.join(f'<a href="?page={n}">{n}</a>' for n in range(2,last+1))

class Hanime1Catalogue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();policy=Path(self.tmp.name)/'policy.json'
  policy.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(policy),'DATA_DIR':self.tmp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db)
 def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()

 def test_listing_cards_parse_with_the_search_function(self):
  base=sites._hanime1_cards(BeautifulSoup(SEARCH,'html.parser'),'https://hanime1.me/search')
  # The sponsor card links elsewhere and drops out, as in search.
  self.assertEqual(len(base),6);self.assertEqual(base[0][:2],(WATCH+'409377','レミ〇ールさん夜の散策(完成版公開)'))
  self.assertTrue(all(c.startswith('https://vdownload.hembed.com/image/thumbnail/') for _,_,c in base))
  # Anime genre routes render a poster grid; the same function reads it.
  grid=sites._hanime1_cards(BeautifulSoup(GENRE,'html.parser'),'https://hanime1.me/search?genre=裏番')
  self.assertEqual([u[-6:] for u,_,_ in grid],['408317','408319','408316','408315'])
  self.assertTrue(all(c.startswith('https://vdownload.hembed.com/image/cover/') for _,_,c in grid))
  soup=BeautifulSoup(SEARCH,'html.parser')
  self.assertEqual(catalogue_hanime1.genres(soup,'https://hanime1.me/search'),['裏番','泡麵番','Motion Anime','3DCG','2.5D','2D動畫','AI生成','MMD','Cosplay','新番預告'])
  self.assertEqual(catalogue_hanime1.last_page(soup,'https://hanime1.me/search',None),387)
  self.assertEqual(catalogue_hanime1.last_page(BeautifulSoup(GENRE,'html.parser'),'https://hanime1.me/search?genre=裏番','裏番'),73)
  self.assertEqual(catalogue_hanime1.listing_url('Motion Anime',2),'https://hanime1.me/search?genre=Motion+Anime&page=2')
  # The search form holds the tag dictionary and the release years.
  self.assertEqual(catalogue_hanime1.tags(soup),['無碼','中文字幕','巨乳','POV'])
  self.assertEqual(catalogue_hanime1.years(soup),['2026 年','2003 年'])
  self.assertEqual(catalogue_hanime1.listing_url(None,2,'巨乳'),'https://hanime1.me/search?'+urlencode([('tags[]','巨乳'),('page',2)]))
  self.assertEqual(catalogue_hanime1.listing_url(None,1,None,'2003 年'),'https://hanime1.me/search?date=2003+%E5%B9%B4')
  # The pager of a tag route writes tags[0]; a pager of another filter does not count.
  pager=BeautifulSoup('<a href="?'+urlencode([('tags[0]','巨乳'),('page',5)])+'">5</a><a href="?'+urlencode([('tags[0]','POV'),('page',9)])+'">9</a>','html.parser')
  self.assertEqual(catalogue_hanime1.last_page(pager,catalogue_hanime1.listing_url(None,1,'巨乳'),None,'巨乳'),5)
  self.assertEqual(catalogue_hanime1.last_page(pager,'https://hanime1.me/search',None),1)

 def test_genre_page_groups_series_with_the_genre_and_the_search_identity(self):
  http=Http({catalogue_hanime1.listing_url('裏番',1):GENRE})
  result=catalogue_hanime1.catalogue(HENTAI_GENRE,{'page':1},http)
  self.assertEqual(len(result['rows']),1);row=result['rows'][0]
  name='與毫無自覺的青梅竹馬出於好奇試著做愛之後'
  self.assertEqual({k:row[k] for k in ('id','provider','kind','title','url','sourceUrl','episodes','genres','tags','age')},
                   {'id':'hanime1:'+WATCH+'408315','provider':'hanime1','kind':'anime','title':name,'url':WATCH+'408315',
                    'sourceUrl':WATCH+'408315','episodes':3,'genres':['裏番'],'tags':[],'age':18})
  self.assertTrue(row['cover'].startswith('https://vdownload.hembed.com/image/cover/408315.jpg'));self.assertNotIn('providerId',row)
  # Episode 2 of another series waits on the next page for its episode 1.
  self.assertEqual(result['next']['page'],2);self.assertEqual([h[:2]+[h[3]] for h in result['next']['held']],[[WATCH+'408319','歡迎來到後宮島！ 2',1]])
  self.assertNotIn('catalogues',result)
  # The live search over the same cards gives the same card id and fields.
  found=sites.hanime1_search(name,Http({'https://hanime1.me/search?'+urlencode({'query':name}):GENRE}))
  live=next(r for r in found if r['title']==name)
  self.assertEqual(live['provider']+':'+live['url'],row['id'])
  self.assertEqual({k:live[k] for k in ('url','title','kind','cover','episodes')},{k:row[k] for k in ('url','title','kind','cover','episodes')})

 def test_a_series_waits_pages_for_its_first_episode(self):
  pages={catalogue_hanime1.listing_url(None,1):page([(9,'Garden 3'),(8,'Solo')],4),
         catalogue_hanime1.listing_url(None,2):page([(7,'Garden 2'),(6,'Late 5')],4),
         catalogue_hanime1.listing_url(None,3):page([(5,'Garden 1'),(4,'Other')],4),
         catalogue_hanime1.listing_url(None,4):page([(3,'Tail 2')],4)}
  http=Http(pages);cursor={'page':1};seen=[]
  while cursor:
   result=catalogue_hanime1.catalogue(BASE,cursor,http);seen.append([(r['title'],r['url'][-1],r['episodes']) for r in result['rows']]);cursor=result['next']
  self.assertEqual(seen,[[('Solo','8',1)],[],[('Garden','5',3),('Other','4',1)],[('Late','6',1),('Tail','3',1)]])
  self.assertEqual(len(http.calls),4)

 def test_listing_rows_are_hentai_by_host_and_carry_genre_facts(self):
  rows=catalogue_hanime1.catalogue(BASE,{'page':1},Http({catalogue_hanime1.listing_url(None,1):SEARCH}))['rows']
  rows+=catalogue_hanime1.catalogue(HENTAI_GENRE,{'page':1},Http({catalogue_hanime1.listing_url('裏番',1):GENRE}))['rows']
  self.assertEqual(content_catalog.ingest(self.db,rows),len(rows))
  data=content_catalog.browse(self.db,kind='anime',genre='Хентай')
  self.assertEqual(data['total'],len(rows));self.assertTrue(all('Хентай' in item['genres'] for item in data['items']))
  self.assertEqual(self.db.execute("SELECT DISTINCT source,category FROM content_tag_facts").fetchall(),[('hanime1.me','genres')])
  # The tag policy shows a source genre it does not map as a tag.
  self.assertEqual(content_catalog.browse(self.db,kind='anime',tag='裏番',genre='Хентай')['total'],1)
  self.assertEqual(content_catalog.browse(self.db,kind='anime',age='adult')['total'],len(rows))

 def test_seeded_job_walks_pages_queues_genre_routes_and_reports_a_challenge(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  worker=Indexer(store,fetch,lambda:now[0],interval=0)
  worker.seed([])
  (key,host,cursor,state,spec),=self.db.execute("SELECT id,host,cursor,state,spec FROM catalogue_jobs WHERE kind='hanime1'").fetchall()
  self.assertEqual((host,cursor,state,json.loads(spec)),('hanime1.me','{"page":1}','queued',BASE))
  self.assertGreaterEqual(Indexer(store,fetch,lambda:now[0]).base_pace('hanime1.me'),1.5)
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind!='hanime1'",(now[0]+10**9,))
  http=Http({catalogue_hanime1.listing_url(None,1):SEARCH,catalogue_hanime1.listing_url(None,2):SourceChallengeError('Источник требует проверку браузера.')})
  with patch('source_parser.PublicHttp',lambda **_:http):
   self.assertTrue(worker.run_once())
   state,records,cursor=self.db.execute('SELECT state,records,cursor FROM catalogue_jobs WHERE id=?',(key,)).fetchone()
   self.assertEqual((state,records,json.loads(cursor)['page']),('queued',5,2))
   terms=[json.loads(s)['term'] for (s,) in self.db.execute("SELECT spec FROM catalogue_jobs WHERE kind='hanime1' AND json_extract(spec,'$.term') IS NOT NULL ORDER BY rowid")]
   routes=[t['label'] for t in terms if t['category']=='genre']
   self.assertEqual(len(routes),10);self.assertIn('裏番',routes)
   # Every tag of the search form and every release year walk as routes too.
   self.assertEqual([t['label'] for t in terms if t['category']=='tag'],['無碼','中文字幕','巨乳','POV'])
   self.assertEqual([(t['label'],t['sourceId']) for t in terms if t['category']=='year'],[('2026','2026 年'),('2003','2003 年')])
   self.assertEqual(len(terms),16)
   self.db.execute("UPDATE catalogue_jobs SET due=? WHERE id!=?",(now[0]+10**9,key));now[0]+=3
   self.assertTrue(worker.run_once())
  state,error=self.db.execute('SELECT state,error FROM catalogue_jobs WHERE id=?',(key,)).fetchone()
  self.assertEqual(state,'retry');self.assertIn('SourceChallengeError',error)
  self.assertEqual(http.calls,[catalogue_hanime1.listing_url(None,1),catalogue_hanime1.listing_url(None,2)])

 def test_tag_and_year_routes_add_facts_to_known_series_only(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  # The genre route found two series; Garden has two episodes.
  listing=Http({catalogue_hanime1.listing_url('裏番',1):page([(9,'Garden 2'),(8,'Solo'),(5,'Garden 1')],1)})
  self.assertEqual(content_catalog.ingest(self.db,catalogue_hanime1.catalogue(HENTAI_GENRE,{'page':1},listing)['rows']),2)
  raw=lambda:{r['title']:r for (v,) in self.db.execute('SELECT raw FROM content_titles') for r in [json.loads(v)]}
  before=raw()
  tag={**BASE,'term':{'category':'tag','label':'巨乳','sourceId':'巨乳'}}
  year={**BASE,'term':{'category':'year','label':'2003','sourceId':'2003 年'}}
  tag_pager=lambda n:'<a href="?'+urlencode([('tags[0]','巨乳'),('page',n)])+'">'+str(n)+'</a>'
  # Garden's first episode carries the tag; Stranger shows only episode 2 and
  # Lonely is not in the index yet: neither becomes a new card.
  pages={catalogue_hanime1.listing_url(None,1,'巨乳'):page([(4,'Stranger 2'),(5,'Garden 1')],1)+tag_pager(2),
         catalogue_hanime1.listing_url(None,2,'巨乳'):page([(3,'Lonely')],1)+tag_pager(2),
         catalogue_hanime1.listing_url(None,1,None,'2003 年'):page([(8,'Solo')],1)}
  http=Http(pages);worker=Indexer(store,fetch,lambda:now[0],interval=0)
  def walk():
   for spec in (tag,year):worker.enqueue(spec)
   self.db.execute("UPDATE catalogue_jobs SET due=? WHERE json_extract(spec,'$.term.category') IN ('tag','year')",(now[0],))
   with patch('source_parser.PublicHttp',lambda **_:http):
    while worker.run_once():now[0]+=3
  walk()
  states=self.db.execute("SELECT json_extract(spec,'$.term.label'),state,pages,records,error FROM catalogue_jobs ORDER BY 1").fetchall()
  self.assertEqual(states,[('2003','done',1,1,''),('巨乳','done',2,1,'')])
  after=raw()
  self.assertEqual(sorted(after),['Garden','Solo'])
  self.assertEqual((after['Garden']['tags'],after['Garden']['genres'],after['Garden']['episodes']),(['巨乳'],['裏番'],2))
  self.assertEqual(after['Garden']['cover'],before['Garden']['cover'])
  self.assertEqual((after['Solo']['year'],after['Solo']['tags'],after['Solo']['genres']),(2003,[],['裏番']))
  facts=lambda:self.db.execute('SELECT * FROM content_tag_facts ORDER BY 1,3,4,5').fetchall()
  garden=content_catalog.title_key('anime','hanime1','hanime1:'+WATCH+'5')
  self.assertEqual([f[1:] for f in facts() if f[0]==garden],[('anime','hanime1.me','genres','裏番'),('anime','hanime1.me','tags','巨乳')])
  # The tag filter finds the series and the site genre stays a fact.
  self.assertEqual([i['title'] for i in content_catalog.browse(self.db,kind='anime',tag='巨乳')['items']],['Garden'])
  self.assertEqual(content_catalog.browse(self.db,kind='anime',tag='裏番',genre='Хентай')['total'],2)
  # The weekly pass again: no fact twice, no new card.
  first=facts();now[0]+=8*86400;walk()
  self.assertEqual(len(http.calls),6);self.assertEqual(facts(),first);self.assertEqual(sorted(raw()),['Garden','Solo'])

 def test_a_genre_route_refreshes_weekly_and_the_listing_every_two_days(self):
  from catalogue_indexer import refresh_interval,REFRESH_TAG
  self.assertEqual((refresh_interval(BASE),refresh_interval(HENTAI_GENRE)),(REFRESH_BASE,REFRESH_TAG))
  self.assertEqual(refresh_interval({**BASE,'term':{'category':'tag','label':'巨乳','sourceId':'巨乳'}}),REFRESH_TAG)

if __name__=='__main__':unittest.main()
