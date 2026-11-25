"""WatchHentai (watchhentai.net) playback and series archive indexing from recorded page fixtures; no network."""
import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from bs4 import BeautifulSoup
import catalogue_watchhentai as watch,content_catalog,hentai_video_sites as sites
from catalogue_indexer import Indexer,refresh_interval
from dynamic_video_sources import inspect,provider_for,resolve_dynamic
from manga_catalog_index import initialize
from source_parser import SourceError

FIXTURES=Path(__file__).parent/'fixtures'
read=lambda name:(FIXTURES/f'watchhentai-{name}.html').read_text(encoding='utf-8')
ARCHIVE,SERIES,EPISODE,PLAYER,SEARCH=(read(n) for n in ('archive','series','episode','player','search'))
SHOWS='https://watchhentai.net/series/'
KISHI=SHOWS+'ntr-kishi-id-01/'
EP1='https://watchhentai.net/videos/ntr-kishi-episode-1-id-01/'
PLAY1='https://watchhentai.net/player/70335/1/mp4/'
CDN='https://hstorage.xyz/files/N/ntr-kishi/ntr-kishi-1'
BASE={'type':'watchhentai','kind':'anime','domain':'watchhentai.net','name':'Хентай · WatchHentai'}

class Http:
 def __init__(self,pages):self.pages=pages;self.calls=[]
 def document(self,url,headers=None,**_):
  self.calls.append(url)
  value=self.pages.get(url)
  if value is None:
   # The transport's answer to a page the site no longer has.
   value=SourceError('Источник вернул HTTP 404.');value.http_status=404
  if isinstance(value,Exception):raise value
  if isinstance(value,tuple):return value[0],value[1],{}
  return value,url,{}
 def close(self):pass

def archive(slugs,pages,genres=('Harem','Vanilla')):
 cards=''.join(f'<article class="item tvshows"><div class="poster"><div class="buttonyear"><span>2021</span></div>'
               f'<img data-src="https://watchhentai.net/uploads/{s}/poster.jpg"></div>'
               f'<div class="data"><strong><h3><a href="{SHOWS}{s}/" title="{s.title()}">{s.title()}</a></h3></strong></div></article>' for s in slugs)
 menu=''.join(f'<li><a href="https://watchhentai.net/genre/{g.lower()}/">{g}</a> <i>3</i></li>' for g in genres)
 return (f'<div id="archive-content" class="animation-2 items full">{cards}</div>'
         f'<nav class="pagination"><span class="pagination__status">Page 1 of {pages}</span></nav><nav class="genres"><ul class="genres scrolling">{menu}</ul></nav>')

def series(slug,title,genres,studio,episodes=2):
 links=''.join(f'<li><a href="https://watchhentai.net/videos/{slug}-episode-{n}/"><span class="eptitle">Episode {n}</span></a></li>' for n in range(1,episodes+1))
 return (f'<link rel="canonical" href="{SHOWS}{slug}/"><div class="sheader"><div class="poster"><img src="https://watchhentai.net/uploads/{slug}/poster.jpg"></div>'
         f'<div class="data"><h1>{title}</h1><div class="extra"><span class="date">Mar. 3, 2024</span><span class="studio"><a href="https://watchhentai.net/studio/{studio.lower()}/">{studio}</a></span></div>'
         '<div class="sgeneros">'+''.join(f'<a href="https://watchhentai.net/genre/{g.lower()}/">{g}</a>' for g in genres)+
         f'</div></div></div><div class="wp-content"><div class="tv-single-synopsis__body"><p>About {title}.</p></div></div><div id="episodes"><ul class="episodios">{links}</ul></div>')

class WatchHentaiPlayback(unittest.TestCase):
 def test_addresses_are_checked_by_host_and_path(self):
  for url in [KISHI,EP1,SHOWS+'majime-na-kimi-ni-hamaru-karada-the-animation/']:
   self.assertEqual(sites.provider_for(url)[0],'watchhentai',url)
  for url in [SHOWS,SHOWS+'page/2/','https://watchhentai.net/videos/',SHOWS+'?letter=09',PLAY1,'https://watchhentai.net/genre/ntr/',
              'https://watchhentai.net/series/a/b/','https://watchhentai.example/series/ntr-kishi-id-01/','https://evil.net/videos/x-episode-1/']:
   self.assertIsNone(sites.provider_for(url),url)
  # Only own series cards and own episode links are kept; a link off the site or
  # into a listing is dropped, and a player page must be /player[-alt]/<post>/<n>/mp4/.
  self.assertEqual(sites._watch_page('https://evil.net/series/a/',SHOWS,'series'),'')
  self.assertEqual(sites._watch_page(EP1,SHOWS,'series'),'')
  self.assertEqual(sites._watch_page('http://watchhentai.net/series/a/',SHOWS,'series'),'')
  self.assertTrue(sites.WATCH_PLAYER.fullmatch('/player-alt/70335/1/mp4/'))
  self.assertIsNone(sites.WATCH_PLAYER.fullmatch('/player/70335/1/m3u8/'))

 def test_search_series_episodes_and_the_encoded_player_sources(self):
  http=Http({'https://watchhentai.net/?s=kishi':SEARCH,KISHI:SERIES,EP1:EPISODE,PLAY1:PLAYER})
  rows=sites.search('watchhentai','kishi',http)
  # The sidebar's popular widget links another series; it is not a result.
  self.assertEqual([(r['title'],r['url'],r['year']) for r in rows][:1],[('NTR Kishi',KISHI,2026)])
  self.assertEqual(len(rows),2);self.assertTrue(rows[0]['cover'].startswith('https://watchhentai.net/uploads/'))
  # An episode page leads to its series («All Episodes»), not to a sidebar card.
  title,episodes=sites.episodes('watchhentai',EP1,http)
  self.assertEqual(title,'NTR Kishi')
  self.assertEqual([(e['number'],e['url'],e['title']) for e in episodes],
                   [(1,EP1,'Episode 1'),(2,'https://watchhentai.net/videos/ntr-kishi-episode-2/','Episode 2 (preview)')])
  streams=sites.streams('watchhentai',EP1,http)
  # The encoded whJwSources, best first; the JSON-LD contentUrl (a file the CDN 404s) is not offered.
  self.assertEqual([(s['quality'],s['url']) for s in streams],[(1080,CDN+'_1080p.mp4'),(720,CDN+'_720p.mp4')])
  self.assertEqual((streams[0]['type'],streams[0]['headers']['Referer']),('mp4','https://watchhentai.net/'))
  self.assertEqual(http.calls[-2:],[EP1,PLAY1])

 def test_player_decoding_and_refusals(self):
  self.assertEqual(sites.watch_decode('not base64 !'),'')
  # The decoder's constants are read from the page; other constants decode the same way.
  encoded=__import__('re').search(r'"file":"([^"]+)","type":"video\\/mp4","label":"720p"',PLAYER)[1]
  self.assertEqual(sites.watch_decode(encoded),CDN+'_720p.mp4')
  self.assertEqual(sites.watch_player_sources(PLAYER.replace('k=13','k=14'),PLAY1),[])
  # A player that names a file on a page instead of an MP4 is not a stream.
  self.assertEqual(sites.watch_player_sources('var whJwSources = [{"file":"https://hstorage.xyz/x.html","label":"720p"}];',PLAY1),[])
  # A player frame pointing off the site is never fetched.
  foreign=EPISODE.replace(PLAY1,'https://evil.net/player/70335/1/mp4/').replace('https://watchhentai.net/player-alt/','https://evil.net/player-alt/')
  http=Http({EP1:foreign})
  with self.assertRaisesRegex(SourceError,'не опубликовал открытое видео'):sites.streams('watchhentai',EP1,http)
  self.assertEqual(http.calls,[EP1])
  with self.assertRaisesRegex(SourceError,'не опубликовал плеер'):sites.streams('watchhentai',EP1,Http({EP1:'<h1>x</h1>'}))
  with self.assertRaisesRegex(SourceError,'серию'):sites.streams('watchhentai',KISHI,Http({}))

 def test_dynamic_routing_plays_in_our_player(self):
  http=Http({KISHI:SERIES,EP1:EPISODE,PLAY1:PLAYER})
  info=inspect(KISHI,provider_for(KISHI),http)
  self.assertEqual((info['provider'],len(info['episodes'])),('watchhentai',2))
  checked=[]
  def check(_,stream,**__):
   checked.append(stream['quality'])
   if stream['quality']==1080:raise SourceError('expired')
  with patch('dynamic_video_sources.check_mp4',side_effect=check):
   page=resolve_dynamic(http,EP1,None,'WatchHentai · EN','watchhentai')
  self.assertEqual((checked,[s['url'] for s in page.streams]),([1080,720],[CDN+'_720p.mp4']))

 def test_site_is_searchable_and_marked_as_hentai(self):
  from site_adapters import SITES
  from catalog_taxonomy import hentai_origin
  self.assertTrue(any(s.id=='watchhentai' for s in SITES))
  self.assertTrue(hentai_origin('watchhentai',KISHI,'anime'))

class WatchHentaiCatalogue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();policy=Path(self.tmp.name)/'policy.json'
  policy.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(policy),'DATA_DIR':self.tmp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db)
 def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()

 def test_archive_series_page_and_genre_menu_parse(self):
  soup=BeautifulSoup(ARCHIVE,'html.parser')
  # The upcoming strip, then the archive; the header menu and the sidebar widget are not cards.
  self.assertEqual(watch.archive_cards(soup,SHOWS),[['majime-na-kimi-ni-hamaru-karada-the-animation',None],
                   ['ichigo-aika-zatsu-de-namaiki-na-imouto-to-warikirenai-ani-id-01',2025],['modaete-yo-adam-kun-id-01',2023],['guilty-hole-id-01',2025]])
  self.assertEqual(watch.last_page(soup),47)
  self.assertEqual((watch.archive_url(1),watch.archive_url(3)),(SHOWS,SHOWS+'page/3/'))
  self.assertEqual(watch.genres(soup),['3D','Action','Adventure','Ahegao','Anal','Animal Ears'])
  # A short link redirected to the -id-01 page: the canonical address is the id.
  row=watch.series_row(SERIES,SHOWS+'ntr-kishi/',2020)
  self.assertEqual({k:row[k] for k in ('id','provider','kind','title','aliases','url','sourceUrl','episodes','year','studios','tags','age')},
                   {'id':'watchhentai:'+KISHI,'provider':'watchhentai','kind':'anime','title':'NTR Kishi','aliases':['NTR Kishi','NTR騎士'],
                    'url':KISHI,'sourceUrl':KISHI,'episodes':1,'year':2026,'studios':['Majin'],'tags':[],'age':18})
  # The series' own genres, not the header menu or the sidebar.
  self.assertEqual(row['genres'],['Blowjob','Brainwashed','Censored','Creampie','Humiliation','Lactation','Megane','NTR','Rape','Stocking'])
  self.assertEqual(row['description'],'A knight academy reunion turns sour in this fixture.\nSecond paragraph of the fixture synopsis.')
  self.assertEqual(row['cover'],'https://watchhentai.net/uploads/2026/ntr-kishi/poster.jpg');self.assertNotIn('providerId',row)
  self.assertIsNone(watch.series_row(SERIES,'https://watchhentai.net/genre/ntr/'))
  self.assertIsNone(watch.series_row('<h1>Not a series</h1>',KISHI))

 def test_a_catalogue_card_plays_through_the_search_path(self):
  row=watch.series_row(SERIES,KISHI)
  found=sites.search('watchhentai','kishi',Http({'https://watchhentai.net/?s=kishi':SEARCH}))
  self.assertEqual(found[0]['provider']+':'+found[0]['url'],row['id'])
  title,episodes=sites.episodes('watchhentai',row['url'],Http({row['url']:SERIES}))
  self.assertEqual((title,episodes[0]['url']),('NTR Kishi',EP1))
  self.assertEqual(len([e for e in episodes if not e.get('preview')]),row['episodes'])

 def test_walk_reads_each_series_once_and_resumes_from_its_cursor(self):
  pages={watch.archive_url(1):archive(['alpha','beta'],2),
         # A new series shifted beta onto page 2; it is not read twice.
         watch.archive_url(2):archive(['beta','gamma'],2),
         SHOWS+'alpha/':series('alpha','Alpha',['Harem'],'Studio A'),
         SHOWS+'gamma/':series('gamma','Gamma',['Vanilla'],'Studio B',3)}
  http=Http(pages);cursor={'page':1};steps=[]
  while cursor:
   result=watch.catalogue(BASE,cursor,http);steps.append(([r['title'] for r in result['rows']],len(result.get('vocabulary') or [])))
   self.assertTrue(result['rows'] or result['emptySpan'])
   cursor=json.loads(json.dumps(result['next'])) if result['next'] else None
   if http.calls[-1]==SHOWS+'alpha/':saved=cursor
  # The genre menu rides on page 1; beta's page went away after its card was listed: skipped, not the end.
  self.assertEqual(steps,[([],2),(['Alpha'],0),([],0),([],0),(['Gamma'],0)])
  self.assertEqual(http.calls,[watch.archive_url(1),SHOWS+'alpha/',SHOWS+'beta/',watch.archive_url(2),SHOWS+'gamma/'])
  self.assertEqual(saved,{'page':2,'last':2,'seen':['alpha','beta'],'queue':[['beta',2021]]})
  again=Http(pages);rest=[]
  while saved:
   result=watch.catalogue(BASE,saved,again);rest+=[r['title'] for r in result['rows']];saved=result['next']
  self.assertEqual((rest,again.calls),(['Gamma'],[SHOWS+'beta/',watch.archive_url(2),SHOWS+'gamma/']))

 def walk(self,worker,http,now):
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind='watchhentai'",(now[0],))
  with patch('source_parser.PublicHttp',lambda **_:http):
   while worker.run_once():now[0]+=3

 def test_seeded_job_writes_series_with_genres_years_and_no_duplicates(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  worker=Indexer(store,fetch,lambda:now[0],interval=0);worker.seed([])
  (key,host,spec),=self.db.execute("SELECT id,host,spec FROM catalogue_jobs WHERE kind='watchhentai'").fetchall()
  self.assertEqual((host,json.loads(spec)),('watchhentai.net',BASE))
  self.assertGreaterEqual(Indexer(store,fetch,lambda:now[0]).base_pace('watchhentai.net'),1.5)
  self.assertEqual(refresh_interval(BASE),7*86400)
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind!='watchhentai'",(now[0]+10**9,))
  pages={watch.archive_url(1):archive(['ntr-kishi-id-01','alpha'],1,('3D','Harem','NTR')),
         KISHI:SERIES,SHOWS+'alpha/':series('alpha','Alpha',['Harem','NTR'],'Majin')}
  http=Http(pages);self.walk(worker,http,now)
  state,pages_read,records,error=self.db.execute('SELECT state,pages,records,error FROM catalogue_jobs WHERE id=?',(key,)).fetchone()
  self.assertEqual((state,pages_read,records,error),('done',3,2,''))
  rows=lambda:sorted((json.loads(v)['title'],json.loads(v).get('year')) for (v,) in self.db.execute("SELECT raw FROM content_titles WHERE json_extract(raw,'$.provider')='watchhentai'"))
  self.assertEqual(rows(),[('Alpha',2024),('NTR Kishi',2026)])
  facts=lambda:self.db.execute("SELECT category,original FROM content_tag_facts WHERE source='watchhentai.net' ORDER BY 1,2").fetchall()
  first=facts()
  self.assertIn(('studios','Majin'),first);self.assertIn(('genres','NTR'),first)
  self.assertEqual(len([f for f in first if f[0]=='genres']),10+2)
  # The genre menu adds genres no indexed series carries yet.
  vocabulary={label for (label,) in self.db.execute("SELECT label FROM catalog_vocabulary WHERE source='watchhentai.net' AND category='genres'")}
  self.assertTrue({'3D','Harem','NTR'}<=vocabulary)
  # The hentai video section's genre filter finds WatchHentai series by a site genre.
  self.assertEqual(content_catalog.browse(self.db,kind='anime',genre='Хентай')['total'],2)
  self.assertEqual(sorted(i['title'] for i in content_catalog.browse(self.db,kind='anime',tag='NTR')['items']),['Alpha','NTR Kishi'])
  # The weekly pass again: the same two series, no fact twice.
  now[0]+=8*86400;self.walk(worker,http,now)
  self.assertEqual(len(http.calls),6);self.assertEqual(rows(),[('Alpha',2024),('NTR Kishi',2026)]);self.assertEqual(facts(),first)

 def test_archive_past_the_site_end_finishes_the_walk_marked(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  worker=Indexer(store,fetch,lambda:now[0],interval=0);worker.seed([])
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind!='watchhentai'",(now[0]+10**9,))
  # The pager names three pages; page 3 is gone.
  pages={watch.archive_url(1):archive(['alpha'],3),SHOWS+'alpha/':series('alpha','Alpha',['Harem'],'A'),
         watch.archive_url(2):archive(['beta'],3),SHOWS+'beta/':series('beta','Beta',['Harem'],'A')}
  http=Http(pages);self.walk(worker,http,now)
  state,error,reason,cursor=self.db.execute("SELECT state,error,reason,cursor FROM catalogue_jobs WHERE kind='watchhentai'").fetchone()
  self.assertEqual((state,cursor),('done','{"page":1}'));self.assertIn('404',error);self.assertIn('страница 3',reason)
  self.assertEqual(http.calls[-1],watch.archive_url(3))

if __name__=='__main__':unittest.main()
