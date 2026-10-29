import io,json,os,sys,tempfile,unittest,zipfile,sqlite3
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import suwayomi_bridge as bridge
from source_parser import SourceError

ENV={'PUBLIC_URL':'https://media.example','SUWAYOMI_URL':'http://suwayomi:4567','SUWAYOMI_AUTH_FILE':'/private/auth'}
class BridgeTests(unittest.TestCase):
    def setUp(self):self.env=patch.dict(os.environ,ENV);self.env.start();bridge._cache.clear()
    def tearDown(self):self.env.stop();bridge._cache.clear()
    def test_failed_novelcool_extension_recovers_only_its_indexed_public_reader(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}):
            path=Path(directory)/'manga-discovery.sqlite'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE titles(id TEXT,metadata TEXT)')
                db.execute('INSERT INTO titles VALUES(?,?)',('suwayomi:2:1',json.dumps({'url':bridge.reference(1),'sourceUrl':'https://ru.novelcool.com/novel/Наруто.html'})))
            class Fake:
                def close(self):pass
                def get(self,*a,**kw):raise SourceError('HTTP 404')
            with patch.object(bridge,'Client',Fake),patch('manga_sources.inspect',return_value={'title':'Наруто','episodes':[]}) as native:
                self.assertEqual(bridge.inspect(bridge.reference(1))['title'],'Наруто')
                native.assert_called_once_with('https://ru.novelcool.com/novel/Наруто.html')
            self.assertIsNone(bridge.indexed_reader(bridge.reference(1,4)))
            with closing(sqlite3.connect(path)) as db,db:db.execute('UPDATE titles SET metadata=?',(json.dumps({'url':bridge.reference(1),'sourceUrl':'https://evil.example/novel/Наруто.html'}),))
            self.assertIsNone(bridge.indexed_reader(bridge.reference(1)))
    def test_mangadex_extension_failure_uses_same_uuid_and_language_native_adapter(self):
        uuid='6b1eb93e-473a-4ab3-9922-1a66d2a29a4a'
        class Fake:
            def close(self):pass
            def get(self,path,*a,**kw):
                if path=='/manga/1':return {'title':'Наруто','realUrl':'https://mangadex.org/title/'+uuid+'/naruto','source':{'id':'2','lang':'ru','name':'MangaDex'}}
                raise SourceError('HTTP 500')
        with patch.object(bridge,'Client',Fake),patch('manga_sources.inspect',return_value={'episodes':[],'available':False}) as native:
            self.assertFalse(bridge.inspect(bridge.reference(1))['available'])
            native.assert_called_once_with('https://mangadex.org/title/'+uuid+'?lang=ru')
        Fake.get=lambda *a,**kw: {'title':'Other','realUrl':'https://untrusted.example/title/'+uuid,'source':{'id':'2','lang':'ru','name':'MangaDex'}} if a[1]=='/manga/1' else (_ for _ in ()).throw(SourceError('HTTP 500'))
        with patch.object(bridge,'Client',Fake),patch('manga_sources.inspect') as native:
            with self.assertRaises(SourceError):bridge.inspect(bridge.reference(1))
            native.assert_not_called()

    def test_error_classification_is_bounded_and_never_returns_upstream_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            auth=Path(directory)/'auth';auth.write_text(json.dumps({'username':'fixture','password':'fixture-private'}))
            with patch.dict(os.environ,{'SUWAYOMI_AUTH_FILE':str(auth)}),patch('suwayomi_bridge.requests.Session') as session:
                response=session.return_value.get.return_value;response.status_code=500
                response.iter_content.return_value=iter([b'CEF is disabled private-provider-cookie=secret'])
                client=bridge.Client()
                with self.assertRaisesRegex(SourceError,'WebView') as failure:client.get('/source/list')
                self.assertNotIn('secret',str(failure.exception))
                response.close.assert_called_once();client.close()
    def test_identifiers_are_not_an_open_proxy(self):
        good='https://media.example/__manga/suwayomi/m/1/c/4/p/0'
        self.assertEqual(bridge.parse_reference(good),(1,4,0))
        for url in [good+'?url=http://127.0.0.1',good.replace('media.example','evil.example'),good.replace('https:','http:'),good.replace('/m/1','/m/0'),good.replace('/c/4','/c/0'),good.replace('/p/0','/p/-1'),good.replace('/p/0','/p/10000')]:self.assertIsNone(bridge.parse_reference(url))
        with patch.dict(os.environ,{'SUWAYOMI_URL':''}):self.assertIsNone(bridge.parse_reference(good))
    def test_chapter_number_is_not_the_source_index(self):
        class Fake:
            def close(self):pass
            def get(self,path,*a,**kw):
                if path=='/manga/1':return {'id':1,'title':'One Piece','source':{'id':'8448310129093543312','lang':'en','name':'MangaPill'}}
                if path.endswith('/chapters'):return [{'index':4,'chapterNumber':0,'name':'Volume 2 Chapter 0','scanlator':'Team'},{'index':5,'chapterNumber':12.5,'name':'Extra'}]
                if path.endswith('/chapter/4'):return {'pageCount':2}
                raise AssertionError(path)
        with patch.object(bridge,'Client',Fake):
            data=bridge.inspect(bridge.reference(1));self.assertEqual([x['number'] for x in data['episodes']],[12.5,0]);self.assertEqual(data['episodes'][1]['url'],bridge.reference(1,4));self.assertEqual(data['episodes'][1]['season'],2)
            data=bridge.inspect(bridge.reference(1,4));self.assertEqual(len(data['pages']),2);self.assertEqual(bridge.parse_reference(data['pages'][0]),(1,4,0))
            with self.assertRaises(SourceError):bridge.inspect(bridge.reference(1,999))
    def test_install_only_catalogued_packages(self):
        with patch.object(bridge,'extensions',return_value=[]),patch.object(bridge,'Client') as client:
            for name in ['../../etc/passwd','eu.kanade.tachiyomi.extension.en.unknown']:
                with self.assertRaises(SourceError):bridge.install(name)
            client.assert_not_called()
    def test_catalogued_mixed_case_package_installs_without_changing_its_id(self):
        package='eu.kanade.tachiyomi.extension.all.vinnieVeritas'
        row={'pkgName':package,'name':'Vinne Veritas - CCC','installed':False}
        with patch.object(bridge,'extensions',return_value=[row]),patch.object(bridge,'Client') as client:
            self.assertTrue(bridge.install(package)['installed'])
            client.return_value.get.assert_called_once_with('/extension/install/'+package,timeout=90)
            client.return_value.close.assert_called_once()
        with patch.object(bridge,'extensions',return_value=[]),patch.object(bridge,'Client') as client:
            with self.assertRaises(SourceError):bridge.install(package)
            client.assert_not_called()
    def test_source_search_requires_exact_title(self):
        class Fake:
            def close(self):pass
            def get(self,*a,**kw):return {'mangaList':[{'id':1,'title':'One Piece'},{'id':2,'title':'Unrelated Adventure'}]}
        with patch.object(bridge,'sources',return_value=[{'id':'8448310129093543312','lang':'en','name':'MangaPill'}]),patch.object(bridge,'Client',Fake):
            result=bridge.search({'kind':'manga','title':'One Piece','aliases':['ワンピース']},'en');self.assertEqual([x['title'] for x in result['results']],['One Piece']);self.assertIn('8448310129093543312',result['results'][0]['provider'])
    def test_every_installed_source_is_reachable_after_the_old_first_32(self):
        contacted=[]
        class Fake:
            def close(self):pass
            def get(self,path,*a,**kw):contacted.append(path);return {'mangaList':[{'id':int(path.split('/')[2]),'title':'One Piece'}]}
        sources=[{'id':str(9000000000000000000+i),'lang':'en','name':f'Source {i:03}'} for i in range(65)]
        offset=0;found=[]
        with patch.object(bridge,'sources',return_value=sources),patch.object(bridge,'Client',Fake):
            while True:
                result=bridge.search({'kind':'manga','title':'One Piece'},'en',offset=offset)
                self.assertLessEqual(result['window']['checked'],8);found.extend(result['results']);offset=result['window']['nextOffset']
                if not result['window']['hasMore']:break
        self.assertEqual(len(contacted),65);self.assertEqual(len({r['provider'] for r in found}),65);self.assertEqual(offset,65)
    def test_supported_catalog_keeps_multilingual_packages_and_excludes_other_languages(self):
        rows=[{'pkgName':lang,'name':lang,'lang':lang} for lang in ['ru','en','ja','ko','all','fr']]
        with patch.object(bridge,'extensions',return_value=rows):
            self.assertEqual({r['language'] for r in bridge.extension_catalog()['extensions']},{'ru','en','ja','ko','all'})
            self.assertEqual({r['language'] for r in bridge.extension_catalog('ja')['extensions']},{'ja','all'})
    def test_chapter_cbz_fetches_images_privately(self):
        from manga_download import download_chapter
        from PIL import Image
        buffer=io.BytesIO();Image.new('RGB',(16,16),'white').save(buffer,'PNG');raw=buffer.getvalue()
        class Http:
            def download(self,*a,**kw):raise AssertionError('Must not HTTP-fetch an identifier URL')
        with tempfile.TemporaryDirectory() as directory,patch.object(bridge,'inspect',return_value={'url':bridge.reference(1,4),'pages':[bridge.reference(1,4,0)]}),patch.object(bridge,'page_image',return_value=(raw,'image/png')):
            result=download_chapter(bridge.reference(1,4),directory,Http())
            with zipfile.ZipFile(result) as z:self.assertEqual(z.read('0001.png'),raw)

    def test_online_capability_uses_private_image_fetch(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import online_sessions as online
        online.sessions.clear();app=FastAPI();online.install(app,lambda:'owner')
        token,session=online.create('owner',{},'manga');key=session.resource(bridge.reference(1,4,0))
        with patch.object(bridge,'page_image',return_value=(b'image bytes','image/jpeg')) as image,patch('online_sessions.PublicHttp._open') as public:
            result=TestClient(app).get('/online/'+token+'/'+key)
        self.assertEqual(result.status_code,200);self.assertEqual(result.content,b'image bytes');self.assertEqual(result.headers['content-type'],'image/jpeg');public.assert_not_called();image.assert_called_once()
        self.assertEqual(TestClient(app).get('/online/'+token+'/unknown').status_code,410)
    def test_internal_client_never_follows_redirects_or_accepts_arbitrary_hosts(self):
        with patch.dict(os.environ,{'SUWAYOMI_URL':'http://evil.example:4567'}):
            with self.assertRaises(SourceError):bridge.Client()
        with tempfile.TemporaryDirectory() as directory:
            auth=Path(directory)/'auth';auth.write_text(json.dumps({'username':'test','password':'fixture-private'}))
            with patch.dict(os.environ,{'SUWAYOMI_AUTH_FILE':str(auth)}),patch('suwayomi_bridge.requests.Session') as session:
                client=bridge.Client();session.return_value.get.return_value.status_code=302
                with self.assertRaises(SourceError):client.get('/source/list')
                self.assertFalse(session.return_value.get.call_args.kwargs['allow_redirects']);self.assertFalse(session.return_value.trust_env)
                client.close()
