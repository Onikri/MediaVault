"""Read-only Simply Hentai v3 catalogue and public album pages."""

import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries, items
from manga_madara import SEGMENT, image_url
from manga_series_port import MAX_PAGES, number
from manga_webcomics import query_url
from source_parser import SourceError


HOST = 'api.simply-hentai.com'
ROOT = 'https://www.simply-hentai.com'
API = 'https://' + HOST + '/v3'
TITLE = rf'/({SEGMENT}/{SEGMENT})/?'
CHAPTER = rf'/({SEGMENT}/{SEGMENT})/all-pages/?'
LANG = {'en': 'english', 'ja': 'japanese', 'zh': 'chinese', 'ko': 'korean', 'es': 'spanish',
        'ru': 'russian', 'fr': 'french', 'de': 'german', 'it': 'italian', 'pl': 'polish'}


def public_api(host, path, query):
    if host != HOST:
        return False
    pairs = parse_qsl(query, keep_blank_values=True)
    args = dict(pairs)
    if len(pairs) != len(args) or any(len(value) > 160 for value in args.values()):
        return False
    if path.startswith('/v3/tag/'):
        return (path.rsplit('/', 1)[-1] in LANG.values() and set(args) <= {'type', 'page', 'sort'}
                and args.get('type') == 'language' and bool(re.fullmatch(r'[1-9]\d{0,3}', args.get('page', '')))
                and args.get('sort', 'newest') == 'newest')
    if path == '/v3/search/complex':
        fields = {'query', 'page', 'blacklist', 'filter[language][0]'}
        return (fields <= set(args) <= fields | {'filter[tags][0]'}
                and args['blacklist'] == '' and args['filter[language][0]'].lower() in LANG.values()
                and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'])))
    return not query and bool(re.fullmatch(rf'/v3/manga/{SEGMENT}(?:/pages)?', path))


def labels(rows):
    return [row['title'] for row in rows if isinstance(row, dict) and isinstance(row.get('title'), str)] if isinstance(rows, list) else []


class SimplyGallery(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, TITLE, CHAPTER, hosts=('simply-hentai.com', 'doujin.sexy', 'www.doujin.sexy'), interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return self.ROOT + '/' + key if key else ''

    def is_title(self, url):
        return super().is_title(url) and self.title_key(url).split('/')[0] not in {'tag', 'manga', 'language', 'search',
                                                                                 'artists', 'characters', 'translators'}

    def saved_title_url(self, value):
        value = self.canonical(value)
        key = self.title_key(value)
        return self.ROOT + '/' + key if key and self.is_title(value) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return self.ROOT + '/' + self.chapter_key(target) + '/all-pages'
        if self.is_title(target) and self.title_key(target) == self.title_key(title):
            return title.rstrip('/') + '/all-pages'
        return ''

    def row_for(self, value):
        series = ((value.get('series') or {}).get('slug') or '') if isinstance(value, dict) else ''
        slug = value.get('slug') if series else ''
        title = value.get('title') if series else ''
        if not all(isinstance(part, str) and re.fullmatch(SEGMENT, part) for part in (series, slug)) or not isinstance(title, str) or not title:
            return None
        target = self.ROOT + '/' + series + '/' + slug
        thumb = ((value.get('preview') or {}).get('sizes') or {}).get('thumb')
        description = value.get('description')
        return self.record(target, title, image_url(thumb, target), description=description if isinstance(description, str) else '',
                           tags=labels(value.get('tags')), authors=labels(value.get('artists')), status='completed')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        language = LANG[self.LANGUAGE]
        if query or tag:
            args = {'query': query, 'page': page, 'blacklist': '', 'filter[language][0]': language.capitalize()}
            if tag:
                args['filter[tags][0]'] = tag[:160]
            data = self.json(http, query_url(API + '/search/complex', **args))
            rows = [row.get('object') for row in items(data, 'data') if isinstance(row, dict)]
        else:
            args = {'type': 'language', 'page': page}
            if sort == 'updated':
                args['sort'] = 'newest'
            data = self.json(http, query_url(API + '/tag/' + language, **args))
            rows = items(data.get('data') or {}, 'albums')
        return [row for entry in rows if (row := self.row_for(entry))], bool((data.get('pagination') or {}).get('next'))

    def series(self, http, url):
        slug = self.title_key(url).rsplit('/', 1)[-1]
        entry = self.json(http, API + '/manga/' + slug, url).get('data')
        row = self.row_for(entry)
        if not row or self.title_key(self.site_link(row['url'])) != self.title_key(url):
            raise SourceError('Источник не подтвердил карточку выбранного альбома.')
        date = entry.get('created_at')
        return row, [self.chapter(url.rstrip('/') + '/all-pages', 'Chapter', 1, date[:10] if isinstance(date, str) else '',
                                  translator=', '.join(labels(entry.get('translators'))))]

    def pages(self, http, url):
        key = self.chapter_key(url).rsplit('/', 1)[-1]
        data = self.json(http, API + f'/manga/{key}/pages', url).get('data') or {}
        result = []
        for index, row in enumerate(items(data, 'pages')):
            if not isinstance(row, dict):
                raise SourceError('Источник изменил формат страницы альбома.')
            target = image_url((row.get('sizes') or {}).get('full'), url)
            if not target:
                raise SourceError('Источник не предоставил одну из страниц альбома.')
            result.append((number(row.get('page_num')) or index, index, target))
        if len(result) > MAX_PAGES:
            raise SourceError('Источник вернул слишком много страниц альбома.')
        return [target for _, _, target in sorted(result)]


SOURCES = tuple(SimplyGallery((sid, 'Simply Hentai', lang, ROOT, True)) for sid, lang in (
    ('298934354390867671', 'en'), ('752674984993743406', 'ja'), ('6411097384584116028', 'zh'),
    ('5425671014693930239', 'ko'), ('666623320329622877', 'es'), ('5942590313591365439', 'ru'),
    ('4451316190554848827', 'fr'), ('5791709100642569951', 'de'), ('9142653224816805805', 'it'),
    ('2725673328914321866', 'pl'),
))
