"""Public API contracts use fixtures; actual Oracle/image/CBZ tests run separately."""
import copy,io,json,os,sys,tempfile,time,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import manga_novelcool as manga
import novelcool_client as client
from source_parser import SourceError,public_url

BOOK='https://ru.novelcool.com/novel/Наруто.html'
CHAPTER='https://ru.novelcool.com/chapter/1%20-%201/123/'
PIC='https://ruwebp.movietop.cc/comics/pic2/1/1.webp'
INFO={'id':'45','book_id':'45','lang':'ru','name':'Наруто','url':BOOK,'copyright_limit':False,'is_novel':'','publish_year':'1999'}
ROW={'id':'123','book_id':'45','lang':'ru','title':'1 - 1','order_id':'999','is_locked':False,'url':CHAPTER,'pic_list':[{'order_id':1,'pic_path':PIC.replace('1.webp','2.webp')},{'order_id':0,'pic_path':PIC}]}

class NativeApi(unittest.TestCase):
 def setUp(self):
  manga._books.clear();self.info=copy.deepcopy(INFO);self.row=copy.deepcopy(ROW)
 def request(self,operation,values,http):
  if operation=='book/search':return {'list':[{'id':'999','lang':'ru','name':'Наруто','url':BOOK.replace('Наруто','Другой')},self.info]}
  if operation=='book/info':return {'info':self.info}
  if operation=='chapter/book_list':return {'list':[self.row,{**self.row,'id':'124','title':'2 - 12.5 Экстра'},{**self.row,'id':'125','title':'72 Экстра Учиха Сарада','order_id':'72.0'}]}
  if operation=='chapter/info':return {'info':self.row}
  raise AssertionError(operation)
 def test_exact_title_and_printed_numbers_include_zero_decimals_and_extra(self):
  self.row.update(title='1 - 0',order_id='500')
  with patch.object(client,'request',side_effect=self.request):data=manga.inspect_api(BOOK,object())
  self.assertEqual(data['title'],'Наруто');self.assertEqual([(e['season'],e['number']) for e in data['episodes']],[(1,0),(2,12.5),(72,72)])
  self.assertEqual(manga.chapter_id(data['episodes'][0]['url']),'123')
 def test_chapter_uses_two_api_requests_and_sorts_images_without_any_html_or_device(self):
  http=MagicMock()
  with patch.object(client,'settings',return_value={'configured':True}),patch.object(client,'request',side_effect=self.request) as api:data=manga.inspect(CHAPTER,http)
  self.assertEqual(data['pages'],[PIC,PIC.replace('1.webp','2.webp')]);self.assertEqual(data['episodes'][0]['number'],1)
  self.assertEqual([x.args[0] for x in api.call_args_list],['chapter/info','book/info']);http.document.assert_not_called()
 def test_wrong_title_url_never_matches_an_alias_or_search_label(self):
  self.info['url']=BOOK.replace('Наруто','Фанфик')
  with patch.object(client,'request',side_effect=self.request),self.assertRaises(SourceError):manga.inspect_api(BOOK,object())
 def test_identity_language_locked_chapter_and_unapproved_images_are_rejected(self):
  for changes in [{'id':'124'},{'lang':'en'},{'is_locked':True},{'url':CHAPTER.replace('123','124')},{'book_id':'46'},{'pic_list':[{'order_id':0,'pic_path':'https://evil.example/a.webp'}]},{'pic_list':[{'order_id':0,'pic_path':'https://127.0.0.1/a.webp'}]},{'pic_list':[{'order_id':0,'pic_path':PIC}]*2}]:
   self.row={**copy.deepcopy(ROW),**changes}
   with patch.object(client,'request',side_effect=self.request),self.assertRaises(SourceError):manga.inspect_api(CHAPTER,object())
 def test_cbz_download_fetches_images_on_server_and_preserves_all_pages(self):
  from manga_download import download_chapter
  from PIL import Image
  buffer=io.BytesIO();Image.new('RGB',(2,3),'white').save(buffer,'PNG');raw=buffer.getvalue();urls=[]
  class Http:
   def download(self,url,target,**kwargs):urls.append(url);Path(target).write_bytes(raw)
  with tempfile.TemporaryDirectory() as directory,patch.object(client,'settings',return_value={'configured':True}),patch.object(client,'request',side_effect=self.request):
   path=download_chapter(CHAPTER,directory,Http())
   with zipfile.ZipFile(path) as archive:self.assertEqual(archive.namelist(),['0001.png','0002.png']);self.assertIsNone(archive.testzip())
  self.assertEqual(urls,[PIC,PIC.replace('1.webp','2.webp')])

class PublicClient(unittest.TestCase):
 def test_generic_source_api_restriction_is_not_relaxed(self):
  with self.assertRaises(SourceError):public_url('https://api.novelcool.com/chapter/info/',resolve_dns=False)
 def test_invalid_operation_identifier_and_search_rejected_before_network(self):
  with patch.object(client.requests,'Session') as session:
   for op,values in [('account/login',{}),('chapter/info',{'chapter_id':'../1'}),('book/search',{'keyword':'','page':1}),('book/info',{'book_id':'12','url':'https://evil.example'})]:
    with self.assertRaises(SourceError):client.request(op,values,object())
   session.assert_not_called()
 def test_http_contract_rejects_redirects_bad_json_oversize_and_expired_requests(self):
  def fetch(status,raw):
   response=MagicMock();response.__enter__.return_value=response;response.status_code=status;response.iter_content.return_value=[raw]
   session=MagicMock();session.__enter__.return_value=session;session.post.return_value=response
   return session
  for status,raw in [(302,b'{}'),(200,b'bad'),(200,json.dumps({'error_code':'denied'}).encode()),(200,b'x'*(client.MAX_DOCUMENT+1))]:
   with patch.object(client,'settings',return_value={'appId':'1','secret':'0'*32}),patch.object(client,'public_url',side_effect=lambda url,**kw:url),patch.object(client.requests,'Session',return_value=fetch(status,raw)),self.assertRaises(SourceError):client.request('book/info',{'book_id':'45'},object())
  session=fetch(200,b'{"error_code":"success","info":{}}')
  with patch.object(client,'settings',return_value={'appId':'1','secret':'0'*32}),patch.object(client,'public_url',side_effect=lambda url,**kw:url),patch.object(client.requests,'Session',return_value=session):
   self.assertEqual(client.request('book/info',{'book_id':'45'},object())['info'],{})
   args=session.post.call_args;self.assertFalse(args.kwargs['allow_redirects']);self.assertFalse(session.trust_env)
   with self.assertRaises(SourceError):client.request('book/info',{'book_id':'45'},SimpleNamespace(deadline=time.monotonic()-1))
 def test_setup_checksum_failure_never_writes_parameters(self):
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}):
   response=MagicMock();response.__enter__.return_value=response;response.content=b'modified upstream'
   session=MagicMock();session.__enter__.return_value=session;session.get.return_value=response
   with patch.object(client.requests,'Session',return_value=session),self.assertRaises(SourceError):client.install()
   self.assertFalse(client.settings_path().exists())
 def test_existing_server_configuration_survives_without_external_setup_request(self):
  with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'DATA_DIR':directory}):
   client.settings_path().write_text(json.dumps({'appId':'1','secret':'0'*32}))
   with patch.object(client.requests,'Session') as session:client.install();session.assert_not_called()

if __name__=='__main__':unittest.main()
