"""Public DLE catalogues with embedded chapter manifests on Com-X and Manga-Bay."""

import json
import re
from datetime import date
from urllib.parse import quote, unquote, urlsplit

from manga_direct_payloads import JsonSeries, strings
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort, number
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

BAY = 'https://manga-bay.biz'
COMX = 'https://com-x.life'
HOSTS = {'manga-bay.biz', 'com-x.life', 'ru.com-x.life'}
ID = r'[1-9]\d{0,12}'
TITLE = rf'/({ID})-({SEGMENT})\.html'
CHAPTER = rf'/reader/({ID})/({ID})/?'
PAGE = r'(?:/page/[1-9]\d{0,3})?/?'
SORTS = {'rating', 'date', 'editdate'}


def public_form(url, data):
    parts = urlsplit(url)
    if (parts.netloc not in HOSTS or parts.query or not isinstance(data, dict)
            or set(data) != {'dlenewssortby', 'dledirection', 'set_new_sort', 'set_direction_sort'}
            or data['dlenewssortby'] not in SORTS or data['dledirection'] != 'desc'):
        return False
    path = unquote(parts.path)
    prefix = '/comix' if parts.netloc == 'manga-bay.biz' else '/comix-read'
    category = 'cat_1'
    if not re.fullmatch(prefix + PAGE, path):
        years = r'/y\[from\]=1980/y\[to\]=20\d{2}' if parts.netloc != 'manga-bay.biz' else ''
        pattern = r'/ComicList(?:/g=[1-9]\d{0,7})?' + years + PAGE
        if not re.fullmatch(pattern, path):
            return False
        category = 'xfilter'
    return data['set_new_sort'] == 'dle_sort_' + category and data['set_direction_sort'] == 'dle_direction_' + category


def inline(doc, field):
    pattern = re.compile(r'\bwindow\.' + re.escape(field) + r'\s*=\s*')
    for script in doc.select('script:not([src])'):
        raw = script.string or ''
        match = pattern.search(raw)
        if match:
            try:
                obj, _ = json.JSONDecoder().raw_decode(raw[match.end():])
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    raise SourceError('Источник не предоставил данные читалки DLE.')


class DleManga(JsonSeries):
    def __init__(self, identity, *, bay):
        super().__init__(identity, TITLE, CHAPTER, hosts=() if bay else ('ru.com-x.life',),
                         legacy_hosts=('read.manga-bay.org',) if bay else (), interval=.55)
        self.bay = bay
        self.list_path = '/comix/' if bay else '/comix-read/'
        self.cards = (Cards('#dle-content > a.cd', '', '.cd__title', '.cd__ph img', next='',
                            image_attrs=('data-src', 'data-adult-src')) if bay
                      else Cards('#dle-content > .readed', '.readed__title > a', cover='img', next='',
                                 image_attrs=('data-src',)))

    def title_for(self, url):
        marker = param(url, 'mv_title')
        if not re.fullmatch(SEGMENT, marker):
            return ''
        ref = self.site_link('/' + marker)
        return ref if self.is_title(ref) and self.title_key(ref) == self.chapter_key(url) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.saved_chapter_matches(url, title):
            return query_url(url, mv_title=urlsplit(title).path.lstrip('/'))
        return ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        fields = None
        tail = f'/page/{page}/' if page > 1 else '/'
        if query:
            search_tail = tail if self.bay else f'/page/{page}/'
            target = self.ROOT + '/search/' + quote(query, safe='') + search_tail
        else:
            path = self.list_path.rstrip('/')
            mode = 'cat_1'
            if re.fullmatch(r'[1-9]\d{0,7}', tag):
                path, mode = '/ComicList/g=' + tag, 'xfilter'
                if not self.bay:
                    path += '/y%5Bfrom%5D=1980/y%5Bto%5D=' + str(date.today().year)
            target = self.ROOT + path + tail
            dated_sort = 'date' if self.bay else 'editdate'
            fields = {'dlenewssortby': dated_sort if sort == 'updated' else 'rating', 'dledirection': 'desc',
                      'set_new_sort': 'dle_sort_' + mode, 'set_direction_sort': 'dle_direction_' + mode}
        if fields:
            self.origin.wait(getattr(http, 'deadline', None))
            from bs4 import BeautifulSoup

            raw, final, _ = http.document(target, headers={'Referer': self.ROOT + self.list_path},
                                          method='POST', action='native-series-form', data=fields)
            doc = BeautifulSoup(raw, 'html.parser')
        else:
            doc, final = self.document(http, target)
        if not self.canonical(final):
            raise SourceError('Каталог DLE перенаправил на другой домен.')
        rows, _ = self.card_rows(doc, final, self.cards)
        if not self.bay:
            for row in rows:
                row['title'] = row['title'].replace(' / ', ' | ').rsplit(' | ', 1)[-1].strip()
        last = doc.select_one('.pagination__pages > :last-child')
        return rows, bool(rows and last and last.name == 'a')

    def vocabulary(self, http):
        result = inline(self.document(http, self.ROOT + self.list_path)[0], '__XFILTER__')
        values = ((result.get('filter_items') or {}).get('g') or {}).get('values') or []
        return [{'key': str(row['id']), 'label': row['value'], 'kind': 'genre'}
                for row in values if isinstance(row, dict) and type(row.get('id')) is int and isinstance(row.get('value'), str)]

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        row = self.metadata(doc, final, Meta('header.page__header h1', '.page__poster img',
                            '.page__desc-text', '.page__alt', '.page__tags a, .page__genres a', '',
                            '.page__list div:-soup-contains-own("Author") + *, .page__list div:-soup-contains-own("Автор") + *'))
        if doc.select_one('.message-info__content:-soup-contains("не имеют доступа")'):
            raise SourceAccessError('Источник ограничивает доступ к выпускам.')
        data = inline(doc, '__DATA__')
        key = str(data.get('news_id', ''))
        if key != self.title_key(url):
            raise SourceError('Каталог DLE вернул данные другого произведения.')
        chapters = {}
        for item in data.get('chapters') or []:
            if not isinstance(item, dict) or not re.fullmatch(ID, identifier := str(item.get('id', ''))):
                continue
            target = query_url(self.ROOT + f'/reader/{key}/{identifier}', mv_title=urlsplit(final).path.lstrip('/'))
            title = ' '.join(str(item.get('title') or '').split())
            stamp = release_date(str(item.get('date') or ''), '%d.%m.%Y')
            chapters[target] = self.chapter(target, title, number(item.get('number')) or None, stamp)
        return row, self.order(chapters)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        url = query_url(url, mv_title=[])
        doc, final = self.page_document(http, url)
        if doc.select_one('.gate') or 'Выпуск был удален по требованию правообладателя' in doc.get_text():
            raise SourceAccessError('Источник ограничивает доступ к главе.')
        data = inline(doc, '__DATA__')
        images = strings(data.get('images'))
        if self.bay:
            count = data.get('pages')
            if type(count) is int and 0 < count <= len(images):
                images = images[:count]
            return [page for item in images if (page := image_url(item, final))]
        host = data.get('host_ru' if urlsplit(final).netloc == 'ru.com-x.life' else 'host')
        if host not in {'img.com-x.life', 'rus.com-x.life'}:
            raise SourceError('Com-X вернул неизвестный домен изображений.')
        origin = 'https://' + host + '/comix/'
        return [page for item in images if (page := image_url(origin + item.lstrip('/'), origin))]


SOURCES = (DleManga(('2338066431666790211', 'Manga-Bay', 'en', BAY, True), bay=True),
           DleManga(('1114173092141608635', 'Com-X', 'ru', COMX, False), bay=False))
