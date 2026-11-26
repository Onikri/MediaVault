"""Native profiles for GroupLe and LibGroup catalogues and publicly readable chapters."""

import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from manga_catalog_adapters import LIB, LIB_SITES, get as get_lib, inspect_catalog, lib_context, lib_identity
from manga_madara import SEGMENT, node_text, release_date
from manga_series_port import NUMBER, Meta, SeriesPort, number
from manga_source_tags import from_api, unique
from manga_sources import parse_pages
from manga_webcomics import query_url
from source_parser import SourceAccessError, SourceAuthError, SourceError


GROUPLE = (
    (('5', 'ReadManga', 'ru', 'https://b.zazaza.me', False), ('readmanga.live', 'readmanga.me', 'a.zazaza.me')),
    (('6', 'MintManga', 'ru', 'https://2.mintmanga.one', True), ('mintmanga.live', 'mintmanga.com')),
    (('1809051393403180443', 'AllHentai', 'ru', 'https://20.allhen.online', True), ('allhentai.ru', 'x.ahen.me')),
    (('6340120447386662351', 'SeiManga', 'ru', 'https://1.seimanga.me', True), ('seimanga.me',)),
    (('5227602742162454547', 'SelfManga', 'ru', 'https://1.selfmanga.live', False), ('selfmanga.live', 'selfmanga.ru')),
    (('5705163226489175947', 'Usagi', 'ru', 'https://web.usagi.one', False), ('usagi.one',)),
)
GROUPLE_HOSTS = {urlsplit(identity[3]).hostname for identity, _ in GROUPLE}
LIB_PROFILES = (
    ('6111047689498497237', 1, ('mangalib.org',)),
    ('6425650164840473547', 4, ('hentailib.org',)),
    ('2730544188738947015', 2, ('slashlib.me', 'shlib.life')),
)


def public_api(host, path, query):
    if host not in GROUPLE_HOSTS:
        return False
    if path == '/api/catalog/elementsByType':
        return query in {'type=2', 'type=40'}
    if path != '/api/catalog/search':
        return False
    try:
        args = parse_qs(query, max_num_fields=4)
    except ValueError:
        return False
    return (set(args) <= {'offset', 'sortType', 'q', 'includeElementIds'}
            and len(args.get('offset', [])) == 1 and bool(re.fullmatch(r'\d{1,6}', args['offset'][0]))
            and args.get('sortType') in (['RATING'], ['DATE_UPDATE'])
            and ('q' not in args or len(args['q']) == 1 and len(args['q'][0]) <= 160)
            and ('includeElementIds' not in args or len(args['includeElementIds']) == 1
                 and bool(re.fullmatch(r'\d{1,12}', args['includeElementIds'][0]))))


class GroupLe(SeriesPort):
    def __init__(self, identity, aliases):
        super().__init__(identity, rf'/({SEGMENT})/?', rf'/({SEGMENT})/vol[0-9]{{1,5}}/{NUMBER}(?:/[^/]+)?/?',
                         legacy_hosts=aliases, interval=.35)
        tags = '.cr-tags .cr-tags__item' if self.NAME == 'AllHentai' else '.creation-element-tags .creation-element-tags__item'
        self.meta = Meta('.cr-hero-names__main', '.cr-hero img[itemprop=image], .cr-hero-pic img, .cr-hero img',
                         '.cr-description__content', '#alt-names-dialog .modal-body',
                         '.cr-hero-short-details a[href*="/list/genre/"]',
                         tags + ':not([class$="--misc"]) span:not(.text-secondary)',
                         '.cr-main-person-item:has(.cr-main-person-item__role:-soup-contains("автор", "Автор")) .cr-main-person-item__name')

    def is_title(self, url):
        return super().is_title(url) and self.title_key(url) not in {'search', 'list', 'api', 'login', 'catalogue'}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'offset': (page - 1) * 50, 'sortType': 'DATE_UPDATE' if sort == 'updated' else 'RATING'}
        if query:
            args['q'] = query
        if tag:
            if not re.fullmatch(r'\d{1,12}', tag):
                raise SourceError('Некорректный фильтр GroupLe.')
            args['includeElementIds'] = tag
        url = self.ROOT + '/api/catalog/search?' + urlencode(args)
        data = self.json(http, url)
        if not isinstance(data, dict) or not isinstance(data.get('list'), list):
            raise SourceError('GroupLe не предоставил каталог.')
        result = {}
        for entry in data['list']:
            link = (entry.get('elementId') or {}).get('linkName')
            title = entry.get('name')
            if isinstance(link, str) and re.fullmatch(SEGMENT, link) and title:
                identifier = self.ROOT + '/' + link
                result[link] = self.record(identifier, title, entry.get('picUrl'))
        offset = data.get('offset', args['offset'])
        limit = data.get('limit', 50)
        total = data.get('total', 0)
        more = bool(result and all(type(v) is int for v in (offset, limit, total)) and offset + limit < total)
        return list(result.values()), more

    def vocabulary(self, http):
        result = []
        for kind, category in ((2, 'genre'), (40, 'tag')):
            data = self.json(http, self.ROOT + f'/api/catalog/elementsByType?type={kind}')
            for item in data.get('results', []) if isinstance(data, dict) else []:
                if item.get('text') and str(item.get('id', '')).isdigit():
                    result.append({'label': item['text'], 'sourceId': str(item['id']), 'category': category})
        return result

    def metadata(self, doc, url, spec):
        title = doc.select_one('.cr-hero-names__main')
        if not title and (meta := doc.select_one('meta[itemprop=name][content]')):
            title = doc.new_tag('span', attrs={'class': 'cr-hero-names__main'})
            title.string = meta['content']
            doc.append(title)
        result = super().metadata(doc, url, spec)
        result['aliases'] = unique([result['title'], *(node_text(e) for e in doc.select('#alt-names-dialog .modal-body .py-1'))])
        return result

    def chapters(self, http, doc, url):
        slug = self.title_key(url)
        result = {}
        for row in doc.select('tr.item-row:has(td > a):has(td.date:not(.text-info))'):
            a, field = row.select_one('a.chapter-link[href]'), row.select_one('td.item-title[data-num]')
            target = self.site_link(a['href'], url) if a else ''
            if not self.is_chapter(target) or self.chapter_key(target) != slug:
                continue
            identity = urlsplit(target).path.rstrip('/')
            target = query_url(self.ROOT + identity, mtr='true')
            n = number(field['data-num']) if field else None
            dates = row.select('td.d-none')
            date = release_date(node_text(dates[-1]) if dates else '', '%d.%m.%Y')
            result[identity] = self.chapter(target, node_text(a), n / 10 if n is not None else None,
                                            date, translator=a.get('title', '').removesuffix(' (Переводчик)').removesuffix(' Переводчик'))
        return self.order(result), False

    def pages(self, http, url):
        target = query_url(urlunsplit(urlsplit(url)._replace(query='', fragment='')), mtr='true')
        try:
            doc, final = self.page_document(http, target)
        except SourceAccessError:
            raise
        except SourceError as error:
            # AllHentai answers every chapter with 404 and placeholder images
            # to guests (checked 2026-11-26 on two titles); only signed-in
            # readers get the pages. MediaVault never signs in for a source.
            if self.NAME == 'AllHentai' and getattr(error, 'http_status', None) == 404:
                raise SourceAuthError('AllHentai показывает главы только вошедшим читателям.') from None
            raise
        if doc.select_one('div.alert, h1:-soup-contains("требуется премиум")'):
            raise SourceAccessError('Выпуск требует доступ на стороне GroupLe.')
        return parse_pages(str(doc), final)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if not target:
            return ''
        # Old extension URLs can contain an account-specific user hash.
        return query_url(urlunsplit(urlsplit(target)._replace(query='', fragment='')), mtr='true')


class LibGroup(SeriesPort):
    def __init__(self, sid, site_id, legacy_hosts):
        _, name, root = LIB_SITES[site_id]
        name = 'SlashLib' if site_id == 2 else name
        super().__init__((sid, name, 'ru', root, True), rf'/ru/(?:manga/)?({SEGMENT})/?',
                         rf'/ru/(?:manga/)?({SEGMENT})/read/v[0-9]{{1,5}}/c{NUMBER}/?', legacy_hosts=legacy_hosts)
        self.site_id = site_id

    def display_url(self, slug):
        return self.ROOT + '/ru/' + slug

    def api(self, http, path, params=()):
        return get_lib(LIB + path + ('?' + urlencode(params) if params else ''), lib_context(http, self.site_id))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = [('site_id[]', self.site_id), ('page', page)]
        if query:
            args.append(('q', query))
        if tag:
            category, sep, term = tag.partition(':')
            if not sep or category not in {'genres', 'tags'} or not term.isdecimal():
                raise SourceError('Некорректный фильтр LibGroup.')
            args.append((category + '[]', term))
        if sort == 'updated' and not query and not tag:
            args.extend([('sort_by', 'last_chapter_at'), ('sort_type', 'desc')])
        data = self.api(http, '/api/manga', args)
        raw = data.get('data')
        if not isinstance(raw, list):
            raise SourceError('LibGroup не предоставил каталог.')
        output = []
        for entry in raw:
            slug = entry.get('slug_url')
            if isinstance(slug, str) and re.fullmatch(SEGMENT, slug):
                output.append(self.item(entry, slug))
        meta = data.get('meta') or {}
        more = bool((data.get('links') or {}).get('next') or (type(meta.get('last_page')) is int and page < meta['last_page']))
        return output, more

    def item(self, entry, slug):
        aliases = unique([entry.get('rus_name'), entry.get('name'), entry.get('eng_name'), *(entry.get('otherNames') or [])])
        terms = from_api(entry)
        cover = entry.get('cover') or {}
        result = self.record(self.display_url(slug), aliases[0] if aliases else slug, cover.get('default', ''),
                             aliases=aliases, description=entry.get('summary') or '', **terms)
        return {**result, **lib_identity(entry), 'adult': self.site_id == 4}

    def vocabulary(self, http):
        args = [('fields[]', kind) for kind in ('genres', 'tags')]
        data = self.api(http, '/api/constants', args).get('data', {})
        result = []
        for kind, category in (('genres', 'genre'), ('tags', 'tag')):
            for item in data.get(kind, []):
                name = item.get('name') or item.get('label')
                if name and str(item.get('id', '')).isdigit():
                    result.append({'label': name, 'sourceId': f'{kind}:{item["id"]}', 'category': category})
        return result

    def details(self, http, url):
        target = self.saved_title_url(url)
        slug = self.title_key(target)
        if not slug:
            raise SourceError('Некорректный тайтл LibGroup.')
        params = [('fields[]', field) for field in ('otherNames', 'eng_name', 'genres', 'tags', 'summary')]
        entry = self.api(http, '/api/manga/' + slug, params).get('data')
        if not isinstance(entry, dict) or entry.get('slug_url', slug) != slug:
            raise SourceError('LibGroup вернул карточку другого произведения.')
        return self.item(entry, slug)

    def inspect(self, url, http):
        target = self.canonical(url)
        slug = self.title_key(target) or self.chapter_key(target)
        if not slug:
            raise SourceError('Некорректная ссылка LibGroup.')
        parts = urlsplit(target)
        path = parts.path.replace('/ru/manga/', '/ru/', 1)
        target = self.ROOT + urlunsplit(('', '', path, parts.query, ''))
        value = inspect_catalog(target, http)
        result = self.record(self.display_url(slug), value['title'], aliases=value.get('aliases', ()),
                             genres=value.get('genres', ()), tags=value.get('tags', ()))
        chapters = [{**row, 'url': self.reader_url(row['url'])} for row in value['episodes']]
        return self.reader_result(result, target, chapters, value['pages'], value.get('truncated', False))

    def saved_title_url(self, value):
        url = self.canonical(value)
        return self.display_url(self.title_key(url)) if self.is_title(url) else ''

    def saved_chapter(self, row, root, title):
        value = row.get('realUrl') or row.get('url') or ''
        if isinstance(value, str) and (match := re.match(r'^/?([\w-]+)/chapter\?', value)):
            slug = match[1]
            query = parse_qs(urlsplit(value).query)
            volume, chapter = query.get('volume', [''])[0], query.get('number', [''])[0]
            if slug == self.title_key(title) and volume.isdecimal() and re.fullmatch(NUMBER, chapter):
                result = self.display_url(slug) + f'/read/v{volume}/c{chapter}'
                branch = query.get('branch_id', [''])[0]
                return query_url(result, bid=branch) if branch.isdecimal() else result
            return ''
        return super().saved_chapter(row, root, title)


SOURCES = (*[GroupLe(*profile) for profile in GROUPLE], *[LibGroup(*profile) for profile in LIB_PROFILES])
