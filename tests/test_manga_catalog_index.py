"""Persistent metadata and tag search use neutral fixture records only."""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'server'))
from manga_catalog_index import initialize, upsert, browse, tags, stats, title
from manga_source_tags import from_api, from_html


class CatalogIndexTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        initialize(self.db)

    def tearDown(self):
        self.db.close()

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
        self.assertEqual(browse(self.db,tag='fantasy')['total'],1)
        self.assertEqual(browse(self.db,tag='фэнтези')['total'],1)
        self.assertEqual(browse(self.db,tag='романтика',format='manhwa')['total'],1)
        self.assertEqual(browse(self.db,tag='романтика',format='manga')['total'],0)
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
        self.assertIn('Приключения',item['tags'])
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
        self.assertEqual(browse(self.db,tag='фэнтези')['total'],2)
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
        filters=dict(q='garden world',tag='FANTASY,romance',genre='DRAMA',format='Манхва',language='ru',
                     source_ids=[row['sourceId']],year='2024',age='adult')
        result=browse(self.db,**filters)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['url'],row['url'])
        self.assertEqual(result['items'][0]['sourceUrl'],row['sourceUrl'])
        for key,value in [('tag','fantasy,horror'),('genre','fantasy'),('language','en'),('year','2023'),
                          ('source_ids',['1']),('age','under18')]:
            self.assertEqual(browse(self.db,**{**filters,key:value})['total'],0,key)

    def test_exact_title_and_alias_rank_ahead_of_newer_partial_names(self):
        upsert(self.db,[{**self.work(slug='exact'),'aliases':['Garden World']}],timestamp=1)
        upsert(self.db,[{**self.work(title_name='Garden World: Another Story',slug='sequel'),'aliases':[]}],timestamp=2)
        self.assertEqual(browse(self.db,q='Garden World')['items'][0]['title'],'Садовый мир')
        self.assertEqual(browse(self.db,q='Садовый мир')['items'][0]['title'],'Садовый мир')

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
