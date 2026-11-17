"""AniList full crawl walks id spans past the 5000-entry listing depth. Fixture answers only."""
import json,os,sys,tempfile,threading,sqlite3,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import catalogue_sources
from catalogue_sources import anilist_span
from catalogue_indexer import Indexer
from manga_catalog_index import initialize

def fake(ids_of_kind,newest):
 calls=[]
 def request(body):
  calls.append(body['variables'])
  ids=set(body['variables']['ids']);page=body['variables']['page']
  found=sorted(i for i in ids_of_kind if i in ids);chunk=found[(page-1)*40:page*40]
  return {'data':{'a':{'pageInfo':{'hasNextPage':len(found)>page*40},'media':[{'id':i,'title':{'romaji':'T'+str(i)},'genres':['Drama'],'tags':[{'name':'Time Skip'}]} for i in chunk]},'b':{'media':[{'id':newest}]}}}
 return request,calls

class AniListSpanTests(unittest.TestCase):
 def walk(self,ids,newest):
  request,calls=fake(ids,newest);cursor={'page':1};seen=[]
  while True:
   result=anilist_span({'kind':'anime'},cursor,'ANIME','','id',request=request,pause=lambda s:None)
   seen+=[int(r['providerId']) for r in result['rows']]
   if not result['next']:return seen,calls
   cursor=result['next']

 def test_walks_every_title_beyond_five_thousand_with_genres_and_tags(self):
  ids=list(range(1,13001))+[50000,50001,60000]
  seen,_=self.walk(ids,60000)
  self.assertEqual(seen,ids)
  row=anilist_span({'kind':'anime'},{'page':1},'ANIME','','id',request=fake([5],5)[0],pause=lambda s:None)['rows'][0]
  self.assertEqual((row['genres'],row['tags'],row['kind']),(['Drama'],['Time Skip'],'anime'))

 def test_spans_without_this_kind_are_skipped_in_one_turn(self):
  request,calls=fake([3,9001],9001)
  first=anilist_span({'kind':'manga'},{'page':1},'MANGA','','id',request=request,pause=lambda s:None)
  self.assertEqual([r['providerId'] for r in first['rows']],['3'])
  second=anilist_span({'kind':'manga'},first['next'],'MANGA','','id',request=request,pause=lambda s:None)
  self.assertEqual([r['providerId'] for r in second['rows']],['9001']);self.assertIsNone(second['next'])
  self.assertEqual(len(calls),1+4)# the empty spans 2001..8000 were read in the same turn

 def test_term_jobs_keep_the_listing_walk(self):
  bodies=[]
  with patch('metadata_catalog.get_json',lambda url,body=None,params=None:bodies.append(body) or {'data':{'Page':{'pageInfo':{'hasNextPage':False,'total':1},'media':[]}}}):
   catalogue_sources.fetch({'type':'anilist','kind':'anime','domain':'anilist.co','term':{'field':'genre','label':'Drama'}},{'page':3})
  self.assertIn('genre_in',bodies[0]['query']);self.assertEqual(bodies[0]['variables']['page'],3)

 def test_a_job_stalled_on_the_old_page_cursor_restarts_on_the_span_walk(self):
  temp=tempfile.TemporaryDirectory();env=patch.dict(os.environ,{'DATA_DIR':temp.name,'MEDIA_VAULT_DISABLE_WORKER':'1'});env.start()
  try:
   db=sqlite3.connect(':memory:',check_same_thread=False);initialize(db);db.commit()
   store=SimpleNamespace(db=db,lock=threading.RLock());worker=Indexer(store,lambda s,c:{},lambda:1000,interval=0)
   spec={'type':'anilist','kind':'anime','domain':'anilist.co','name':'Аниме · AniList'}
   with db:
    key=worker.enqueue(spec);term=worker.enqueue({**spec,'term':{'field':'genre','label':'Drama'}})
    db.execute("UPDATE catalogue_jobs SET cursor='{\"page\":126}',state='retry',pages=125,records=5000,error='x' WHERE id IN (?,?)",(key,term))
    db.execute('INSERT INTO catalogue_page_fingerprints VALUES(?,?)',(key,'d'))
   with patch('catalogue_sources.base_sources',lambda installed:[spec]):worker.seed([])
   self.assertEqual(db.execute('SELECT cursor,state,pages FROM catalogue_jobs WHERE id=?',(key,)).fetchone(),('{"page":1}','queued',0))
   self.assertEqual(db.execute('SELECT COUNT(*) FROM catalogue_page_fingerprints WHERE job=?',(key,)).fetchone()[0],0)
   self.assertEqual(db.execute('SELECT cursor FROM catalogue_jobs WHERE id=?',(term,)).fetchone()[0],'{"page":126}')
   db.close()
  finally:env.stop();temp.cleanup()

if __name__=='__main__':unittest.main()
