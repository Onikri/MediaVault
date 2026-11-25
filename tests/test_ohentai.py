"""OHentai (ohentai.org) playback and series list indexing from recorded page fixtures; no network."""
import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from bs4 import BeautifulSoup
import catalogue_ohentai as oh,content_catalog,hentai_video_sites as sites
from catalogue_indexer import Indexer,refresh_interval
from dynamic_video_sources import inspect,provider_for,resolve_dynamic
from manga_catalog_index import initialize
from source_parser import SourceError

FIXTURES=Path(__file__).parent/'fixtures'
read=lambda name:(FIXTURES/f'ohentai-{name}.html').read_text(encoding='utf-8')
LIST,TAGS,SERIES,EPISODE,SEARCH=(read(n) for n in ('series-list','tags','series','episode','search'))
ROOT='https://ohentai.org/'
INGRID=ROOT+'sery_video.php?seryid=MjIz'
EP1,EP3,RE1=ROOT+'detail.php?vid=NDgz',ROOT+'detail.php?vid=NDg1',ROOT+'detail.php?vid=MTQ5NA=='
SNOW='https://videos.ohentai.org/videos/storage.bunnycdn.com/storage.bunnycdn.com/Old%20Anime/Makai%20Kishi%20Ingrid/Makai%20Kishi%20Ingrid_ep3_en.mp4?token=FIXTURE&expires=1795608063'
BUNNY='https://openload.b-cdn.net/Old%20Anime/Makai%20Kishi%20Ingrid/Makai%20Kishi%20Ingrid_ep3_en.mp4?token=FIXTURE&expires=1795608063'
BASE={'type':'ohentai','kind':'anime','domain':'ohentai.org','name':'Хентай · OHentai'}

class Http:
 def __init__(self,pages):self.pages=pages;self.calls=[]
 def document(self,url,headers=None,**_):
  self.calls.append(url)
  value=self.pages.get(url)
  if value is None:
   # The transport's answer to a page the site no longer has.
   value=SourceError('Источник вернул HTTP 404.');value.http_status=404
  if isinstance(value,Exception):raise value
  return value,url,{}
 def close(self):pass

def series_list(entries):
 items=''.join(f"<div class='sererytitle'><a href='{sites.oh_address('/sery_video.php',n).removeprefix(ROOT)}' >{t}</a></div>" for n,t in entries)
 return f"<div class='videoseryconatiner'><div class='serywrapper'><a class='alpahticlabel' name='a'>A</a>{items}</div></div>"

def series(title,tags,year,episodes):
 bricks=''.join(f"<div class='videobrick'><a href='detail.php?vid={v}' class='interlink'><div class='videocontentblock'><img src=\"video_data/{title}/Episode-{i}/Episode-{i}.png\"></div></a>"
                f"<div class='videotitle' title='{title} - Episode {i}'><a href='detail.php?vid={v}' class='interlink' >{title} - Episode {i}</a></div></div>" for i,v in enumerate(episodes,1))
 links=''.join(f"<a href='tagsearch.php?tag={t}'>{t}</a>" for t in tags)
 return (f"<div class='serylistcontainer'><img src=\"video_data/{title}/cover.png\" alt=\"{title}\"><div class='serydetailsection'><h1 class='title'>{title}</h1>"
         f"<div class='tagcontainer'>{links}</div><div class='longdes'><span>Year: </span>{year}</div><div class='longdes'><span>Episode Included: </span>{len(episodes)}</div></div></div>"
         f"<div class='videobrickwrap'>{bricks}</div>")

class OHentaiPlayback(unittest.TestCase):
 def test_addresses_are_checked_by_host_path_and_id(self):
  for url in [INGRID,EP3,RE1,ROOT+'sery_video.php?seryid=MA==',ROOT+'sery_video.php?seryid=MA%3D%3D']:
   self.assertEqual(sites.provider_for(url)[0],'ohentai',url)
  for url in [ROOT,ROOT+'series.php',ROOT+'alltags.php',ROOT+'tagsearch.php?tag=Rape',ROOT+'search.php?k=ingrid',
              ROOT+'sery_video.php',ROOT+'sery_video.php?seryid=bm90LWEtbnVtYmVy',ROOT+'sery_video.php?seryid=MjIz&x=1',
              ROOT+'detail.php?seryid=MjIz',ROOT+'sery_video.php?vid=MjIz','http://ohentai.org/detail.php?vid=NDg1',
              'https://evil.net/detail.php?vid=NDg1','https://ohentai.org.evil.net/detail.php?vid=NDg1',
              'https://www.ohentai.org/detail.php?vid=NDg1',ROOT+'detail.php/x?vid=NDg1']:
   self.assertIsNone(sites.provider_for(url),url)
  # Ids are base64 of the decimal id; the site's own spelling is kept.
  self.assertEqual((sites.oh_number('MjIz'),sites.oh_number('MTQ5NA=='),sites.oh_number('MTQ5NA'),sites.oh_number('bm90')),(223,1494,1494,None))
  self.assertEqual(sites.oh_address('/detail.php',1494),RE1)
  self.assertEqual(sites._oh_page('sery_video.php?seryid=MjIz',ROOT+'series.php','/detail.php'),'')
  self.assertEqual(sites._oh_page('https://evil.net/sery_video.php?seryid=MjIz',ROOT,'/sery_video.php'),'')

 def test_search_groups_episodes_into_series_and_drops_sponsored_bricks(self):
  http=Http({ROOT+'search.php?k=ingrid':SEARCH})
  rows=sites.search('ohentai','ingrid',http)
  self.assertEqual([(r['title'],r['url']) for r in rows],[('Makai Kishi Ingrid:Re',RE1),('Ingrid 7 Days Keep Diary Turbo ss',ROOT+'detail.php?vid=NDMzNw=='),
                   ('Makai Kishi Ingrid',ROOT+'detail.php?vid=NDg2')])
  self.assertEqual(rows[0]['cover'],ROOT+'video_data/Makai%20Kishi%20Ingrid%20Re/Episode-1/Episode-1.png')
  self.assertTrue(all(r['provider']=='ohentai' and sites.provider_for(r['url']) for r in rows))

 def test_series_and_episode_pages_list_the_same_episodes(self):
  http=Http({INGRID:SERIES,EP3:EPISODE})
  title,episodes=sites.episodes('ohentai',INGRID,http)
  # The fifth video of the series is «Makai Kishi Ingrid:Re»; the sponsored brick is not an episode.
  self.assertEqual(title,'Makai Kishi Ingrid')
  self.assertEqual([(e['number'],e['url']) for e in episodes],[(1,EP1),(2,ROOT+'detail.php?vid=NDg0'),(3,EP3),(4,ROOT+'detail.php?vid=NDg2'),(5,RE1)])
  self.assertEqual(episodes[4]['title'],'Makai Kishi Ingrid:Re - Episode 1')
  title,strip=sites.episodes('ohentai',EP3,http)
  self.assertEqual((title,[e['url'] for e in strip]),('Makai Kishi Ingrid',[e['url'] for e in episodes]))
  # A lone video outside any series is its own single episode.
  lone="<h1 class='title'>Lone Video</h1>"
  self.assertEqual(sites.episodes('ohentai',ROOT+'detail.php?vid=Nw==',Http({ROOT+'detail.php?vid=Nw==':lone})),
                   ('Lone Video',[{'number':1,'season':1,'url':ROOT+'detail.php?vid=Nw==','title':'Lone Video'}]))

 def test_episode_page_gives_both_servers_mp4_for_our_player(self):
  http=Http({EP3:EPISODE})
  streams=sites.streams('ohentai',EP3,http)
  # The selected server (Snowcore) first, then Openload; the VAST advertising tag is not a source.
  self.assertEqual([s['url'] for s in streams],[SNOW,BUNNY])
  self.assertEqual({(s['type'],s['headers']['Referer']) for s in streams},{('mp4',ROOT)})
  self.assertEqual(http.calls,[EP3])
  # A non-MP4 file is not a stream; a series page is not an episode.
  self.assertEqual(sites.oh_player_sources('sources: [{"file":"https://videos.ohentai.org/x.html"}],',EP3),[])
  self.assertEqual(sites.oh_player_sources('sources: [{"file":"http://videos.ohentai.org/x.mp4"}],',EP3),[])
  with self.assertRaisesRegex(SourceError,'не опубликовал открытое видео'):sites.streams('ohentai',EP3,Http({EP3:'<h1>x</h1>'}))
  with self.assertRaisesRegex(SourceError,'серию'):sites.streams('ohentai',INGRID,Http({}))

 def test_dynamic_routing_plays_in_our_player(self):
  http=Http({INGRID:SERIES,EP3:EPISODE})
  info=inspect(INGRID,provider_for(INGRID),http)
  self.assertEqual((info['provider'],len(info['episodes'])),('ohentai',5))
  checked=[]
  def check(_,stream,**__):
   checked.append(stream['url'])
   if stream['url']==SNOW:raise SourceError('expired')
  with patch('dynamic_video_sources.check_mp4',side_effect=check):
   page=resolve_dynamic(http,EP3,None,'OHentai · EN','ohentai')
  self.assertEqual((checked,[s['url'] for s in page.streams]),([SNOW,BUNNY],[BUNNY]))

 def test_site_is_searchable_and_marked_as_hentai(self):
  from site_adapters import SITES
  from catalog_taxonomy import hentai_origin
  self.assertTrue(any(s.id=='ohentai' for s in SITES))
  self.assertTrue(hentai_origin('ohentai',INGRID,'anime'))

class OHentaiCatalogue(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();policy=Path(self.tmp.name)/'policy.json'
  policy.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(policy),'DATA_DIR':self.tmp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db)
 def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()

 def test_series_list_tag_dictionary_and_series_page_parse(self):
  # The A–Z list only; the «Latest» sidebar's episode links, an off-site link and a non-numeric id are not series.
  self.assertEqual(oh.series_ids(BeautifulSoup(LIST,'html.parser'),ROOT+'series.php'),[0,236,392])
  self.assertEqual(oh.tags(BeautifulSoup(TAGS,'html.parser'))[:4],['.ini.','01-Torte','0721 Master - Paisen','1080p'])
  self.assertEqual(len(oh.tags(BeautifulSoup(TAGS,'html.parser'))),12)
  row=oh.series_row(SERIES,INGRID)
  self.assertEqual({k:row[k] for k in ('id','provider','kind','title','aliases','url','sourceUrl','episodes','year','studios','genres','age')},
                   {'id':'ohentai:'+INGRID,'provider':'ohentai','kind':'anime','title':'Makai Kishi Ingrid','aliases':['Makai Kishi Ingrid','魔界騎士イングリッド'],
                    'url':INGRID,'sourceUrl':INGRID,'episodes':5,'year':2009,'studios':[],'genres':[],'age':18})
  self.assertEqual(row['tags'][:5],['Rape','Blow Job','Monster','Mind Break','Mind Contro']);self.assertEqual(len(row['tags']),14)
  self.assertEqual(row['cover'],ROOT+'video_data/Makai%20Kishi%20Ingrid/cover.png');self.assertNotIn('providerId',row)
  self.assertIsNone(oh.series_row(SERIES,ROOT+'detail.php?vid=NDg1'))
  self.assertIsNone(oh.series_row('<h1>Not a series</h1>',INGRID))

 def test_cursor_bitmap_round_trip(self):
  ids=[0,7,8,236,5218]
  bits=oh.unpack(oh.pack(ids));walk=[];at=0
  while (n:=oh.next_id(bits,at)) is not None:walk.append(n);at=n+1
  self.assertEqual(walk,ids);self.assertLess(len(oh.pack(list(range(0,5219,1)))),200)
  with self.assertRaises(SourceError):oh.unpack('not a map')

 def test_a_catalogue_card_plays_through_the_search_path(self):
  row=oh.series_row(SERIES,INGRID)
  info=inspect(row['url'],provider_for(row['url']),Http({INGRID:SERIES}))
  found=sites.search('ohentai','ingrid',Http({ROOT+'search.php?k=ingrid':SEARCH}))
  searched=inspect(found[2]['url'],provider_for(found[2]['url']),Http({found[2]['url']:EPISODE}))
  self.assertEqual([e['url'] for e in info['episodes']],[e['url'] for e in searched['episodes']])
  self.assertEqual(len(info['episodes']),row['episodes'])

 def test_walk_reads_each_series_once_and_resumes_from_its_cursor(self):
  pages={oh.SERIES_LIST:series_list([(5,'Echo'),(2,'Bravo'),(3,'Charlie')]),oh.TAG_LIST:TAGS,
         oh.series_url(2):series('Bravo',['Vanilla'],2020,['MjAx']),
         # Charlie went away after the list named it: skipped, not the end.
         oh.series_url(5):series('Echo',['NTR','Vanilla'],2021,['NTAx','NTAy'])}
  http=Http(pages);cursor={'page':1};steps=[]
  while cursor:
   result=oh.catalogue(BASE,cursor,http);steps.append(([r['title'] for r in result['rows']],len(result.get('vocabulary') or [])))
   self.assertTrue(result['rows'] or result['emptySpan'])
   cursor=json.loads(json.dumps(result['next'])) if result['next'] else None
   if http.calls[-1]==oh.series_url(2):saved=cursor
  self.assertEqual(steps,[([],0),([],12),(['Bravo'],0),([],0),(['Echo'],0)])
  self.assertEqual(http.calls,[oh.SERIES_LIST,oh.TAG_LIST,oh.series_url(2),oh.series_url(3),oh.series_url(5)])
  self.assertEqual({k:saved[k] for k in ('page','from')},{'page':4,'from':3});self.assertLess(len(json.dumps(saved)),200)
  again=Http(pages);rest=[]
  while saved:
   result=oh.catalogue(BASE,saved,again);rest+=[r['title'] for r in result['rows']];saved=result['next']
  self.assertEqual((rest,again.calls),(['Echo'],[oh.series_url(3),oh.series_url(5)]))
  # A missing tag dictionary only costs its labels.
  self.assertEqual(oh.catalogue(BASE,{'page':2,'map':oh.pack([2]),'from':0},Http({}))['vocabulary'],[])
  with self.assertRaisesRegex(SourceError,'список сериалов'):oh.catalogue(BASE,{'page':1},Http({oh.SERIES_LIST:'<h1>x</h1>'}))

 def walk(self,worker,http,now):
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind='ohentai'",(now[0],))
  with patch('source_parser.PublicHttp',lambda **_:http):
   while worker.run_once():now[0]+=3

 def test_seeded_job_writes_series_with_tags_years_and_no_duplicates(self):
  store=SimpleNamespace(db=self.db,lock=threading.RLock());now=[10000.0]
  from catalogue_sources import fetch
  worker=Indexer(store,fetch,lambda:now[0],interval=0);worker.seed([])
  (key,host,spec),=self.db.execute("SELECT id,host,spec FROM catalogue_jobs WHERE kind='ohentai'").fetchall()
  self.assertEqual((host,json.loads(spec)),('ohentai.org',BASE))
  self.assertGreaterEqual(Indexer(store,fetch,lambda:now[0]).base_pace('ohentai.org'),1.5)
  self.assertEqual(refresh_interval(BASE),7*86400)
  self.db.execute("UPDATE catalogue_jobs SET due=? WHERE kind!='ohentai'",(now[0]+10**9,))
  pages={oh.SERIES_LIST:series_list([(223,'Makai Kishi Ingrid'),(9,'Alpha')]),oh.TAG_LIST:TAGS,
         INGRID:SERIES,oh.series_url(9):series('Alpha',['Vanilla','Rape'],2024,['OTAx'])}
  http=Http(pages);self.walk(worker,http,now)
  state,pages_read,records,expected,error=self.db.execute('SELECT state,pages,records,expected,error FROM catalogue_jobs WHERE id=?',(key,)).fetchone()
  self.assertEqual((state,pages_read,records,expected,error),('done',4,2,2,''))
  rows=lambda:sorted((json.loads(v)['title'],json.loads(v).get('year'),json.loads(v).get('episodes')) for (v,) in self.db.execute("SELECT raw FROM content_titles WHERE json_extract(raw,'$.provider')='ohentai'"))
  self.assertEqual(rows(),[('Alpha',2024,1),('Makai Kishi Ingrid',2009,5)])
  facts=lambda:self.db.execute("SELECT category,original FROM content_tag_facts WHERE source='ohentai.org' ORDER BY 1,2").fetchall()
  first=facts()
  self.assertIn(('tags','Rape'),first);self.assertEqual(len(first),14+2)
  # The dictionary adds tags no indexed series carries yet.
  vocabulary={label for (label,) in self.db.execute("SELECT label FROM catalog_vocabulary WHERE source='ohentai.org' AND category='tags'")}
  self.assertTrue({'.ini.','12CUT','Rape','Vanilla'}<=vocabulary)
  # The hentai video section's tag filter finds OHentai series by a site tag.
  self.assertEqual(content_catalog.browse(self.db,kind='anime',genre='Хентай')['total'],2)
  self.assertEqual(sorted(i['title'] for i in content_catalog.browse(self.db,kind='anime',tag='Rape')['items']),['Alpha','Makai Kishi Ingrid'])
  # The weekly pass again: the same two series, no fact twice.
  now[0]+=8*86400;self.walk(worker,http,now)
  self.assertEqual(len(http.calls),8);self.assertEqual(rows(),[('Alpha',2024,1),('Makai Kishi Ingrid',2009,5)]);self.assertEqual(facts(),first)

if __name__=='__main__':unittest.main()
