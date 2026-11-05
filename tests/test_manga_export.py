"""Real archives, encrypted cache, queue and HTTP; translation is a marked fixture."""
import hashlib,io,os,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from fastapi import FastAPI,Header
from fastapi.testclient import TestClient
from local_exports import Exports,Budget,ExportMissing
from manga_export import Options,PageCache,produce
from test_local_exports import wait_terminal

def png(color='white'):
    stream=io.BytesIO();Image.new('RGB',(80,100),color).save(stream,'PNG');return stream.getvalue()

class MangaExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'service.key').write_bytes(os.urandom(32));self.managers=[]
        self.env=patch.dict(os.environ,DATA_DIR=str(self.root));self.env.start()
    def tearDown(self):
        for manager in self.managers:manager.close()
        self.env.stop();self.temp.cleanup()
    def manager(self,**kwargs):
        value=Exports(self.root,reserve=0,**kwargs);self.managers.append(value);return value
    def options(self,format='cbz'):
        data=png();return Options(mode='cached',format=format,name='Глава 1',cached=[{'chapter':0,'page':0,'imageHash':hashlib.sha256(data).hexdigest()}]).model_dump(),data
    def test_staged_upload_owner_hash_and_commit(self):
        options,data=self.options();manager=self.manager(start_worker=False)
        value=manager.start('A','','manga',manga=options);identity=value['id']
        self.assertEqual(value['state'],'staging')
        with self.assertRaises(ExportMissing):manager.put_page('B',identity,0,0,data)
        with self.assertRaises(ValueError):manager.put_page('A',identity,0,0,png('black'))
        with self.assertRaises(ValueError):manager.enqueue('A',identity)
        manager.put_page('A',identity,0,0,data);self.assertEqual(manager.enqueue('A',identity)['state'],'queued')
        manager.cancel('A',identity);self.assertFalse(manager.jobs[identity].directory.exists())
    def test_cached_chapter_cbz_zip_pdf_without_source_or_translation(self):
        for format in ['cbz','zip','pdf']:
            manager=self.manager();options,data=self.options(format)
            with patch('manga_download.download_chapter',side_effect=AssertionError('Cached export must not fetch originals')),patch('manga_export_runtime.translate_pages',side_effect=AssertionError('No paid request for ready pages')):
                value=manager.start('A','','manga',manga=options);manager.put_page('A',value['id'],0,0,data);manager.enqueue('A',value['id']);result=wait_terminal(manager,'A',value['id'])
            self.assertEqual(result['state'],'done',result)
            path=manager.jobs[value['id']].file
            self.assertTrue(result['filename'].endswith('.'+format))
            if format=='pdf':
                pdf=path.read_bytes();self.assertTrue(pdf.startswith(b'%PDF-1.4'));self.assertIn(b'/Count 1',pdf);self.assertIn(b'/DCTDecode',pdf)
                offset=int(pdf.split(b'startxref\n')[1].splitlines()[0]);self.assertEqual(pdf[offset:offset+4],b'xref')
            else:
                with zipfile.ZipFile(path) as archive:self.assertEqual(archive.read('0001.png'),data)
            job,_=manager.acquire(result['downloadUrl'].split('/')[-1]);manager.release(job,True);self.assertFalse(job.directory.exists())
    def test_translation_reuses_valid_pages_and_encrypted_vm_cache(self):
        from manga_export import cached_path
        raw=[png('white'),png('black')];translated=png('red');calls=[]
        options=Options(mode='translate',chapters=[{'url':'https://mangapill.com/chapters/fixture','number':1}],cached=[{'chapter':0,'page':0,'sourceHash':hashlib.sha256(raw[0]).hexdigest(),'imageHash':hashlib.sha256(translated).hexdigest()}]).model_dump()
        def download(url,directory,http,**kwargs):
            path=directory/'source.cbz'
            with zipfile.ZipFile(path,'w') as archive:
                for i,data in enumerate(raw):archive.writestr(f'{i+1:04}.png',data)
            return path
        def translate(job,pages,config,skip,save,progress,budget):
            calls.append(skip.copy());self.assertEqual(pages[1],raw[1]);save(1,translated)
        for repeat in range(2):
            directory=self.root/str(repeat);directory.mkdir();job=SimpleNamespace(directory=directory,manga=options,owner='A',quality='best',cancel=__import__('threading').Event())
            cached_path(job,0,0).write_bytes(translated)
            with patch('manga_download.download_chapter',download),patch('manga_export_runtime.translate_pages',translate):
                result=produce(job,None,Budget(job,1024**2,reserve=0),lambda p:None)
            with zipfile.ZipFile(result) as archive:self.assertEqual([archive.read(n) for n in archive.namelist()],[translated,translated])
        self.assertEqual(calls,[[0]],'Second attempt uses the encrypted VM page cache')
        files=list((self.root/'.codex-local/export-translations').glob('*.cache'));self.assertTrue(files);self.assertNotIn(translated,files[0].read_bytes())
        cache=PageCache(self.root);self.assertNotEqual(cache.key('A',raw[0],{}),cache.key('B',raw[0],{}))
    def test_partial_cached_chapter_cannot_be_presented_as_complete(self):
        options,data=self.options();options['chapters']=[{'url':'https://mangapill.com/chapters/fixture','number':1,'pageCount':2}]
        manager=self.manager();value=manager.start('A','','manga',manga=options);manager.put_page('A',value['id'],0,0,data);manager.enqueue('A',value['id']);result=wait_terminal(manager,'A',value['id'])
        self.assertEqual(result['state'],'error');self.assertIn('все страницы',result['error'])
    def test_upload_endpoint_accepts_binary_only_for_its_owner(self):
        import local_exports
        app=FastAPI();manager=self.manager(start_worker=False)
        def owner(authorization:str=Header(default='')):return authorization
        local_exports.install(app,owner);client=TestClient(app);options,data=self.options()
        with patch.object(local_exports,'manager',return_value=manager):
            value=client.post('/online/exports',headers={'Authorization':'A'},json={'kind':'manga','manga':options}).json();route='/online/exports/'+value['id']
            self.assertEqual(client.put(route+'/pages/0/0',headers={'Authorization':'B'},content=data).status_code,404)
            self.assertEqual(client.put(route+'/pages/0/0',headers={'Authorization':'A'},content=data).status_code,200)
            self.assertEqual(client.post(route+'/start',headers={'Authorization':'A'}).json()['state'],'queued')
