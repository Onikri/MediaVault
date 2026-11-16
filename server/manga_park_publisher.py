"""Hakusensha Manga-Park's Japanese catalogue and public image format."""

import base64
import binascii
import re
from urllib.parse import urlsplit

from manga_madara import image_url, node_text, release_date
from manga_mangaplus import XorPage
from manga_series_port import Cards, Meta, SeriesPort, number
from manga_speedbinb import remember
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://manga-park.com'
ID = r'[1-9]\d{0,12}'
TITLE = rf'/title/({ID})/?'
CHAPTER = rf'/title/({ID})/chapter/({ID})/?'
DAYS = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'end'}
RANK = {'all', 'woman', 'man', 'adult'}


def public_api(host, path, query):
    return host == 'manga-park.com' and not query and bool(re.fullmatch(rf'/api/chapter/{ID}', path))


class MangaPark(SeriesPort):
    cards = Cards('div.list div.rankingHome ul.common-list li a[href], div.list div.series div.titles li a[href], '
                  'div.list div.search-result ul.common-list li a[href]', '', 'div.info h3', 'div.thumb > img', next='')
    meta = Meta('div.titleMain div.titleInfo h1', 'div.titleThumb img', 'p.explanation', '',
                'div.titleInfo div.titleCategory ul li a', '', 'div.titleInfo p.author', 'div.titleInfo div.tag ul li a')

    def __init__(self):
        super().__init__(('2905661176145448719', 'Manga-Park', 'ja', ROOT, True),
                         TITLE, CHAPTER, interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/title/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return ROOT + '/title/' + key if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        key = urlsplit(url).path.strip('/')
        return title.rstrip('/') + '/chapter/' + key if self.is_title(title) and re.fullmatch(ID, key) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page > 1:
            return [], False
        if query:
            dest = query_url(ROOT + '/search/freeword', key=query)
        elif tag in DAYS:
            dest = ROOT + '/series/' + tag
        elif sort == 'updated':
            dest = ROOT + '/series'
        else:
            dest = query_url(ROOT + '/ranking', target=tag if tag in RANK else 'all')
        return self.card_rows(*self.document(http, dest), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        value = row['status']
        row['status'] = ('completed' if '完結' in value else 'hiatus' if '休載' in value else
                         'ongoing' if '更新' in value else '')
        return row

    def chapters(self, http, doc, final):
        rows = {}
        for node in doc.select('div.chapter ul li[data-chapter-id]'):
            identity = node['data-chapter-id']
            label = node_text(node.select_one('p.chapterTitle'))
            date = release_date(node_text(node.select_one('div.date span')), '%Y/%m/%d')
            if not re.fullmatch(ID, identity):
                continue
            target = final.split('?', 1)[0].rstrip('/') + '/chapter/' + identity
            free = bool(node.select_one('div.free-badge img'))
            rows[target] = self.chapter(target, ('🆓 ' if free else '') + label,
                                        number(node.get('data-chapter-name')), date)
        return self.order(rows), False

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        response = self.json(http, ROOT + '/api/chapter/' + match[2], self.title_for(url))
        data = (response.get('data') or {}).get('chapter')
        if not isinstance(data, list):
            raise SourceAccessError('Manga-Park не предоставил открытые страницы главы.')
        result = []
        for chapter in data:
            for row in chapter.get('images') or []:
                value = row.get('key', '')
                if not isinstance(value, str) or len(value) > 400:
                    raise SourceError('Manga-Park вернул неизвестный формат страницы.')
                try:
                    key = base64.b64decode(value, validate=True)
                except binascii.Error:
                    raise SourceError('Manga-Park вернул повреждённый ключ изображения.') from None
                image = image_url(row.get('path'), url)
                if image:
                    result.append((image, XorPage(key)))
        return remember(result, self.title_for(url))


SOURCES = (MangaPark(),)
