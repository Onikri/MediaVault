"""Real queue/files/capability/HTTP contracts; media provider work is a fixture."""
import os,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import FastAPI,Header,HTTPException
from fastapi.testclient import TestClient
import local_exports as exports
import online_sessions

URL='https://mangapill.com/chapters/fixture'
def fixture(job,progress,maximum,reserve):
    progress({'phase':'downloading','loaded':1,'total':2,'secret':'not metadata'})
    (job.directory/'input.tmp').write_bytes(b'input')
    target=job.directory/('chapter.cbz' if job.kind=='manga' else 'episode.mp4');target.write_bytes(b'checked media fixture'*5000);return target
def wait_terminal(manager,owner,identity):
    until=time.monotonic()+5
    while time.monotonic()<until:
        value=manager.status(owner,identity)
        if value['state'] in {'done','error','cancelled'} and not manager.jobs[identity].running:return value
        time.sleep(.01)
    raise AssertionError('Export did not finish')

class LocalExportTests(unittest.TestCase):
 def setUp(self):self.directory=tempfile.TemporaryDirectory();self.managers=[]
 def tearDown(self):
    for manager in self.managers:manager.close()
    self.directory.cleanup()
 def manager(self,**kw):
    manager=exports.Exports(self.directory.name,**kw);self.managers.append(manager);return manager
 def test_file_response_streams_range_and_keeps_owner_isolation_route_order_and_cleanup(self):
    manager=self.manager(producer=fixture)
    def owner(authorization:str=Header(default='')):
        if authorization not in {'Bearer A','Bearer B'}:raise HTTPException(401)
        return authorization[-1]
    app=FastAPI();online_sessions.install(app,owner);client=TestClient(app)
    with patch.object(exports,'manager',return_value=manager):
        self.assertEqual(client.post('/online/exports',json={'url':URL,'kind':'manga'}).status_code,401)
        response=client.post('/online/exports',headers={'Authorization':'Bearer A'},json={'url':URL,'kind':'manga'})
        self.assertEqual(response.status_code,202);identity=response.json()['id'];value=wait_terminal(manager,'A',identity)
        self.assertEqual(client.get('/online/exports/'+identity,headers={'Authorization':'Bearer B'}).status_code,404)
        self.assertEqual(client.delete('/online/exports/'+identity,headers={'Authorization':'Bearer B'}).status_code,404)
        self.assertEqual(client.get('/online/exports/'+identity,headers={'Authorization':'Bearer A'}).json()['state'],'done')
        response=client.get(value['downloadUrl'],headers={'Range':'bytes=0-19'})
        self.assertEqual(response.status_code,206);self.assertEqual(response.content,b'checked media fixture'[:20]);self.assertIn('attachment',response.headers['content-disposition']);self.assertEqual(response.headers['cache-control'],'private, no-store')
        job=manager.jobs[identity];self.assertEqual(job.leases,0);self.assertEqual([p.name for p in job.directory.iterdir()],['chapter.cbz'])
        self.assertEqual(client.get('/online/exports/file/not-a-capability').status_code,410)
        self.assertEqual(client.delete('/online/exports/'+identity,headers={'Authorization':'Bearer A'}).json()['state'],'cancelled')
        self.assertFalse(job.directory.exists());self.assertEqual(client.get(value['downloadUrl']).status_code,410)
 def test_complete_download_releases_plaintext_and_allows_more_than_four_sequential_exports(self):
    manager=self.manager(producer=fixture)
    app=FastAPI();online_sessions.install(app,lambda:'A');client=TestClient(app)
    with patch.object(exports,'manager',return_value=manager):
        for index in range(6):
            value=wait_terminal(manager,'A',manager.start('A',URL+str(index),'manga')['id'])
            response=client.get(value['downloadUrl'])
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.content)
            self.assertEqual(manager.status('A',value['id'])['state'],'downloaded')
            self.assertFalse(manager.jobs[value['id']].directory.exists())
 def test_one_worker_dedup_and_active_limits_prevent_unbounded_tasks(self):
    gate=threading.Event();entered=threading.Event();lock=threading.Lock();running=peak=0
    def produce(job,progress,maximum,reserve):
        nonlocal running,peak
        with lock:running+=1;peak=max(peak,running)
        entered.set();gate.wait(3)
        with lock:running-=1
        return fixture(job,progress,maximum,reserve)
    manager=self.manager(producer=produce)
    first=manager.start('A',URL,'manga');self.assertTrue(entered.wait(2));self.assertEqual(first['id'],manager.start('A',URL,'manga')['id'])
    second=manager.start('A',URL+'2','manga')
    with self.assertRaises(exports.ExportLimit):manager.start('A',URL+'3','manga')
    third=manager.start('B',URL+'3','manga');fourth=manager.start('B',URL+'4','manga')
    with self.assertRaises(exports.ExportLimit):manager.start('C',URL+'5','manga')
    manager.cancel('A',second['id']);gate.set()
    for owner,value in [('A',first),('B',third),('B',fourth)]:self.assertEqual(wait_terminal(manager,owner,value['id'])['state'],'done')
    self.assertEqual(peak,1)
 def test_cancellation_does_not_delete_running_files_or_resurrect_finished_job(self):
    gate=threading.Event();entered=threading.Event()
    def produce(job,progress,maximum,reserve):
        (job.directory/'active.tmp').write_bytes(b'active');entered.set();gate.wait(3);return fixture(job,progress,maximum,reserve)
    manager=self.manager(producer=produce);value=manager.start('A',URL,'manga');self.assertTrue(entered.wait(2));job=manager.jobs[value['id']]
    self.assertEqual(manager.cancel('A',job.id)['state'],'cancelled');self.assertTrue((job.directory/'active.tmp').exists())
    gate.set();self.assertEqual(wait_terminal(manager,'A',job.id)['state'],'cancelled');self.assertFalse(job.directory.exists())
 def test_download_lease_survives_expiry_and_capabilities_can_be_renewed_only_by_owner(self):
    now=[1000.];manager=self.manager(producer=fixture,clock=lambda:now[0]);value=wait_terminal(manager,'A',manager.start('A',URL,'manga')['id'])
    original=value['downloadUrl'].rsplit('/',1)[1];now[0]+=901
    with self.assertRaises(exports.ExportMissing):manager.acquire(original)
    with self.assertRaises(exports.ExportMissing):manager.status('B',value['id'])
    refreshed=manager.status('A',value['id']);self.assertNotEqual(refreshed['downloadUrl'],value['downloadUrl'])
    job,metadata=manager.acquire(refreshed['downloadUrl'].rsplit('/',1)[1]);now[0]+=3601
    with self.assertRaises(exports.ExportMissing):manager.status('A',job.id)
    self.assertTrue(job.file.exists());manager.release(job);self.assertFalse(job.directory.exists())
 def test_generic_failures_do_not_expose_source_secrets_and_restart_removes_only_generated_dirs(self):
    def fail(*args):raise RuntimeError('secret-key and internal hostname')
    manager=self.manager(producer=fail);value=wait_terminal(manager,'A',manager.start('A',URL,'manga')['id'])
    self.assertEqual(value['state'],'error');self.assertNotIn('secret',value['error']);self.assertFalse(manager.jobs[value['id']].directory.exists())
    keep=manager.root/'operator-notes';keep.mkdir();(keep/'note.txt').write_text('keep')
    old=manager.root/('f'*32);old.mkdir();(old/'plaintext.cbz').write_bytes(b'old');manager.close();self.managers.remove(manager)
    manager=self.manager(start_worker=False);self.assertFalse(old.exists());self.assertTrue((keep/'note.txt').exists())
 def test_validation_and_disk_reserve_reject_unsupported_or_private_targets_before_queue(self):
    manager=self.manager(start_worker=False)
    for url,kind,quality in [('https://127.0.0.1/one','manga','best'),('https://untrusted.example/movie.mp4','video','best'),('https://youtube.com/watch?v=one','video','best'),(URL,'manga','2160')]:
        with self.assertRaises((ValueError,exports.SourceError)):manager.start('A',url,kind,quality)
    self.assertEqual(manager.jobs,{})
    with patch.object(exports.shutil,'disk_usage',return_value=SimpleNamespace(free=exports.GiB)):
        with self.assertRaises(exports.ExportLimit):manager.start('A',URL,'manga')
 def test_shared_network_budget_cancels_and_caps_all_http_forks(self):
    directory=Path(self.directory.name);job=exports.Export('x','A',URL,'manga','best',0,10,directory)
    budget=exports.Budget(job,100,reserve=0);http=exports.ExportHttp(budget);fork=http.fork()
    try:
        self.assertIs(fork.budget,budget);budget.consume(60)
        with self.assertRaises(exports.ExportProblem):fork.budget.consume(41)
        job.cancel.set()
        with self.assertRaises(exports.ExportCancelled):budget.check()
    finally:fork.close();http.close()
 def test_cancelled_remux_process_is_terminated_and_temp_logs_are_removed(self):
    directory=Path(self.directory.name);job=exports.Export('x','A',URL,'video','best',0,10,directory);budget=exports.Budget(job,1024*1024,reserve=0)
    original=exports.subprocess.Popen;processes=[]
    def popen(*args,**kwargs):
        if os.name=='nt':kwargs['creationflags']=getattr(exports.subprocess,'CREATE_NO_WINDOW',0)
        process=original(*args,**kwargs);processes.append(process);return process
    timer=threading.Timer(.3,job.cancel.set);timer.start()
    try:
        with patch.object(exports.subprocess,'Popen',side_effect=popen),self.assertRaises(exports.ExportCancelled):budget.run([sys.executable,'-c','import time;time.sleep(30)'],timeout=10)
    finally:timer.cancel()
    self.assertEqual(len(processes),1);self.assertIsNotNone(processes[0].poll());self.assertEqual(list(directory.iterdir()),[])
