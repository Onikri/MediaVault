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
