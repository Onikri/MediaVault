"""GirlsTop's public model catalogue, galleries, and image links."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from bs4 import BeautifulSoup

from manga_madara import image_url, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://en.girlstop.info'
MODEL = '/models.php'
GALLERY = '/psto.php'
CHROME = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36')


def search_form(url, data):
    return (url == ROOT + MODEL and set(data) == {'text'} and isinstance(data['text'], str)
            and 1 <= len(data['text']) <= 160)


def key(url):
    parts = urlsplit(url)
    if parts.path not in (MODEL, GALLERY):
        return ''
    pairs = [(name, value) for name, value in parse_qsl(parts.query) if name not in {'page', 'mv_gallery', 'mv_model'}]
    if not 1 <= len(pairs) <= 5 or not all(re.fullmatch(r'\w{1,30}', name) and re.fullmatch(r'[\w.~+-]{1,160}', value)
                                          for name, value in pairs):
        return ''
    return parts.path + '?' + urlencode(sorted(pairs))


class GirlsTop(SeriesPort):
    cards = Cards('.thumbs .thumb', '.post_title a[href]', cover='picture img', next='li.next a[href]')
    meta = Meta('h1', '.tiles-wrap img', '.ps-desc:not(.ps-tags)', tags='.ps-tags a',
                author='.ps-desc a[href*="user.php"]')
    model = Meta('h1.index', '.model-cover img', '#modeldesc')

    def __init__(self):
        super().__init__(('1368670128695001652', 'GirlsTop', 'en', ROOT, True),
                         r'(/(?:models|psto)\.php)', r'(/psto\.php)', hosts=('girlstop.info', 'www.girlstop.info'), interval=.35)

    def is_title(self, url):
        return bool(key(url) and param(url, 'mv_gallery') != '1')

    def is_chapter(self, url):
        return bool(key(url) and super().is_chapter(url))

    def title_key(self, url):
        return key(url)

    def chapter_identity(self, url):
        return key(url)

    def title_for(self, url):
        model = param(url, 'mv_model')
        value = self.site_link(model, ROOT) if model.startswith(MODEL + '?') else self.site_link(ROOT + key(url))
        return value if self.is_title(value) else ''

    def saved_chapter_matches(self, target, title):
        if self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title):
            return True
        return self.is_chapter(target) and self.confirm_archive_membership(target, title)

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'User-Agent': CHROME})
        if not self.site_link(final):
            raise SourceError('GirlsTop перенаправил запрос на другой сайт.')
        return BeautifulSoup(raw, 'html.parser'), final

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page > 1:
                return [], False
            raw, final, _ = http.document(ROOT + MODEL, method='POST', data={'text': query},
                                          headers={'User-Agent': CHROME}, action='native-series-form')
            if final != ROOT + MODEL:
                raise SourceError('GirlsTop перенаправил поиск.')
            return self.card_rows(BeautifulSoup(raw, 'html.parser'), final, self.cards)
        rules = {'weekly': ('/filter.php', {'srt': 'viw'}), 'best': ('/filter.php', {'srt': 'pop'}),
                 'models': (MODEL, {'popular': ''}), 'new': ('/index.php', {'new': 'd'})}
        path, params = rules.get(tag, ('/index.php', {}) if sort == 'updated' else ('/filter.php', {'srt': 'viw'}))
        if page > 1:
            params = {**params, 'page': page - 1}
        return self.card_rows(*self.document(http, query_url(ROOT + path, **params)), self.cards)

    def metadata(self, doc, url, spec):
        model = urlsplit(url).path == MODEL
        row = super().metadata(doc, url, self.model if model else self.meta)
        row['title'] = re.sub(r' - nude galleries.*$', '', row['title'], flags=re.I) if model else row['title']
        row['status'] = 'ongoing' if model else 'completed'
        row['format'] = 'gallery'
        return row

    def chapters(self, http, doc, final):
        if urlsplit(final).path == GALLERY:
            return [self.chapter(query_url(final, mv_gallery=1), 'Gallery', 1)], False
        rows = {}
        visited = set()
        identity = key(final)
        for _ in range(80):
            if final in visited:
                break
            visited.add(final)
            for item in doc.select('.thumbs .thumb'):
                anchor = item.select_one('.post_title a[href]')
                path = self.site_link(anchor.get('href', ''), final) if anchor else ''
                if not self.is_chapter(path):
                    continue
                target = query_url(path, mv_gallery=1, mv_model=identity)
                date = node_text(item.select_one('tr:has(td:first-child:-soup-contains-own("Approved")) td:last-child'))
                stamp = release_date(date, '%d %b %Y')
                rows[target] = self.chapter(target, node_text(anchor), date=stamp)
            node = doc.select_one('li.next a[href]')
            if not node:
                return self.order(rows), False
            target = self.site_link(node['href'], final)
            if not target or key(target) != identity:
                raise SourceError('GirlsTop перенаправил на другую коллекцию.')
            doc, final = self.document(http, target)
        return self.order(rows), True

    def pages(self, http, url):
        value = ROOT + key(url)
        doc, final = self.page_document(http, value)
        return [src for a in doc.select('a.fullimg[href]') if (src := image_url(a['href'], final))]


SOURCES = (GirlsTop(),)
