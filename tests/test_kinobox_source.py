"""Kinobox balancer answer captured on 2026-11-08 (tokens scrubbed) + real Collaps page."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import kinobox_source
from source_parser import PublicHttp, SourceError
FIXTURES=Path(__file__).parent/'fixtures'/'players'


class Http(PublicHttp):
    def document(self,value,*,headers=None,**_):
        if value.startswith('https://fbphdplay.top/api/players?imdb=tt0903747'):return (FIXTURES/'kinobox_breaking_bad.json').read_text(encoding='utf-8'),value,'application/json'
        if value.startswith('https://api.nextembed.ws/embed/movie/255'):return (FIXTURES/'collaps_serial.html').read_text(encoding='utf-8'),value,'text/html'
        raise SourceError('offline fixture')


class KinoboxTests(unittest.TestCase):
    def setUp(self):kinobox_source._cache.clear()

    def run_discover(self,kind,alloha=True):
        import alloha_profiles
        with patch.object(kinobox_source,'PublicHttp',lambda **_:Http()),patch.object(alloha_profiles,'playback_available',lambda *a:alloha):
            return kinobox_source.discover({'title':'Во все тяжкие','kind':kind,'ids':{'imdb':'tt0903747'}})

    def test_collaps_comes_first_and_alloha_does_not_depend_on_browser_profiles(self):
        value=self.run_discover('tv')
        self.assertTrue(value['sources'][0]['providerName'].startswith('Collaps'))
        kinobox_source._cache.clear()
        movie=self.run_discover('movie',alloha=False)
        self.assertTrue(any(s['providerName'].startswith('Alloha') for s in movie['sources']))

    def test_profile_state_file_decides_availability(self):
        import json,tempfile,time,alloha_profiles
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'active.json').write_text(json.dumps({'id':'a'}));(root/'candidates.json').write_text(json.dumps({'id':'b'}))
            (root/'health.json').write_text(json.dumps({'a':{'successes':18,'retired':True},'b':{'successes':3,'quarantine_until':time.time()+600}}))
            self.assertFalse(alloha_profiles.playback_available(root))
            (root/'health.json').write_text(json.dumps({'a':{'successes':18,'retired':True}}))
            self.assertTrue(alloha_profiles.playback_available(root),'a new candidate without history is usable')
        self.assertTrue(alloha_profiles.playback_available(Path(folder)/'missing'),'unknown state lets playback try')

    def test_serial_uses_collaps_dubs_including_lostfilm_and_ukrainian(self):
        value=self.run_discover('tv')
        self.assertEqual(value['status'],'ok')
        collaps=next(s for s in value['sources'] if s['providerName'].startswith('Collaps'))
        dubs={d['name']:d['language'] for d in collaps['dubs']}
        self.assertIn('LostFilm',dubs);self.assertEqual(dubs['AMC (укр)'],'uk')
        self.assertIn('Veoveo',value['message']);self.assertIn('Alloha',value['message'])  # offline here → reported, not guessed

    def test_movie_alloha_translations_are_listed_without_fetching(self):
        value=self.run_discover('movie')
        alloha=next(s for s in value['sources'] if s['providerName'].startswith('Alloha'))
        names={d['name']:d['language'] for d in alloha['dubs']}
        self.assertEqual(names['Украинский'],'uk');self.assertIn('LostFilm',names)

    def test_without_ids_nothing_is_requested(self):
        self.assertEqual(kinobox_source.discover({'title':'X','kind':'movie','ids':{}})['status'],'no_match')

    # Search answer captured 2026-11-09 for «Тетрадь смерти» (18 hits: the
    # anime, live-action films, the 2015 drama, the anime film recap …).
    def anime(self,**card):
        search=(FIXTURES/'kinobox_search_death_note.json').read_text(encoding='utf-8');asked=[]
        class SearchHttp(PublicHttp):
            def document(self,value,**_):
                asked.append(value)
                if value.startswith(kinobox_source.SEARCH):return search,value,'application/json'
                raise SourceError('offline fixture')
        base={'title':'Тетрадь смерти','titles':{'en':'Death Note','ja':'デスノート'},'year':2006,'format':'TV','kind':'anime','ids':{'mal':'1535'}}
        return kinobox_source.anime_kinopoisk({**base,**card},SearchHttp()),asked

    def test_anime_card_gets_the_kinopoisk_id_only_for_the_anime_series(self):
        found,asked=self.anime()
        self.assertEqual(found,'406148')
        self.assertEqual(len(asked),1,'the Russian title already matched')
        self.assertIsNone(self.anime(format='Movie')[0],'no anime film of 2006 has this title')
        self.assertIsNone(self.anime(year=2015)[0],'the 2015 series is live action')
        self.assertIsNone(self.anime(year=None)[0])
        self.assertIsNone(self.anime(title='Совсем другое',titles={})[0])

    def test_two_matching_hits_mean_no_id(self):
        import json
        data=json.loads((FIXTURES/'kinobox_search_death_note.json').read_text(encoding='utf-8'))
        twin=dict(next(r for r in data['data']['items'] if r['id']==406148),id=999)
        data['data']['items'].append(twin)
        class SearchHttp(PublicHttp):
            def document(self,value,**_):return json.dumps(data),value,'application/json'
        self.assertIsNone(kinobox_source.anime_kinopoisk({'title':'Тетрадь смерти','year':2006,'format':'TV','kind':'anime'},SearchHttp()))

    def test_anime_discovery_asks_the_balancer_with_the_matched_id(self):
        import alloha_profiles
        search=(FIXTURES/'kinobox_search_death_note.json').read_text(encoding='utf-8');asked=[]
        class Both(PublicHttp):
            def document(self,value,**_):
                asked.append(value)
                if value.startswith(kinobox_source.SEARCH):return search,value,'application/json'
                if value.startswith(kinobox_source.API):return '{"data":[]}',value,'application/json'
                raise SourceError('offline fixture')
        with patch.object(kinobox_source,'PublicHttp',lambda **_:Both()),patch.object(alloha_profiles,'playback_available',lambda *a:True):
            value=kinobox_source.discover({'title':'Тетрадь смерти','year':2006,'format':'TV','kind':'anime','ids':{'mal':'1535'}})
        self.assertIn(kinobox_source.API+'?kinopoisk=406148',asked)
        self.assertEqual(value['status'],'no_match')


if __name__=='__main__':unittest.main()
