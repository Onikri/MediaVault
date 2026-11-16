"""Direct adapters for comic archives that group strips into books."""

import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import MAX_PAGES, picture
from manga_webcomics import Archive, Profile, Reader, Webcomic, Work, param
from source_parser import SourceError


STRIP_DATE = r'\d{4}-\d{2}-\d{2}'


def schlock_books(adapter, http):
    doc, final = adapter.document(http, adapter.ROOT + '/archives/')
    for block in doc.select('div.archive-book:has(h4 > a[href])'):
        link = block.select_one('h4 > a[href]')
        value = adapter.site_link(link['href'], final)
        if adapter.is_title(value):
            yield value, block, link


class Schlock(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'(/archives/{SEGMENT}|/book/{SEGMENT}|/{SEGMENT})/?',
                         rf'/({STRIP_DATE})/?', interval=.35)

    def is_title(self, url):
        return super().is_title(url) and not self.is_chapter(url)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        rows = []
        for url, block, link in schlock_books(self, http):
            title = node_text(link)
            if title and query in title.casefold():
                rows.append(self.record_book(url, title, block))
        return rows, False

    def record_book(self, url, title, block):
        cover = picture(block.select_one('img'), url) or self.ROOT + '/static/img/logo.b6dacbb8.jpg'
        return self.record(url, title, cover.split('?', 1)[0], description=node_text(block.select_one('p')),
                           authors=['Howard Tayler'], status='completed')

    def chapter_entries(self, blocks):
        rows = {}
        for book, block, _ in blocks:
            for n, anchor in enumerate(block.select('ul.chapters > li > a[href]'), 1):
                target = self.site_link(anchor['href'], book)
                if self.is_chapter(target):
                    rows[target.rstrip('/')] = (book, n, node_text(anchor))
        return rows

    def title_for(self, url):
        raise SourceError('Глава Schlock Mercenary определяется по оглавлению.')

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            return super().inspect(value, http)
        books = list(schlock_books(self, http))
        entries = self.chapter_entries(books)
        chapter = entries.get(url.rstrip('/'))
        if chapter is None:
            raise SourceError('Глава отсутствует в архиве Schlock Mercenary.')
        book, n, title = chapter
        data = next((block, link) for target, block, link in books if target == book)
        pages = self.chapter_pages(http, url, sorted(entries))
        return self.reader_result(self.record_book(book, node_text(data[1]), data[0]), url,
                                  [self.chapter(url, title, n, self.chapter_key(url))], pages)

    def series(self, http, url):
        match = next(((key, block, link) for key, block, link in schlock_books(self, http)
                      if self.title_key(key) == self.title_key(url)), None)
        if match is None:
            raise SourceError('Источник не предоставил этот архив.')
        url, block, link = match
        rows = [self.chapter(key, title, n, self.chapter_key(key))
                for key, (_, n, title) in self.chapter_entries([match]).items()]
        return self.record_book(url, node_text(link), block), rows

    def saved_chapter_matches(self, target, title):
        from source_parser import PublicHttp

        http = PublicHttp(timeout=(3, 6))
        try:
            _, rows = self.series(http, title)
            return any(self.chapter_key(self.site_link(item['url'])) == self.chapter_key(target) for item in rows)
        finally:
            http.close()

    def chapter_pages(self, http, url, ordered):
        key = url.rstrip('/')
        index = ordered.index(key)
        try:
            start = date.fromisoformat(self.chapter_key(key))
            end = date.fromisoformat(self.chapter_key(ordered[index + 1])) if index + 1 < len(ordered) else start + timedelta(days=1)
        except ValueError:
            raise SourceError('Некорректные даты главы.') from None
        count = (end - start).days
        if not 1 <= count <= MAX_PAGES:
            raise SourceError('Неподдерживаемая длина главы.')
        result = []
        for shift in range(count):
            stamp = (start + timedelta(days=shift)).isoformat()
            panel, final = self.document(http, self.ROOT + '/' + stamp)
            result.extend(picture(node, final) for node in panel.select(f'div[id="strip-{stamp}"] > img'))
        if not 1 <= len(result) <= MAX_PAGES or not all(result):
            raise SourceError('Источник не предоставил полный список страниц.')
        return result


DARTH_CAST = ('QuiGon', 'Anakin2', 'ObiWan3', 'JarJar2', 'Leia4', 'Han5', 'Luke6', 'Cassian', 'C3PO4',
              'Finn7', 'Han4', 'Hux8')


def darth_catalogue(source, http, page, query, sort, tag):
    if page != 1:
        return [], False
    archive = source.ROOT + '/archive.html'
    doc, final = source.document(http, archive)
    result, name = [], source.NAME
    for node in doc.select('div.text > table.text > tbody > tr'):
        heading = node.select_one('th')
        if heading:
            name = source.NAME + ' ' + node_text(heading)
            continue
        link = node.select_one('td[colspan="3"] > a[href]')
        target = source.site_link(link['href'], final) if link else archive
        if source.is_title(target):
            char = DARTH_CAST[len(result)] if len(result) < len(DARTH_CAST) else 'Vader4'
            result.append(Work(target, name, f'/cast/{char}.jpg', author='David Morgan-Mar & Co.'))
        if not link:
            break
    return [work for work in result if query.casefold() in work.title.casefold()], False


def darth_archive(source, http, work, url):
    doc, final = source.document(http, url)
    result = []
    for row in doc.select('div.text > table.text > tbody > tr'):
        cells = row.find_all('td', recursive=False)
        if not cells or any(cell.has_attr('colspan') for cell in cells):
            continue
        anchor = cells[2].select_one('a[href]') if len(cells) > 2 else cells[0].select_one('a[href]')
        target = source.site_link(anchor['href'], final) if anchor else ''
        if not source.is_chapter(target):
            continue
        stamp = release_date(node_text(cells[0]), '%a %d %b, %Y') if len(cells) > 2 else ''
        result.append((target, node_text(anchor), len(result), stamp))
    return result, False


def darths(identity):
    return Webcomic(identity, Profile(
        browse=darth_catalogue, chapters=darth_archive, reader=Reader('div.center img'),
        title_path=r'/(?:archive[\w-]*\.html|solo/?)', chapter_path=rf'/(?:episodes|solo)/{SEGMENT}\.html',
    ))


XKCD = {
    'en': ('/archive/', '#middleContainer > a[href]', '#comic > img', r'/\d+/?', ''),
    'es': ('/archive/', '.archive-entry > a[href]', '#middleContent .strip', rf'/strips/{SEGMENT}/?', ''),
    'fr': ('/tous-episodes.php', '#content .s > a[href]:not(:last-of-type)', '#content .s img[src^="strips/"]',
           r'/[^/]+\.php', 'id|num|n|strip'),
    'ru': ('/img', '.main > a[href]', '.main img[src*="/i/"]', r'/\d+/?', ''),
    'zh': ('/api/strips.json', '', '#content > img:not([id])', r'/\d+/?', ''),
}


class Xkcd(Webcomic):
    def __init__(self, identity):
        lang = identity[2]
        archive, _, img, chapter, required = XKCD[lang]
        work = Work('/', 'xkcd', author='Randall Munroe', description='A webcomic of romance, sarcasm, math and language.', archive=archive)
        super().__init__(identity, Profile((work,), reader=Reader(img), title_path='/', chapter_path=chapter,
                                           chapter_query=required, chapters=xkcd_archive, pages=Xkcd.pages))

    def is_chapter(self, url):
        if self.LANGUAGE != 'fr':
            return super().is_chapter(url)
        # The translated PHP reader's first query value is the strip number.
        return bool(self.CHAPTER_PATH.fullmatch(urlsplit(url).path) and urlsplit(url).path != '/tous-episodes.php'
                    and re.search(r'(?:^|&)[\w-]+=\d{1,6}(?:&|$)', urlsplit(url).query))

    def saved_title_url(self, url):
        return self.ROOT + '/' if urlsplit(url).path.strip('/') == 'SINGLE' else super().saved_title_url(url)

    def pages(self, http, url):
        doc, final = self.document(http, url)
        if not self.is_chapter(final):
            raise SourceError('Источник перенаправил запрос на другой выпуск.')
        node = doc.select_one(self.profile.reader.selector)
        if not node:
            raise SourceError('У этого интерактивного выпуска нет изображения.')
        srcset = node.get('srcset', '').split()
        page = image_url(srcset[0], final) if srcset else picture(node, final)
        text = node_text(doc.select_one('.comics_text, #content .s div:not(.buttons)')) or node.get('title', '')
        return node.get('alt', ''), [page], text


def xkcd_archive(source, http, work, title):
    archive, selector, _, _, _ = XKCD[source.LANGUAGE]
    if source.LANGUAGE == 'zh':
        data = source.json(http, archive)
        rows = [(f'{source.ROOT}/{row["id"]}', str(row['title']), row['id'], '') for row in data.values()
                if isinstance(row, dict) and type(row.get('id')) is int and row.get('title')]
        return sorted(rows, key=lambda row: row[2]), False
    doc, final = source.document(http, source.ROOT + archive)
    rows = []
    for anchor in doc.select(selector):
        target = source.site_link(anchor.get('href'), final)
        if not source.is_chapter(target):
            continue
        text = node_text(anchor) or (anchor.img or {}).get('alt', '')
        if source.LANGUAGE == 'fr':
            found = re.search(r'=(\d+)(?:&|$)', urlsplit(target).query)
            n = int(found[1]) if found else None
        else:
            path = urlsplit(target).path.strip('/')
            n = int(path) if path.isdecimal() else None
        stamp = anchor.get('title', '') or node_text(anchor.parent.select_one('time'))
        stamp = release_date(stamp, '%Y-%m-%d')
        rows.append((target, text, n, stamp))
    return rows if source.LANGUAGE == 'fr' else rows[::-1], False


def public_api(host, path, query):
    return host == 'xkcd.tw' and path == '/api/strips.json' and not query
