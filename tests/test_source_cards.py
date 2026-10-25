from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from site_adapters import BY_ID,parse_search,search_site
from title_identity import match_title
from player_catalog import inspect_catalog
from source_parser import PublicHttp,public_url,SourceError,parse_page

class SourceCardTests(unittest.TestCase):
    def test_search_scope_excludes_sidebar_cards_and_uses_published_image_title(self):
        text='''<aside><div class="movie-item"><h2><a href="/1-other.html">Другое</a></h2></div></aside>
        <main><div id="dle-content"><a href="/7576-dandadan.html"><span>9.4 8.42</span>
        <img alt="Дандадан" src="/poster.jpg"><span>2024, экшен, комедия</span></a></div></main>'''
        result=parse_search(BY_ID['anixart'],text,'https://anixart.site/index.php','Дандадан')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['title'],'Дандадан')
        self.assertEqual(result[0]['year'],2024)
        self.assertTrue(match_title({'title':'Дандадан','kind':'anime','year':2024},result[0])[0])

    def test_source_year_comes_from_labelled_metadata_and_heading_not_description(self):
        class Http:
            def document(self,*args,**kwargs):raise AssertionError('No player URL is published by this fixture')
        value=inspect_catalog('https://anixart.site/7576-dandadan.html',
            '<title>Аниме онлайн</title><h1>Дандадан</h1><p>История началась в 1999 году.</p><ul><li>Год выхода: 2024</li></ul>',
            'https://anixart.site/7576-dandadan.html',Http(),provider='anixart')
        self.assertEqual(value['title'],'Дандадан');self.assertEqual(value['year'],2024)

    def test_fallback_keeps_explicit_title_attribute_above_rating_text(self):
        result=parse_search(BY_ID['animedia'],'<div id="dle-content"><a href="/4662-dandadan.html" title="Дандадан"><b>9.8</b></a></div>',
                            'https://amd.online/index.php','Дандадан')
        self.assertEqual(result[0]['title'],'Дандадан')

    def test_freeanime_uses_the_published_post_search_form(self):
        calls=[]
        class Http:
            def document(self,url,**kwargs):
                calls.append((url,kwargs));return '<main><a href="/12-dandadan.html" title="Дандадан">2024</a></main>',url,{}
        result=search_site(BY_ID['freeanime'],'Дандадан',http=Http())
        self.assertEqual(result['status'],'ok')
        self.assertEqual(calls,[('https://freeanime.ru/',{'method':'POST','data':{'do':'search','subaction':'search','story':'Дандадан'}})])

    def test_public_search_post_never_opens_login_or_arbitrary_forms(self):
        from unittest.mock import Mock
        import requests
        session=requests.Session();response=Mock(status_code=200,headers={});session.request=Mock(return_value=response)
        http=PublicHttp(session=session,validate=lambda u:public_url(u,resolve_dns=False))
        data={'do':'search','subaction':'search','story':'Дандадан'}
        http._open('https://freeanime.ru/',method='POST',data=data,headers={'Cookie':'private-fixture','Authorization':'Bearer fixture'})
        headers=session.request.call_args.kwargs['headers']
        self.assertNotIn('Cookie',headers);self.assertNotIn('Authorization',headers)
        for url,body in [('https://freeanime.ru/login',data),('https://other.example.com/',data),('https://freeanime.ru/',{**data,'login_password':'fixture'})]:
            with self.assertRaises(SourceError):http._open(url,method='POST',data=body)

    def test_escaped_iframe_switcher_preserves_public_player_and_selected_translation(self):
        text=r'''<script>const player = "<iframe src=\"https:\/\/public.stravers.live\/?token_movie=public-fixture\u0026translation=7\"></iframe>";</script>'''
        page=parse_page(text,'https://anixart.site/7576-dandadan.html')
        self.assertIn('https://public.stravers.live/?token_movie=public-fixture&translation=7',page.players)
        self.assertFalse(page.streams,'An iframe is never a downloadable media stream')
