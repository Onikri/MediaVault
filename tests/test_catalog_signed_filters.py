import json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import content_catalog
from manga_catalog_index import initialize,upsert,browse
from manga_tag_policy import current

class SignedFilters(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)/'policy.json'
  p.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(p)});self.env.start()
  self.db=sqlite3.connect(':memory:');initialize(self.db)
 def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()
 def row(self,title,slug,genres,tags):
  return {'provider':'fixture','kind':'manga','title':title,'aliases':[title],'sourceUrl':'https://fixture.example/'+slug,'format':'manhwa','genres':genres,'tags':tags}
 def test_or_within_groups_and_between_groups_and_exclusion_before_paging(self):
  upsert(self.db,[self.row('Мир А','a',['Fantasy'],['Dragons']),self.row('Мир Б','b',['Comedy'],['Robots']),self.row('Мир В','c',['Fantasy'],['Robots'])])
  self.assertEqual(browse(self.db,genre='Фэнтези,Комедия',tag='Dragons,Robots')['workTotal'],3)
  self.assertEqual(browse(self.db,genre='Comedy',tag='Dragons')['workTotal'],0)
  r=browse(self.db,genre='Fantasy,Comedy',excludeTag='Robots',limit=1)
  self.assertEqual(r['workTotal'],1);self.assertEqual(r['items'][0]['title'],'Мир А')
  self.assertEqual(browse(self.db,excludeGenre='Fantasy')['workTotal'],1)
 def test_exclusion_checks_other_source_of_the_same_work(self):
  upsert(self.db,[self.row('Общий мир','source-a',['Fantasy'],[]),self.row('Общий мир','source-b',[],['Robots'])])
  self.assertEqual(browse(self.db,genre='Fantasy',tag='Robots')['workTotal'],1)
  self.assertEqual(browse(self.db,excludeTag='Robots')['workTotal'],0)
 def test_book_subjects_are_not_tags_or_genres_but_novel_tags_survive(self):
  content_catalog.ingest(self.db,[{'id':'book1','provider':'fixture','kind':'book','title':'Книга','genres':['Fantasy','library shelf 106'],'tags':['Dragons','106']},{'id':'novel1','provider':'fixture','kind':'ranobe','title':'Новелла','genres':['Fantasy'],'tags':['Dragons']}])
  book=content_catalog.browse(self.db,kind='book')['items'][0]
  self.assertEqual(book['genres'],['Фэнтези']);self.assertEqual(book['tags'],[])
  self.assertEqual(content_catalog.browse(self.db,kind='book',tag='Dragons')['total'],0)
  self.assertEqual(content_catalog.browse(self.db,kind='ranobe',tag='Dragons')['total'],1)
 def test_content_or_and_exclusions_and_numeric_labels(self):
  content_catalog.ingest(self.db,[{'id':'film1','provider':'fixture','kind':'movie','title':'Фильм','genres':['Comedy'],'tags':['Robots','106','3D','Hentai']}])
  row=content_catalog.browse(self.db,kind='movie',genre='Fantasy,Comedy')['items'][0]
  self.assertEqual(row['tags'],['Robots','3D']);self.assertEqual(row['genres'],['Комедия'])
  self.assertEqual(content_catalog.browse(self.db,kind='movie',excludeGenre='Comedy')['total'],0)
  self.assertEqual(content_catalog.browse(self.db,kind='movie',excludeTag='Robots')['total'],0)
 def test_generic_work_groups_share_filters_and_totals_before_paging(self):
  content_catalog.ingest(self.db,[{'id':'one','provider':'one','kind':'anime','title':'Мир','ids':{'mal':'20'},'genres':['Fantasy'],'tags':[]},{'id':'two','provider':'two','kind':'anime','title':'World','ids':{'mal':'20'},'genres':[],'tags':['Robots']}])
  result=content_catalog.browse(self.db,kind='anime',genre='Fantasy',tag='Robots',limit=1)
  self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['providerCount'],2)
  self.assertEqual(result['items'][0]['tags'],['Robots'])
  self.assertEqual(set(result['items'][0]['aliases']),{'Мир','World'})
  self.assertEqual(content_catalog.browse(self.db,kind='anime',q='World',genre='Fantasy',tag='Robots')['total'],1)
  self.assertEqual(content_catalog.browse(self.db,kind='anime',excludeTag='Robots')['total'],0)
 def test_catalogue_orders_works_before_paging_and_keeps_distinct_remakes(self):
  def row(provider,source_id,year,imdb):
   return {'id':f'{provider}:{source_id}','provider':provider,'providerId':str(source_id),
           'kind':'movie','title':'One Name','year':year,'ids':{'imdb':imdb}}
  content_catalog.ingest(self.db,[row('omdb',1,1930,'tt0001000'),{**row('fixture',2,'1930','tt0001000'),'cover':'https://fixture.example/poster.jpg'},
                                  row('omdb',3,2020,'tt1234567'),row('omdb',4,None,'tt1234568')])
  first=content_catalog.browse(self.db,kind='movie',sort='new',limit=1)
  second=content_catalog.browse(self.db,kind='movie',sort='new',limit=1,offset=1)
  self.assertEqual((first['total'],first['items'][0]['ids']['imdb'],second['items'][0]['ids']['imdb']),
                   (3,'tt1234567','tt0001000'))
  self.assertEqual({*second['items'][0]['providers']},{'omdb','fixture'})
  self.assertEqual([r['ids']['imdb'] for r in content_catalog.browse(self.db,kind='movie',sort='old')['items']],
                   ['tt0001000','tt1234567','tt1234568'])
  detail=content_catalog.title(self.db,'movie','omdb','1')
  self.assertEqual(detail['id'],'omdb:1')
  self.assertEqual(detail['cover'],'https://fixture.example/poster.jpg')
  self.assertIsNone(content_catalog.title(self.db,'tv','omdb','1'))
 def test_malformed_or_overlarge_filter_lists_do_not_widen_the_query(self):
  from fastapi import HTTPException
  for value in ['["Fantasy"',json.dumps(['Fantasy']*65)]:
   with self.assertRaises(HTTPException) as error:browse(self.db,genre=value)
   self.assertEqual(error.exception.status_code,422)
 def test_resumable_book_cleanup_preserves_titles_raw_facts_and_crawl_queue(self):
  import threading
  from types import SimpleNamespace
  from catalog_taxonomy import maintain_books
  content_catalog.ingest(self.db,[{'id':'book','provider':'fixture','kind':'book','title':'Книга','genres':['Fantasy'],'tags':[]}])
  self.db.execute("INSERT INTO catalog_vocabulary VALUES('shelf 106','fixture.example','genres','book')")
  identity=self.db.execute('SELECT id FROM content_titles').fetchone()[0]
  self.db.execute('INSERT INTO content_tag_facts VALUES(?,?,?,?,?)',(identity,'book','fixture.example','genres','shelf 106'))
  self.db.execute('CREATE TABLE catalogue_jobs(id TEXT,state TEXT,cursor TEXT)')
  self.db.execute("INSERT INTO catalogue_jobs VALUES('running-crawl','running','page=47')")
  snapshot=self.db.execute('SELECT * FROM catalogue_jobs').fetchall()
  store=SimpleNamespace(db=self.db,lock=threading.RLock(),stopping=False)
  maintain_books(store);maintain_books(store)
  self.assertEqual(self.db.execute('SELECT * FROM catalogue_jobs').fetchall(),snapshot)
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM content_titles').fetchone()[0],1)
  self.assertEqual(self.db.execute("SELECT COUNT(*) FROM content_tag_facts WHERE original='shelf 106'").fetchone()[0],1)
  self.assertEqual(self.db.execute("SELECT COUNT(*) FROM catalog_vocabulary WHERE label='shelf 106'").fetchone()[0],0)
