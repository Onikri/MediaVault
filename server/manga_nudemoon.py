"""Nude-Moon (keiyoushi ``src/ru/nudemoon`` at 6f345a8), installed mirror g.nude-moon.fun.

Guest pages need the site's own "adult confirmed / mobile" cookies. Text
search exists only for signed-in users, so guests browse the catalogue and
tags; titles are either single releases or a paged list of chapters.
"""

import re
from urllib.parse import quote, urljoin, urlsplit

from manga_madara import image_url, node_text
from manga_webcomics import param, query_url
from manga_ninth_routes import Route, register
from manga_series_port import SeriesPort, label_number
from source_parser import SourceAccessError, SourceError

ROOT = 'https://g.nude-moon.fun'
HOSTS = ('g.nude-moon.fun', 'nude-moon.org')
TITLE = r'/([0-9]{1,9}--[^/]{1,300}\.html)'
NEXT = 'a.small'
SORTS = {'popular': 'views', 'updated': 'date', 'new': 'date', 'rating': 'like'}
MONTHS = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма': 5, 'июн': 6, 'июл': 7, 'август': 8,
          'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12}
DATE = re.compile(r'\b(\d{1,2})\s+([А-Яа-яЁё]+)\s+((?:19|20)\d{2})\b')


def route(url, method, data, headers):
    if url.netloc != 'g.nude-moon.fun' or method != 'GET' or data is not None:
        return None
    if not re.fullmatch(r'/(?:all_manga|tags/[^/]{1,300}|tags/|[0-9]{1,9}--[^/]{1,300}\.html|all_manga/[^/]{1,300}|'
                        r'[0-9]{1,9}-online--[^/]{1,300}\.html)', url.path):
        return None
    return Route({'Cookie': 'NMfYa=1; nm_mobile=1',
                  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                  'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.6'})


register('nudemoon', route)


def russian_date(text):
    match = DATE.search(text or '')
    if not match:
        return ''
    month = next((n for stem, n in MONTHS.items() if match[2].lower().startswith(stem)), 0)
    return f'{int(match[3]):04d}-{month:02d}-{int(match[1]):02d}' if month else ''


class NudeMoon(SeriesPort):
    def __init__(self):
        super().__init__(('6384784374922886076', 'Nude-Moon', 'ru', ROOT, True), TITLE, TITLE,
                         legacy_hosts=('nude-moon.org',), interval=.5)

    def document(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        from bs4 import BeautifulSoup

        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'}, action='n9:nudemoon')
        target = self.site_link(final)
        if not target:
            raise SourceError('Nude-Moon перенаправил на другой сайт.')
        return BeautifulSoup(raw, 'html.parser'), target

    def title_key(self, url):
        match = self.TITLE_PATH.fullmatch(urlsplit(url).path)
        return match[1] if match else ''

    def is_title(self, url):
        return bool(self.TITLE_PATH.fullmatch(urlsplit(url).path)) and not param(url, 'mv_read')

    def is_chapter(self, url):
        return bool(self.TITLE_PATH.fullmatch(urlsplit(url).path)) and param(url, 'mv_read') == '1'

    def chapter_key(self, url):
        return self.title_key(url)

    def title_for(self, url):
        return self.ROOT + urlsplit(url).path

    def chapter_identity(self, url):
        return urlsplit(url).path

    def read_url(self, url):
        return query_url(self.ROOT + urlsplit(url).path, mv_read='1')

    def saved_chapter(self, row, root, title):
        target = self.canonical(urljoin(root.rstrip('/') + '/', str(row.get('realUrl') or row.get('url') or '')))
        return self.read_url(target) if target and self.TITLE_PATH.fullmatch(urlsplit(target).path) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target)

    def cards(self, doc, final):
        rows = {}
        for block in doc.select('table.news_pic2'):
            anchor = block.select_one('a:has(h2)')
            url = self.canonical(urljoin(final, anchor.get('href', ''))) if anchor else ''
            if not self.is_title(url):
                continue
            title = node_text(anchor).split(' / ')[0].split(' №')[0].strip()
            image = block.select_one('a img')
            row = self.record(url, title, image_url(image.get('src'), final) if image else '')
            row['genres'] = [node_text(a) for a in block.select('div.tag-links a')]
            rows[row['id']] = row
        more = any(node_text(a) == '>' for a in doc.select(NEXT))
        return list(rows.values()), more

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            # The site answers text search only for signed-in users.
            raise SourceAccessError('Поиск Nude-Moon доступен только авторизованным пользователям.')
        order = SORTS.get(sort, 'views')
        offset = 30 * (page - 1)
        if tag:
            if not re.fullmatch(r'[0-9A-Za-zА-Яа-яЁё _-]{1,60}', tag):
                return [], False
            url = f"{ROOT}/tags/{quote(tag.replace(' ', '_'))}&{order}&rowstart={offset}"
        else:
            url = f'{ROOT}/all_manga?{order}&rowstart={offset}'
        return self.cards(*self.document(http, url))

    def vocabulary(self, http):
        doc, _ = self.document(http, ROOT + '/tags/')
        values = {node['value'].strip() for node in doc.select('input[name*=tag][value]') if node['value'].strip()}
        return [{'key': value, 'label': value.replace('_', ' '), 'kind': 'tag'} for value in sorted(values)]

    def metadata(self, doc, url, spec=None):
        heading = doc.select_one('h1')
        title = node_text(heading).split(' / ')[0].split(' №')[0].strip() if heading else ''
        if not title:
            raise SourceError('Nude-Moon не предоставил карточку тайтла.')
        info = doc.select_one('table.news_pic2')
        image = doc.select_one('meta[property="og:image"][content]')
        description = doc.select_one('.description')
        authors = [node_text(a) for a in info.select('a[href*=mangaka]')] if info else []
        tags = [node_text(a) for a in info.select('div.tag-links a')] if info else []
        return self.record(url, title, image_url(image['content'], url) if image else '',
                           description=node_text(description) if description else '', genres=tags, authors=authors)

    def chapters(self, http, doc, final):
        button = next((a for a in doc.select('td.button a[href]') if 'Все главы' in node_text(a)), None)
        if button is None:
            return [self.single(doc, final)], False
        rows, seen = {}, set()
        target = urljoin(final, button['href'])
        for _ in range(60):
            if target in seen:
                break
            seen.add(target)
            page, current = self.document(http, target)
            for block in page.select('table.news_pic2'):
                anchor = block.select_one('tr[valign=top] a:has(h2)')
                url = self.canonical(urljoin(current, anchor.get('href', ''))) if anchor else ''
                if not self.TITLE_PATH.fullmatch(urlsplit(url).path):
                    continue
                url = self.read_url(url)
                name = node_text(anchor.select_one('h2'))
                info = block.select_one('tr[valign=top] td[align=left]')
                date = russian_date(node_text(info.select_one('span.small2'))) if info and info.select_one('span.small2') else ''
                translator = node_text(info.select_one('a[href*=perevod]')) if info and info.select_one('a[href*=perevod]') else ''
                found = re.search(r'№\s*([0-9]+(?:-[0-9]+)?)', name)
                n = float(found[1].replace('-', '.')) if found else label_number(name)
                rows[url] = self.chapter(url, name, n, date, translator=translator)
            more = next((a for a in page.select(NEXT) if node_text(a) == '>' and a.get('href')), None)
            if not more:
                break
            target = urljoin(current, more['href'])
        if not rows:
            return [self.single(doc, final)], False
        return self.order(rows), False

    def single(self, doc, final):
        heading = doc.select_one('table td.bg_style1 h1') or doc.select_one('h1')
        name = node_text(heading).split('/', 1)[-1].strip() if heading else ''
        when = doc.select_one('td:has(img[src*=time]) span.small2')
        translator = doc.select_one('table.news_pic2 a[href*=perevod]')
        return self.chapter(self.read_url(final), f'Сингл {name}'.strip(), 0.0, russian_date(node_text(when)) if when else '',
                            translator=node_text(translator) if translator else '')

    def pages(self, http, url):
        doc, _ = self.document(http, self.ROOT + urlsplit(url).path)
        pages = [image_url(img['data-src'], url) for img in doc.select('img[title][loading="lazy"][data-src]')
                 if img.get('title', '').strip()]
        if not pages:
            raise SourceAccessError('Страницы Nude-Moon открываются только после входа на сайт.')
        return pages


SOURCES = (NudeMoon(),)
