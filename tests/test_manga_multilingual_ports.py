from urllib.parse import parse_qs, urlsplit
from unittest import TestCase
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import manga_mangaball_native as ball
import manga_mangamillion as million
import mangaball_reader
from manga_foolslide import SOURCES as FOOLSLIDE
from manga_million_wire import Message
from manga_native_sources import saved_reader_url
from manga_page_media import fetch_page, page_reference
from source_parser import PublicHttp, SourceAccessError, SourceError, public_url


def varint(value):
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint((number << 3) | 2) + varint(len(value)) + value


def response(raw, **kwargs):
    result = Mock(status_code=200, headers=kwargs)
    result.iter_content.return_value = iter([raw])
    return result


class NativeProfileTests(TestCase):
    def setUp(self):
        self.http = Mock(deadline=None, timeout=(3, 8))
        for state in (million._tokens, million._catalogues, million._viewers, mangaball_reader._cache):
            state.clear()
            self.addCleanup(state.clear)
        rate = patch.object(million.PACE, 'interval', 0)
        rate.start()
        self.addCleanup(rate.stop)

    def test_million_reads_guest_protobuf_shared_catalogue_and_chapter_images(self):
        fi = next(source for source in million.SOURCES if source.LANGUAGE == 'fi')
        ca = next(source for source in million.SOURCES if source.LANGUAGE == 'ca')
        a = field(1, 123) + field(3, 'Story') + field(7, 600)
        b = field(1, 987) + field(3, 'Other') + field(7, 999)
        rows = field(1, field(1, a) + field(2, 'fi')) + field(1, field(1, b) + field(2, 'ca'))
        unlocked = field(1, '#5-2') + field(2, 'Chapter') + field(3, 84)
        locked = field(1, '#5-3') + field(2, 'Unavailable')
        key, iv = bytes(range(16)), bytes(range(16, 32))
        pages = field(1, field(1, 'https://cdn.example/p1.avif')) + field(7, key.hex()) + field(8, iv.hex())
        image = b'\x00\x00\x00\x20ftypavif' + b'test-image'
        padder = padding.PKCS7(128).padder()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        encrypted = cipher.update(padder.update(image) + padder.finalize()) + cipher.finalize()
        calls = []
        outcomes = {
            'register': field(170, field(1, 'guest-credential')),
            'manga_list': field(22, rows),
            'search': field(20, rows),
            'chapter_list': field(60, field(2, field(2, unlocked) + field(2, locked))),
            'title_detail': field(50, field(1, field(2, 'Story') + field(4, field(2, 'Fantasy')))),
            'viewer': field(70, pages),
        }

        def opened(url, **opts):
            parts = urlsplit(url)
            endpoint = parts.path.split('/')[-1]
            calls.append((endpoint, opts, parse_qs(parts.query)))
            if parts.hostname == 'cdn.example':
                self.assertNotIn('Access-Token', opts['headers'])
                return response(encrypted), url
            self.assertEqual(opts['headers']['Access-Token'], '' if endpoint == 'register' else 'guest-credential')
            return response(outcomes[endpoint]), url

        self.http._open.side_effect = opened
        card, = fi.catalogue(self.http)[0]
        self.assertEqual(ca.catalogue(self.http)[0][0]['title'], 'Other')
        self.assertEqual([call[0] for call in calls], ['register', 'manga_list'])
        self.assertEqual(fi.catalogue(self.http, query='Story', tag='tag:3')[0][0]['id'], card['id'])
        self.assertEqual(calls[-1][2]['translated_language'], ['fi'])
        self.assertEqual(calls[-1][2]['tag_id'], ['3'])
        toc = fi.inspect(card['url'], self.http)
        self.assertEqual(toc['genres'], ['Fantasy'])
        chapter, = toc['episodes']
        self.assertEqual(chapter['number'], 5.2)
        bridge = Mock()
        bridge.get.return_value = [{'index': 1, 'url': '84'}]
        self.assertEqual(saved_reader_url(fi, bridge, {'baseUrl': fi.ROOT}, fi.ROOT + '/123', 1, 1), chapter['url'])
        direct = fi.inspect(chapter['url'], self.http)
        page, = direct['pages']
        self.assertNotIn(key.hex(), page)
        self.assertNotIn('cdn.example', page)
        raw, mime = fetch_page(self.http, page_reference(page), {})
        self.assertEqual((raw, mime), (image, 'image/avif'))
        with self.assertRaises(SourceAccessError):
            fi.inspect(chapter['url'].replace('/84', '/85'), self.http)

    def test_million_refreshes_rejected_guest_token_once(self):
        initial = Message(field(170, field(1, 'first')))
        renewed = Message(field(170, field(1, 'second')))
        catalogue = Message(field(22, b''))
        with patch.object(million, 'fetch', side_effect=[initial, SourceAccessError('expired'), renewed, catalogue]) as fetch:
            result = million.request(self.http, 'manga_list', 'en')
        self.assertIs(result, catalogue)
        self.assertEqual([call.args[1] for call in fetch.call_args_list], ['register', 'manga_list', 'register', 'manga_list'])
        self.assertEqual(fetch.call_args.args[-1], 'second')
        for broken in (b'\x80', field(1, b'test')[:-1], b'\0'):
            with self.assertRaises(SourceError):
                Message(broken)

    def test_api_transport_scopes_binary_headers_and_foolslide_forms(self):
        client = PublicHttp(session=Mock(), validate=lambda url: public_url(url, resolve_dns=False))
        success = response(b'data')
        client.session.request.return_value = success
        endpoint = million.API + 'register?service_language=en'
        client._open(endpoint, action='mangamillion-proto', method='POST', data=b'')
        self.assertNotIn('Access-Token', client.session.request.call_args.kwargs['headers'])
        cat = million.API + 'manga_list?service_language=en&avif_enable=true'
        client._open(cat, action='mangamillion-proto', headers={'Access-Token': 'guest'})
        self.assertEqual(client.session.request.call_args.kwargs['headers']['Access-Token'], 'guest')
        with self.assertRaises(SourceError):
            client._open('https://outside.example/api/register?service_language=en',
                         action='mangamillion-proto', method='POST', data=b'')
        with self.assertRaises(SourceError):
            client._open(cat, action='mangamillion-proto', headers={'Access-Token': 'guest\nprivate'})
        client.session.request.return_value = Mock(status_code=302, headers={'Location': 'https://outside.example/'})
        before = client.session.request.call_count
        with self.assertRaises(SourceError):
            client._open(cat, action='mangamillion-proto', headers={'Access-Token': 'guest'})
        self.assertEqual(client.session.request.call_count, before+1)
        client.session.request.return_value = success
        search = FOOLSLIDE[0].ROOT + '/search/'
        client._open(search, method='POST', data={'search': 'Story'}, action='foolslide-form')
        self.assertEqual(client.session.request.call_args.kwargs['data'], {'search': 'Story'})
        with self.assertRaises(SourceError):
            client._open(search, method='POST', data={'adult': 'true'}, action='foolslide-form')

    def test_ball_preserves_locale_legacy_links_and_reserve_page(self):
        source = next(profile for profile in ball.SOURCES if profile.LANGUAGE == 'ko')
        title = '685183da0b95030249822109'
        chapter = '68dde53b1ec6dc083a2f8069'
        work = {'id': title, 'name': 'Sample', 'slug': 'sample', 'tags': [{'name': 'Fantasy'}, {'name': 'Long Strip'}],
                'image': {'cover': {'path': 'sample\\1.jpg'}}}
        entry = {'id': chapter, 'title_id': title, 'lang': 'kr', 'name': 'Chapter', 'number': 1,
                 'pages': ['https://cdn.example/01.webp', 'https://cdn.example/02.webp']}
        with (patch.object(ball, 'request', side_effect=[{'pagination': {'page': 1, 'total_pages': 2}, 'data': [work]},
                                                       {'data': work}, {'data': [entry, {**entry, 'lang': 'en'}]},
                                                       {'data': work}, {'data': work}]) as request,
              patch.object(mangaball_reader, 'chapter_data', return_value=entry),
              patch.object(mangaball_reader, 'reserve_image', return_value=(b'fixture', 'image/webp')) as reserve):
            cards, more = source.catalogue(self.http, query='Sample')
            self.assertTrue(more)
            self.assertEqual(request.call_args.kwargs['params']['chapterLanguage'], 'ko,kr')
            self.assertEqual(cards[0]['cover'], ball.COVER_BASE + 'sample/1.jpg')
            toc = source.inspect(cards[0]['url'], self.http)
            self.assertEqual(toc['genres'], ['Fantasy'])
            self.assertEqual(toc['tags'], ['Long Strip'])
            episode, = toc['episodes']
            bridge = Mock()
            bridge.get.return_value = [{'index': 1, 'url': chapter}]
            self.assertEqual(saved_reader_url(source, bridge, {'baseUrl': source.ROOT},
                             'https://mangaball.net/title-detail/' + title, 2, 1), episode['url'])
            value = source.inspect(episode['url'], self.http)
            other = episode['url'].replace(title, '685183da0b95030249822105')
            with self.assertRaises(SourceError):
                source.inspect(other, self.http)
            self.http._open.return_value = response(b'<html>unavailable</html>'), entry['pages'][1]
            self.assertEqual(fetch_page(self.http, page_reference(value['pages'][1]), {}), (b'fixture', 'image/webp'))
            reserve.assert_called_once_with(chapter, 1, title, expected=entry['pages'][1], http=self.http)
