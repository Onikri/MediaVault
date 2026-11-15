from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image

import manga_dbmultiverse as dbm
import manga_globalcomix as gc
import manga_mangatoon as mt
import manga_saymanhwa as say
from manga_native_sources import saved_reader_url
from manga_page_media import fetch_page, page_reference
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


class PublisherAdapterTests(TestCase):
    def setUp(self):
        self.http = Mock(deadline=None)
        for pace in (gc.PACE, mt.PACE, say.PACE):
            setting = patch.object(pace, 'interval', 0)
            setting.start()
            self.addCleanup(setting.stop)

    def test_globalcomix_translation_filter_and_locked_release(self):
        source = next(profile for profile in gc.SOURCES if profile.LANGUAGE == 'ko')
        work = {'id': 12, 'name': 'A story', 'slug': 'story', 'artist': {'roman_name': 'Writer'}, 'category_name': 'Adventure'}
        chapters = [{'key': 'gated', 'chapter': '1', 'premium_only': 1},
                    {'key': 'available', 'chapter': '1.5', 'lang_id': 'kr'}]
        pages = [{'desktop_image_url': 'https://cdn.example/a.png'}, {'desktop_image_url': 'https://cdn.example/b.png'}]

        def get(_http, path, args=()):
            if path == '/comics':
                self.assertEqual(args['lang_id[]'], 'kr')
                return {'results': [work], 'pagination': {'total_pages': 2}}
            if path == '/read/story':
                return {'results': work}
            if path == '/comics/12/releases':
                self.assertEqual(args['lang_id'], 'kr')
                return {'results': chapters}
            self.assertEqual(path, '/readV2/available')
            return {'results': {'key': 'available', 'page_objects': pages}}

        with patch.object(gc, 'get', side_effect=get):
            results, more = source.catalogue(self.http, query='A story')
            self.assertTrue(more)
            self.assertEqual(results[0]['authors'], ['Writer'])
            saved = Mock()
            saved.get.return_value = [{'index': 2, 'url': 'available'}]
            link = saved_reader_url(source, saved, {'baseUrl': source.ROOT}, results[0]['url'], 1, 2)
            info = source.inspect(link, self.http)
            self.assertEqual(info['episodes'][0]['number'], 1.5)
            self.assertEqual(info['pages'], [page['desktop_image_url'] for page in pages])
            with self.assertRaises(SourceAccessError):
                source.inspect(link.replace('/available', '/gated'), self.http)
            pages[0]['is_page_paid'] = True
            with self.assertRaises(SourceAccessError):
                source.inspect(link, self.http)

    def test_globalcomix_headers_stay_on_the_public_api(self):
        client = PublicHttp(session=Mock(), validate=lambda url: public_url(url, resolve_dns=False, allow_api=True))
        target = 'https://api.globalcomix.com/v1/comics?lang_id%5B%5D=kr&p=2'
        client.session.request.return_value = Mock(status_code=200)
        with patch.dict('os.environ', {'GLOBALCOMIX_CLIENT_ID': 'fixture-test-client'}):
            client._open(target, action='globalcomix-json')
            sent = client.session.request.call_args.kwargs['headers']
            self.assertEqual(sent['X-GC-Client'], 'fixture-test-client')
            self.assertNotIn('Cookie', sent)
            for url in ('https://api.globalcomix.com/v1/account', 'https://outside.example/v1/read/story'):
                with self.assertRaises(SourceError):
                    client._open(url, action='globalcomix-json')
            before = client.session.request.call_count
            client.session.request.return_value = Mock(status_code=302, headers={'Location': 'https://outside.example/'})
            with self.assertRaises(SourceError):
                client._open(target, action='globalcomix-json')
            self.assertEqual(client.session.request.call_count, before + 1)

    def test_dbmultiverse_reads_pages_lazily_and_renders_published_balloons(self):
        source = next(profile for profile in dbm.SOURCES if profile.LANGUAGE == 'en')
        home = '/en/read.html'
        chapter = '/en/chapters.html'
        page = '/en/page-0.html'
        catalogue = ('<section id="dbm-reads"><div class="dbm-read"><a href="chapters.html?comic=page">Read</a>'
                     '<h3>Story</h3><div>Summary</div></div></section>')
        toc = '<div class="cadrelect chapter"><a href="chapters.html?comic=page&chapter=1"><h4>Chapter</h4></a></div>'
        links = '<div class="pageslist"><a href="page-0.html">0</a><a href="other-1.html">Other</a></div>'
        image_ref = ('<div id="balloonsimg" style="background:url(/image.php?idp=1); transform:scale(1.25)">'
                     '<div class="balloon" style="left:4px; top:4px; width:80px">Story test!</div></div>')

        def read(url, **_):
            path = urlsplit(url).path
            if path == chapter:
                html = links if 'chapter' in parse_qs(urlsplit(url).query) else toc
            else:
                html = {home: catalogue, page: image_ref}[path]
            return html, url, {}

        self.http.document.side_effect = read
        card, = source.catalogue(self.http, query='story')[0]
        entry, = source.inspect(card['url'], self.http)['episodes']
        page_url, = source.inspect(entry['url'], self.http)['pages']
        self.assertNotIn('/image.php', page_url)
        self.assertNotIn(page, [urlsplit(call.args[0]).path for call in self.http.document.call_args_list])
        base = BytesIO()
        with Image.new('RGB', (110, 70), 'white') as canvas:
            canvas.save(base, 'PNG')
        response = Mock()
        response.iter_content.return_value = iter([base.getvalue()])
        self.http._open.return_value = response, source.ROOT + '/image.php?idp=1'
        raw, mime = fetch_page(self.http, page_reference(page_url), {})
        self.assertEqual(mime, 'image/jpeg')
        with Image.open(BytesIO(raw)) as image:
            self.assertEqual(image.size, (110, 70))
            self.assertLess(image.convert('L').getextrema()[0], 100)
        self.assertEqual(self.http._open.call_args.kwargs['headers']['Referer'], source.ROOT + page)

    def test_saymanhwa_locale_genres_and_vip_status(self):
        source = next(profile for profile in say.SOURCES if profile.LANGUAGE == 'pt')
        prefix = '/pt-br/series/'
        listing = ('<article class="series-card"><div class="series-card-body">'
                   '<h2><a href="' + prefix + 'story">Story</a></h2></div></article>')
        work = ('<h1>Story</h1><a href="/pt-br/genres/fantasy">Fantasy</a><div class="series-v72-chapter-list">'
                '<a class="series-v72-chapter-row" href="' + prefix + 'story/chapter-2-5">'
                '<span class="series-chapter-number-text">Chapter 2.5</span></a>'
                '<a class="series-v72-chapter-row" href="' + prefix + 'story/chapter-3">'
                '<span class="chapter-mini-lock"></span><span class="series-chapter-number-text">Chapter 3</span></a></div>')
        read = '<div class="reader-pages"><img src="/p1.png"><img data-src="/p2.png"></div>'

        def document(url, **_):
            path = urlsplit(url).path
            if path == prefix.rstrip('/'):
                self.assertEqual(parse_qs(urlsplit(url).query)['genre'], ['fantasy'])
                return listing, url, {}
            return (work if path.endswith('/story') else read), url, {}

        self.http.document.side_effect = document
        card, = source.catalogue(self.http, query='Story', tag='fantasy')[0]
        reader = source.inspect(card['url'], self.http)
        self.assertEqual(reader['genres'], ['Fantasy'])
        chapter, vip = reader['episodes']
        self.assertEqual(chapter['number'], 2.5)
        self.assertEqual(source.inspect(chapter['url'], self.http)['pages'], [source.ROOT + '/p1.png', source.ROOT + '/p2.png'])
        with self.assertRaises(SourceAccessError):
            source.inspect(vip['url'], self.http)

    def test_mangatoon_follows_title_redirect_and_filters_paid_episodes(self):
        source = next(profile for profile in mt.SOURCES if profile.LANGUAGE == 'pt-BR')
        title_url = mt.ROOT + '/pt/story?content_id=5'
        data = [{'id': 14, 'title': 'Chapter 1', 'weight': 1},
                {'id': 18, 'title': "Publisher's Chapter 2", 'weight': 2, 'is_fee': True}]
        js = json.dumps(data).replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
        title = '<h1 class="detail-title">Story</h1><script>data = JSON.parse(\'' + js + '\');</script>'
        read = '<div class="pictures"><div><img data-src="/p1.jpg"></div><div><img src="/p2.jpg"></div></div>'
        paths = []

        def document(url, **_):
            path = urlsplit(url).path
            paths.append(path)
            if path == '/pt/detail/5':
                return title, title_url, {}
            return read, url, {}

        self.http.document.side_effect = document
        info = source.inspect(title_url, self.http)
        part, = info['episodes']
        self.assertEqual(source.inspect(part['url'], self.http)['pages'], [source.ROOT + '/p1.jpg', source.ROOT + '/p2.jpg'])
        with self.assertRaises(SourceAccessError):
            source.inspect(part['url'].replace('/14', '/18'), self.http)
        self.assertNotIn('/pt/watch/5/18', paths)
