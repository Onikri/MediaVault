import os,time,tempfile,threading,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from playback_resolver import PlaybackResolver
import character_profile,source_discovery,source_index
from player_catalog import choice
from source_parser import PublicHttp,SourceError

class AccelerationTests(unittest.TestCase):
 def test_simultaneous_resolution_is_shared_and_owner_scoped(self):
  cache=PlaybackResolver();calls=[];start=threading.Event()
  def load():calls.append(1);start.wait(2);return SimpleNamespace(streams=[{'url':'https://cdn.example/video'}])
  with ThreadPoolExecutor(max_workers=3) as pool:
   a=pool.submit(cache.page,'a','url',None,load);b=pool.submit(cache.page,'a','url',None,load);time.sleep(.04);start.set();first=a.result();second=b.result()
  self.assertEqual(len(calls),1);self.assertEqual(sum(x[1] for x in [first,second]),1)
  first[0].streams.clear();self.assertEqual(len(cache.page('a','url',None,load)[0].streams),1)
  cache.page('b','url',None,load);cache.page('a','url',None,load,refresh=True);self.assertEqual(len(calls),3)
 def test_failed_resolution_and_expired_signature_are_not_cached(self):
  cache=PlaybackResolver();calls=[]
  def bad():calls.append(1);raise SourceError('offline')
  for _ in range(2):
   with self.assertRaises(SourceError):cache.get('bad',bad)
  self.assertEqual(len(calls),2)
  def expired():return SimpleNamespace(streams=[{'url':'https://cdn.example/v?exp=1000000000'}])
  self.assertFalse(cache.get('signed',expired)[1]);self.assertFalse(cache.get('signed',expired)[1])
 def test_public_connections_share_pool_but_not_cookies_or_headers(self):
  a,b=PublicHttp(),PublicHttp()
  try:
   self.assertIs(a.session.adapters['https://'],b.session.adapters['https://'])
   a.session.cookies.set('secret','one');a.session.headers['X-Test']='one'
   self.assertNotIn('secret',b.session.cookies);self.assertNotIn('X-Test',b.session.headers)
   a.close();self.assertIs(b.session.adapters['https://'],a.session.adapters['https://'])
  finally:b.close()
 def test_discovery_releases_first_voice_without_waiting_for_slow_provider(self):
  selected={'title':'Progressive fixture','kind':'anime','year':2024,'ids':{'mal':'991991'}};slow=threading.Event();finished=threading.Event()
  sites=[SimpleNamespace(id=x,name=x,kind='anime') for x in ['fast','slow']]
  def search(site,*args,**kwargs):
   if site.id=='slow':slow.wait(3)
   return {'status':'ok','results':[{'title':selected['title'],'kind':'anime','year':2024,'url':'https://catalog.example/'+site.id,'provider':site.id}]}
  def inspect(url,**kwargs):return {'url':url,'title':selected['title'],'year':2024,'dubs':[choice('Studio '+url.split('/')[-1],'https://kodikplayer.com/serial/1/h/720p')],'complete':True}
  with patch.object(source_discovery,'SITES',sites),patch.object(source_discovery,'search_site',side_effect=search),patch.object(source_discovery,'inspect_source',side_effect=inspect),patch.object(source_index,'save'):
   try:
    first=source_discovery.discover(selected,refresh=True);self.assertTrue(first['pending']);self.assertEqual(len(first['voices']),1)
    slow.set()
    for _ in range(50):
     result=source_discovery.discover(selected,refresh=True,continuing=True)
     if not result['pending']:break
     time.sleep(.02)
    self.assertFalse(result['pending']);self.assertEqual(len(result['voices']),2)
   finally:
    slow.set()
    for _ in range(100):
     with source_discovery._jobs_lock:running=bool(source_discovery._jobs)
     if not running:break
     time.sleep(.02)
 def test_disk_index_retains_public_voice_identity_not_cdn_credentials(self):
  with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'DISCOVERY_CACHE_DIR':folder}):
   source_index.save('日本語 и русский',{'voices':[{'id':'studio','name':'Studio','variants':[{'id':'v','url':'https://kodikplayer.com/serial/1/h/720p','sourceUrl':'https://catalog.example/show','headers':{'Authorization':'private'},'episodes':[{'number':1,'url':'https://cdn.example/private.mp4?token=private'}]}]}]})
   value=source_index.load('日本語 и русский');self.assertEqual(value['voices'][0]['name'],'Studio');self.assertNotIn('private',str(value));self.assertEqual(value['voices'][0]['variants'][0]['episodes'],[{'number':1}])

class CharacterTests(unittest.TestCase):
 def test_only_explicit_facts_with_attribution_and_spoilers(self):
  result=character_profile.build('42',{'id':42,'russian':'Герой','description':'Рост: 175 см'}, {'mal_id':42,'name':'Hero','about':'Birthdate: March 30\nAge: 19,\nHeight: 180 cm\nGender: Male\nMother: Example\nStatus: Alive\nFirst appearance: Episode 2','anime':[{'anime':{'mal_id':1,'title':'Show'},'role':'Main'}]})
  values={r['key']:r for r in result['attributes']}
  self.assertEqual(values['height']['value'],'175 см');self.assertEqual(values['birthday']['value'],'March 30');self.assertEqual(values['age']['value'],'19');self.assertEqual(values['gender']['value'],'Мужской');self.assertTrue(values['mother']['spoiler']);self.assertTrue(values['debut']['spoiler']);self.assertNotIn('father',values);self.assertEqual(result['appearances'][0]['id'],'1');self.assertTrue(all(v['url'] for v in values.values()))
 def test_wrong_character_is_rejected_and_missing_attributes_remain_missing(self):
  for base,extra in [({'id':43},{}),({}, {'mal_id':43})]:
   with self.assertRaises(SourceError):character_profile.build('42',base,extra)
  self.assertEqual(character_profile.build('42',{'id':42},{})['attributes'],[])

class TrailerHostTests(unittest.TestCase):
 def test_youtube_confirmation_uses_only_catalogue_verified_embed_id(self):
  import sys,trailer_service
  token='confirmed-fixture';trailer_service.jobs[token]={'id':token,'status':'preparing','youtubeId':'abcdefghijk'}
  with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'playwright':SimpleNamespace(__file__=__file__)}),patch.object(trailer_service.subprocess,'run',return_value=SimpleNamespace(returncode=1,stderr=b'Sign in to confirm you are not a bot')):
   try:
    trailer_service.download(token,'https://www.youtube.com/watch?v=abcdefghijk',Path(folder),release_slot=False)
    public=trailer_service.public(trailer_service.jobs[token]);self.assertEqual(public['status'],'browser');self.assertEqual(public['youtubeId'],'abcdefghijk')
   finally:trailer_service.jobs.pop(token,None)
