"""Neutral public catalogue fixtures; no reader pages or image downloads."""
import copy,json,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_hentaichan_cc import catalogue_page,catalogue_metadata,flight_tags
from bs4 import BeautifulSoup
from catalogue_indexer import Indexer,identity
from manga_catalog_index import initialize,upsert,browse
from content_management import save
from manga_tag_policy import canonical_json,current

def listing(page,total=51):
    flight='0:'+json.dumps({'currentPage':page,'limit':25,'totalPosts':total})
    script='<script>self.__next_f.push('+json.dumps([1,flight])+')</script>'
    return '<a href="/manga/garden-'+str(page)+'"><img alt="Garden" src="https://cdn.hentaichan.cc/cover.jpg"><p>Garden '+str(page)+'</p><span>123</span></a>'+script+(f'<a aria-label="Go to next page" href="/catalog?page={page+1}">Next</a>' if page*25<total else '')

class ParserTests(unittest.TestCase):
 def test_long_source_slugs_remain_available_in_catalogue_and_search(self):
  import manga_hentaichan_cc as cc
  slug='garden-'+'a'*250
  row=catalogue_page(listing(1).replace('/manga/garden-1','/manga/'+slug),'https://hentaichan.cc/catalog',1)['rows'][0]
  self.assertEqual(row['url'],cc.ROOT+'/manga/'+slug);self.assertIsNotNone(cc.PATH.fullmatch('/read/'+slug))
  http=SimpleNamespace(document=lambda url,**kw:('1:'+json.dumps({'data':[{'name':'Garden','slug':slug}]}),url,{}))
  self.assertEqual(cc.search('Garden',http)[0]['url'],row['url'])
 def test_catalogue_walks_actual_links_and_declared_last_page(self):
  r=catalogue_page(listing(1),'https://hentaichan.cc/catalog',1)
  self.assertEqual(r['total'],51);self.assertEqual(r['next'],{'page':2,'url':'https://hentaichan.cc/catalog?page=2'})
  self.assertEqual(r['rows'][0]['title'],'Garden 1');self.assertEqual(r['rows'][0]['cover'],'https://cdn.hentaichan.cc/cover.jpg')
  self.assertIsNone(catalogue_page(listing(3),'https://hentaichan.cc/catalog?page=3',3)['next'])
 def test_missing_next_link_or_wrong_page_cannot_claim_completion(self):
  from source_parser import SourceError
  with self.assertRaises(SourceError):catalogue_page(listing(1).replace('href="/catalog?page=2"','href="/catalog?page=9"'),'https://hentaichan.cc/catalog',1)
  with self.assertRaises(SourceError):catalogue_page(listing(1),'https://hentaichan.cc/catalog?page=2',2)
 def test_explicit_card_tags_work_without_semantic_css_classes_and_deduplicate(self):
  soup=BeautifulSoup('<a href="/catalog/tags/kimono">Кимоно</a><a href="/catalog/tags/kimono">Кимоно</a><a href="/catalog/tags/ecology">Экология</a><a href="/author/someone">Имя автора</a><meta name="description" content="A garden.">','html.parser')
  r=catalogue_metadata(soup);self.assertEqual(r['tags'],['Кимоно','Экология']);self.assertEqual(r['description'],'A garden.')
 def test_all_tags_are_read_from_work_props_including_tags_hidden_from_the_dom(self):
  data=['$',{'tags':[{'id':1,'name':'Экология','slug':'ecology'},{'id':2,'name':'Кимоно','slug':'kimono'}]}, {'tags':[{'id':3,'name':'Not a work tag','slug':'global'}],'maxViews':99}]
  flight='a:'+json.dumps(data,ensure_ascii=False)
  soup=BeautifulSoup('<a href="/catalog/tags/ecology">Экология</a><script>self.__next_f.push('+json.dumps([1,flight])+')</script>','html.parser')
  metadata=catalogue_metadata(soup)
  self.assertEqual(set(metadata['tags']),{'Кимоно','Экология'});self.assertEqual(metadata['sourceMetadataVersion'],2)
  self.assertEqual(flight_tags('1:'+json.dumps({'tags':[]})),[]);self.assertIsNone(flight_tags('1:'+json.dumps({'tags':[], 'maxViews':1})))

class IndexTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.policy={'schemaVersion':1,'includeDiscovered':True,'excludedTerms':['Экология'],'excludedPrefixes':[],'tags':[]}
  self.path=Path(self.temp.name)/'manga-tag-policy.json';self.path.write_bytes(canonical_json(self.policy));self.env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(self.path),'DATA_DIR':self.temp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
  self.db=sqlite3.connect(':memory:');initialize(self.db);self.store=SimpleNamespace(db=self.db,lock=threading.RLock());self.now=1000
 def tearDown(self):self.db.close();self.env.stop();self.temp.cleanup()
 def test_obsolete_homepage_job_is_retired_without_deleting_cards(self):
  worker=Indexer(self.store,interval=0)
  old={'type':'html','domain':'hentaichan.cc','name':'HentaiChan.cc','url':'https://hentaichan.cc/','hosts':['hentaichan.cc']}
  with self.db:
   key=worker.enqueue(old);upsert(self.db,[catalogue_page(listing(1),'https://hentaichan.cc/catalog',1)['rows'][0]])
  worker.seed([])
  self.assertIsNone(self.db.execute('SELECT 1 FROM catalogue_jobs WHERE id=?',(key,)).fetchone());self.assertEqual(browse(self.db)['total'],1)
  specs=[json.loads(r[0]) for r in self.db.execute("SELECT spec FROM catalogue_jobs WHERE kind='html'")]
  self.assertEqual([s['url'] for s in specs if s['domain']=='hentaichan.cc'],['https://hentaichan.cc/catalog'])
 def test_full_listing_is_not_complete_until_detail_tags_are_enriched_and_unhidden(self):
  spec={'type':'html','domain':'hentaichan.cc','name':'HentaiChan.cc','url':'https://hentaichan.cc/catalog','hosts':['hentaichan.cc']}
  row=catalogue_page(listing(1,1),spec['url'],1)['rows'][0]
  upsert(self.db,[{**row,'description':'Legacy cached summary','sourceMetadataVersion':1,'metadataInspected':True}]);self.db.commit()
  def fetch(s,c):return {'rows':[{**row,'tags':['Кимоно','Экология'],'sourceMetadataVersion':2,'metadataInspected':True}],'next':None} if s['type']=='html-detail' else {'rows':[row],'next':None,'state':'done','total':1,'details':[{**spec,'type':'html-detail','url':row['url'],'row':row}]}
  worker=Indexer(self.store,fetch,lambda:self.now,interval=0)
  with self.db:worker.enqueue(spec)
  worker.run_once();status=worker.status()['sources'][0]
  self.assertEqual(status['status'],'enriching');self.assertEqual(status['pendingDetails'],1);self.assertEqual(status['expected'],1)
  worker.run_once();self.assertEqual(worker.status()['sources'][0]['status'],'done')
  self.assertEqual(browse(self.db,tag='Кимоно')['total'],1);self.assertEqual(browse(self.db)['items'][0]['tags'],['Кимоно'])
  policy=copy.deepcopy(self.policy);policy['excludedTerms']=[];save(self.store,policy,current().revision)
  self.assertEqual(browse(self.db,tag='Экология')['total'],1);self.assertIn('Экология',browse(self.db)['items'][0]['tags'])
 def test_urgent_rescan_does_not_starve_regular_jobs(self):
  worker=Indexer(self.store,clock=lambda:self.now,interval=0)
  with self.db:
   ordinary=worker.enqueue({'type':'unsupported','domain':'ordinary.example','name':'Ordinary'},1)
   for n in range(6):worker.enqueue({'type':'unsupported','domain':f'urgent{n}.example','name':'Urgent'},100)
  claimed=[worker.claim()['id'] for _ in range(4)]
  self.assertEqual(claimed[3],ordinary)

if __name__=='__main__':unittest.main()
