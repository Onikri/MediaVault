"""Whole-catalogue manga index orders; neutral fixture titles only."""
import sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_catalog_index import initialize,upsert,browse

class IndexSortTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');initialize(self.db)
  rows=[{'provider':'fixture','kind':'manga','title':name,'url':'https://fixture.example/'+str(i),'sourceUrl':'https://fixture.example/'+str(i),'year':year,'episodes':[{'number':n} for n in range(chapters or 0)] if chapters else None,'language':'en'} for i,(name,year,chapters) in enumerate([('Garden',2001,10),('Brook',2019,None),('Atlas',None,300),('Cedar',2010,40),('Dune',2019,5)])]
  upsert(self.db,rows);self.db.commit()
 def titles(self,**options):return [row['title'] for row in browse(self.db,limit=2,**options)['items']]+[row['title'] for row in browse(self.db,limit=3,offset=2,**options)['items']]
 def test_pages_never_repeat_a_title(self):
  for sort in ('','new','old','title','length','added'):
   pages=self.titles(sort=sort);self.assertEqual(len(pages),5,sort);self.assertEqual(len(set(pages)),5,sort)
 def test_orders(self):
  self.assertEqual(self.titles(sort='title'),['Atlas','Brook','Cedar','Dune','Garden'])
  self.assertEqual(self.titles(sort='new')[-1],'Atlas','unknown years go last')
  self.assertEqual(self.titles(sort='old')[:2],['Garden','Cedar'])
  self.assertEqual(self.titles(sort='length')[0],'Atlas')

if __name__=='__main__':unittest.main()

class WorkPagingTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');initialize(self.db)
  # Three sites list "Garden"; two list "Brook"; years and chapters differ by site.
  rows=[('a','Garden',2001,3),('b','Garden',None,9),('c','GARDEN!',2002,None),('a','Brook',2019,4),('b','Brook',2018,1),('a','Cedar',2010,2),('a','Dune',None,None)]
  for i,(site,name,year,chapters) in enumerate(rows):
   upsert(self.db,[{'provider':'site-'+site,'kind':'manga','title':name,'url':f'https://{site}.example/{i}','sourceUrl':f'https://{site}.example/{i}','year':year,'episodes':[{'number':n} for n in range(chapters)] if chapters else None,'language':'en'}])
  self.db.commit()
 def test_a_work_is_one_entry_on_one_page_with_all_its_sources(self):
  for sort in ('new','old','title','length','added'):
   seen=[]
   for page in range(4):
    data=browse(self.db,limit=1,offset=page,sort=sort);keys={row['workKey'] for row in data['items']}
    self.assertLessEqual(len(keys),1);self.assertEqual(data['workTotal'],4);self.assertEqual(data['total'],7);self.assertEqual(data['works'],len(keys))
    seen+=list(keys)
   self.assertEqual(len(seen),len(set(seen)),sort);self.assertEqual(len(seen),4,sort)
  garden=browse(self.db,limit=4,sort='title')['items']
  self.assertEqual(sorted(r['url'] for r in garden if r['workKey']=='garden'),['https://a.example/0','https://b.example/1','https://c.example/2'])
 def test_work_orders_use_the_work_as_a_whole(self):
  keys=lambda sort:list(dict.fromkeys(r['workKey'] for r in browse(self.db,limit=4,sort=sort)['items']))
  self.assertEqual(keys('new'),['brook','cedar','garden','dune'])
  self.assertEqual(keys('length')[0],'garden')
  self.assertEqual(keys('title'),['brook','cedar','dune','garden'])
 def test_search_still_lists_each_source(self):
  self.assertEqual(len(browse(self.db,q='garden')['items']),3)
