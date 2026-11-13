"""ReManga JSON adapter, Suwayomi filter vocabulary and their catalogue routes."""
import json,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from source_parser import SourceError,public_url
import manga_remanga
from manga_tag_policy import canonical_json
from manga_catalog_index import initialize,upsert,browse
import content_catalog
import suwayomi_bridge
import catalogue_sources
from catalogue_indexer import Indexer
import manga_discovery

TITLE={'id':7,'dir':'neutral_story','main_name':'Нейтральная история','secondary_name':'Neutral Story','another_name':'Story of Nobody / 中立',
       'type':{'name':'Манхва'},'issue_year':2020,'cover':{'mid':'/media/titles/neutral/cover.jpg'},'count_chapters':3,
       'genres':[{'id':1,'name':'Драма'}],'categories':[{'id':2,'name':'Магия'}],'is_erotic':False,'is_yaoi':False,
       'branches':[{'id':10,'count_chapters':1,'publishers':[{'name':'Small team'}]},{'id':11,'count_chapters':3,'publishers':[{'name':'Big team'}]}]}


class Api:
    """Answers only the documented public endpoints, like the real API host."""
    def __init__(self):self.calls=[]
    def close(self):pass
    def document(self,url,**kw):
        public_url(url,resolve_dns=False)
        self.calls.append(url);parts=urlsplit(url);query=parse_qs(parts.query)
        if parts.path=='/api/v2/search/':body={'results':[TITLE,{'id':8,'main_name':''}]}
        elif parts.path=='/api/v2/titles/neutral_story/':body=TITLE
        elif parts.path=='/api/v2/titles/chapters/' and query['branch_id']==['11']:
            body={'next':2 if query['page']==['1'] else None,'results':[
                {'id':101,'chapter':'1','tome':1,'name':'Начало','is_paid':False,'is_published':True},
                {'id':102,'chapter':'2','tome':1,'name':'','is_paid':True,'is_published':True}] if query['page']==['1'] else [
                {'id':103,'chapter':'2.5','tome':2,'name':'','is_paid':False,'is_published':True}]}
        elif parts.path=='/api/v2/titles/chapters/' and query['branch_id']==['10']:
            body={'next':None,'results':[{'id':201,'chapter':'1','tome':1,'name':'','is_paid':False}]}
        elif parts.path=='/api/v2/titles/chapters/101/':
            body={'is_paid':False,'pages':[[{'link':'https://img.example.org/1_a.jpg'},{'link':'https://img.example.org/1_b.jpg'}],[{'link':'https://img.example.org/2.webp'}],[{'link':'https://img.example.org/2.webp'}]]}
        elif parts.path=='/api/v2/titles/chapters/102/':body={'is_paid':True,'is_bought':False,'pages':[]}
        elif parts.path=='/api/forms/titles/':body={'content':{'genres':[{'id':1,'name':'Драма'}],'categories':[{'id':2,'name':'Магия'},{'name':'Без id'}]}}
        elif parts.path=='/api/v2/search/catalog/':body={'next':None,'results':[TITLE]}
        else:raise AssertionError('Unexpected request '+url)
        return json.dumps(body,ensure_ascii=False),url,{}


class ReMangaTests(unittest.TestCase):
    def test_search_maps_public_card_without_inventing_fields(self):
        rows=manga_remanga.search('Нейтральная',Api())
        self.assertEqual(len(rows),1,'a card without a name is skipped')
        row=rows[0]
        self.assertEqual((row['title'],row['format'],row['year'],row['url']),('Нейтральная история','manhwa',2020,'https://remanga.org/manga/neutral_story'))
        self.assertEqual(row['aliases'],['Нейтральная история','Neutral Story','Story of Nobody','中立'])
        self.assertEqual(row['cover'],'https://api.remanga.org/media/titles/neutral/cover.jpg')
        self.assertEqual((row['genres'],row['tags'],row['adult']),(['Драма'],['Магия'],False))

    def test_chapters_follow_every_branch_and_skip_paid_ones(self):
        value=manga_remanga.inspect('https://remanga.org/manga/neutral_story',Api())
        self.assertEqual([(e['season'],e['number'],e['translator']) for e in value['episodes']],[(1,1,'Big team'),(1,1,'Small team'),(2,2.5,'Big team')])
        self.assertNotIn('/ch102',json.dumps(value['episodes']),'a paid chapter is never offered')
        self.assertEqual(value['translations'],['Big team','Small team']);self.assertEqual(value['pages'],[])

    def test_chapter_pages_keep_split_pieces_in_order(self):
        value=manga_remanga.inspect('https://remanga.org/manga/neutral_story/ch101',Api())
        self.assertEqual(value['pages'],['https://img.example.org/1_a.jpg','https://img.example.org/1_b.jpg','https://img.example.org/2.webp'])
        with self.assertRaisesRegex(SourceError,'платная'):manga_remanga.inspect('https://remanga.org/manga/neutral_story/ch102',Api())

    def test_only_documented_api_paths_are_allowed(self):
        for path in ['/api/v2/search/','/api/v2/titles/chapters/5/','/api/v2/titles/a%3Cb%3E_/','/media/titles/x/y.jpg']:
            public_url('https://api.remanga.org'+path,resolve_dns=False)
        for path in ['/api/v2/users/current/','/api/v2/titles/chapters/5/buy/']:
            with self.subTest(path=path),self.assertRaises(SourceError):public_url('https://api.remanga.org'+path,resolve_dns=False)

    def test_catalogue_vocabulary_and_filtered_page(self):
        terms=manga_remanga.vocabulary(Api())
        self.assertEqual(terms,[{'label':'Драма','category':'genre','sourceId':1},{'label':'Магия','category':'tag','sourceId':2}])
        api=Api();page=manga_remanga.catalogue_page(1,api,category=2)
        self.assertEqual(len(page['rows']),1);self.assertIsNone(page['next'])
        self.assertIn('categories=2',api.calls[0])


class Client:
    def __init__(self,filters=None,pages=None):self.filters=filters or [];self.pages=pages or {};self.calls=[]
    def get(self,path,params=None,timeout=12,body=None):
        self.calls.append((path,params,body))
        if path.endswith('/filters'):return self.filters
        return self.pages[path]
    def close(self):pass


FILTERS=[{'type':'Select','filter':{'name':'Сортировать по','values':['A','B']}},
         {'type':'Group','filter':{'name':'Жанры','state':[{'type':'TriState','filter':{'name':'Драма'}},{'type':'Text','filter':{'name':'От 1988'}}]}},
         {'type':'Group','filter':{'name':'Тэги','state':[{'type':'CheckBox','filter':{'name':'Магия'}}]}},
         {'type':'Group','filter':{'name':'Статус выхода','state':[{'type':'TriState','filter':{'name':'Завершён'}}]}}]


class BridgeTagTests(unittest.TestCase):
    def test_vocabulary_takes_only_subject_groups_with_their_filter_path(self):
        terms=suwayomi_bridge.filter_vocabulary(Client(FILTERS),'42')
        self.assertEqual(terms,[{'label':'Драма','category':'genre','sourceId':{'position':1,'child':0,'kind':'TriState'}},
                                {'label':'Магия','category':'tag','sourceId':{'position':2,'child':0,'kind':'CheckBox'}}])

    def test_filtered_page_is_a_stateless_single_filter_search(self):
        client=Client(pages={'/source/42/quick-search':{'mangaList':[],'hasNextPage':False}})
        suwayomi_bridge.filtered_page(client,'42',{'label':'Драма','sourceId':{'position':1,'child':0,'kind':'TriState'}},3)
        path,params,body=client.calls[0]
        self.assertEqual((path,params),('/source/42/quick-search',{'pageNum':3}))
        self.assertEqual(body,{'searchTerm':'','filter':[{'position':1,'state':json.dumps({'position':0,'state':'1'})}]})
        with self.assertRaises(SourceError):suwayomi_bridge.filtered_page(client,'42',{'sourceId':{'position':-1,'child':0,'kind':'TriState'}},1)

    def test_post_is_limited_to_the_quick_search_path(self):
        client=suwayomi_bridge.Client.__new__(suwayomi_bridge.Client)
        with self.assertRaises(SourceError):client.get('/source/42/preferences',body={'position':0,'value':'x'})


class CrawlerRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();policy=Path(self.temp.name)/'manga-tag-policy.json'
        policy.write_bytes(canonical_json({'schemaVersion':1,'includeDiscovered':True,'hiddenTags':[],'excludedTerms':[],'excludedPrefixes':[],'tags':[]}))
        self.env=patch.dict(os.environ,{'DATA_DIR':self.temp.name,'MANGA_TAG_POLICY_FILE':str(policy),'MEDIA_VAULT_DISABLE_WORKER':'1'});self.env.start()
        self.db=sqlite3.connect(':memory:',check_same_thread=False);initialize(self.db);content_catalog.initialize(self.db)
        self.store=SimpleNamespace(db=self.db,lock=threading.RLock())
    def tearDown(self):self.db.close();self.env.stop();self.temp.cleanup()

    def test_extension_tags_become_vocabulary_and_prioritized_filter_routes(self):
        source={'id':'42','name':'Fixture','lang':'ru','baseUrl':'https://fixture.example','isNsfw':True}
        manga={'id':5,'title':'Отмеченная история','url':'/api/v1/manga/5','thumbnailUrl':'','sourceId':'42'}
        client=Client(FILTERS,{'/source/42/quick-search':{'mangaList':[manga],'hasNextPage':False}})
        def fetch(spec,cursor):
            with patch('suwayomi_bridge.Client',return_value=client),patch.dict(os.environ,{'PUBLIC_URL':'https://vault.example'}):
                return catalogue_sources.fetch(spec,cursor)
        worker=Indexer(self.store,fetch,lambda:1000,interval=0)
        spec={'type':'bridge','domain':'fixture.example','name':'Fixture · ru','source':source}
        with self.store.lock,self.db:worker.enqueue({**spec,'type':'bridge-vocabulary'},30)
        self.assertTrue(worker.run_once())
        targets={label:json.loads(target) for _,label,target in self.db.execute('SELECT source,label,target FROM catalogue_tag_targets')}
        self.assertEqual(set(targets),{'Драма','Магия'})
        self.assertEqual(targets['Драма']['type'],'bridge');self.assertEqual(targets['Драма']['term']['sourceId'],{'position':1,'child':0,'kind':'TriState'})
        worker.prioritize(['Драма'])
        job=self.db.execute("SELECT spec,priority FROM catalogue_jobs WHERE json_extract(spec,'$.term.label')='Драма'").fetchone()
        self.assertEqual(job[1],80)
        self.db.execute("DELETE FROM catalogue_jobs WHERE kind!='bridge'");self.db.commit()
        self.assertTrue(worker.run_once())
        found=browse(self.db,genre='Драма')['items']
        self.assertEqual([r['title'] for r in found],['Отмеченная история'],'a filtered listing labels its titles')
        detail=json.loads(self.db.execute("SELECT spec FROM catalogue_jobs WHERE kind='bridge-detail'").fetchone()[0])
        self.assertNotIn('term',detail)

    def test_remanga_replaces_the_captcha_html_listing(self):
        from manga_source_coverage import SOURCES
        jobs={j['domain']:j for j in catalogue_sources.base_sources([])}
        self.assertEqual(jobs['remanga.org'],{'type':'remanga','domain':'remanga.org','name':'ReManga'})
        with patch('source_parser.PublicHttp',return_value=Api()):
            self.assertEqual(len(catalogue_sources.fetch({'type':'remanga-vocabulary','domain':'remanga.org','name':'ReManga'},{'page':1})['vocabulary']),2)
            result=catalogue_sources.fetch({'type':'remanga','domain':'remanga.org','name':'ReManga','term':{'label':'Драма','category':'genre','sourceId':1}},{'page':1})
        self.assertEqual(result['rows'][0]['provider'],'remanga')

    def test_search_falls_back_to_the_crawled_catalogue_when_an_extension_requires_sign_in(self):
        upsert(self.db,[{'provider':'suwayomi:42','sourceId':'42','kind':'manga','title':'Отмеченная история','aliases':['Отмеченная история'],
                         'url':'https://vault.example/__manga/suwayomi/m/5','sourceUrl':'https://fixture.example/m/5','language':'ru'}],source_id='42');self.db.commit()
        manager=SimpleNamespace(db=self.db,lock=threading.RLock())
        class Failing:
            def get(self,*a,**k):raise suwayomi_bridge.BridgeError('upstream','Ошибка источника (HTTP 500).')
            def close(self):pass
        with patch('manga_discovery.manager',return_value=manager),patch('suwayomi_bridge.Client',return_value=Failing()),patch('suwayomi_bridge.origin_block',return_value=None):
            rows=manga_discovery.search_source({'id':'42','name':'Fixture','lang':'ru','baseUrl':'https://fixture.example'},'Отмеченная')
        self.assertEqual([r['title'] for r in rows],['Отмеченная история'])


class DomainOverrideTests(unittest.TestCase):
    def test_moved_extension_domain_is_restored_and_others_untouched(self):
        posts=[]
        class Response:status_code=200
        class Session:
            def post(self,url,json=None,**kw):posts.append((url,json));return Response()
        class Prefs:
            root='http://suwayomi:4567';session=Session()
            def __init__(self,value):self.value=value
            def get(self,path,params=None,timeout=12):
                return [{'type':'ListPreference','props':{'key':'other'}},{'type':'EditTextPreference','props':{'key':'overrideBaseUrl','currentValue':self.value}}]
        installed=[{'id':'6384784374922886076','name':'Nude-Moon','lang':'ru'},{'id':'7','name':'MangaChan','lang':'ru'}]
        self.assertEqual(suwayomi_bridge.apply_domain_overrides(Prefs('https://nude-moon.org'),installed),[('Nude-Moon','https://g.nude-moon.fun')])
        self.assertEqual(posts,[('http://suwayomi:4567/api/v1/source/6384784374922886076/preferences',{'position':1,'value':'https://g.nude-moon.fun'})])
        posts.clear()
        self.assertEqual(suwayomi_bridge.apply_domain_overrides(Prefs('https://g.nude-moon.fun'),installed),[])
        self.assertEqual(posts,[],'an already correct domain is not rewritten')


if __name__=='__main__':unittest.main()
