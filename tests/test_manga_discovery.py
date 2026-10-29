"""Real SQLite/queue/auth tests; upstream manga provider responses are fixtures."""
import json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import manga_discovery as discovery
from source_parser import SourceError

SOURCES=[{'id':str(i+1),'name':'Fixture '+str(i+1),'lang':['ru','en','ja','ko'][i%4],'baseUrl':'https://source.example','isNsfw':False} for i in range(16)]
ENV={'PUBLIC_URL':'https://media.example','SUWAYOMI_URL':'http://suwayomi:4567','SUWAYOMI_AUTH_FILE':'/private/auth'}

def fixture(source,query):return [discovery.result_row(source,{'id':int(source['id']),'title':'One Piece '+source['id'],'url':'/manga/'+source['id']})]
def wait_done(manager,owner,identity):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        value=manager.status(owner,identity)
        if value['state']!='running':return value
        time.sleep(.01)
    raise AssertionError('Discovery job did not finish')

class NativeSourceFallbackTests(unittest.TestCase):
    def test_upgrade_expires_only_ambiguous_legacy_mangalib_public_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=discovery.Discovery(directory,start_workers=False)
            with manager.db:
                manager.db.execute('INSERT INTO titles VALUES(?,?,?,?,?,?)',('legacy-lib','1','ru','naruto',json.dumps({'provider':'mangalib'}),time.time()))
                for sid in ['1','2']:manager.db.execute('INSERT INTO query_cache VALUES(?,?,?,?)',('naruto',sid,'[]',time.time()+900))
                manager.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('old-job','owner','signature','naruto','ru','done',time.time(),time.time(),time.time()+900,time.time()))
                manager.db.execute('INSERT INTO work VALUES(?,?,?,?,?,?)',('old-job','1','{}','done','[]',1))
                manager.db.execute('PRAGMA user_version=0')
            manager.close();manager=discovery.Discovery(directory,start_workers=False)
            self.assertEqual(manager.db.execute('SELECT count(*) FROM titles').fetchone()[0],0)
            self.assertEqual([r[0] for r in manager.db.execute('SELECT source_id FROM query_cache')],['2'])
            self.assertEqual(manager.db.execute("SELECT state FROM jobs WHERE id='old-job'").fetchone()[0],'interrupted')
            manager.close()
    def test_mangalib_extension_failure_keeps_source_selectable_through_its_public_api(self):
        source={'id':'6111047689498497237','name':'MangaLib','lang':'ru'}
        native={'title':'Наруто','aliases':['Naruto'],'kind':'manga','url':'https://mangalib.me/ru/195--naruto','language':'ru'}
        with patch.object(discovery.bridge,'Client') as client,patch('manga_catalog_adapters.lib_search',return_value=[native]):
            client.return_value.get.side_effect=SourceError('CEF initialization failed')
            first=discovery.search_source(source,'Наруто');second=discovery.search_source(source,'Naruto')
            self.assertEqual(first[0]['id'],second[0]['id']);self.assertEqual(first[0]['sourceId'],source['id'])
            self.assertEqual(first[0]['url'],native['url']);self.assertEqual(first[0]['aliases'],['Naruto'])
            self.assertEqual(first[0]['providerName'],'MangaLib');self.assertTrue(first[0]['sourceOnly'])
        with patch.object(discovery.bridge,'Client') as client,patch('manga_catalog_adapters.lib_search') as other:
            client.return_value.get.side_effect=SourceError('Other source failed')
            with self.assertRaises(SourceError):discovery.search_source({**source,'name':'Other'},'Наруто')
            other.assert_not_called()

class MangaDiscoveryTests(unittest.TestCase):
 def setUp(self):
    self.directory=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,ENV);self.env.start();self.sources=patch.object(discovery.bridge,'sources',return_value=SOURCES);self.sources.start();self.managers=[]
 def tearDown(self):
    for manager in self.managers:manager.close()
    self.sources.stop();self.env.stop();self.directory.cleanup()
 def manager(self,**options):
    manager=discovery.Discovery(self.directory.name,**options);self.managers.append(manager);return manager
 def test_global_queue_reaches_every_source_with_four_shared_workers_and_partial_results(self):
    gate=threading.Event();lock=threading.Lock();active=peak=0;contacted=[]
    def fetch(source,query):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active);contacted.append(source['id'])
        if source['id']!='2':gate.wait(3)
        with lock:active-=1
        return fixture(source,query)
    manager=self.manager(fetch=fetch)
    value=manager.start('A','One P')
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        value=manager.status('A',value['id'])
        if value['results']:break
        time.sleep(.01)
    self.assertEqual(value['state'],'running');self.assertGreater(len(value['results']),0);self.assertLess(value['progress']['completed'],16)
    second=manager.start('B','Piece')
    self.assertEqual(len(manager.threads),4);gate.set()
    value=wait_done(manager,'A',value['id']);wait_done(manager,'B',second['id'])
    self.assertEqual(value['progress']['completed'],16);self.assertEqual(len(value['results']),16);self.assertLessEqual(peak,4);self.assertEqual(set(contacted),{s['id'] for s in SOURCES})
 def test_query_script_prioritizes_matching_language_without_excluding_other_sources(self):
    manager=self.manager(fetch=fixture,start_workers=False)
    for owner,query,language in [('A','Наруто','ru'),('B','ナルト','ja'),('C','나루토','ko'),('D','Naruto','en')]:
        value=manager.start(owner,query)
        queued=manager.db.execute('SELECT source_id FROM work WHERE job=? ORDER BY rowid',(value['id'],)).fetchall()
        by_id={s['id']:s for s in SOURCES}
        self.assertEqual([by_id[r[0]]['lang'] for r in queued[:4]],[language]*4)
        self.assertEqual(len(queued),len(SOURCES))
 def test_selected_sources_are_installed_validated_and_raw_query_is_not_exact_title_matched(self):
    calls=[]
    def fetch(source,query):calls.append((source['id'],query));return fixture(source,query)
    manager=self.manager(fetch=fetch)
    value=wait_done(manager,'A',manager.start('A','  One   P  ','en',['2','6'])['id'])
    self.assertEqual(value['progress']['total'],2);self.assertEqual({sid for sid,q in calls},{'2','6'});self.assertTrue(all(q=='One P' for sid,q in calls));self.assertEqual(len(value['results']),2)
    for ids in [[],['999'],['../../secret'],['2?url=evil']]:
        with self.assertRaises(ValueError):manager.start('A','query','all',ids)
    with self.assertRaises(ValueError):manager.start('A','one\nquery')
    with self.assertRaises(discovery.SearchMissing):manager.status('B',value['id'])
    with self.assertRaises(discovery.SearchMissing):manager.cancel('B',value['id'])
 def test_cache_survives_restart_and_ttl_refresh_seeds_metadata_without_hiding_provider_work(self):
    now=[1000.];calls=[]
    def fetch(source,query):calls.append(source['id']);return fixture(source,query)
    manager=self.manager(fetch=fetch,clock=lambda:now[0],cache_ttl=10)
    first=wait_done(manager,'A',manager.start('A','One Piece','all',['1'])['id']);manager.close();self.managers.remove(manager)
    manager=self.manager(fetch=fetch,clock=lambda:now[0],cache_ttl=10)
    cached=manager.start('B','ONE PIECE','all',['1'])
    self.assertEqual(cached['state'],'done');self.assertEqual(cached['progress']['cached'],1);self.assertEqual(calls,['1'])
    self.assertEqual(manager.start('B','one piece','all',['1'])['id'],cached['id'])
    refreshed=wait_done(manager,'B',manager.start('B','one piece','all',['1'],refresh=True)['id'])
    self.assertNotEqual(refreshed['id'],cached['id']);self.assertEqual(calls,['1','1'])
    now[0]+=11
    gate=threading.Event();manager.fetch=lambda s,q:(gate.wait(2) or True) and fixture(s,q)
    fresh=manager.start('A','One Piece','all',['1']);self.assertEqual(fresh['state'],'running');self.assertEqual(fresh['progress']['cached'],0);self.assertEqual(len(fresh['results']),1)
    gate.set();wait_done(manager,'A',fresh['id'])
    self.assertTrue(Path(self.directory.name,'manga-discovery.sqlite').exists())
 def test_limits_cancellation_and_restart_do_not_launch_more_workers_or_leak_work(self):
    gate=threading.Event();calls=[]
    def fetch(s,q):calls.append(s['id']);gate.wait(3);return fixture(s,q)
    manager=self.manager(fetch=fetch,max_jobs=2,per_owner=1)
    first=manager.start('A','query one');self.assertEqual(manager.start('A','query one')['id'],first['id'])
    with self.assertRaises(discovery.SearchLimit):manager.start('A','query two')
    second=manager.start('B','query two')
    with self.assertRaises(discovery.SearchLimit):manager.start('C','query three')
    cancelled=manager.cancel('A',first['id']);self.assertEqual(cancelled['state'],'cancelled')
    gate.set();wait_done(manager,'B',second['id']);self.assertEqual(manager.status('A',first['id'])['state'],'cancelled')
    self.assertLessEqual(calls.count('1'),2)
 def test_upstream_failures_are_reported_separately_and_queries_are_sql_parameters(self):
    def fetch(s,q):
        if s['id']=='2':raise SourceError('secret upstream details')
        return fixture(s,q)
    manager=self.manager(fetch=fetch)
    result=wait_done(manager,'A',manager.start('A',"x%' OR 1=1 --",'all',['1','2'])['id'])
    self.assertEqual(result['progress']['failed'],1);self.assertEqual(result['progress']['completed'],2)
    self.assertNotIn('secret',json.dumps(result));self.assertEqual(manager.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
 def test_restart_marks_pending_job_interrupted_and_can_resume_with_fresh_job(self):
    manager=self.manager(fetch=fixture,start_workers=False)
    pending=manager.start('A','One Piece','all',['1','2'])
    self.assertEqual(pending['state'],'running');manager.close();self.managers.remove(manager)
    manager=self.manager(fetch=fixture)
    self.assertEqual(manager.status('A',pending['id'])['state'],'interrupted')
    resumed=wait_done(manager,'A',manager.start('A','One Piece','all',['1','2'])['id'])
    self.assertEqual(resumed['state'],'done');self.assertEqual(resumed['progress']['completed'],2)
 def test_source_list_and_result_metadata_never_expose_internal_image_targets(self):
    self.assertEqual(discovery.source_list('ja')['total'],4);self.assertEqual(len(discovery.source_list('all','Fixture 1')['sources']),8)
    row=discovery.result_row(SOURCES[0],{'id':1,'title':'候補の漫画','url':'/one','thumbnailUrl':'http://suwayomi:4567/private'})
    self.assertEqual(row['cover'],'');self.assertEqual(row['sourceUrl'],'https://source.example/one');self.assertEqual(row['sourceURL'],'https://media.example/__manga/suwayomi/m/1');self.assertTrue(row['sourceOnly'])
    self.assertIsNone(discovery.result_row(SOURCES[0],{'id':'bad','title':'text'}))
 def test_cancelled_job_does_not_contact_queued_sources(self):
    gate=threading.Event();started=threading.Event();calls=[];lock=threading.Lock()
    def fetch(s,q):
        with lock:
            calls.append(s['id'])
            if len(calls)==4:started.set()
        gate.wait(3);return fixture(s,q)
    manager=self.manager(fetch=fetch);value=manager.start('A','One Piece')
    self.assertTrue(started.wait(2));manager.cancel('A',value['id']);gate.set()
    manager.close();self.managers.remove(manager)
    self.assertEqual(len(calls),4)
 def test_provider_search_passes_raw_query_and_accepts_partial_title_candidates(self):
    with patch.object(discovery.bridge,'Client') as client:
        client.return_value.get.return_value={'mangaList':[{'id':8,'title':'One Piece: Adventure'}]}
        results=discovery.search_source(SOURCES[0],'One P')
        client.return_value.get.assert_called_once_with('/source/1/search',{'searchTerm':'One P','pageNum':1},timeout=4)
        self.assertEqual(results[0]['title'],'One Piece: Adventure');client.return_value.close.assert_called_once()

class MangaDiscoveryApiTests(unittest.TestCase):
 def test_routes_are_owner_isolated_and_expose_versioned_capability(self):
    import api
    from fastapi.testclient import TestClient
    client=TestClient(api.app)
    self.assertEqual(client.get('/discovery/manga/sources').status_code,401)
    with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,ENV),patch.object(discovery.bridge,'sources',return_value=SOURCES),patch.object(api,'store',SimpleNamespace(key=b'x'*32,setting=lambda name:None)):
        manager=discovery.Discovery(directory,fetch=fixture)
        try:
            with patch.object(discovery,'manager',return_value=manager):
                auth=lambda name:{'Authorization':'Bearer '+api.session_token(name)}
                response=client.post('/discovery/manga/search',headers=auth('A'),json={'query':'One P','sourceIds':['1']})
                self.assertEqual(response.status_code,202);identity=response.json()['id']
                self.assertEqual(client.get('/discovery/manga/search/'+identity,headers=auth('B')).status_code,404)
                self.assertEqual(client.delete('/discovery/manga/search/'+identity,headers=auth('B')).status_code,404)
                self.assertEqual(client.delete('/discovery/manga/search/'+identity,headers=auth('A')).status_code,200)
                self.assertEqual(client.post('/discovery/manga/search',headers=auth('A'),json={'query':'abc','sourceIds':['999']}).status_code,422)
                self.assertEqual(client.get('/health').json()['version'],27);self.assertTrue(client.get('/health').json()['mangaGlobalDiscovery'])
        finally:manager.close()

class VoiceSuggestionTests(unittest.TestCase):
 def test_autocomplete_uses_only_observed_unexpired_named_voices(self):
    import source_discovery as voices
    observed={'voices':[{'id':'real','name':'Реальная студия','kind':'voice','language':'ru','variants':[{'named':True,'sourceUrl':'https://source.example/title','providerName':'Source'}]},{'id':'sub','name':'Субтитры','kind':'subtitles','language':'ru','variants':[{'sourceUrl':'https://source.example'}]},{'id':'unnamed','name':'Без названия','kind':'voice','variants':[{'named':False,'sourceUrl':'https://source.example'}]}]}
    with patch.object(voices,'_cache',{'real':(time.monotonic()+30,observed),'expired':(0,{'voices':[{'id':'expired','name':'Expired'}]})}):
        response=voices.voice_suggestions('студ')
        self.assertEqual([v['id'] for v in response['voices']],['real']);self.assertTrue(response['observedOnly']);self.assertEqual(voices.voice_suggestions('fiction')['voices'],[])
