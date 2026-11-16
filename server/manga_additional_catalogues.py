"""Native catalogue and reader for MangaMen and SilentQuill."""

import json
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_catalogues import SERIES, SERIES_CHAPTER, SLUG
from manga_html_archives import LinkedArchive
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_CHAPTERS, MAX_PAGES, Meta, SeriesPort, number, picture
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceError


KIND = {'Манхва': 'manhwa', 'Маньхуа': 'manhua', 'Комикс': 'comic', 'Манга': 'manga'}
SETTER = re.compile(r'\bwindow\.(?P<key>__DATA__|__pg)\s*=\s*')
URL_CSS = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""")
QUILL = 'silentquill.net'
ID = r'[1-9]\d{0,13}'


def public_rsc(host, path, query):
    if host != QUILL:
        return False
    if path == '/search/':
        fields = parse_qsl(query, keep_blank_values=True)
        args = dict(fields)
        return (len(fields) == len(args) and {'q', 'page'} <= set(args) <= {'q', 'page', 'genre'}
                and len(args['q']) <= 160 and bool(re.fullmatch(ID, args['page']))
                and ('genre' not in args or bool(re.fullmatch(SEGMENT, args['genre']))))
    return not query and (path == '/' or bool(re.fullmatch(SERIES_CHAPTER, path)))


def script_value(doc, key):
    for script in doc.select('script:not([src])'):
        text = script.string or ''
        for match in SETTER.finditer(text):
            if match['key'] == key:
                try:
                    return json.JSONDecoder().raw_decode(text, match.end())[0]
                except (ValueError, RecursionError):
                    break
    raise SourceError('Источник изменил данные веб-читалки.')


class MangaMen(LinkedArchive):
    meta = Meta('h1[itemprop=name], h1', '.manga__image img.manga__cover, .manga__image img', '.info-desc__content',
                'h4[itemprop=alternativeHeadline]', genres='a[href*="genres[include]"]', tags='a[href*="tags[include]"]')

    def __init__(self, identity):
        super().__init__(identity, rf'/{SLUG}/?', rf'/{SLUG}/{SEGMENT}(?:/{SEGMENT}){{0,4}}/?', interval=.35)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        fields = {node_text(node.select_one('strong')): node_text(node.select_one('span'))
                  for node in doc.select('.info-list__row')}
        author = fields.get('Автор', '')
        row.update(format=KIND.get(fields.get('Тип'), 'manga'), authors=[author] if author else [],
                   status=fields.get('Статус тайтла', ''))
        cover = picture(doc.select_one(self.meta.cover), url, ('data-src',))
        if cover and not urlsplit(cover).path.endswith('/preroll.svg'):
            row['cover'] = cover
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'sort': 'last_chapter_at' if sort == 'updated' else 'views', 'dir': 'desc', 'page': page}
        if query:
            args['q'] = query
        section, _, value = tag.partition(':')
        if section in ('genres', 'tags') and re.fullmatch(ID, value):
            args[f'{section}[include][]'] = value
        doc, final = self.document(http, query_url(self.ROOT + '/manga-list', **args))
        rows = {}
        for node in doc.select('a.media-card[href]'):
            url, title = self.site_link(node['href'], final), node_text(node.select_one('.media-card__title'))
            if not self.is_title(url) or not title:
                continue
            match = URL_CSS.search(node.get('style') or '')
            cover = node.get('data-src') or (match[1] if match else '')
            rows[url] = self.record(url, title, image_url(cover, final))
        return list(rows.values()), len(rows) >= 30

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/manga-list')
        data = script_value(doc, '__DATA__')
        filters = (data.get('filters') or data.get('data') or data) if isinstance(data, dict) else {}
        rows = []
        for section in ('genres', 'tags'):
            for item in (filters.get(section.upper()) or filters.get(section) or ()):
                if isinstance(item, dict):
                    key = str(item.get('id') or item.get('value') or '')
                    label = item.get('name') or item.get('label') or item.get('title')
                    if isinstance(label, str) and re.fullmatch(ID, key):
                        rows.append({'label': label, 'sourceId': f'{section}:{key}',
                                     'category': 'genre' if section == 'genres' else 'tag'})
        return rows

    def series(self, http, url):
        doc, final = self.title_document(http, url)
        result = self.metadata(doc, final, self.meta)
        rows = {}
        for node in doc.select('.chapter-item:has(.chapter-item__name a[href])'):
            anchor = node.select_one('.chapter-item__name a[href]')
            target = self.site_link(anchor['href'], final)
            if not self.CHAPTER_PATH.fullmatch(urlsplit(target).path):
                continue
            target = query_url(target, mv_title=urlsplit(final).path)
            n, volume = number(node.get('data-number')), number(node.get('data-volume'))
            date = release_date(node_text(node.select_one('.chapter-item__date')), '%d.%m.%Y')
            group = node_text(node.select_one('.chapter-item__added span'))
            rows[target] = self.chapter(target, node_text(anchor), n, date, int(volume) if volume else 1, group)
        return result, self.order(rows)

    def pages(self, http, url):
        doc, final = self.chapter_document(http, url)
        payload = script_value(doc, '__pg')
        if not isinstance(payload, list) or len(payload) > MAX_PAGES:
            raise SourceError('MangaMen изменил список изображений главы.')
        data = [(number(item.get('p')), image_url(item.get('u'), final)) for item in payload if isinstance(item, dict)]
        if len(data) != len(payload) or any(index is None or not url for index, url in data):
            raise SourceError('MangaMen не предоставил все изображения главы.')
        return [url for _, url in sorted(data)]


def flight_objects(raw):
    models = flight_models(flight_stream(raw))
    return [node for model in models.values() for node in dictionaries(resolve_fields(model, models, [50000]))]


class SilentQuill(SeriesPort):
    meta = Meta('h1', 'main img[src^="/img/"]', 'div.reader-content',
                genres='a[href^="/search/?genre="]', author='p.mt-2.text-sm.text-ink-dim',
                status='dt:-soup-contains-own("Status") + dd')

    def __init__(self, identity):
        super().__init__(identity, SERIES, SERIES_CHAPTER, interval=.35)

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url) + '/'

    def saved_title_url(self, value):
        target = self.canonical(value)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/series/' + key + '/' if re.fullmatch(SEGMENT, key) else ''

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if self.is_chapter(value):
            return value
        key = urlsplit(value).path.strip('/')
        if self.is_title(title) and re.fullmatch(ID, key):
            return query_url(title.rstrip('/') + '/chapter-' + key + '/', mv_id=key, mv_saved=1)
        return ''

    def chapter_identity(self, url):
        tag = param(url, 'mv_id')
        return tag or super().chapter_identity(url)

    def flight(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'}, action='native-series-rsc')
        if final != url:
            raise SourceError('SilentQuill перенаправил на неизвестный маршрут.')
        return flight_objects(raw)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        is_top = not query and not tag and sort == 'popular'
        if is_top and page > 1:
            return [], False
        args = {'q': query, 'page': page}
        if re.fullmatch(SEGMENT, tag):
            args['genre'] = tag
        target = self.ROOT + '/' if is_top else query_url(self.ROOT + '/search/', **args)
        rows, more = {}, False
        for node in self.flight(http, target):
            if not is_top and param(node.get('href', '') if isinstance(node.get('href'), str) else '', 'page') == str(page + 1):
                more = True
            if 'grid-cols' not in str(node.get('className') or '') or not isinstance(node.get('children'), list):
                continue
            children = node['children']
            for card in children:
                for props in dictionaries(card):
                    href = self.site_link(props.get('href'))
                    if not self.is_title(href):
                        continue
                    image = next((t for t in dictionaries(props) if t.get('alt') and t.get('src')), {})
                    if image and isinstance(image['alt'], str):
                        rows[href] = self.record(href, image['alt'], image_url(image['src'], target))
        return list(rows.values()), bool(rows and more)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and param(url, 'mv_saved') == '1':
            title = self.title_for(url)
            result = super().inspect(title, http)
            for chapter in result['episodes']:
                target = self.site_link(chapter['url'])
                if self.chapter_identity(target) == self.chapter_identity(url):
                    return super().inspect(target, http)
            raise SourceError('SilentQuill не нашёл сохранённую главу в оглавлении.')
        return super().inspect(url, http)

    def chapters(self, http, doc, final):
        rows = {}
        for data in flight_objects(str(doc)):
            key, slug = str(data.get('id') or ''), data.get('slug')
            if 'chapter_no' not in data or not re.fullmatch(ID, key) or not isinstance(slug, str) or not re.fullmatch(SEGMENT, slug):
                continue
            target = query_url(final.rstrip('/') + '/' + slug + '/', mv_id=key)
            number_label = str(data['chapter_no'])
            rows[key] = self.chapter(target, 'Chapter ' + number_label, number(number_label))
        return self.order(rows)[:MAX_CHAPTERS], len(rows) > MAX_CHAPTERS

    def pages(self, http, url):
        rows = next((node['pages'] for node in self.flight(http, url.split('?')[0]) if isinstance(node.get('pages'), list)), [])
        return [image_url(row.get('url'), url) for row in rows if isinstance(row, dict)]


SOURCES = (
    MangaMen(('601889634773560665', 'MangaMen', 'ru', 'https://mangamen.com', False)),
    SilentQuill(('3696994059835859589', 'SilentQuill', 'en', 'https://silentquill.net', True)),
)
