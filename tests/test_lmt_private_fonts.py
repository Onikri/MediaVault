# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owner-only private fonts: file selection and the authenticated routes."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))


class PrivateFonts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fonts = self.root / 'reader-fonts'
        fonts.mkdir()
        (fonts / 'B Smash.TTF').write_bytes(b'two')
        (fonts / 'a-kunkel.otf').write_bytes(b'one')
        (fonts / 'notes.txt').write_bytes(b'not a font')
        (fonts / 'huge.woff2').write_bytes(b'x' * 4_000_001)
        (fonts / 'folder.otf').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_only_bounded_font_files_are_listed_in_stable_order(self):
        from lmt_runtime import private_fonts
        self.assertEqual([p.name for p in private_fonts(self.root)], ['B Smash.TTF', 'a-kunkel.otf'])
        self.assertEqual(private_fonts(self.root / 'missing'), [])

    def test_routes_require_the_owner_and_return_the_bytes(self):
        try:
            from fastapi.testclient import TestClient
            import lmt_service
        except Exception as error:  # optional service dependencies
            self.skipTest(str(error))
        previous = os.environ.get('LMT_DATA_DIR')
        os.environ['LMT_DATA_DIR'] = str(self.root)
        try:
            client = TestClient(lmt_service.app)
            self.assertEqual(client.get('/reader/lmt/fonts').status_code, 401)
            self.assertEqual(client.get('/reader/lmt/fonts/0').status_code, 401)
            lmt_service.app.dependency_overrides[lmt_service.owner] = lambda: 'owner'
            listing = client.get('/reader/lmt/fonts').json()['fonts']
            self.assertEqual([f['name'] for f in listing], ['B Smash.TTF', 'a-kunkel.otf'])
            self.assertEqual(listing[1]['bytes'], 3)
            self.assertEqual(len(listing[0]['sha256']), 64)
            response = client.get('/reader/lmt/fonts/1')
            self.assertEqual(response.content, b'one')
            self.assertIn('private', response.headers['cache-control'])
            self.assertEqual(client.get('/reader/lmt/fonts/2').status_code, 404)
        finally:
            lmt_service.app.dependency_overrides.clear()
            if previous is None:
                os.environ.pop('LMT_DATA_DIR', None)
            else:
                os.environ['LMT_DATA_DIR'] = previous


if __name__ == '__main__':
    unittest.main()
