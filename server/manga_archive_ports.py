"""Public webcomic archives and their installed language editions."""

from datetime import date
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from manga_individual_catalogues import HTML
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_second_batch_profiles import IDENTITIES
from manga_series_port import Archive as SeriesArchive, Cards, Meta, SeriesPort, document_json, picture
from manga_webcomic_profiles import single
from manga_webcomics import Archive, Profile, Reader, Webcomic, Work, numeric, param, query_url
from source_parser import SourceError


DATE_POST = r'/\d{4}/\d{2}/\d{2}/[\w%-]+/?'
POST = r'/[\w/.%-]+/?'
DB = (
    ('english', 'chapters', 'English'), ('francais', 'chapitres', 'Français'), ('espanol', 'capitulos', 'Español'),
)
OHARA = {
    'en': ('English', (589813936, 607613583, 43972770, 9363667, 634609261, 699200615, 139757, 22695, 648324575)),
    'id': ('Indonesia', (702404482, 699200615)), 'es': ('Spanish', (693784776, 699200615)),
    'fr': ('French', (699200615,)), 'ar': ('Arabic', (699200615,)), 'it': ('Italian', (699200615,)),
}


def public_api(host, path, query):
    if host != 'mayochuu.xyz':
        return False
    if re.fullmatch(r'/api/manga/[\w-]{1,120}/[1-9][0-9]{0,3}', path):
        return not query
    if path not in {'/api/chapters', '/api/raw/chapters'}:
        return False
    if not query:
        return True
    try:
        args = parse_qs(query, max_num_fields=2)
    except ValueError:
        return False
    return (set(args) in ({'id'}, {'id', 'number'}) and len(args.get('id', [])) == 1
            and bool(re.fullmatch(r'[\w-]{1,120}', args['id'][0]))
            and ('number' not in args or len(args['number']) == 1 and numeric(args['number'][0]) is not None))


def one_picture(adapter, http, url, selector):
    doc, final = adapter.document(http, url)
    return picture(doc.select_one(selector), final, ('data-original',))


def startmatch(target, parent):
    return urlsplit(target).path.rstrip('/').startswith(urlsplit(parent).path.rstrip('/') + '/')


def iso(value):
    return release_date(str(value or '')[:10], '%Y-%m-%d')


def html_group(adapter, http, page, query, tag, *, path, cards, selector, title, cover='img', prefix=''):
    if page != 1 or tag:
        return (), False
    doc, final = adapter.document(http, adapter.ROOT + path)
    work = {}
    for item in doc.select(cards):
        a = item.select_one(selector)
        if not a or not a.get('href'):
            continue
        link = adapter.site_link(a['href'], final)
        label = prefix + node_text(item.select_one(title) if title else a)
        if link and label.strip() and query.casefold() in label.casefold():
            work[link] = Work(link, label, picture(item.select_one(cover), final) if cover else '')
    return list(work.values()), False


def hololive(adapter, http, page, query, _sort, tag):
    path = '' if adapter.LANGUAGE == 'ja' else '/' + adapter.LANGUAGE
    rows, more = html_group(adapter, http, page, query, tag, path=path + '/alt/holonometria/manga/',
                            cards='.manga__item', selector='a[href]', title='.manga__title')
    # The cards now link only their first episode (/<title>/ep0/); the title is its parent.
    from dataclasses import replace

    titles = {}
    for row in rows:
        parts = urlsplit(row.path)
        parent = re.sub(r'/ep[0-9]{1,4}/?$', '/', parts.path)
        row = replace(row, path=urlunsplit(parts._replace(path=parent))) if parent != parts.path else row
        titles.setdefault(row.path, row)
    return list(titles.values()), more


def ohara(adapter, http, page, query, _sort, tag):
    _, ids = OHARA[adapter.LANGUAGE]
    cards = ', '.join(f'#categories-7 li.cat-item-{n}' for n in ids)
    return html_group(adapter, http, page, query, tag, path='/', cards=cards, selector='a[href]', title='', cover='')


def ohara_chapters(adapter, http, _work, url):
    language = OHARA[adapter.LANGUAGE][0]
    languages = re.compile(r'French|Arabic|Italian|Indonesia|Spanish', re.I)
    doc, final = adapter.document(http, url)
    seen, rows = set(), []
    reverie = 'reverie' in url.casefold() or 'reverie' in node_text(doc.select_one('h1.page-title')).casefold()
    for _ in range(80):
        seen.add(final)
        for article in doc.select('article'):
            anchor = article.select_one('a.entry-thumbnail[href], h2.entry-title a[href]')
            title = node_text(article.select_one('h2.entry-title a'))
            if not anchor or not title:
                continue
            if reverie and ((adapter.LANGUAGE == 'en' and languages.search(title))
                            or (adapter.LANGUAGE != 'en' and language.casefold() not in title.casefold())):
                continue
            if not reverie and adapter.LANGUAGE == 'es' and 'indonesia' in title.casefold():
                continue
            stamp = article.select_one('span.posted-on time[datetime]')
            rows.append((adapter.site_link(anchor['href'], final), title, None, iso(stamp['datetime']) if stamp else ''))
        next_link = doc.select_one('div.nav-previous a[href]')
        if not next_link:
            return rows, False
        target = adapter.site_link(next_link['href'], final)
        if not target or target in seen or not startmatch(target, url):
            raise SourceError('Каталог The Library of Ohara вернул чужую страницу архива.')
        doc, final = adapter.document(http, target)
    return rows, True


def vinnie_chapters(adapter, http, _work, url):
    doc, final = adapter.document(http, url)
    rows = []
    for node in doc.select('.cccLeftInd .cccArchiveEntry[onclick]'):
        m = re.search(r'changeToComic\("([\w-]{1,100})"\)', node['onclick'])
        if m:
            rows.append((adapter.site_link('/' + m[1] + '.php', final), node_text(node), None, ''))
    return rows, False


def db_title(_adapter, url):
    directory = urlsplit(url).path.strip('/').split('/', 1)[0]
    return next((f'/{prefix}/{archive}.php' for prefix, archive, _ in DB if directory == prefix), '')


def db_chapters(adapter, http, _work, url):
    doc, final = adapter.document(http, url)
    result = []
    pattern = re.compile(r'(?:chapter|chapitre|cap[ií]tulo)\s*(\d+)', re.I)
    for node in doc.select('div.card:has(a[href$="/01.php"])'):
        link = adapter.site_link(node.select_one('a[href$="/01.php"]')['href'], final)
        title = node_text(node.select_one('h5.card-title'))
        found = pattern.search(title)
        if title and db_title(adapter, link) == urlsplit(url).path:
            result.append((link, title, int(found[1]) if found else 0, ''))
    return sorted(result, key=lambda row: row[2], reverse=True), False


def db_pages(adapter, http, url):
    doc, final = adapter.document(http, url.split('?')[0])
    if urlsplit(final).path != urlsplit(url).path:
        raise SourceError('DB New Hope вернул другую главу.')
    count = len(doc.select('div.nav select option')) or 1
    if count > 500:
        return '', [], ''
    pages = [picture(doc.select_one('img.manga-page'), final)]
    pages.extend(one_picture(adapter, http, query_url(final, page=i), 'img.manga-page') for i in range(2, count + 1))
    return '', pages, ''


def aurora_catalogue(adapter, http, page, query, _sort, tag):
    return html_group(adapter, http, page, query, tag, path='/archive/', cards='.wp-block-image:has(a)',
                      selector='a[href]', title='', prefix='Aurora — ')


def aurora_chapters(adapter, http, _work, url):
    doc, final = adapter.document(http, url)
    pages = {final: doc}
    for a in doc.select('#paginav a[title][href]')[1:80]:
        link = adapter.site_link(a['href'], final)
        if link and link not in pages:
            payload, target = adapter.document(http, link)
            pages[target] = payload
    result = []
    for base, part in pages.items():
        for item in part.select('.post-content'):
            a = item.select_one('a.webcomic-link[href]')
            if not a:
                continue
            title = node_text(item.select_one('.post-title a'))
            n = re.search(r'\.(\d+(?:\.\d+)?)\s*-', title)
            result.append((adapter.site_link(a['href'], base), title, numeric(n[1]) if n else None,
                           release_date(node_text(item.select_one('.post-date')), '%B %d, %Y')))
    return result[::-1], len(doc.select('#paginav a[title]')) > 80


def year_catalogue(adapter, _http, page, query, _sort, tag):
    if page != 1 or tag:
        return (), False
    real = adapter.NAME == 'Real Life Comics'
    years = range(date.today().year, 1998 if real else 2011, -1)
    records = []
    for year in years:
        title = f'{adapter.NAME} ({year})'
        if query.casefold() not in title.casefold() or real and year in {2016, 2017}:
            continue
        path = f'/archivepage.php?year={year}' if real else f'/{adapter.LANGUAGE}/{year}'
        logo = '/images/logo.png' if real else 'https://i.imgur.com/' + ('I7ps9zS.jpg' if adapter.LANGUAGE == 'fr' else 'HODJlt9.jpg')
        author = 'Maelyn Dean' if real else 'Thomas Gx' if adapter.LANGUAGE == 'fr' else 'Mark Nightingale'
        records.append(Work(path, title, logo, author=author))
    return records, False


def real_life_chapters(adapter, http, _work, url):
    doc, final = adapter.document(http, url)
    out = []
    for node in doc.select('.calendar tbody tr td a[href], .calendar tr td a[href]'):
        group = node.find_parent(class_='calendar')
        heading = group.find_previous_sibling('h4', class_='month') if group else None
        stamp = f'{node_text(heading)} {node_text(node)}'.strip()
        published = release_date(stamp, '%B %Y %d')
        out.append((adapter.site_link(node['href'], final), stamp, None, published))
    return out, False


def commit_archive(adapter, http, _work, url):
    try:
        doc, final = adapter.document(http, url.rstrip('/') + '/?')
    except SourceError as error:
        if type(error) is SourceError and str(error) == 'Источник вернул HTTP 404.':
            return [], False
        raise
    pages = re.findall(r'\d+', node_text(doc.select_one('.wp-pagenavi .pages')))
    count = int(pages[-1]) if pages else 1
    result = []
    for page in range(1, min(count, 80) + 1):
        part, final = adapter.document(http, url.rstrip('/') + f'/page/{page}/?')
        for a in part.select('.excerpt a[href]'):
            link = adapter.site_link(a['href'], final)
            parts = urlsplit(link)
            if link and not parts.path.startswith('/' + adapter.LANGUAGE + '/'):
                link = adapter.site_link('/' + adapter.LANGUAGE + parts.path)
            stamp = re.search(r'/(\d{4}/\d{2}/\d{2})/', link)
            title = node_text(a.select_one('span')) or node_text(a)
            if stamp:
                result.append((link, title, None, stamp[1].replace('/', '-')))
    return result, count > 80


def commit_title(adapter, url):
    return '/' + adapter.LANGUAGE + '/' + urlsplit(url).path.strip('/').split('/')[1]


def grrl_chapters(adapter, http, _work, url):
    result = []
    for year in range(date.today().year, 2009, -1):
        doc, final = adapter.document(http, query_url(url.rstrip('/') + '/', archive_year=year))
        for node in doc.select('.archive-date'):
            sibling = node.find_next_sibling()
            a = sibling.select_one('a[href]') if sibling else None
            if a:
                date_text = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', node_text(node))
                stamp = release_date(f'{date_text} {year}', '%b %d %Y') or release_date(f'{date_text} {year}', '%B %d %Y')
                result.append((adapter.site_link(a['href'], final), node_text(a), None, stamp))
    return sorted(result, key=lambda row: row[3], reverse=True), False


def broccoli_chapters(adapter, http, _work, url):
    doc, final = adapter.document(http, url)
    out = [('/comic-characters', 'Character Summary', 0, '')]
    for group in doc.select('li.archive-marker'):
        arc = node_text(group.select_one('.archive-header .marker-title'))
        for a in group.select('li.archive-page a[href]'):
            title = node_text(a.select_one('span.page-title'))
            target = adapter.site_link(a['href'], final)
            if target and title:
                out.append((target, ' — '.join(filter(None, (arc, title))), numeric(urlsplit(target).path.rstrip('/').rsplit('/', 1)[-1]), ''))
    return out[::-1], False


def broccoli_pages(adapter, http, url):
    if urlsplit(url).path.rstrip('/') != '/comic-characters':
        return adapter.pages(http, url)
    doc, final = adapter.document(http, url)
    sections = doc.select('section.static-block:has(figure, .block-content)')
    pictures = [picture(item.select_one('figure img'), final) for item in sections]
    return 'Character Summary', [link for link in pictures if link], '\n\n'.join(node_text(item) for item in sections)


def hate_options(doc, final, adapter):
    return [(node, adapter.site_link(node['value'], final))
            for node in doc.select('select.jumpbox option[value]:not([value="-1"])')]


def hate_chapters(adapter, http, _work, _url):
    doc, final = adapter.document(http, adapter.ROOT + '/TPoH/')
    rows, active = [], False
    for node, target in hate_options(doc, final, adapter):
        label = node_text(node)
        if 'bold' in node.get('style', ''):
            rows.append((target, label, len(rows) + 1, ''))
        elif not active and target:
            rows.append((target.rsplit('/', 1)[0] + '/', label.split(' : Page', 1)[0], len(rows) + 1, ''))
            active = True
    return rows[::-1], False


def hate_pages(adapter, http, url):
    doc, final = adapter.document(http, url)
    links = [target for node, target in hate_options(doc, final, adapter)
             if target and 'bold' not in node.get('style', '')]
    if len(links) > 500:
        return '', [], ''
    return '', [one_picture(adapter, http, link, '.comic_comic > img') for link in links], ''


def twokinds_list(adapter, http):
    doc, final = adapter.document(http, adapter.ROOT + '/archive/')
    result = []
    for a in doc.select('.chapter-links > a[href]'):
        url = adapter.site_link(a['href'], final)
        match = re.fullmatch(r'/comic/([\w-]+)/?', urlsplit(url).path)
        if match:
            result.append((match[1], node_text(a.select_one('span')) or match[1]))
    return result


def twokinds_chapters(adapter, http, _work, url):
    size = int(urlsplit(url).path.strip('/'))
    pages = twokinds_list(adapter, http)
    rows = []
    for i in range(0, len(pages), size):
        key, first = pages[i]
        last = pages[min(i + size, len(pages)) - 1][1]
        rows.append((f'/{size}-{key}', f'Pages {first}–{last}' if size != 1 else f'Page {first}', i // size + 1, ''))
    return rows[::-1], False


def twokinds_title(_adapter, url):
    return '/' + urlsplit(url).path.strip('/').split('-', 1)[0]


def twokinds_pages(adapter, http, url):
    size, key = urlsplit(url).path.strip('/').split('-', 1)
    ids = [key]
    if size == '20':
        entries = [value for value, _ in twokinds_list(adapter, http)]
        if key not in entries:
            return '', [], ''
        index = entries.index(key)
        ids = entries[index:index + 20]
    return '', [one_picture(adapter, http, adapter.ROOT + '/comic/' + key + '/', '#content article img') for key in ids], ''


def mayo_api(adapter, http, values=None):
    segment = '/raw' if adapter.LANGUAGE == 'ja' else ''
    endpoint = adapter.ROOT + '/api' + segment + '/chapters'
    return document_json(http, query_url(endpoint, **values) if values else endpoint, adapter.ROOT + '/')


def mayo_chapters(adapter, http, _work, _url):
    data = mayo_api(adapter, http)
    if not isinstance(data, list):
        raise SourceError('MayoTune не предоставил оглавление.')
    out = []
    segment = '/raw' if adapter.LANGUAGE == 'ja' else ''
    for item in data:
        key, number = item.get('id'), numeric(item.get('number'))
        if isinstance(key, str) and re.fullmatch(r'[\w-]{1,120}', key) and number is not None:
            label = f'Chapter {number:g}' + (': ' + item['title'] if item.get('title') else '')
            out.append((query_url(f'{segment}/chapter/{key}', number=f'{number:g}'), label, number, iso(item.get('date'))))
    return sorted(out, key=lambda row: row[2], reverse=True), False


def mayo_pages(adapter, http, url):
    key = urlsplit(url).path.rsplit('/', 1)[-1]
    value = param(url, 'number')
    item = mayo_api(adapter, http, {'id': key, **({'number': value} if value else {})})
    count = item.get('pageCount') if isinstance(item, dict) and item.get('id') == key else 0
    return '', [f'{adapter.ROOT}/api/manga/{key}/{index}' for index in range(1, count + 1)] if type(count) is int and 0 < count <= 500 else [], ''


class MayoTune(Webcomic):
    def stored_target(self, value):
        if isinstance(value, str):
            parts = urlsplit(value)
            if parts.path in {'/api/chapters', '/api//chapters', '/api/raw/chapters'}:
                key, number = param(value, 'id'), param(value, 'number')
                prefix = '/raw' if self.LANGUAGE == 'ja' else ''
                if re.fullmatch(r'[\w-]{1,120}', key):
                    return self.site_link(query_url(f'{prefix}/chapter/{key}', number=number))
        return super().stored_target(value)


class Nikkan(HTML):
    def __init__(self):
        super().__init__('nikkangecchan', Cards('.contentInner > figure', '.imgBox a', '.detailBox:last-of-type h3', next=''),
                         Meta('#comicDetail .detailBox h3', '#comicDetail .imgBox img', '.description', author='#comicDetail .author'),
                         SeriesArchive('.episodeBox'), '', title=rf'/({SEGMENT}(?:/{SEGMENT})?)/?',
                         chapter=rf'/({SEGMENT})(?:/{SEGMENT})+/?')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1 or tag:
            return [], False
        rows, _ = self.card_rows(*self.document(http, self.ROOT + '/'), self.cards)
        return [entry for entry in rows if query.casefold() in entry['title'].casefold()], False

    def chapters(self, http, doc, url):
        out = {}
        for node in doc.select('.episodeBox'):
            page = node.select_one('.episode-page[data-src]')
            anchor = self.site_link(page['data-src'], url) if page else ''
            if not anchor:
                continue
            link = anchor.rstrip('/').rsplit('/', 1)[0]
            title = node_text(node.select_one('h4.episodeTitle'))
            extra = page.get('data-title', '').split('|', 1)[0].strip()
            out[link] = self.chapter(link, ' — '.join(filter(None, (title, extra))), numeric(title), translator='Akita Publishing')
        return self.order(out), False

    def inspect(self, value, http):
        if param(value, 'mv_episode') == '1':
            link = self.site_link(value)
            if not self.is_chapter(link):
                raise SourceError('Некорректная ссылка на выпуск Nikkangecchan.')
            path = urlsplit(link).path
            return self.reader_result(self.record(link, self.NAME), link, [self.chapter(link, n=0)],
                                      [self.ROOT + path.rstrip('/') + '/image'])
        return super().inspect(value, http)

    def chapter(self, url, *args, **kwargs):
        return super().chapter(query_url(url, mv_episode=1), *args, **kwargs)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        return query_url(target, mv_episode=1) if target else ''

    def saved_chapter_matches(self, target, title):
        return self.confirm_archive_membership(target, title)

    def page_headers(self, url):
        parent = urlsplit(self.site_link(url)).path.rstrip('/').rsplit('/', 1)[0]
        return {'Referer': self.ROOT + parent + '/'}


class CutieComics(SeriesPort):
    cards = Cards('#dle-content > div.w25', 'strong.field-content > a', next='.navigation a:has(i.fa-angle-right)')
    meta = Meta('h1#page-title', 'div.galery > img', genres='h3.field-label ~ span')

    def __init__(self):
        super().__init__(IDENTITIES['cutiecomics'], rf'/({SEGMENT})/?', rf'/({SEGMENT})/?', interval=.5)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag or query and len(query) < 4:
            return [], False
        if not query:
            return self.card_rows(*self.document(http, self.ROOT + f'/page/{page}'), self.cards)
        data = {'do': 'search', 'subaction': 'search', 'full_search': '0', 'search_start': str(page),
                'result_from': str((page-1)*20+1), 'story': query}
        text, final, _ = http.document(self.ROOT + '/index.php?do=search', method='POST',
                                       headers={'Referer': self.ROOT + '/'}, action='native-series-form', data=data)
        return self.card_rows(BeautifulSoup(text, 'html.parser'), final, self.cards)

    def inspect(self, value, http):
        url = self.site_link(value)
        target = self.ROOT + urlsplit(url).path
        if not url or not self.is_title(target):
            raise SourceError('Некорректная ссылка галереи.')
        doc, final = self.title_document(http, target)
        row = self.metadata(doc, final, self.meta)
        chapter = query_url(final, mv_gallery=1)
        images = []
        if param(url, 'mv_gallery') == '1':
            images = [picture(node, final) for node in doc.select('div.galery > img')]
            if not images or not all(images):
                raise SourceError('Источник не предоставил страницы галереи.')
        return self.reader_result(row, url, [self.chapter(chapter, 'Chapter', 1)], images)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        return query_url(target, mv_gallery=1) if target else ''


def vinnie(language):
    title = 'CCC: The city of opportunities' if language == 'en' else 'CCC: La ciudad de las oportunidades'
    cover = '/comics/CCCr000E.jpg' if language == 'en' else '/comics/CCCr000.jpg'
    return single('/archiveIndex.php', title, cover, author='Vinnie Veritas', chapters=vinnie_chapters,
                  reader=Reader('img.cccComic.crazylan-' + language), chapter_path=r'/[\w-]+\.php')


def mayo(language):
    title = '真夜中ハートチューン' if language == 'ja' else 'Tune In to the Midnight Heart'
    chapter = '/raw/chapter/' if language == 'ja' else '/chapter/'
    return single('/', title, '/img/cover.jpg', author='Masakuni Igarashi',
                  aliases=('Mayonaka Heart Tune', 'Masakuni Igarashi'), chapters=mayo_chapters, pages=mayo_pages,
                  chapter_path=chapter + r'[\w-]{1,120}', enrich=True,
                  cover_selector='img.object-contain', description_selector='.text-lg')


def hololive_profile(language):
    path = ('/' + language if language != 'ja' else '') + '/alt/holonometria/manga/'
    return Profile(browse=hololive, title_path=path + r'[\w%.-]+/?',
                   chapter_path=path + r'.+', enrich=True,
                   title_selector='.alt-nav__met-sub-link.is-current', cover_selector='.manga-detail__thumb img',
                   description_selector='.manga-detail__caption', author_selector='.manga-detail__person',
                   archive=Archive('.manga-detail__list .manga-detail__list-item a[href]',
                                   title='.manga-detail__list-title', date='.manga-detail__list-date', date_format='%Y.%m.%d'),
                   reader=Reader('.manga-detail__swiper-wrapper img'))


ARCHIVES = {
    **{'holonometria_' + lang: hololive_profile(lang) for lang in ('en', 'id', 'ja')},
    **{'thelibraryofohara_' + lang: Profile(browse=ohara, chapters=ohara_chapters, title_path=r'/category/[\w%/-]+/?',
                                           chapter_path=DATE_POST, reader=Reader('.entry-content a img, .entry-content img.size-full', ('data-orig-file', 'src')),
                                           enrich=True, cover_selector='article img') for lang in OHARA},
    'vinnieVeritas_en': vinnie('en'),
    'vinnieVeritas_es': vinnie('es'),
    'dbnewhope': Profile(
        tuple(Work(f'/{prefix}/{archive}.php', f'DB New Hope ({language})', archive=f'/{prefix}.php')
              for prefix, archive, language in DB),
        chapters=db_chapters, pages=db_pages, title_for=db_title, enrich=True,
        cover_selector='img.masthead-avatar', description_selector='header p.masthead-subheading, section#sagas p',
        chapter_path=r'/(?:english|francais|espanol)/[\w/.-]+/01\.php'),
    'aurora': Profile(browse=aurora_catalogue, chapters=aurora_chapters,
                      reader=Reader('.webcomic-media .webcomic-link .attachment-full'),
                      title_path=POST, chapter_path=POST),
    'reallifecomics': Profile(browse=year_catalogue, chapters=real_life_chapters, reader=Reader('.comic img'),
                             title_path=r'/archivepage\.php', title_query='year',
                             chapter_path=r'/(?:comic|archivepage|index)\.php', chapter_query='comic|date|strip'),
    **{'commitstrip_' + lang: Profile(browse=year_catalogue, chapters=commit_archive, title_for=commit_title,
                                      reader=Reader('.entry-content p img'),
                                      title_path=rf'/{lang}/\d{{4}}/?', chapter_path=f'/{lang}' + DATE_POST) for lang in ('en', 'fr')},
    'grrlpower': single('/archive', 'Grrl Power', 'https://static.tvtropes.org/pmwiki/pub/images/rsz_grrl_power.png',
                        author='David Barrack', chapters=grrl_chapters, reader=Reader('div#comic img', notes='.entry'),
                        chapter_path=r'/(?:comic/|\d{4}/\d{2}/\d{2}/comic/)[\w%-]+/?'),
    'broccolisoup': single('/comic/archive', 'Broccoli Soup', '/assets/images/static/Bocki%20(correct%20size).png',
                          chapters=broccoli_chapters, pages=broccoli_pages, reader=Reader('#comic img'),
                          chapter_path=r'/(?:comic-characters|comic/[\w/.-]+)/?'),
    'thepropertyofhate': single('/', 'The Property of Hate', '/images/Index/tpoh.png', chapters=hate_chapters,
                               pages=hate_pages, chapter_path=r'/TPoH/[\w/.-]+/?'),
    'keenspot': Profile((Work('/1', 'TwoKinds (1 page per chapter)', author='Tom Fischbach'),
                          Work('/20', 'TwoKinds (20 pages per chapter)', author='Tom Fischbach')),
                         chapters=twokinds_chapters, pages=twokinds_pages, title_for=twokinds_title,
                         chapter_path=r'/(?:1|20)-[\w-]+/?'),
}
SOURCES = (*[Webcomic(IDENTITIES[key], profile) for key, profile in ARCHIVES.items()],
           *[MayoTune(IDENTITIES['mayotune_' + lang], mayo(lang)) for lang in ('en', 'ja')],
           Nikkan(), CutieComics())
