"""Offline tests for the static 18-domain manga taxonomy action."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('manga_snapshot', ROOT / 'scripts' / 'sync-manga-tags.py')
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class SnapshotTests(unittest.TestCase):
    def test_exact_requested_sources(self):
        self.assertEqual(len(snapshot.SOURCES),18)
        self.assertEqual(len({row[0] for row in snapshot.SOURCES}),18)

    def test_lib_group_taxonomy_is_extracted_not_invented(self):
        payload = {'data':{'genres':[{'id':1,'name':'Фэнтези'}, {'name':{'ru':'Романтика','en':'Romance'}}],
                           'tags':[{'name':'Приключения'}]}}
        rows, complete=snapshot.parse_lib_taxonomy(json.dumps(payload).encode())
        self.assertTrue(complete)
        self.assertIn(('genre','Романтика'),rows)
        self.assertIn(('genre','Romance'),rows)
        self.assertIn(('tag','Приключения'),rows)
        empty, complete=snapshot.parse_lib_taxonomy(b'{"data":{"other":[]}}')
        self.assertEqual(empty,[])
        self.assertFalse(complete)

    def test_html_tags_require_taxonomy_links(self):
        html = b'''<main><a href="/manga/sample">Not tag</a>
          <a href="/tags/fantasy">Fantasy</a>
          <a href="/genre/romance">Romance</a>
          <a href="https://unknown.example/tags/bad">Bad</a>
          <a href="/tags/fantasy">Fantasy</a></main>'''
        rows=snapshot.parse_html_taxonomy(html,'https://manga-chan.me/catalog',{'manga-chan.me'})
        self.assertEqual(rows,[('tag','Fantasy'),('genre','Romance')])

    def test_disallow_explicit_minor_sexual_categories(self):
        self.assertEqual(snapshot.clean('lolicon'),'')
        self.assertEqual(snapshot.clean('shotacon'),'')
        self.assertEqual(snapshot.clean('underage'),'')
        self.assertEqual(snapshot.clean('школа'),'школа')

    def test_host_rejects_non_https_and_credentials(self):
        self.assertIsNone(snapshot.host('http://manga-chan.me/'))
        self.assertIsNone(snapshot.host('https://user:password@manga-chan.me/'))
        self.assertEqual(snapshot.host('https://manga-chan.me/catalog'),'manga-chan.me')

    def test_build_preserves_source_provenance_and_staleness(self):
        original = [('tag','Фэнтези'),('genre','Romance')]
        with patch.object(snapshot, 'source_tags', return_value=(original,'partial','one_public_catalogue_page')):
            data=snapshot.build(object(), now='2026-11-13T00:00:00Z',pause=0)
        self.assertEqual(len(data['sources']),18)
        self.assertTrue(data['tags'])
        key=next(v for v in data['tags'] if v['key']=='фэнтези')
        self.assertEqual(key['category'],'tag')
        self.assertEqual(len(key['sources']),17)  # closed site excluded
        self.assertFalse(data['coverageGuaranteed'])
        old={'sources':data['sources'],'tags':data['tags']}
        with patch.object(snapshot,'source_tags',return_value=([],'unavailable','temporary_failure')):
            next_run=snapshot.build(object(),old,now='2026-11-14T00:00:00Z',pause=0)
        self.assertEqual(len(next_run['tags']),len(data['tags']))
        self.assertEqual(next_run['sources'][0]['status'],'stale')
        self.assertEqual(next_run['sources'][-1]['status'],'closed')

    def test_empty_or_rejected_url_is_not_saved_as_taxonomy(self):
        with patch.object(snapshot,'source_tags',return_value=([('tag','lolicon')], 'partial','test')):
            data=snapshot.build(object(),now='2026-11-13T00:00:00Z',pause=0)
        self.assertEqual(data['tags'],[])
        self.assertEqual(data['sources'][0]['tagsFound'],0)


if __name__ == '__main__':
    unittest.main()
