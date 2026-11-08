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

    def run_discover(self,kind):
        with patch.object(kinobox_source,'PublicHttp',lambda **_:Http()):
            return kinobox_source.discover({'title':'Во все тяжкие','kind':kind,'ids':{'imdb':'tt0903747'}})

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


if __name__=='__main__':unittest.main()
