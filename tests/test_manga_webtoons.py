import sys
import unittest
import tempfile
import zipfile
import base64
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import manga_sources as sources
import manga_webtoons as web
from source_parser import SourceError
from manga_download import download_chapter

TITLE = 'https://www.webtoons.com/en/fantasy/demo/list?title_no=95'
CHAPTER = 'https://www.webtoons.com/en/fantasy/demo/season-1-ep-0/viewer?title_no=95&episode_no=1'


class Http:
    def __init__(self, text, final=None):
        self.text, self.final = text, final
    def document(self, url):
        return self.text, self.final or url, {}


class WebtoonSources(unittest.TestCase):
    def setUp(self):
        self.site = sources.site_for(TITLE)

    def test_host_and_public_api_boundary(self):
        self.assertEqual(self.site.id, 'webtoons')
        for url in ['https://www.webtoons.com.evil.example/en/fantasy/demo/list?title_no=95',
                    'https://www.webtoons.com/en/member/login?title_no=95',
                    'https://www.webtoons.com/ko/fantasy/demo/list?title_no=95',
                    TITLE.replace('95', '-1')]:
            with self.subTest(url=url), self.assertRaises(SourceError):
                web.reader_url(url)
        for url in ['https://m.webtoons.com/api/v1/member/profile',
                    'https://m.webtoons.com/api/v1/webtoon/../episodes',
                    'https://127.0.0.1/api/v1/webtoon/95/episodes']:
            with self.subTest(url=url), self.assertRaises(SourceError):
                web.public_api(url)

    def test_search_retains_only_english_title_links_and_deduplicates_cards(self):
        card = '<li><a href="' + TITLE + '"><span class="title">Demo</span><img src="/cover.jpg"></a></li>'
        html = '<ul class="webtoon_list">' + card * 2 + '<li><a href="https://evil.example/a"><b class="title">Demo</b></a></li></ul>'
        rows = web.search('Demo', self.site, Http(html))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['language'], rows[0]['readingMode']), ('en', 'scroll'))
        self.assertEqual(rows[0]['cover'], 'https://www.webtoons.com/cover.jpg')

    def test_seasons_zero_and_decimal_chapters_are_distinct_and_locked_rows_are_skipped(self):
        rows = []
        for i, title in enumerate(['[Season 1] Ep. 0', '[Season 1] Ep. 2.5', '[Season 2] Ep. 0']):
            rows.append({'episodeNo': i + 1, 'episodeTitle': title,
                         'viewerLink': CHAPTER.replace('episode_no=1', 'episode_no=' + str(i + 1))})
        rows += [{**rows[0], 'isPaid': True}, {**rows[0], 'viewerLink': CHAPTER.replace('title_no=95', 'title_no=96')}]
        with patch('manga_webtoons.get_episodes', return_value=rows):
            result = sources.inspect(TITLE, Http('<h1 class="subj">Demo</h1>'))
        self.assertEqual([(v['season'], v['number']) for v in result['episodes']], [(1, 0), (1, 2.5), (2, 0)])
        self.assertEqual(result['seasons'], [{'number': 1, 'name': 'Том 1'}, {'number': 2, 'name': 'Том 2'}])

    def test_chapter_reads_only_reader_images_in_original_order(self):
        html = '<h1 class="subj">Demo</h1><span class="subj_episode">[Season 1] Ep. 0</span><img src="/advert.jpg"><div id="_imageList"><img data-url="https://cdn.example/2.jpg"><img data-url="https://cdn.example/1.jpg"><img data-url="https://cdn.example/1.jpg"></div>'
        with patch('manga_webtoons.get_episodes') as api:
            result = sources.inspect(CHAPTER, Http(html))
        api.assert_not_called()
        self.assertEqual(result['pages'], ['https://cdn.example/2.jpg', 'https://cdn.example/1.jpg'])
        self.assertEqual(result['episodes'][0]['number'], 0)
        self.assertEqual(result['readingMode'], 'scroll')

    def test_closed_chapters_and_login_redirects_fail_without_guessing_images(self):
        for http in [Http('<img src="/cover.jpg">'), Http('<div id="_imageList"><img data-url="/secret.jpg"></div>', 'https://www.webtoons.com/member/login')]:
            with self.assertRaises(SourceError):
                sources.inspect(CHAPTER, http)

    def test_import_uses_the_same_verified_reader_pages_as_online_viewing(self):
        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a+kkAAAAASUVORK5CYII=')
        downloads = []
        class ReaderHttp(Http):
            def download(self, url, path, **kwargs):
                downloads.append((url, kwargs.get('headers', {}).get('Referer')))
                Path(path).write_bytes(image)
        html = '<h1 class="subj">Demo</h1><div id="_imageList"><img data-url="https://cdn.example/2.png"><img data-url="https://cdn.example/1.png"></div>'
        with tempfile.TemporaryDirectory() as directory:
            path = download_chapter(CHAPTER, directory, ReaderHttp(html))
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ['0001.png', '0002.png'])
                self.assertEqual(archive.read('0002.png'), image)
        self.assertEqual(downloads, [('https://cdn.example/2.png', CHAPTER), ('https://cdn.example/1.png', CHAPTER)])


if __name__ == '__main__':
    unittest.main()
