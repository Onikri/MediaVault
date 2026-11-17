"""Sugo Comics catalogue, volumes and published Clip Studio Reader previews."""

import re
from urllib.parse import urlsplit

from manga_clipstudio import viewer_pages
from manga_direct_payloads import JsonSeries
from manga_madara import node_text
from manga_series_port import picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError, SourceTemporaryError


ROOT = 'https://nadeshiko-shoten.jp'
ID = r'[1-9][0-9]{0,12}'
LIST_URL = ROOT + '/products/list.php'
DETAIL = '/products/detail.php'
READ = '/products/reading.php'
NEXT = 'ul.result-pager li.active + li:not(:has(a[aria-disabled="true"])):has(a[href])'
TRIAL = re.compile(r'^【期間限定[^】]*閲覧期限[^】]*】')
CATEGORIES = {
    '1': '少年・青年', '2': 'メンズコミック', '3': '少女・女性', '4': 'ボーイズラブ',
    '5': 'ティーンズラブ', '8': 'ガールズラブ', '9': '恋愛', '10': '転生・異世界',
    '11': 'ビジネス・ヒューマンドラマ', '12': 'TV・映画・アニメ・ゲーム',
    '13': '日常', '14': 'ギャグ・コメディ', '16': 'サスペンス・ホラー',
    '17': '書き下ろし', '18': 'スポーツ', '19': 'アングラ・裏社会',
    '20': 'グルメ・芸術・趣味', '21': '作品集・短編集', '22': '4コママンガ',
    '23': '時代・歴史・戦争', '25': 'ファンタジー', '26': '自然・風景・動物',
    '27': '芸術', '29': '写真集(男性タレント)', '30': '雑誌', '99': '特集・キャンペーン',
}


def product(path, item, **options):
    return query_url(ROOT + path, product_id=item, **options)


class SugoComics(JsonSeries):
    def __init__(self):
        super().__init__(('4036523004624942398', 'Sugo Comics', 'ja', ROOT, False),
                         re.escape(DETAIL), re.escape(READ), interval=.45)

    def title_key(self, url):
        product_id = param(url, 'product_id')
        return product_id if re.fullmatch(ID, product_id) else ''

    chapter_key = title_key

    def is_title(self, url):
        return super().is_title(url) and bool(self.title_key(url))

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.chapter_key(url))

    def title_for(self, url):
        key = param(url, 'mv_sugo_series')
        return product(DETAIL, key) if re.fullmatch(ID, key) else ''

    def title_identity(self, url):
        return self.title_key(url)

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return product(DETAIL, key) if re.fullmatch(ID, key) else url

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.chapter_key(url) or urlsplit(url).path.strip('/')
        if not re.fullmatch(ID, key) or not self.is_title(title):
            return ''
        return product(READ, key, mv_sugo_series=self.title_key(title))

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title)

    def document(self, http, url):
        doc, final = super().document(http, url)
        if node_text(doc.title).startswith('メンテナンス'):
            raise SourceTemporaryError('Sugo Comics показывает страницу технического обслуживания.')
        return doc, final

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        popular = sort == 'popular' and not query and not tag
        if popular and page != 1:
            return [], False
        options = {'mode': 'week_series_ranking', 'group_id': '1'} if popular else {
            'name': query, 'pageno': page, 'orderby': 'date',
        }
        if tag in CATEGORIES:
            options['category_id'] = tag
        doc, final = self.document(http, query_url(LIST_URL, **options))
        rows = {}
        for item in doc.select('li.product_list-book-item'):
            element = item.select_one('input[name="product_id"][value]')
            key = element['value'] if element else ''
            title = node_text(item.select_one('.top-book-title')).removesuffix(' (無料)')
            if title and re.fullmatch(ID, key):
                url = product(DETAIL, key)
                rows[url] = self.record(url, title, picture(item.select_one('img.book_cover'), final))
        return list(rows.values()), bool(rows and not popular and doc.select_one(NEXT))

    def vocabulary(self, http):
        return [{'key': key, 'label': text, 'kind': 'genre'} for key, text in CATEGORIES.items()]

    def series(self, http, url):
        key = self.title_key(self.saved_title_url(url))
        if not key:
            raise SourceError('Некорректная ссылка Sugo Comics.')
        records = {}
        row = None
        for page in range(1, 31):
            args = {'disp_number': 500}
            if page > 1:
                args['pageno'] = page
            doc, final = self.title_document(http, product(DETAIL, key, **args))
            if row is None:
                meta = {node_text(item.select_one('.detail-name')): node_text(item.select_one('.detail-content'))
                        for item in doc.select('ul.product_details-main-content-list li')}
                title = meta.get('シリーズ') or node_text(doc.select_one('h1.product_details-title'))
                if not title:
                    raise SourceError('Sugo Comics не предоставил карточку тайтла.')
                authors = [value.partition('（')[0].rsplit('：', 1)[-1].strip() for value in meta.get('著者', '').split('/')]
                genres = [meta.get('カテゴリー', ''), *re.split(r'[,、/]', meta.get('ジャンル', ''))]
                desc = '\n\n'.join(filter(None, (meta.get('出版社'), meta.get('掲載誌'),
                                                 node_text(doc.select_one('p.product_details-area-text')))))
                row = self.record(product(DETAIL, key), title,
                                  picture(doc.select_one('img.product_details-main-content-img'), final),
                                  description=desc, genres=genres, authors=authors)
            for item in doc.select('#product_details-series-list > li'):
                if not item.select_one('.product_details-btn-box button[onclick*="reading"]'):
                    continue
                anchor = item.select_one('a.product_details-series-content-img-box[href]')
                cid = self.title_key(self.site_link(anchor['href'], final)) if anchor else ''
                if not cid:
                    continue
                title = TRIAL.sub('', node_text(item.select_one('h2.product_details-series-title'))).strip()
                target = product(READ, cid, mv_sugo_series=key)
                if target not in records:
                    index = len(records) + 1
                    records[target] = self.chapter(target, title, n=index, season=index)
            if not doc.select_one(NEXT):
                break
        return row, self.order(records)

    def viewer(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        target = product(READ, self.chapter_key(url))
        response, final = http._open(target, method='HEAD', headers={'Referer': self.title_for(url) or ROOT + '/'})
        response.close()
        if not param(final, 'cgi'):
            raise SourceAccessError('Sugo Comics не открыл читалку для этого выпуска.')
        return final

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            viewer = self.viewer(http, url)
            title = f'Выпуск {self.chapter_key(url)}'
            row = self.record(url, title)
            return self.reader_result(row, url, [self.chapter(url, title, 1)], viewer_pages(http, viewer, url))
        return super().inspect(url, http)

    def pages(self, http, url):
        viewer = self.viewer(http, url)
        return viewer_pages(http, viewer, url)


SOURCES = (SugoComics(),)
