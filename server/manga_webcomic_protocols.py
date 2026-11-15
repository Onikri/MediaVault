"""Source-specific archive and reader protocols for independent webcomics."""

from datetime import UTC, datetime
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_webcomics import Work, numeric, param, query_url
from source_parser import SourceError


def public_api(host, path, query):
    """Limit public JSON transport to protocol routes used by these adapters."""
    if host == 'arknights.global':
        if path == '/api/resource/comic/list':
            return not query
        try:
            args = parse_qs(query, max_num_fields=4)
        except ValueError:
            return False
        return (path == '/api/resource/comic/details'
                and set(args) in ({'name', 'index', 'size'}, {'name', 'index', 'size', 'chapter'})
                and args.get('index') == ['1'] and args.get('size') == ['9999']
                and len(args.get('name', ())) == 1 and 1 <= len(args['name'][0]) <= 300
                and ('chapter' not in args or len(args['chapter']) == 1 and bool(re.fullmatch(r'\d{1,9}', args['chapter'][0]))))
    if host == 'readbagabondo.com':
        if path == '/api/mihon/mangas':
            try:
                args = parse_qs(query, max_num_fields=2)
            except ValueError:
                return False
            return (not query or set(args) == {'q', 'page'} and len(args['q']) == len(args['page']) == 1
                    and 1 <= len(args['q'][0]) <= 160 and bool(re.fullmatch(r'\d{1,4}', args['page'][0])))
        return not query and bool(re.fullmatch(r'/api/mihon/mangas/\d{1,9}(?:/chapters(?:/\d{1,9})?)?', path))
    if host in {'www.kunmanga.online', 'www.zinmanga.net'}:
        if not re.fullmatch(rf'/api/comics/{SEGMENT}/chapters', path):
            return False
        return bool(re.fullmatch(r'page=(?:[1-9]\d?|100)&per_page=(?:50|100)&order=desc', query))
    if query:
        return False
    if host == 'manga.honkaiimpact3.com':
        return bool(re.fullmatch(r'/book/\d{1,9}/get_chapter', path))
    if host == 'sas-api.fly.dev':
        return bool(re.fullmatch(r'/page(?:/\d{1,9})?', path))
    if host == 'thegirlfromrandomchatting.com':
        return path == '/wp-json/mg/v1/chapters-list'
    if host == 'loadingartist.com':
        return path == '/search.json'
    return False


def rows(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise SourceError('Некорректный список в каталоге комиксов.')
    return value


def date(value, template='%Y-%m-%d'):
    return release_date(str(value or '')[:10], template)


def image_list(values, base):
    return [image_url(value, base) for value in values] if isinstance(values, list) else []


def html_catalogue(adapter, http, page, query, tag, *, path, cards, title, covers='', search='', local=False, next_page=''):
    if tag or page > 1 and not next_page:
        return (), False
    if search and query:
        path = query_url(search, q=query)
    doc, final = adapter.document(http, adapter.ROOT + path)
    works = []
    for card in doc.select(cards):
        anchor = card if card.name == 'a' else card.select_one('a[href]')
        target = adapter.site_link(anchor.get('href'), final) if anchor else ''
        label = node_text(card.select_one(title)) if title else node_text(anchor)
        if not target or not label or local and query.casefold() not in label.casefold():
            continue
        picture = card.select_one(covers) if covers else None
        cover = image_url(picture.get('data-src') or picture.get('src'), final) if picture else ''
        if picture and not cover:
            match = re.search(r'url\([\'"]?([^\'")]+)', picture.get('style', ''))
            cover = image_url(match[1], final) if match else ''
        works.append(Work(target, label, cover, node_text(card.select_one('h4'))))
    return works, bool(next_page and doc.select_one(next_page))


def clone_catalogue(adapter, http, page, query, _sort, tag):
    return html_catalogue(adapter, http, page, query, tag, path='/viewer_landing.php',
                          cards='.comicPreviewContainer', title='h3', covers='.comicPreview', local=True)


def clone_archive(adapter, http, _work, title):
    doc, final = adapter.document(http, title)
    scripts = doc.select('script')
    values = re.findall(r'&page=(\d+)&lang=', scripts[3].get_text() or scripts[3].string or '') if len(scripts) > 3 else []
    return numbered_query(final, 'page', int(values[3]) if len(values) > 3 else 0)


def clone_identity(_adapter, url):
    return re.sub(r'([?&])page=\d+(?:&|$)', r'\1', url).rstrip('?&')


def honkai_catalogue(adapter, http, page, query, _sort, tag):
    return html_catalogue(adapter, http, page, query, tag, path='/book', cards='a[href*="book"]',
                          title='.container-title', covers='.container-cover img', local=True)


def honkai_archive(adapter, http, _work, title):
    path = urlsplit(title).path.rstrip('/')
    result = []
    for item in rows(adapter.json(http, path + '/get_chapter')):
        number = numeric(item.get('chapterid'))
        if number is not None and str(item.get('bookid')) == path.rsplit('/', 1)[-1]:
            result.append((f'{path}/{int(number)}', item.get('title') or '', number, date(item.get('timestamp'))))
    return result, False


def parent_path(_adapter, url):
    return urlsplit(url).path.rstrip('/').rsplit('/', 1)[0]


def numbered_query(url, key, count):
    return [(query_url(url, **{key: n}), str(n), n, '') for n in range(min(count, 10000), 0, -1)], count > 10000


def supermega_archive(adapter, http, _work, title):
    doc, final = adapter.document(http, title)
    previous = doc.select_one('a:has([name="bigbuttonprevious"])')
    link = adapter.site_link(previous.get('href'), final) if previous else ''
    last = numeric(param(link, 'i'))
    return numbered_query(title, 'i', int(last) + 1 if last is not None else 0)


def collected_archive(adapter, http, _work, title):
    doc, final = adapter.document(http, title)
    last = doc.select_one('a:has(img[title="Last"])')
    jump = doc.select_one('input[title="Jump to number"]')
    back = doc.select_one('a:has(img[title="Back one"])')
    count = numeric(param(adapter.site_link(last['href'], final), 's')) if last and last.get('href') else None
    if count is None and jump:
        count = numeric(jump.get('value'))
    if count is None and back and back.get('href'):
        count = (numeric(param(adapter.site_link(back['href'], final), 's')) or 0) + 1
    return numbered_query(title, 's', int(count or 0))


def collected_identity(_adapter, url):
    return urlsplit(url).path


def loading_archive(adapter, http, _work, _title):
    return [(row.get('url'), row.get('title') or '', None, date(row.get('date')))
            for row in rows(adapter.json(http, '/search.json')) if row.get('section') in {'comic', 'game', 'art'}], False


def darklegacy_archive(adapter, http, _work, title):
    if urlsplit(title).path.startswith('/specials/'):
        names = ('Looking For Group', 'Rover', 'Fan Comic')
        return [(f'/specials/{i}', name, i, '2014-05-12') for i, name in reversed(list(enumerate(names, 1)))], False
    doc, _ = adapter.document(http, title)
    result = {}
    for node in doc.select('.archive_link'):
        raw = node_text(node.select_one('.index'))
        if raw.isdecimal():
            label = node_text(node.select_one('.name'))
            published = node_text(node.select_one('.date'))
            published = date('2015-09-20') if published == 'Sep 20' else (
                release_date(published, '%B %d, %Y') or release_date(published, '%b %d, %Y'))
            result[int(raw)] = (f'/{raw}', f'#{raw}: {label}', int(raw), published)
    return [row for _, row in sorted(result.items(), reverse=True)], False


def darklegacy_identity(_adapter, url):
    return '/specials/1.php' if urlsplit(url).path.startswith('/specials/') else '/archive'


def egs_archive(adapter, http, _work, title):
    doc, final = adapter.document(http, title)
    result = []
    group = urlsplit(title).path.split('/')[1]
    for node in doc.select('select[name=comic] option[value]'):
        url = adapter.site_link('/' + node['value'].lstrip('/'), final)
        if urlsplit(url).path.split('/')[1:2] == [group] and adapter.is_chapter(url):
            published, sep, label = node_text(node).partition(' - ')
            result.append((url, label if sep else published, None, release_date(published, '%B %d, %Y')))
    return result[::-1], False


def egs_identity(_adapter, url):
    return '/' + urlsplit(url).path.split('/')[1] + '/archive'


def vision_archive(adapter, http, _work, _title):
    doc, final = adapter.document(http, adapter.ROOT + '/archive/')
    result = []
    for head, group in zip(doc.select('.archive'), doc.select('.archivepayload')):
        title = node_text(head.select_one('b'))
        for a in group.select('a[href]'):
            target = adapter.site_link(a['href'], final)
            number = numeric(param(target, 'p'))
            if number is not None:
                result.append((target, f'Page {node_text(a)} - {title}', number, ''))
    return result[::-1], False


def vision_pages(adapter, _http, url):
    page = numeric(param(url, 'p'))
    if page is None:
        return '', [], ''
    return '', [f'{adapter.ROOT}/comic/p{int(page):03d}.png'], ''


def solar_archive(adapter, http, _work, _title):
    return [(f'/page/{number}', row.get('name') or '', number, date(row.get('published_at')))
            for row in reversed(rows(adapter.json(http, '/page')))
            if isinstance((number := row.get('page_number')), int) and number >= 0], False


def solar_pages(adapter, http, url):
    item = adapter.json(http, urlsplit(url).path)
    if not isinstance(item, dict) or str(item.get('page_number')) != urlsplit(url).path.rsplit('/', 1)[-1]:
        raise SourceError('API вернул другую страницу Solar and Sundry.')
    return item.get('name') or '', [image_url(item.get('image_url'), adapter.ROOT)], ''


def randowis_archive(adapter, http, _work, title):
    from manga_webcomics import Archive
    doc, final = adapter.document(http, title)
    return adapter.archive_rows(http, Archive('.has-post-thumbnail .elementor-post__title a[href]', next_page='a.next'), doc, final)


def random_chat_archive(adapter, http, _work, _title):
    output = []
    for item in rows(adapter.json(http, '/wp-json/mg/v1/chapters-list')):
        title = str(item.get('title') or '').split(', ', 1)[-1]
        found = re.search(r'Chapter\s+(\d+(?:\.\d+)?)', title, re.I)
        output.append((item.get('url'), title, numeric(found[1]) if found else None, date(item.get('date'))))
    return output, False


def arknights_rows(adapter, http, endpoint):
    data = adapter.json(http, endpoint)
    return rows(data.get('data', {}).get('rows') if isinstance(data, dict) and isinstance(data.get('data'), dict) else None)


def arknights_catalogue(adapter, http, page, query, _sort, tag):
    if page != 1 or tag:
        return (), False
    result = []
    for item in arknights_rows(adapter, http, '/api/resource/comic/list'):
        name, cover = item.get('name'), item.get('smallImage')
        if not isinstance(name, str) or not name or query.casefold() not in name.casefold():
            continue
        if isinstance(cover, list):
            cover = cover[0] if cover else ''
        description = node_text(BeautifulSoup(item.get('comicDescribe') or '', 'html.parser'))
        result.append(Work(query_url('/comic', name=name), name, cover, description))
    return result, False


def arknights_chapters(adapter, http, url, **extra):
    name = param(url, 'name')
    if not name or len(name) > 300:
        raise SourceError('Некорректное название Arknights Comics.')
    return [row for row in arknights_rows(adapter, http, query_url('/api/resource/comic/details', name=name, index=1, size=9999, **extra))
            if row.get('name') == name and isinstance(row.get('chapter'), int)]


def arknights_archive(adapter, http, _work, title):
    result = []
    for row in sorted(arknights_chapters(adapter, http, title), key=lambda entry: entry['chapter'], reverse=True):
        timestamp = row.get('publishTime')
        published = datetime.fromtimestamp(timestamp / 1000, UTC).date().isoformat() if isinstance(timestamp, int) and 0 < timestamp < 5000000000000 else ''
        result.append((query_url('/comic-detail', name=row['name'], chapter=row['chapter']),
                       row.get('detailsName') or '', row['chapter'], published))
    return result, False


def arknights_pages(adapter, http, url):
    chapter = param(url, 'chapter')
    matches = [row for row in arknights_chapters(adapter, http, url, chapter=chapter) if str(row['chapter']) == chapter]
    if not matches:
        return '', [], ''
    return matches[0].get('detailsName') or '', [
        page for row in matches for page in image_list(row.get('detailsContent'), adapter.ROOT)
    ], ''


def arknights_identity(_adapter, url):
    return query_url('/comic', name=param(url, 'name'))


def vagabond_catalogue(adapter, http, page, query, _sort, tag):
    if (page > 1 and not query) or tag:
        return (), False
    path = query_url('/api/mihon/mangas', q=query, page=page) if query else '/api/mihon/mangas'
    return [Work(f'/#{row["id"]}', row['title'], row.get('cover'), row.get('description') or '', row.get('author') or '')
            for row in rows(adapter.json(http, path)) if isinstance(row.get('id'), int) and row.get('title')], False


def vagabond_identity(_adapter, url):
    return '/#' + urlsplit(url).fragment


def vagabond_archive(adapter, http, _work, title):
    identity = urlsplit(title).fragment
    if not identity.isdecimal():
        return [], False
    result = []
    for row in rows(adapter.json(http, f'/api/mihon/mangas/{identity}/chapters')):
        number = row.get('number')
        volume = row.get('volume') or 'null'
        if isinstance(number, int) and str(row.get('mangaId')) == identity:
            result.append((f'/volume-{volume}/chapter-{number}/#{identity}', row.get('title') or '', number, date(row.get('releaseDate'))))
    return result, False


def vagabond_pages(adapter, http, url):
    parts = urlsplit(url)
    number = parts.path.rstrip('/').split('-')[-1]
    if not parts.fragment.isdecimal() or not number.isdecimal():
        return '', [], ''
    data = adapter.json(http, f'/api/mihon/mangas/{parts.fragment}/chapters/{number}')
    if (not isinstance(data, dict) or str(data.get('number')) != number
            or str(data.get('mangaId')) != parts.fragment or type(data.get('pageCount')) is not int):
        raise SourceError('API вернул другую главу Read Vagabond Manga.')
    total = data['pageCount']
    return data.get('title') or '', [
        f'https://pub.moleve.net/chapter-{number}/page-{i}.png' for i in range(1, total + 1)
    ] if 1 <= total <= 500 else [], ''


def patch_archive(adapter, http, _work, _title):
    seen, result, before = set(), [], None
    for _ in range(80):
        path = query_url('/search/', search='', id=before) if before else '/search/?search='
        doc, final = adapter.document(http, adapter.ROOT + path)
        added = []
        for a in doc.select('div > div > div:first-of-type > a[href]'):
            target = adapter.site_link(a['href'], final)
            if not re.fullmatch(r'/\d+/?', urlsplit(target).path) or target in seen:
                continue
            seen.add(target)
            n = int(urlsplit(target).path.strip('/'))
            added.append(n)
            result.append((target, node_text(a), n, ''))
        if not added or min(added) <= 1:
            return result, False
        before = min(added)
    return result, True


def vgperson_catalogue(adapter, http, page, query, _sort, tag):
    works, more = html_catalogue(adapter, http, page, query, tag, path='/other/mangaviewer.php',
                                 cards='.content a[href^="?m"]', title='', local=True)
    covers = {'The Festive Monster\'s Cheerful Failure': 'kEK10GL.png',
              'Azure and Claude': 'buXnlmh.jpg', 'Three Days of Happiness': 'kL5dvnp.jpg'}
    return [Work(work.path, work.title, 'https://i.imgur.com/' + covers[work.title] if work.title in covers else '') for work in works], more


def vgperson_archive(adapter, http, _work, title):
    doc, final = adapter.document(http, title)
    result = []
    for tr in doc.select('.chaptertable tbody tr, .chaptertable > tr'):
        a = tr.select_one('td > a[href]')
        if not a:
            continue
        target = adapter.site_link(a['href'], final)
        if param(target, 'm') != param(title, 'm'):
            continue
        number = numeric(param(target, 'c'))
        bonus = numeric(param(target, 'b'))
        label = ' - '.join(filter(None, (node_text(a), node_text(tr.select_one('td:last-child:not(:first-child)')).removeprefix('- '))))
        result.append((target, label, 16.5 + bonus / 10 if number is None and bonus is not None else number, ''))
    return result[::-1], False


def vgperson_identity(_adapter, url):
    return query_url('/other/mangaviewer.php', m=param(url, 'm'))


def nux_catalogue(adapter, http, page, query, _sort, tag):
    return html_catalogue(adapter, http, page, query, tag, path='/', cards='.index-post',
                          title='.post-title a', covers='.post-thumb', search='/search')


def nux_pages(adapter, http, url):
    name, pages, notes = adapter.pages(http, query_url(url, m=0))
    return name, [page for page in pages if not any(word in urlsplit(page).path.casefold()
                                                    for word in ('logo', 'footer', 'credit'))], notes


def sandra_archive(adapter, http, _work, title):
    doc, final = adapter.document(http, title)
    result, last = [], 0
    for a in reversed(doc.select('#column a[href]')):
        target = adapter.site_link(a['href'], final)
        if not adapter.is_chapter(target):
            continue
        label = a.get('title', '').removeprefix('Permanent Link:').strip() or node_text(a)
        found = re.search(r'\[(?:[^\]]*?)(\d{4})\]', label)
        last = int(found[1]) if found else (last + int(last + 1)) / 2
        published = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', target)
        result.append((target, label, last, '-'.join(published.groups()) if published else ''))
    return result[::-1], False


def single_madara_archive(adapter, http, _work, title):
    doc, final = adapter.document(http, title)
    battle = adapter.NAME.startswith('Battle')
    dates = {}
    if battle:
        for item in doc.select('.chapter-item:has(a[href])'):
            href = adapter.site_link(item.select_one('a[href]')['href'], final)
            dates[urlsplit(href).path.rstrip('/').rsplit('/', 1)[-1]] = node_text(item.select_one('.post-on'))
    result = []
    for item in doc.select('.main-chapter' if battle else 'li.m-chapter'):
        a = item.select_one('a[href]' if battle else 'a[href]:has(.chapter-content)')
        if not a:
            continue
        href = adapter.site_link(a['href'], final)
        if not href:
            continue
        slug = urlsplit(href).path.rstrip('/').rsplit('/', 1)[-1]
        label = node_text(item.select_one('.chapter-content')).split(', ', 1)[-1]
        found = re.search(r'(?:chapter|ch)[-\s]*(\d+(?:[.,]\d+)?)', label + ' ' + slug, re.I)
        published = dates.get(slug) if battle else node_text(item.select_one('.chapter-release-date'))
        result.append((f'/manga/{slug}/', label, numeric(found[1]) if found else None, release_date(published or '', '%B %d, %Y')))
    return result, False


def single_madara_pages(adapter, http, url):
    from manga_madara import Madara

    source = Madara(adapter.SOURCE_ID, adapter.NAME, adapter.ROOT, adapter.IS_NSFW)
    pages, _ = source.pages(http, url, urlsplit(url).path)
    return '', pages, ''
