"""HentaiMama series archive indexing from recorded page fixtures; no network."""
import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from bs4 import BeautifulSoup
import catalogue_hentaimama as mama,content_catalog,hentai_video_sites as sites
from catalogue_indexer import Indexer,refresh_interval
from manga_catalog_index import initialize
from source_parser import SourceError

FIXTURES=Path(__file__).parent/'fixtures'
ARCHIVE=(FIXTURES/'hentaimama-archive.html').read_text(encoding='utf-8')
SERIES=(FIXTURES/'hentaimama-series.html').read_text(encoding='utf-8')
GENRES=(FIXTURES/'hentaimama-genres.html').read_text(encoding='utf-8')
SHOWS='https://hentaimama.io/tvshows/'
BASE={'type':'hentaimama','kind':'anime','domain':'hentaimama.io','name':'Хентай · HentaiMama'}

class Http:
 def __init__(self,pages):self.pages=pages;self.calls=[]
 def document(self,url,**_):
  self.calls.append(url)
  value=self.pages.get(url)
  if value is None:
   # The transport's answer to a page the site no longer has.
   value=SourceError('Источник вернул HTTP 404.');value.http_status=404
  if isinstance(value,Exception):raise value
  return value,url,{}
 def close(self):pass

def archive(slugs,pages):
 cards=''.join(f'<article class="item tvshows"><div class="poster"><img src="https://hentaimama.io/wp-content/uploads/{s}.webp"></div>'
               f'<div class="data"><h3><a href="{SHOWS}{s}/">{s.title()}</a></h3><div class="card-tags"><span class="tag">2021</span></div></div></article>' for s in slugs)
 return f'<div class="items">{cards}</div><div class="pagination dt-pg" data-page="1" data-pages="{pages}"></div>'

def series(slug,title,genres,studio,episodes=2):
 links=''.join(f'<a class="dt-se-item" href="https://hentaimama.io/episodes/{slug}-episode-{n}/">EP {n}</a>' for n in range(1,episodes+1))
 return (f'<div class="sbox dt-show-card"><div class="dsc-left"><div class="dsc-poster"><img src="https://hentaimama.io/wp-content/uploads/{slug}.webp"></div>'
         f'<div class="dsc-stats"><div class="dsc-stat"><span>Studio</span><b><a href="https://hentaimama.io/studio/{studio.lower()}/">{studio}</a></b></div></div></div>'
         f'<div class="dsc-body"><h1 class="dsc-title">{title}</h1><div class="dsc-genres">'+''.join(f'<a href="https://hentaimama.io/genre/{g.lower()}/">{g}</a>' for g in genres)+
         f'</div><div class="dsc-desc"><p>About {title}.</p></div></div></div><div id="episodes" class="dt-se-list">{links}</div>')

class HentaiMamaCatalogue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();policy=Path(self.tmp.name)/'policy.json'
  policy.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(policy),'DATA_DIR':self.tmp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db)
 def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()

 def test_archive_series_page_and_genre_dictionary_parse(self):
  soup=BeautifulSoup(ARCHIVE,'html.parser')
  # The header menu links genres too; only series cards count.
  self.assertEqual(mama.archive_cards(soup,SHOWS),[['yoasobi-gurashi',2024],['hitori-tsuma',2026],['harem-camp',2022]])
  self.assertEqual(mama.last_page(soup),62)
  self.assertEqual((mama.archive_url(1),mama.archive_url(3)),(SHOWS,SHOWS+'page/3/'))
  row=mama.series_row(SERIES,SHOWS+'harem-camp/',2020)
  self.assertEqual({k:row[k] for k in ('id','provider','kind','title','aliases','url','sourceUrl','episodes','year','studios','tags','age')},
                   {'id':'hentaimama:'+SHOWS+'harem-camp/','provider':'hentaimama','kind':'anime','title':'Harem Camp!',
                    'aliases':['Harem Camp!','ハーレムきゃんぷっ！'],'url':SHOWS+'harem-camp/','sourceUrl':SHOWS+'harem-camp/',
                    'episodes':8,'year':2022,'studios':['Hokiboshi'],'tags':[],'age':18})
  # The series' own genres, not the header menu (3D is not one of them).
  self.assertEqual(len(row['genres']),21);self.assertEqual(row['genres'][:3],['Blonde','Blowjob','Comedy']);self.assertNotIn('3D',row['genres'])
  self.assertEqual(row['description'],'A camping trip goes wrong in a crowded tent.\nSecond paragraph of the fixture synopsis.')
  self.assertTrue(row['cover'].startswith('https://hentaimama.io/wp-content/uploads/'));self.assertNotIn('providerId',row)
  self.assertEqual(mama.genres(BeautifulSoup(GENRES,'html.parser')),['3D','Action','Adventure','Ahegao','Anal','Animal Girls'])
  # Without the HTML card the JSON-LD still names genres, studio, year and episodes.
  ld=str(BeautifulSoup(SERIES,'html.parser').select_one('script[type="application/ld+json"]'))
  bare=mama.series_row('<h1>Harem Camp!</h1>'+ld,SHOWS+'harem-camp/')
  self.assertEqual((bare['studios'],bare['year'],bare['episodes'],len(bare['genres'])),(['Hokiboshi'],2022,8,21))
  self.assertIsNone(mama.series_row(SERIES,'https://hentaimama.io/genre/harem/'))

 def test_a_catalogue_card_plays_through_the_search_path(self):
  row=mama.series_row(SERIES,SHOWS+'harem-camp/')
  self.assertEqual(sites.provider_for(row['url'])[0],'hentaimama')
  search='<article class="series-card"><a href="'+SHOWS+'harem-camp/"><img src="https://hentaimama.io/x.jpg"></a><h3>Harem Camp!</h3></article>'
  found=sites.search('hentaimama','harem camp',Http({'https://hentaimama.io/?s=harem+camp':search}))
  self.assertEqual(found[0]['provider']+':'+found[0]['url'],row['id'])
  title,episodes=sites.episodes('hentaimama',row['url'],Http({row['url']:SERIES}))
  self.assertEqual((title,len(episodes),episodes[0]['url']),('Harem Camp!',8,'https://hentaimama.io/episodes/harem-camp-episode-1/'))
  self.assertEqual(len(episodes),row['episodes'])
  # A percent-encoded slug ("star☆jewel") is a series page the player opens.
  self.assertEqual(sites.provider_for(SHOWS+'star%e2%98%86jewel/')[0],'hentaimama')

 def test_walk_reads_each_series_once_and_resumes_from_its_cursor(self):
  pages={mama.archive_url(1):archive(['alpha','beta'],2),mama.GENRES:GENRES,
         # A new series shifted beta onto page 2; it is not read twice.
         mama.archive_url(2):archive(['beta','gamma'],2),
         SHOWS+'alpha/':series('alpha','Alpha',['Harem'],'Studio A'),
         SHOWS+'gamma/':series('gamma','Gamma',['Vanilla'],'Studio B',3)}
  http=Http(pages);cursor={'page':1};steps=[]
  while cursor:
   result=mama.catalogue(BASE,cursor,http);steps.append(([r['title'] for r in result['rows']],len(result.get('vocabulary') or [])))
   self.assertTrue(result['rows'] or result['emptySpan'])
   cursor=json.loads(json.dumps(result['next'])) if result['next'] else None
   if http.calls[-1]==SHOWS+'alpha/':saved=cursor
  # beta's page went away after its card was listed: skipped, not the end.
  self.assertEqual(steps,[([],0),([],6),(['Alpha'],0),([],0),([],0),(['Gamma'],0)])
  self.assertEqual(http.calls,[mama.archive_url(1),mama.GENRES,SHOWS+'alpha/',SHOWS+'beta/',mama.archive_url(2),SHOWS+'gamma/'])
  # The stored cursor continues where the walk stopped.
  self.assertEqual(saved,{'page':2,'last':2,'seen':['alpha','beta'],'queue':[['beta',2021]]})
  again=Http(pages);rest=[]
  while saved:
   result=mama.catalogue(BASE,saved,again);rest+= [r['title'] for r in result['rows']];saved=result['next']
  self.assertEqual((rest,again.calls),(['Gamma'],[SHOWS+'beta/',mama.archive_url(2),SHOWS+'gamma/']))

 def walk(self,worker,http,now):
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind='hentaimama'",(now[0],))
  with patch('source_parser.PublicHttp',lambda **_:http):
   while worker.run_once():now[0]+=3

 def test_seeded_job_writes_series_with_genres_studios_and_no_duplicates(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  worker=Indexer(store,fetch,lambda:now[0],interval=0);worker.seed([])
  (key,host,spec),=self.db.execute("SELECT id,host,spec FROM catalogue_jobs WHERE kind='hentaimama'").fetchall()
  self.assertEqual((host,json.loads(spec)),('hentaimama.io',BASE))
  self.assertGreaterEqual(Indexer(store,fetch,lambda:now[0]).base_pace('hentaimama.io'),1.5)
  self.assertEqual(refresh_interval(BASE),7*86400)
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind!='hentaimama'",(now[0]+10**9,))
  pages={mama.archive_url(1):archive(['harem-camp','alpha'],1),mama.GENRES:GENRES,
         SHOWS+'harem-camp/':SERIES,SHOWS+'alpha/':series('alpha','Alpha',['Harem','Vanilla'],'Hokiboshi')}
  http=Http(pages);self.walk(worker,http,now)
  state,pages_read,records,error=self.db.execute('SELECT state,pages,records,error FROM catalogue_jobs WHERE id=?',(key,)).fetchone()
  self.assertEqual((state,pages_read,records,error),('done',4,2,''))
  titles=lambda:sorted(json.loads(v)['title'] for (v,) in self.db.execute("SELECT raw FROM content_titles WHERE json_extract(raw,'$.provider')='hentaimama'"))
  self.assertEqual(titles(),['Alpha','Harem Camp!'])
  facts=lambda:self.db.execute("SELECT category,original FROM content_tag_facts WHERE source='hentaimama.io' ORDER BY 1,2").fetchall()
  first=facts()
  self.assertIn(('studios','Hokiboshi'),first);self.assertIn(('genres','Vanilla'),first)
  self.assertEqual(len([f for f in first if f[0]=='genres']),21+2)
  # The genre dictionary page adds genres no indexed series carries yet.
  vocabulary={label for (label,) in self.db.execute("SELECT label FROM catalog_vocabulary WHERE source='hentaimama.io' AND category='genres'")}
  self.assertTrue({'3D','Action','Animal Girls'}<=vocabulary);self.assertIn('Harem',vocabulary)
  # The hentai video section's genre filter finds HentaiMama series by a site genre.
  self.assertEqual(content_catalog.browse(self.db,kind='anime',genre='Хентай')['total'],2)
  self.assertEqual(sorted(i['title'] for i in content_catalog.browse(self.db,kind='anime',tag='Vanilla')['items']),['Alpha','Harem Camp!'])
  # The weekly pass again: the same two series, no fact twice.
  now[0]+=8*86400;self.walk(worker,http,now)
  self.assertEqual(len(http.calls),8);self.assertEqual(titles(),['Alpha','Harem Camp!']);self.assertEqual(facts(),first)

 def test_archive_past_the_site_end_finishes_the_walk_marked(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  worker=Indexer(store,fetch,lambda:now[0],interval=0);worker.seed([])
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind!='hentaimama'",(now[0]+10**9,))
  # The pager names three pages; page 3 is gone.
  pages={mama.archive_url(1):archive(['alpha'],3),mama.GENRES:GENRES,SHOWS+'alpha/':series('alpha','Alpha',['Harem'],'A'),
         mama.archive_url(2):archive(['beta'],3),SHOWS+'beta/':series('beta','Beta',['Harem'],'A')}
  http=Http(pages);self.walk(worker,http,now)
  state,error,reason,cursor=self.db.execute("SELECT state,error,reason,cursor FROM catalogue_jobs WHERE kind='hentaimama'").fetchone()
  self.assertEqual((state,cursor),('done','{"page":1}'));self.assertIn('404',error);self.assertIn('страница 3',reason)
  self.assertEqual(http.calls[-1],mama.archive_url(3))

if __name__=='__main__':unittest.main()
