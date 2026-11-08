"""Russian ranobe sources: RanobeLib (LibGroup API), Jaomix, Rulate — offline.

Fixtures reproduce the markup and JSON seen live from the VM on 2026-11-08.
"""
import json, sys, unittest
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import ranobe_ru as ru
import ranobe_sources as rs
from source_parser import SourceError, public_url

LIB_SEARCH = {'data': [{'id': 6709, 'name': 'Youkoso Jitsuryoku Shijou Shugi no Kyoushitsu e', 'rus_name': 'Добро пожаловать в класс превосходства',
                        'eng_name': 'Classroom of the Elite', 'slug_url': '6709--youkoso-jitsuryoku-shijou-shugi-no-kyoushitsu-e-novel', 'cover': {'default': 'https://cover.imglib.info/c.jpg'}},
                       {'id': 1, 'rus_name': 'bad', 'slug_url': '../etc'}]}
LIB_DETAIL = {'data': {'rus_name': 'Добро пожаловать в класс превосходства', 'eng_name': 'Classroom of the Elite', 'name': 'Youkoso'}}
LIB_CHAPTERS = {'data': [
    {'volume': '1', 'number': '1', 'name': 'Добро пожаловать', 'branches': [{'branch_id': None, 'teams': [{'name': 'RanobeList'}]}]},
    {'volume': '1', 'number': '2', 'name': '', 'branches': [{'branch_id': 77, 'teams': [{'name': 'Team B'}]}]},
    {'volume': '1', 'number': '../x', 'name': 'broken'}]}
LIB_CHAPTER = {'data': {'name': 'Добро пожаловать', 'content': '<p data-paragraph-index="1">Вступление</p><p>— Аянокоджи-кун, ты в порядке?</p>'}}

JAOMIX_SEARCH = '''<div class="block-home"><div class="one"><div class="header-home"><div class="img-home"> <a href="https://jaomix.ru/klass/" title="добро пожаловать в класс превосходства"><img src="x.jpg"></a></div>
<div><a href="https://jaomix.ru/klass/"><div class="title-home">Добро пожаловать в <span>класс</span> превосходства</div></a></div></div>
<div class="info-p"><span class="title-p">Доп. название:</span> <span class="en-title-home">Classroom of the Elite</span></div></div>
<div class="one"><div class="img-home"><a href="https://evil.example/klass/" title="x"></a></div></div></div>'''
JAOMIX_BOOK = '''<h1>Добро пожаловать в класс превосходства</h1><select class="sel-toc"><option value="1">От Глава 3</option><option value="2">От Глава 1</option></select>
<div class="columns-toc"><div class="flex-dow-txt"><div class="title"><a href="https://jaomix.ru/klass/glava-3/" title="Том 1. Глава 3. Третья"><h2>x</h2></a></div></div></div>'''
JAOMIX_PAGES = {'1': '<div class="flex-dow-txt"><div class="title"><a href="https://jaomix.ru/klass/glava-3/" title="Том 1. Глава 3. Третья"></a></div></div>'
                     '<div class="flex-dow-txt"><div class="title"><a href="https://jaomix.ru/klass/glava-2/" title="Том 1. Глава 2. Вторая"></a></div></div>',
                '2': '<div class="flex-dow-txt"><div class="title"><a href="https://jaomix.ru/klass/glava-1/" title="Том 1. Глава 1. Первая"></a></div></div>'
                     '<div class="flex-dow-txt"><div class="title"><a href="https://jaomix.ru/other/glava-9/" title="Чужая книга"></a></div></div>'}
JAOMIX_CHAPTER = '''<h1>Том 1. Глава 1. Первая</h1><div class="entry-content entry"><div class="adblock-service">Реклама</div><p>Том 1. Глава 1. Первая</p>
<p>Джек никогда не чувствовал себя так хорошо.</p><p>«Ты шутишь, да?!»</p><script>ads()</script></div>'''

RULATE_SEARCH = '''<ul class='search-results'><li><p class='book-tooltip'><a href='/book/56392?bt_page=search'>Я действительно не Повелитель Демонов</a><br/><small>I Really Am Not The Lord of Demon</small></p></li>
<li><p><a href='/blog/1'>Не книга</a></p></li></ul>'''
RULATE_BOOK = '''<h1>I Really Am Not The Lord of Demon / Я действительно не Повелитель Демонов</h1><table id='Chapters'>
<tr><td><strong>Том 1</strong></td><td><a href='/book/56392/downloadVolume' class='btn btn-small btn-success'>скачать том</a></td></tr>
<tr data-id='1878156' class='chapter_row'><td class='t'><a href='/book/56392/1878156/ready_new'>Глава 1.1. Поздний клиент</a></td><td><a href='/book/56392/1878156/ready_new' class='btn btn-small btn-info'>читать</a></td></tr>
<tr data-id='1878157' class='chapter_row'><td class='t'><a href='/book/56392/1878157'>Глава 1.2. Платная</a></td><td><a href='/book/56392/1878157/buy' class='btn btn-small btn-warning'>купить</a></td></tr>
<tr><td><strong>Том 2</strong></td></tr>
<tr data-id='1878200' class='chapter_row'><td class='t'><a href='/book/56392/1878200/ready_new'>Глава 2.1. Утро</a></td><td><a href='/book/56392/1878200/ready_new' class='btn btn-small btn-info'>читать</a></td></tr></table>'''
RULATE_CHAPTER = '''<div id="text-container"><h1>Готовый перевод I Really Am Not / Я действительно не Повелитель Демонов: Глава 1.1. Поздний клиент</h1>
<div class="content-text"><p><p><span>Территория Федеративной Империи Дасяо.</span></p></p><p>Прибрежный промышленный город.</p></div></div>'''


class Http:
    def __init__(self): self.calls = []
    def document(self, url, *, headers=None, method='GET', data=None, action=None, **_):
        public_url(url, resolve_dns=False)
        self.calls.append((method, url, data, (headers or {}).get('Referer')))
        parts = urlsplit(url)
        if parts.hostname == 'jaomix.ru':
            if parts.path == '/wp-admin/admin-ajax.php':
                assert method == 'POST' and data['action'] == 'loadpagenavchapstt' and headers['Referer'] == 'https://jaomix.ru/klass/'
                return JAOMIX_PAGES[data['page']], url, {}
            if parts.query.startswith('searchrn='): return JAOMIX_SEARCH, url, {}
            if parts.path == '/klass/': return JAOMIX_BOOK, url, {}
            if parts.path == '/klass/glava-1/': return JAOMIX_CHAPTER, url, {}
        if parts.hostname == 'tl.rulate.ru':
            if parts.path == '/search': return RULATE_SEARCH, url, {}
            if parts.path == '/book/56392': return RULATE_BOOK, url, {}
            if parts.path == '/book/56392/1878156/ready_new': return RULATE_CHAPTER, url, {}
        raise SourceError('offline fixture ' + url)


class Lib(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.original = ru._lib
        def fake(path, http, params=None):
            self.requests.append((path, params))
            if path == '/api/manga': return LIB_SEARCH
            if path.endswith('/chapters'): return LIB_CHAPTERS
            if path.endswith('/chapter'): return LIB_CHAPTER
            return LIB_DETAIL
        ru._lib = fake

    def tearDown(self): ru._lib = self.original

    def test_search_book_and_chapter(self):
        found = list(ru.lib_search('класс превосходства', None))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['url'], 'https://ranobelib.me/ru/book/6709--youkoso-jitsuryoku-shijou-shugi-no-kyoushitsu-e-novel')
        self.assertIn('Classroom of the Elite', found[0]['aliases'])
        self.assertEqual(self.requests[0], ('/api/manga', {'q': 'класс превосходства', 'site_id[]': 3}))
        book = rs.inspect(found[0]['url'])
        self.assertEqual((book['provider'], book['providerName'], book['title']), ('ranobelib', 'RanobeLib', 'Добро пожаловать в класс превосходства'))
        self.assertEqual([c['number'] for c in book['episodes']], [1, 2])
        self.assertEqual(book['episodes'][0]['translator'], 'RanobeList')
        self.assertIn('mv_branch=77', book['episodes'][1]['url'])
        text = rs.chapter(book['episodes'][1]['url'])
        self.assertEqual(text['paragraphs'], ['Вступление', '— Аянокоджи-кун, ты в порядке?'])
        self.assertEqual(self.requests[-1][1], {'number': '2', 'volume': '1', 'branch_id': '77'})

    def test_routes_refuse_other_paths(self):
        with self.assertRaises(SourceError): ru.route('https://ranobelib.me/admin')
        with self.assertRaises(SourceError): ru.route('https://ranobelib.me/ru/book/x?mv_number=1;rm')
        self.assertIsNone(ru.route('http://ranobelib.me/ru/book/x'))
        self.assertIsNone(ru.route('https://ranobehub.org/ranobe/1'))


class Jaomix(unittest.TestCase):
    def test_search_book_pages_and_chapter(self):
        http = Http()
        found = list(ru.jaomix_search('класс превосходства', http))
        self.assertEqual([(r['title'], r['url']) for r in found], [('Добро пожаловать в класс превосходства', 'https://jaomix.ru/klass/')])
        self.assertEqual(found[0]['aliases'][1], 'Classroom of the Elite')
        book = rs.inspect('https://jaomix.ru/klass/', http)
        self.assertEqual([c['title'] for c in book['episodes']], ['Том 1. Глава 1. Первая', 'Том 1. Глава 2. Вторая', 'Том 1. Глава 3. Третья'])
        self.assertEqual([c['number'] for c in book['episodes']], [1, 2, 3])
        self.assertEqual(sum(1 for c in http.calls if c[0] == 'POST'), 2)
        text = rs.chapter('https://jaomix.ru/klass/glava-1/', http)
        self.assertEqual(text['paragraphs'], ['Джек никогда не чувствовал себя так хорошо.', '«Ты шутишь, да?!»'])

    def test_only_the_table_of_contents_post_is_allowed(self):
        from source_parser import PublicHttp
        client = PublicHttp(timeout=(1, 1))
        try:
            with self.assertRaises(SourceError):
                client.document('https://jaomix.ru/wp-admin/admin-ajax.php', method='POST', data={'action': 'delete_post', 'page': '1'})
        finally:
            client.close()


class Rulate(unittest.TestCase):
    def test_free_chapters_only_with_volumes(self):
        http = Http()
        found = list(ru.rulate_search('повелитель', http))
        self.assertEqual([(r['title'], r['url']) for r in found], [('Я действительно не Повелитель Демонов', 'https://tl.rulate.ru/book/56392')])
        book = rs.inspect('https://tl.rulate.ru/book/56392', http)
        self.assertEqual(book['title'], 'Я действительно не Повелитель Демонов')
        self.assertEqual([(c['season'], c['title']) for c in book['episodes']], [(1, 'Глава 1.1. Поздний клиент'), (2, 'Глава 2.1. Утро')])
        text = rs.chapter('https://tl.rulate.ru/book/56392/1878156/ready_new', http)
        self.assertEqual(text['title'], 'Глава 1.1. Поздний клиент')
        self.assertEqual(text['paragraphs'], ['Территория Федеративной Империи Дасяо.', 'Прибрежный промышленный город.'])


class Search(unittest.TestCase):
    def test_exact_titles_win_over_fan_fics_sharing_the_headline(self):
        original = dict(rs.SEARCH)
        rs.SEARCH['rulate'] = lambda query, http: iter([
            {'provider': 'rulate', 'providerName': 'Rulate', 'language': 'ru', 'title': t, 'aliases': [t], 'url': 'https://tl.rulate.ru/book/' + str(i)}
            for i, t in enumerate(['Класс превосходства: фанфик ' + str(n) for n in range(6)] + ['Класс превосходства'])])
        for other in ('ranobehub', 'ranobelib', 'jaomix'):
            rs.SEARCH[other] = lambda query, http: iter([])
        rs._cache.clear()
        try:
            value = rs.search({'title': 'Класс превосходства', 'kind': 'ranobe'}, 'ru')
        finally:
            rs.SEARCH.clear(); rs.SEARCH.update(original); rs._cache.clear()
        self.assertEqual([r['title'] for r in value['results']], ['Класс превосходства'])
        self.assertEqual([p['provider'] for p in value['providers']], ['ranobehub', 'ranobelib', 'jaomix', 'rulate'])


if __name__ == '__main__':
    unittest.main()
