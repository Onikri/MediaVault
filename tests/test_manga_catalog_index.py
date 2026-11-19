"""Persistent metadata and tag search use neutral fixture records only."""
import sqlite3
import sys
import unittest
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'server'))
from manga_catalog_index import initialize, upsert, browse, tags, stats, title
from manga_source_tags import from_api, from_html


class CatalogIndexTests(unittest.TestCase):
    def setUp(self):
        self.policy_env=patch.dict(os.environ,{'MANGA_TAG_POLICY_FILE':str(Path(__file__).parent/'fixtures/manga-tag-policy.json')});self.policy_env.start()
        self.db=sqlite3.connect(':memory:')
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.policy_env.stop()

    @staticmethod
    def work(provider='hmanga',title_name='Садовый мир',slug='garden-world'):
        return {
            'provider':provider, 'sourceId':'990000000000000003',
            'sourceUrl':'https://hmanga.me/manga/'+slug+'/',
            'url':'https://hmanga.me/manga/'+slug+'/',
            'title':title_name,'aliases':[title_name,'Garden World'],
            'kind':'manga','language':'ru','format':'manhwa','adult':True,
            'tags':['Фэнтези','Романтика'],'genres':['Драма'],
        }

    def test_upsert_and_search_tag_facets(self):
        row=self.work()
        self.assertEqual(upsert(self.db,[row]),1)
        self.assertEqual(upsert(self.db,[row]),1)
        self.assertEqual(stats(self.db)['totalTitles'],1)
        self.assertEqual(browse(self.db,q='garden')['total'],1)
        self.assertEqual(browse(self.db,genre='fantasy')['total'],1)
        self.assertEqual(browse(self.db,genre='фэнтези')['total'],1)
        self.assertEqual(browse(self.db,genre='романтика',format='manhwa')['total'],1)
        self.assertEqual(browse(self.db,genre='романтика',format='manga')['total'],0)
        self.assertEqual(tags(self.db)['tags'][0]['works'],1)

    def test_detail_preserved_after_search_without_tags(self):
        original=self.work()
        upsert(self.db,[original],timestamp=1)
        detail={**original,'title':'Садовый мир','tags':['Фэнтези','Романтика','Приключения'],
                'episodes':[{'season':1,'number':1},{'season':1,'number':1},
                            {'season':1,'number':1.5}],
                'pages':['https://cdn.example.org/private-image.jpg']}
        upsert(self.db,[detail],timestamp=2)
        search_result={**original,'tags':[],'genres':[],'aliases':['Garden World']}
        upsert(self.db,[search_result],timestamp=3)
        item=browse(self.db)['items'][0]
        self.assertEqual(item['chapterCount'],2)
        self.assertIn('Приключения',item['genres'])
        self.assertNotIn('pages',item)
        self.assertNotIn('episodes',item)
        self.assertEqual(item['tagStatus'],'present')
        self.assertEqual(title(self.db,item['catalogId'])['title'],'Садовый мир')

    def test_same_work_from_two_sources_keeps_separate_provenance(self):
        left=self.work()
        right=self.work('mangalib','Садовый мир')
        right['sourceUrl']='https://mangalib.me/ru/garden-world'
        upsert(self.db,[left,right])
        self.assertEqual(stats(self.db)['totalTitles'],2)
        self.assertEqual(browse(self.db,provider='hmanga')['total'],1)
        self.assertEqual(browse(self.db,genre='фэнтези')['total'],2)
        self.assertEqual(tags(self.db,source_id='990000000000000003')['tags'][0]['works'],2)

    def test_missing_taxonomy_is_not_invented_and_bad_url_ignored(self):
        row=self.work()
        row.pop('tags')
        row.pop('genres')
        upsert(self.db,[row])
        self.assertEqual(browse(self.db)['items'][0]['tagStatus'],'not_requested')
        self.assertEqual(tags(self.db)['tags'],[])
        row['sourceUrl']='http://127.0.0.1/private'
        row['url']=row['sourceUrl']
        self.assertEqual(upsert(self.db,[row]),0)
        self.assertEqual(stats(self.db)['totalTitles'],1)
        self.assertEqual(browse(self.db,q='%" OR 1=1 --')['total'],0)

    def test_libgroup_tags_from_title_details(self):
        from unittest.mock import patch
        from manga_catalog_adapters import inspect_catalog
        detail={'data':{'rus_name':'Garden World','genres':[{'name':'Фэнтези'}],
                        'tags':[{'name':'Romance'}]}}
        chapters={'data':[{'number':'1','volume':'1','branches':[{}]}]}
        with patch('manga_catalog_adapters.get',side_effect=[detail,chapters]):
            item=inspect_catalog('https://hentailib.me/ru/garden-world',None)
        self.assertEqual(item['genres'],['Фэнтези'])
        self.assertEqual(item['tags'],['Romance'])

    def test_taxonomy_from_structured_and_html_metadata(self):
        self.assertEqual(from_api({'genres':[{'name':'Фэнтези'}],
                                   'tags':[{'name':{'ru':'Романтика','en':'Romance'}}]}),
                         {'tags':['Романтика','Romance'],'genres':['Фэнтези']})
        html='<div class="manga-tags"><a href="/tag/fantasy">Fantasy</a></div>'
        self.assertEqual(from_html(html)['tags'],['Fantasy'])
        self.assertEqual(from_html('<a href="/manga/anything/">Not a tag</a>')['tags'],[])

    def test_combined_filters_require_each_fact_and_keep_reader_reference(self):
        row={**self.work(),'year':2024,'url':'https://media.example/__manga/suwayomi/m/42'}
        upsert(self.db,[row])
        filters=dict(q='garden world',genre='FANTASY,romance,DRAMA',format='Манхва',language='ru',
                     source_ids=[row['sourceId']],year='2024',age='adult')
        result=browse(self.db,**filters)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['url'],row['url'])
        self.assertEqual(result['items'][0]['sourceUrl'],row['sourceUrl'])
        for key,value in [('tag','unknown'),('genre','horror'),('language','en'),('year','2023'),
                          ('source_ids',['1']),('age','under18')]:
            self.assertEqual(browse(self.db,**{**filters,key:value})['total'],0,key)

    def test_exact_title_and_alias_rank_ahead_of_newer_partial_names(self):
        upsert(self.db,[{**self.work(slug='exact'),'aliases':['Garden World']}],timestamp=1)
        upsert(self.db,[{**self.work(title_name='Garden World: Another Story',slug='sequel'),'aliases':[]}],timestamp=2)
        self.assertEqual(browse(self.db,q='Garden World')['items'][0]['title'],'Садовый мир')
        self.assertEqual(browse(self.db,q='Садовый мир')['items'][0]['title'],'Садовый мир')

    def test_search_counts_groups_and_hydrates_only_matching_sources(self):
        first={**self.work(title_name='Garden',slug='first'),'aliases':['Green Garden'],'year':2020}
        matching={**self.work('mirror','Garden','matching'),'aliases':['Green Garden'],'year':2020}
        other={**self.work('other','Garden','other'),'aliases':['Blue Garden'],'year':2020}
        sequel={**self.work(title_name='Another Garden',slug='sequel'),'aliases':['Green Garden Story'],'year':2024}
        upsert(self.db,[first,matching,other,sequel])
        result=browse(self.db,q='Green Garden',limit=1)
        self.assertEqual((result['total'],result['workTotal'],result['works']),(3,2,1))
        self.assertEqual({row['provider'] for row in result['items']},{'hmanga','mirror'})
        beyond=browse(self.db,q='Green Garden',offset=130000,limit=1)
        self.assertEqual((beyond['total'],beyond['workTotal'],beyond['offset'],beyond['items']),(3,2,130000,[]))

    def test_release_status_filters_works_before_pagination(self):
        rows=[
            {**self.work(title_name='Published Garden',slug='published'), 'status':'Завершён'},
            {**self.work('other','Published Garden','published-mirror'), 'status':'Онгоинг'},
            {**self.work(title_name='Open Garden',slug='open'), 'status':'OnGoing'},
            {**self.work(title_name='Future Garden',slug='future'), 'status':'Анонс'},
            {**self.work(title_name='Unknown Garden',slug='unknown'), 'status':'Приостановлен'},
        ]
        upsert(self.db,rows)
        for state, title_name in [('released','Published Garden'),('ongoing','Open Garden'),('anons','Future Garden')]:
            with self.subTest(state=state):
                result=browse(self.db,q='Garden',status=state,limit=1)
                self.assertEqual(result['workTotal'],1)
                self.assertEqual({(row['title'],row['releaseStatus']) for row in result['items']},{(title_name,state)})
        self.assertEqual(browse(self.db,status='released')['total'],2)
        self.assertEqual(browse(self.db)['workTotal'],4)

    def test_catalogue_reads_the_committed_index_while_a_crawl_batch_is_writing(self):
        from manga_discovery import Discovery, catalogue_reader
        with TemporaryDirectory() as directory:
            store=Discovery(directory,start_workers=False)
            try:
                with store.lock,store.db:
                    upsert(store.db,[self.work(slug='committed')])
                with store.lock,store.db:
                    upsert(store.db,[self.work(title_name='Upcoming',slug='uncommitted')])
                    with catalogue_reader(store) as db:
                        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
                        self.assertEqual(browse(db)['workTotal'],1)
                with catalogue_reader(store) as db:
                    self.assertEqual(browse(db)['workTotal'],2)
            finally:
                store.close()

    def test_facet_query_filters_before_limit_and_metadata_check_is_cached(self):
        upsert(self.db,[{**self.work(),'tags':['Comedy','Time Travel'],'metadataInspected':True}])
        facet=tags(self.db,q='TRAVEL',limit=1)['tags']
        self.assertEqual(len(facet),1)
        self.assertEqual(facet[0]['original'],'Time Travel')
        self.assertTrue(browse(self.db)['items'][0]['metadataChecked'])
        self.assertIsNone(browse(self.db)['items'][0]['chapterCount'])

    def test_mangadex_genres_are_not_flattened_into_tags(self):
        facts=from_api({'tags':[{'attributes':{'name':{'en':'Drama'},'group':'genre'}},
                               {'attributes':{'name':{'en':'Time Travel'},'group':'theme'}}]})
        self.assertEqual(facts,{'genres':['Drama'],'tags':['Time Travel']})


if __name__=='__main__':
    unittest.main()
