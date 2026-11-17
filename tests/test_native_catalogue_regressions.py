"""Catalogue failures seen after the direct sources went live (2026-11-17)."""

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import manga_masonry
import manga_native_registry
import manga_native_sources
import manga_senkuro_native
from source_parser import SourceError, SourceRedirectError, public_url


def adapter(name):
    return next(item for item in manga_native_registry.profiles().values() if item.NAME == name)


class NativeCatalogueRegressionTests(TestCase):
    def test_masonry_newest_listing_is_one_page_and_vocabulary_follows_it(self):
        source = manga_masonry.SOURCES[0]
        seen = []
        html = '''<div class="list-gallery"><figure><a href="/demo-gallery/" title="Gallery">
        <img src="/small.jpg"></a></figure></div><div id="filter-a"><span><input value="blonde">
        <label>Blonde</label></span></div>'''

        def document(url, **_options):
            seen.append(url)
            return html, url, {}

        http = Mock(document=Mock(side_effect=document))
        rows, more = source.catalogue(http, sort='updated')
        self.assertEqual(([row['title'] for row in rows], more), (['Gallery'], False))
        self.assertEqual(source.catalogue(http, page=2, sort='updated'), ([], False))
        self.assertEqual(source.vocabulary(http), [{'label': 'Blonde', 'sourceId': 'blonde', 'category': 'tag'}])
        self.assertEqual(seen, [source.ROOT + '/sort/newest/'] * 2)

    def test_masonry_index_walks_archive_and_stops_on_an_empty_page(self):
        source = manga_masonry.SOURCES[0]
        pager = '<ul class="pagination-a"><li class="next"><a href="/archive/page/2/">Next</a></li></ul>'
        full = '<div class="list-gallery"><figure><a href="/demo-gallery/" title="Gallery"></a></figure></div>'
        pages = {source.ROOT + '/archive/': full + pager, source.ROOT + '/archive/page/2/': pager}
        http = Mock(document=Mock(side_effect=lambda url, **_options: (pages[url], url, {})))
        with patch.object(manga_native_sources, 'PublicHttp', return_value=http):
            first = manga_native_sources.catalogue_job(source, {'type': 'bridge'}, 1)
            last = manga_native_sources.catalogue_job(source, {'type': 'bridge'}, 2)
        self.assertEqual((len(first['rows']), first['next']), (1, {'page': 2}))
        self.assertEqual((last['rows'], last['next']), ([], None))
        pages = {source.ROOT + '/archive/': pager, source.ROOT + '/sort/newest/': full}
        rows, more = source.catalogue(http, page=1, sort=source.index_sort)
        self.assertEqual(([row['title'] for row in rows], more), (['Gallery'], False))

    def test_vocabulary_job_for_adapter_without_vocabulary_is_empty(self):
        bare = SimpleNamespace(NAME='Bare', ROOT='https://example.com')
        result = manga_native_sources.catalogue_job(bare, {'type': 'bridge-vocabulary'}, 1)
        self.assertEqual(result, {'rows': [], 'next': None, 'vocabulary': []})

    def test_zazamanga_vocabulary_avoids_the_plain_http_redirect(self):
        source = adapter('Zazamanga')
        seen = []

        def document(url, **_options):
            seen.append(url)
            return '<div class="genres"><a href="/manga-genre/action/">Action</a></div>', url, {}

        source.vocabulary(Mock(document=Mock(side_effect=document)))
        self.assertEqual(seen, [source.ROOT + '/manga'])

    def test_hentaikisu_redirect_past_last_page_ends_catalogue(self):
        source = adapter('HentaiKisu')

        def redirected(url, **_options):
            public_url(url, resolve_dns=False)
            raise SourceRedirectError('Некорректное перенаправление источника.')

        http = Mock(document=Mock(side_effect=redirected), deadline=None)
        self.assertEqual(source.catalogue(http, page=11), ([], False))
        with self.assertRaises(SourceRedirectError):
            source.catalogue(http, page=1)

    def test_senkuro_accepts_long_slugs_and_skips_malformed_rows(self):
        source = adapter('Senkuro')
        slug = 'game-kaishi-mae-ni-shinu-' + 'mobu-akuyaku-ouji-' * 13
        self.assertGreater(len(slug), 200)
        rows = [{'id': 'TUFOR0E6MjQ5', 'slug': slug, 'titles': [{'lang': 'RU', 'content': 'Тёмный Клинок'}]},
                {'id': 'TUFOR0E6MjQ6', 'slug': 'broken'}]
        reply = json.dumps({'data': {manga_senkuro_native.KEY['search']: {'mangas': rows}}})
        http = Mock(document=Mock(return_value=(reply, 'https://api.senkuro.com/graphql', {})), deadline=None)
        records, more = source.catalogue(http)
        self.assertEqual(([record['title'] for record in records], more), (['Тёмный Клинок'], False))
        self.assertIn(slug, records[0]['url'])
        reply = json.dumps({'data': {manga_senkuro_native.KEY['search']: {'mangas': rows[1:]}}})
        http.document.return_value = (reply, 'https://api.senkuro.com/graphql', {})
        with self.assertRaises(SourceError):
            source.catalogue(http)
