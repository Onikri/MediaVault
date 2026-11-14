import json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import manga_catalog_index as manga,content_catalog
from manga_tag_policy import current
from content_vocabulary import public

class HentaiOrigins(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.file=Path(self.tmp.name)/'policy.json'
  self.file.write_text(json.dumps({'schemaVersion':1,'tags':[],'includeDiscovered':True,'excludedTerms':[],'excludedPrefixes':[],'hiddenTags':[]}),encoding='utf-8')
  self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(self.file)});self.env.start();self.db=sqlite3.connect(':memory:');manga.initialize(self.db)
 def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()
 def row(self,title,host='hentailib.me',provider='fixture',tags=(),genres=()):return {'kind':'manga','title':title,'provider':provider,'sourceUrl':'https://'+host+'/'+title,'genres':list(genres),'tags':list(tags)}
 def test_existing_source_rows_need_no_crawl_or_policy_rewrite(self):
  raw=self.file.read_bytes();manga.upsert(self.db,[self.row('Garden'),self.row('River','hitomi.la'),self.row('Sky','x17.h-chan.me'),self.row('Cloud','20.allhen.online'),self.row('Moon','g.nude-moon.fun')])
  self.assertEqual(manga.browse(self.db,genre='Хентай')['workTotal'],5)
  for row in manga.browse(self.db,genre='Hentai')['items']:
   self.assertIn('Хентай',row['genres']);self.assertIn('Хентай',manga.title(self.db,row['catalogId'])['genres'])
  self.assertEqual(self.file.read_bytes(),raw)
  self.assertEqual(self.db.execute("SELECT count(*) FROM catalog_tag_facts WHERE original='Хентай'").fetchone()[0],0,'Derived genre must not pretend to be an upstream fact')
 def test_veto_overrides_explicit_genre_and_cross_source_work(self):
  manga.upsert(self.db,[self.row('Garden',genres=['Hentai']),self.row('Garden','mangalib.me',tags=['Не хентай']),self.row('River',tags=['NON-HENTAI'])])
  self.assertEqual(manga.browse(self.db,genre='Хентай')['workTotal'],0)
  for row in manga.browse(self.db)['items']:
   self.assertTrue(row['hentaiExcluded']);self.assertNotIn('Хентай',row['genres']);self.assertNotIn('Хентай',manga.title(self.db,row['catalogId'])['genres'])
 def test_hidden_veto_still_controls_membership(self):
  manga.upsert(self.db,[self.row('Garden',tags=['Не хентай'])]);data=json.loads(self.file.read_text());data['hiddenTags']=['Не хентай'];self.file.write_text(json.dumps(data))
  self.assertEqual(manga.browse(self.db,genre='Хентай')['workTotal'],0)
  row=manga.browse(self.db)['items'][0];self.assertTrue(row['hentaiExcluded']);self.assertNotIn('Не хентай',row['tags'])
 def test_signed_or_and_exclusion_remain_work_level(self):
  manga.upsert(self.db,[self.row('Garden',tags=['Robots']),self.row('River','mangalib.me',genres=['Fantasy']),self.row('Sky','mangalib.me',tags=['Не хентай'],genres=['Fantasy'])])
  self.assertEqual(manga.browse(self.db,genre='Хентай,Fantasy')['workTotal'],3)
  self.assertEqual(manga.browse(self.db,genre='Хентай',tag='Robots')['workTotal'],1)
  self.assertEqual(manga.browse(self.db,excludeGenre='Хентай')['workTotal'],2)
  self.assertEqual(manga.browse(self.db,genre='Хентай',excludeGenre='Хентай')['workTotal'],0)
 def test_adult_rating_and_lookalike_domains_do_not_imply_genre(self):
  rows=[self.row('Garden','mangalib.me'),self.row('River','hentailib.me.evil.example'),self.row('Sky','manga-chan.me')]
  for row in rows:row['adult']=True
  manga.upsert(self.db,rows);self.assertEqual(manga.browse(self.db,genre='Хентай')['workTotal'],0)
 def test_public_vocabulary_exposes_inferred_genre(self):
  manga.upsert(self.db,[self.row('Garden')]);data=public(SimpleNamespace(db=self.db,lock=threading.RLock()))
  self.assertTrue(any(row['label']=='Хентай' for row in data['policy']['tags']))
 def test_hanime_generic_catalogue_and_other_kinds(self):
  content_catalog.ingest(self.db,[{'kind':'anime','id':'garden','title':'Garden','provider':'hanime','sourceUrl':'https://hanime.tv/videos/hentai/garden','genres':[],'tags':[],'ids':{'mal':'42'}},{'kind':'anime','id':'river','title':'Garden','provider':'fixture','sourceUrl':'https://fixture.example/garden','genres':[],'tags':[],'ids':{'mal':'42'}},{'kind':'movie','id':'sky','title':'Sky','provider':'hanime','genres':[],'tags':[]},{'kind':'book','id':'moon','title':'Moon','provider':'hitomi','genres':[],'tags':[]}])
  data=content_catalog.browse(self.db,kind='anime',genre='Хентай');self.assertEqual(data['total'],1);self.assertIn('Хентай',data['items'][0]['genres'])
  self.assertEqual(content_catalog.browse(self.db,kind='movie',genre='Хентай')['total'],0)
  self.assertNotIn('Хентай',content_catalog.browse(self.db,kind='book')['items'][0]['genres'])
  content_catalog.ingest(self.db,[{'kind':'anime','id':'river','title':'Garden','provider':'fixture','tags':['Не хентай'],'ids':{'mal':'42'}}])
  self.assertEqual(content_catalog.browse(self.db,kind='anime',genre='Хентай')['total'],0)
  row=content_catalog.browse(self.db,kind='anime')['items'][0];self.assertTrue(row['hentaiExcluded']);self.assertNotIn('Хентай',row['genres'])

 def test_source_rule_updates_replace_derived_indexes_without_rewriting_facts(self):
  from catalog_taxonomy import HENTAI,initialize_origins
  manga.upsert(self.db,[self.row('Garden')]);before=self.db.execute('SELECT * FROM catalog_tag_facts').fetchall()
  with patch.dict(HENTAI,{'hosts':['fixture.example']}):
   initialize_origins(self.db,manga=True)
   self.assertEqual(manga.browse(self.db,genre='Хентай')['workTotal'],0)
   self.assertEqual(self.db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name LIKE 'catalog_hentai_%'").fetchone()[0],2)
  initialize_origins(self.db,manga=True)
  self.assertEqual(manga.browse(self.db,genre='Хентай')['workTotal'],1)
  self.assertEqual(self.db.execute('SELECT * FROM catalog_tag_facts').fetchall(),before)
