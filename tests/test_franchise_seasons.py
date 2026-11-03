import unittest
from franchise_seasons import main_seasons
class FranchiseSeasonTests(unittest.TestCase):
 def setUp(self):
  self.items=[{'id':'54492','title':'Монолог фармацевта','kind':'TV Сериал','date':1},{'id':'58514','title':'Монолог фармацевта 2','kind':'tv','date':3},{'id':'61987','title':'Монолог фармацевта 3','kind':'tv','date':5},{'id':'62841','title':'Монолог фармацевта 3. Часть 2','kind':'tv','date':7},{'id':'56975','title':'Монолог Маомао','kind':'ONA','date':2},{'id':'60749','title':'Монолог Маомао 2','kind':'ONA','date':4},{'id':'62844','title':'Фильм','kind':'Фильм','date':6}]
  self.links=[{'source_id':a,'target_id':b,'relation':r} for a,b,r in [('54492','58514','sequel'),('58514','61987','sequel'),('61987','62841','sequel'),('54492','56975','other'),('56975','60749','sequel'),('58514','62844','side_story')]]
 def test_every_entry_point_has_all_main_seasons_without_spinoffs(self):
  for identity in ['54492','58514','61987','62841']:
   values=main_seasons(identity,self.items,self.links)
   self.assertEqual([v['id'] for v in values],['54492','58514','61987','62841']);self.assertEqual([v['name'] for v in values],['Сезон 1','Сезон 2','Сезон 3','Сезон 3 · часть 2'])
 def test_unknown_or_unrelated_work_does_not_invent_seasons(self):
  self.assertEqual(main_seasons('000',self.items,self.links),[]);self.assertEqual(main_seasons('56975',self.items,self.links),[])
 def test_adaptation_and_alternative_version_are_not_main_continuity(self):
  self.links.append({'source_id':'54492','target_id':'100','relation':'alternative_version'});self.items.append({'id':'100','title':'Другой сериал','date':.5,'kind':'tv'})
  self.assertNotIn('100',[r['id'] for r in main_seasons('61987',self.items,self.links)])
