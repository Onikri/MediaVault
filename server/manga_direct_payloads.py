"""Standalone public JSON and React Flight source protocols."""

import re
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, MANGA, SERIES, SLUG
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Archive, Cards, MAX_CHAPTERS, MAX_PAGES, Meta, SeriesPort, number, picture
from manga_vinetheme import dictionaries, flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError, SourcePaidError


ID = r'[0-9]{1,18}'


def items(value, key):
    values = value.get(key) if isinstance(value, dict) else None
    if not isinstance(values, list):
        raise SourceError('Источник изменил формат списка.')
    return values


def segment(value):
    if not isinstance(value, str) or not value or len(value) > 180:
        return ''
    value = quote(value, safe='')
    return value if re.fullmatch(SEGMENT, value) else ''


def strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


class JsonSeries(SeriesPort):
    def details(self, http, url):
        url = self.saved_title_url(url)
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на карточку источника.')
        return self.series(http, url)[0]

    def inspect(self, value, http):
        url = self.canonical(value)
        title = self.title_for(url) if self.is_chapter(url) else url
        if not self.is_title(title):
            raise SourceError('Некорректная ссылка на тайтл или главу.')
        row, chapters = self.series(http, title)
        pages = []
        if self.is_chapter(url):
            chapter = next((row for row in chapters if self.chapter_identity(self.site_link(row['url'])) ==
                            self.chapter_identity(url)), None)
            if chapter is None:
                raise SourceAccessError('Источник не предоставил эту главу в открытом списке.')
            if chapter.get('locked'):
                # Paid chapters stay listed with their status and are never bypassed.
                raise SourcePaidError('Глава платная или доступна только по подписке.')
            pages = self.pages(http, self.site_link(chapter['url']))
            if not 1 <= len(pages) <= MAX_PAGES or not all(pages):
                raise SourceError('Источник не предоставил полный список изображений главы.')
        return self.reader_result(row, url, chapters[:MAX_CHAPTERS], pages, len(chapters) > MAX_CHAPTERS)


class XoManga(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, r'(/details\.html)', r'(/reader\.html)', interval=.35)

    def title_key(self, url):
        return segment(param(url, 'id'))

    def is_title(self, url):
        return super().is_title(url) and bool(self.title_key(url))

    def chapter_key(self, url):
        return self.title_key(url)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.chapter_key(url) and segment(param(url, 'ch')))

    def chapter_identity(self, url):
        return self.chapter_key(url), param(url, 'ch')

    def title_for(self, url):
        return self.title_url(param(url, 'id'))

    def title_url(self, slug):
        return query_url(self.ROOT + '/details.html', id=slug)

    def saved_title_url(self, url):
        target = self.canonical(url)
        if self.is_title(target):
            return target
        slug = urlsplit(target).path.strip('/')
        return self.title_url(slug) if re.fullmatch(SEGMENT, slug) else ''

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        if self.is_chapter(value):
            return value
        parts = urlsplit(value)
        slug = parts.path.strip('/')
        if re.fullmatch(SEGMENT, slug) and segment(parts.fragment):
            return query_url(self.ROOT + '/reader.html', id=slug, ch=parts.fragment)
        return ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        exclusive = None
        if not query and sort == 'popular' and not tag:
            doc, _ = self.document(http, self.ROOT + '/our-works')
            for script in doc.select('script'):
                match = re.search(r'\bmyExclusiveWorksTitles\s*=\s*\[([^\]]+)\]', script.string or '')
                if match:
                    exclusive = [' '.join(value.casefold().split()) for value in re.findall(r'"([^"]+)"', match[1])]
                    break
            if exclusive is None:
                raise SourceError('Источник изменил список собственных тайтлов.')
        rows = {}
        for item in items(self.json(http, self.ROOT + '/index.json'), 'latest'):
            if not isinstance(item, dict) or not isinstance(item.get('title'), str):
                continue
            title = item['title']
            slug = param(self.site_link(item.get('link')), 'id')
            if not segment(slug) or query not in title.casefold():
                continue
            if exclusive is not None and not any(value in ' '.join(title.casefold().split()) for value in exclusive):
                continue
            target = self.title_url(slug)
            rows[slug] = self.record(target, title, image_url(item.get('image'), self.ROOT))
        return list(rows.values()), False

    def series(self, http, url):
        slug = self.title_key(url)
        data = self.json(http, f'{self.ROOT}/manga/{slug}/details.json', url)
        if not isinstance(data, dict) or not isinstance(data.get('title'), str) or not data['title']:
            raise SourceError('Источник не предоставил карточку тайтла.')
        record = self.record(url, data['title'], image_url(data.get('cover'), url), description=data.get('description') or '',
                             tags=strings(data.get('tags')), status=data.get('status') or '')
        chapters = {}
        for item in items(data, 'chapters_list'):
            if not isinstance(item, dict) or item.get('is_vip'):
                continue
            target = self.site_link(item.get('link'))
            n = number(item.get('chapter'))
            if not self.is_chapter(target) or self.chapter_key(target) != slug or n is None:
                continue
            chapters[target] = self.chapter(target, f'Chapter {n:g}', n, str(item.get('date', ''))[:10])
        return record, self.order(chapters)

    def pages(self, http, url):
        slug, chapter = self.chapter_key(url), segment(param(url, 'ch'))
        data = self.json(http, f'{self.ROOT}/manga/{slug}/chapters/{chapter}.json', url)
        return [image_url(item, url) for item in items(data, 'images')]


class RevivalScans(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, SERIES, rf'/read/{SLUG}/{SEGMENT}/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + '/series/' + self.chapter_key(url)

    def unpack(self, http, url, field, shape):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, action='native-series-rsc', headers={'Referer': self.ROOT + '/'})
        if self.site_link(final).rstrip('/') != url.rstrip('/'):
            raise SourceError('Источник перенаправил запрос данных на другой маршрут.')
        models = flight_models(flight_stream(raw))
        for value in models.values():
            for entry in dictionaries(value):
                if field in entry and isinstance(candidate := resolve_fields(entry[field], models, [50000]), shape):
                    return candidate
        raise SourceError('Источник изменил формат React Flight.')

    def record_from(self, url, data):
        title = data.get('title')
        if not isinstance(title, str) or not title:
            raise SourceError('Источник не предоставил название тайтла.')
        return self.record(url, title, image_url(data.get('coverImage'), url), description=data.get('description') or '',
                           genres=strings(data.get('genres')), status=data.get('status') or '',
                           authors=[value for value in (data.get('author'), data.get('artist')) if isinstance(value, str)])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        records = self.unpack(http, self.ROOT + '/series', 'series', list)
        rows = {}
        for row in records:
            if isinstance(row, dict) and (slug := segment(row.get('id'))) and query in str(row.get('title', '')).casefold():
                rows[slug] = self.record_from(f'{self.ROOT}/series/{slug}', row)
        return list(rows.values()), False

    def series(self, http, url):
        data = self.unpack(http, url, 'manhwa', dict)
        slug = self.title_key(url)
        if segment(data.get('id')) != slug:
            raise SourceError('Источник вернул другой тайтл.')
        rows = {}
        for row in data.get('chapters') or []:
            if not isinstance(row, dict) or row.get('accessRoles') is not None and 'reader' not in strings(row['accessRoles']):
                continue
            identity, n = segment(row.get('id')), number(row.get('number'))
            if identity and n is not None:
                target = f'{self.ROOT}/read/{slug}/{identity}'
                rows[target] = self.chapter(target, row.get('title') or f'Chapter {n:g}', n, str(row.get('releaseDate') or '')[:10])
        return self.record_from(url, data), self.order(rows)

    def pages(self, http, url):
        return [image_url(row.get('url'), url) if isinstance(row, dict) else ''
                for row in self.unpack(http, url, 'pages', list)]


class MangaBolt(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            MANGA, rf'/chapter/({SEGMENT})-chapter-{SEGMENT}/?', Cards('', ''),
            Meta('#main-content h1', 'div.flex img', 'div.bg-bg-secondary div.px-6 div.flex-col div.text-text-muted'),
            Archive('div.w-full div.bg-bg-secondary:has(div.grid)', anchor='div.grid a'),
            '.js-pages-container img.js-page:not(noscript img)', Browse('/manga-list/'),
        ))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        rows = {}
        if sort == 'updated' and not query:
            if page != 1:
                return [], False
            doc, final = self.document(http, self.ROOT + '/latest')
            for card in doc.select('div.bg-bg-secondary:has(a[href*="/chapter/"])'):
                link = self.site_link(card.select_one('a[href*="/chapter/"]')['href'], final)
                slug = self.chapter_key(link)
                title = node_text(card.select_one('.font-bold')).partition('Chapter')[0].strip()
                if slug and title:
                    rows[slug] = self.record(f'{self.ROOT}/manga/{slug}/', title, picture(card.select_one('img'), final))
            return list(rows.values()), False
        url = query_url(self.ROOT + '/manga-list/', page=page, **({'search': query} if query else {})) + '&_=/'
        data = self.json(http, url)
        for row in items(data, 'mangas'):
            if isinstance(row, dict) and (slug := segment(row.get('slug'))) and isinstance(row.get('name'), str):
                rows[slug] = self.record(f'{self.ROOT}/manga/{slug}/', row['name'], image_url(row.get('image_url'), url))
        return list(rows.values()), bool(data.get('next_page_url'))

    def pages(self, http, url):
        return list(dict.fromkeys(value for value in super().pages(http, url) if value))


class KodokuStudio(JsonSeries):
    SLUG = 'reverend-insanity'

    def __init__(self, identity):
        super().__init__(identity, rf'/manhwa/({self.SLUG})/?', rf'/read/({self.SLUG})/([a-z]{{2,8}})/{SEGMENT}/?', interval=.35)

    def language(self, url):
        lang = param(url, 'lang') or 'en'
        if not re.fullmatch('[a-z]{2,8}', lang):
            raise SourceError('Некорректный язык издания.')
        return lang

    def title_url(self, lang):
        return query_url(f'{self.ROOT}/manhwa/{self.SLUG}', lang=lang)

    def title_for(self, url):
        return self.title_url(urlsplit(url).path.split('/')[3])

    def saved_title_url(self, url):
        target = self.canonical(url)
        path = urlsplit(target).path.strip('/').split('/')
        if len(path) == 2 and path[0] == self.SLUG and re.fullmatch('[a-z]{2,8}', path[1]):
            return self.title_url(path[1])
        return target

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        parts = urlsplit(target).path.strip('/').split('/')
        if len(parts) == 2 and number(parts[0]) is not None and re.fullmatch('[a-z]{2,8}', parts[1]):
            return f'{self.ROOT}/read/{self.SLUG}/{parts[1]}/{parts[0]}'
        return target

    def saved_chapter_matches(self, target, title):
        return super().saved_chapter_matches(target, title) and self.title_for(target) == self.title_url(self.language(title))

    def api(self, http, path=''):
        return self.json(http, self.ROOT + '/api/series' + path)

    def record_from(self, url, data):
        if not isinstance(data, dict) or data.get('slug') != self.SLUG or not isinstance(data.get('title'), str):
            raise SourceError('Источник вернул другой тайтл.')
        name = f'{data["title"]} [{self.language(url).upper()}]'
        return self.record(url, name, image_url(data.get('coverUrl'), url), description=data.get('description') or '', status='ongoing')

    def releases(self, http):
        records = self.api(http, f'/{self.SLUG}/chapters')
        if not isinstance(records, list):
            raise SourceError('Источник изменил оглавление.')
        return [row for row in records if isinstance(row, dict)]

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        data = self.api(http)
        match = next((row for row in data if isinstance(row, dict) and row.get('slug') == self.SLUG), None)
        langs = sorted({row['languageCode'] for row in self.releases(http)
                        if re.fullmatch('[a-z]{2,8}', str(row.get('languageCode', '')))})
        rows = [self.record_from(self.title_url(lang), match) for lang in langs]
        return [row for row in rows if query in row['title'].casefold()], False

    def series(self, http, url):
        lang = self.language(url)
        result = self.record_from(url, self.api(http, f'/{self.SLUG}'))
        rows = {}
        for row in self.releases(http):
            chapter = segment(row.get('chapterNumber'))
            n = number(chapter)
            if n is None or row.get('languageCode') != lang or row.get('available') is not True:
                continue
            target = f'{self.ROOT}/read/{self.SLUG}/{lang}/{chapter}'
            rows[target] = self.chapter(target, f'Chapter {chapter}', n, str(row.get('availableAt') or row.get('uploadedAt') or '')[:10])
        return result, self.order(rows)

    def pages(self, http, url):
        lang, n = urlsplit(url).path.strip('/').split('/')[-2:]
        data = self.api(http, f'/{self.SLUG}/chapters/{n}/{lang}')
        records = [item for item in items(data, 'images') if isinstance(item, dict)]
        return [image_url(item.get('url'), url) for item in sorted(records, key=lambda row: number(row.get('sequence')) or 0)]


class OnePieceFans(JsonSeries):
    def __init__(self, identity):
        lang = re.escape(identity[2])
        super().__init__(identity, rf'/manga/{lang}/{SLUG}/?', rf'/manga/{lang}/{SLUG}/{SEGMENT}/?', interval=.35)

    def title_for(self, url):
        return self.ROOT + f'/manga/{self.LANGUAGE}/' + self.chapter_key(url)

    def saved_title_url(self, url):
        value = self.canonical(url)
        slug = urlsplit(value).path.strip('/')
        return f'{self.ROOT}/manga/{self.LANGUAGE}/{slug}' if re.fullmatch(SEGMENT, slug) else value

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        path = urlsplit(value).path
        return f'{self.ROOT}/manga/{self.LANGUAGE}{path}' if re.fullmatch(rf'/{SEGMENT}/{SEGMENT}', path) else value

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        result = self.json(http, self.ROOT + '/fansubs-config.json')
        rows = {}
        for item in result.get(self.LANGUAGE, []):
            if not isinstance(item, dict) or not (key := segment(item.get('path'))) or not isinstance(item.get('title'), str):
                continue
            title = f'One Piece ({item["title"]})'
            if query in title.casefold():
                rows[key] = self.record(f'{self.ROOT}/manga/{self.LANGUAGE}/{key}', title, self.ROOT + '/images/luffy.png')
        return list(rows.values()), False

    def series(self, http, url):
        folder = self.title_key(url)
        rows, _ = self.catalogue(http)
        result = next((row for row in rows if self.title_key(self.site_link(row['url'])) == folder), None)
        if result is None:
            raise SourceError('Источник не предоставил это издание One Piece.')
        target = query_url(self.ROOT + '/server.php', lang=self.LANGUAGE, folderName=unquote(folder))
        chapters = {}
        labels = {'fr': 'Chapitre', 'es': 'Capítulo', 'it': 'Capitolo', 'pt-BR': 'Capítulo'}
        for label in strings(self.json(http, target, url)):
            if n := segment(label):
                chapter = url.rstrip('/') + '/' + n
                chapters[chapter] = self.chapter(chapter, f'{labels.get(self.LANGUAGE, "Chapter")} {label}', number(label))
        return result, self.order(chapters)

    def pages(self, http, url):
        folder, chapter = urlsplit(url).path.strip('/').split('/')[-2:]
        target = query_url(self.ROOT + '/server.php', lang=self.LANGUAGE, folderName=unquote(folder), chapter=unquote(chapter))
        return [image_url(f'{self.ROOT}/mangafiles/{self.LANGUAGE}/{folder}/{chapter}/{filename}', url)
                if (filename := segment(item)) else '' for item in strings(self.json(http, target, url))]


class MangaDE(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, rf'/comic/{SEGMENT}-pid({ID})/?', rf'/comic/{SEGMENT}-({ID})/{SEGMENT}/?', interval=.35)
        self.api = f'https://api.{self.hostname}/api'

    def unpack(self, http, path):
        data = self.json(http, self.api + path)
        if not isinstance(data, dict) or not isinstance(data.get('data'), dict):
            raise SourceError('Источник изменил формат каталога.')
        return data['data']

    def record_from(self, data):
        key, slug, title = str(data.get('id', '')), segment(data.get('slug')), data.get('name')
        if not re.fullmatch(ID, key) or not slug or not isinstance(title, str) or not title:
            raise SourceError('Источник не предоставил карточку тайтла.')
        url = f'{self.ROOT}/comic/{slug}-pid{key}'
        return self.record(url, title, image_url(data.get('image'), url), description=data.get('description') or '',
                           genres=str(data.get('genre_names') or '').split(','), status=data.get('status') or '')

    def title_for(self, url):
        slug = urlsplit(url).path.split('/')[2].rsplit('-', 1)[0]
        return f'{self.ROOT}/comic/{slug}-pid{self.chapter_key(url)}'

    def saved_title_url(self, url):
        target = self.canonical(url)
        if self.is_title(target):
            return target
        slug, mid = urlsplit(target).path.strip('/'), param(target, 'mid')
        return f'{self.ROOT}/comic/{slug}-pid{mid}' if re.fullmatch(SEGMENT, slug) and re.fullmatch(ID, mid) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        slug, _, chapter = urlsplit(target).path.strip('/').partition('/')
        mid = param(target, 'mid')
        if re.fullmatch(ID, mid) and all(re.fullmatch(SEGMENT, value) for value in (slug, chapter)):
            cid = param(target, 'cid')
            url = f'{self.ROOT}/comic/{slug}-{mid}/{chapter}'
            return query_url(url, mv_chapter=cid) if re.fullmatch(ID, cid) else url
        return ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        args = {'name': query} if query else {'sort': 'newest' if sort == 'updated' else 'most-viewed'}
        if tag:
            if not re.fullmatch(ID, tag):
                raise SourceError('Некорректный жанр каталога.')
            args['genres[]'] = tag
        path = query_url('/comics', page=page, size=20, **args)
        data = self.unpack(http, path)
        return [self.record_from(row) for row in items(data, 'list') if isinstance(row, dict)], page < (number(data.get('totalPage')) or 0)

    def vocabulary(self, http):
        data = self.unpack(http, '/genres?size=500')
        return [{'label': row['name'], 'sourceId': str(row['id']), 'category': 'genre'} for row in items(data, 'genres')
                if isinstance(row, dict) and isinstance(row.get('name'), str) and re.fullmatch(ID, str(row.get('id', '')))]

    def series(self, http, url):
        mid = self.title_key(url)
        data = self.unpack(http, f'/comics/{mid}/view')
        result = self.record_from(data)
        if self.title_key(self.site_link(result['url'])) != mid:
            raise SourceError('Источник вернул другой тайтл.')
        slug = segment(data['slug'])
        rows = {}
        for row in items(data, 'news_chapters'):
            if not isinstance(row, dict):
                continue
            cid, ch = str(row.get('id', '')), segment(row.get('slug'))
            if not re.fullmatch(ID, cid) or not ch:
                continue
            target = query_url(f'{self.ROOT}/comic/{slug}-{mid}/{ch}', mv_chapter=cid)
            rows[target] = self.chapter(target, row.get('name') or '', number(row.get('chapter_number')),
                                        str(row.get('published_date') or '')[:10])
        return result, self.order(rows)

    def pages(self, http, url):
        cid = param(url, 'mv_chapter')
        if not re.fullmatch(ID, cid):
            return []
        data = self.unpack(http, f'/chapters/{cid}/view')
        if str(data.get('id')) != cid:
            raise SourceError('Источник вернул другую главу.')
        return [image_url(row.get('image'), url) if isinstance(row, dict) else '' for row in items(data, 'chapter_images')]


class Leslie(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, '(/)', '(/)', interval=.35)

    def title_key(self, url):
        return segment(param(url, 'series'))

    def chapter_key(self, url):
        return self.title_key(url)

    def is_title(self, url):
        return super().is_title(url) and bool(self.title_key(url)) and not param(url, 'ch')

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_key(url) and segment(param(url, 'ch')))

    def chapter_identity(self, url):
        return self.title_key(url), param(url, 'ch')

    def title_for(self, url):
        return query_url(self.ROOT + '/', series=param(url, 'series'))

    def library(self, http):
        data = self.json(http, self.ROOT + '/manga.json')
        if not isinstance(data, list):
            raise SourceError('Источник изменил формат каталога.')
        return {key: row for row in data if isinstance(row, dict) and (key := segment(row.get('id')))
                and isinstance(row.get('title'), str) and row['title']}

    def record_from(self, url, data):
        return self.record(url, data['title'], image_url(data.get('cover'), self.ROOT + '/'))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        return [self.record_from(query_url(self.ROOT + '/', series=row['id']), row)
                for row in self.library(http).values() if query in row['title'].casefold()], False

    def record_data(self, http, url):
        data = self.library(http).get(self.title_key(url))
        if data is None:
            raise SourceError('Источник не предоставил этот тайтл.')
        return data

    def series(self, http, url):
        data = self.record_data(http, url)
        chapters = [self.chapter(query_url(url, ch=label), f'Chapter {label}', number(label.split()[0]))
                    for label in reversed(items(data, 'chapters')) if segment(label)]
        return self.record_from(url, data), self.order({row['url']: row for row in chapters})

    def pages(self, http, url):
        data = self.record_data(http, url)
        label = param(url, 'ch')
        roots = data.get('chapter_roots')
        root = roots.get(label) if isinstance(roots, dict) else None
        if isinstance(root, dict):
            target = image_url(root.get('url'), self.ROOT + '/').rstrip('/')
            if not target:
                return []
            if root.get('mode') == 'list':
                return [image_url(f'{target}/{path}', url) if (path := segment(value)) else ''
                        for value in items(root, 'data')]
            if root.get('mode') == 'count' and type(total := root.get('data')) is int and 1 <= total <= MAX_PAGES:
                return [f'{target}/{idx:02d}.webp' for idx in range(1, total + 1)]
            return []
        pages = []
        for idx in range(1, 151):
            target = f'{self.ROOT}/content/{self.title_key(url)}/{segment(label)}/{idx:02d}.webp'
            if not http.leslie_image_exists(target, url):
                break
            pages.append(target)
        return pages


class Explosm(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, r'(/comics)/?', rf'/comics/{SLUG}/?', interval=.35)

    def title_url(self, year):
        return f'{self.ROOT}/comics#{year}-01'

    def title_key(self, url):
        suffix = urlsplit(url).fragment
        return suffix[:4] if re.fullmatch(r'20\d\d-01', suffix) else ''

    def is_title(self, url):
        return super().is_title(url) and bool(self.title_key(url))

    def saved_title_url(self, url):
        target = self.canonical(url)
        slug = urlsplit(target).path.strip('/')
        return self.title_url(slug) if re.fullmatch(r'20\d\d', slug) else target

    def saved_chapter(self, row, root, title):
        value = super().saved_chapter(row, root, title)
        return urlunsplit(urlsplit(value)._replace(fragment=self.title_key(title) + '-01'))

    def saved_chapter_matches(self, target, title):
        return self.title_key(title) == self.title_key(target) and self.confirm_chapter(target, title)

    def confirm_chapter(self, target, title):
        from source_parser import PublicHttp

        http = PublicHttp(timeout=(3, 6))
        try:
            _, chapters = self.series(http, title)
            return any(self.chapter_key(self.site_link(row['url'])) == self.chapter_key(target) for row in chapters)
        finally:
            http.close()

    def archive_data(self, http):
        doc, final = self.document(http, self.ROOT + '/comics')
        script = (doc.select('head > script[src]') or [None])[-1]
        src = self.site_link(script['src'], final) if script else ''
        build = re.search(r'/_next/static/([A-Za-z0-9_-]{1,128})/', urlsplit(src).path)
        if build is None:
            raise SourceError('Источник изменил адрес архива комиксов.')
        data = self.json(http, f'{self.ROOT}/_next/data/{build[1]}/comics.json', final)
        result = data.get('pageProps', {}).get('comicArchiveData') if isinstance(data, dict) else None
        if not isinstance(result, dict):
            raise SourceError('Источник изменил формат архива комиксов.')
        return result

    def record_year(self, year):
        cover = 'https://vhx.imgix.net/vitalyuncensored/assets/13ea3806-5ebf-4987-bcf1-82af2b689f77/S2E4_Still1.jpg'
        return self.record(self.title_url(year), f'C&H {year}', cover, aliases=[f'Cyanide & Happiness {year}'], authors=['Explosm.net'])

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        return [self.record_year(year) for year in sorted(self.archive_data(http), reverse=True)
                if re.fullmatch(r'20\d\d', year) and any(query in name for name in (f'c&h {year}', f'cyanide & happiness {year}'))], False

    def year_rows(self, http, year):
        data = self.archive_data(http).get(year, {})
        if not isinstance(data, dict):
            raise SourceError('Источник изменил архив этого года.')
        return [value for month in data.values() if isinstance(month, list) for value in month if isinstance(value, dict)]

    def title_for(self, url):
        year = self.title_key(url)
        if not year:
            raise SourceError('У ссылки на комикс отсутствует год архива.')
        return self.title_url(year)

    def series(self, http, url):
        year = self.title_key(url)
        chapters = {}
        for n, row in enumerate(self.year_rows(http, year), 1):
            if slug := segment(row.get('slug')):
                target = f'{self.ROOT}/comics/{slug}#{year}-01'
                chapters[target] = self.chapter(target, str(row['slug']), n, str(row.get('publish_at', ''))[:10],
                                                translator=str(row.get('author_name') or ''))
        return self.record_year(year), self.order(chapters)

    def pages(self, http, url):
        for row in self.year_rows(http, self.title_key(url)):
            if segment(row.get('slug')) == self.chapter_key(url):
                value = row.get('file_static') or row.get('file')
                if not isinstance(value, str) or not value:
                    break
                return [image_url(value, 'https://files.explosm.net/comics/')]
        return []


def public_api(host, path, query):
    if host == 'www.xomanga.site':
        return not query and bool(re.fullmatch(rf'/index\.json|/manga/{SEGMENT}/(?:details\.json|chapters/{SEGMENT}\.json)', path))
    if host == 'www.revivalscans.com':
        return not query and bool(re.fullmatch(rf'/series(?:/{SEGMENT}/?)?|/read/{SEGMENT}/{SEGMENT}/?', path))
    if host == 'mangabolt.com' and path == '/manga-list/':
        args = parse_qs(query, keep_blank_values=True)
        return (set(args) <= {'page', 'search', '_'} and args.get('_') == ['/'] and
                len(args.get('page', [])) == 1 and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'][0])) and
                len(args.get('search', [])) <= 1 and len(args.get('search', [''])[0]) <= 160)
    if host == 'kodokueasyaccess.com':
        return not query and bool(re.fullmatch(
            rf'/api/series(?:/{KodokuStudio.SLUG}(?:/chapters(?:/{SEGMENT}/[a-z]{{2,8}})?)?)?', path))
    if host == 'one-piece-fans2.com':
        if path == '/fansubs-config.json':
            return not query
        if path == '/server.php':
            args = parse_qs(query, keep_blank_values=True)
            return (set(args) in ({'lang', 'folderName'}, {'lang', 'folderName', 'chapter'}) and
                    all(len(value) == 1 and segment(value[0]) for value in args.values()))
    if host == 'api.mangade.io':
        if path == '/api/genres':
            return query == 'size=500'
        if path == '/api/comics':
            args = parse_qs(query, keep_blank_values=True)
            return (set(args) <= {'page', 'size', 'name', 'sort', 'genres[]'} and args.get('size') == ['20'] and
                    len(args.get('page', [])) == 1 and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'][0])) and
                    len(args.get('name', [])) <= 1 and len(args.get('name', [''])[0]) <= 160 and
                    args.get('sort') in (None, ['newest'], ['most-viewed']) and
                    len(args.get('genres[]', [])) <= 1 and all(re.fullmatch(ID, x) for x in args.get('genres[]', [])))
        return not query and bool(re.fullmatch(rf'/api/(?:comics|chapters)/{ID}/view', path))
    if host == 'leslie-victims.pages.dev':
        return path == '/manga.json' and not query
    if host == 'explosm.net':
        return not query and bool(re.fullmatch(r'/_next/data/[A-Za-z0-9_-]{1,128}/comics\.json', path))
    return False


def sources():
    from manga_third_batch_profiles import PAYLOADS

    classes = {'xomanga': XoManga, 'revivalscans': RevivalScans, 'mangabolt': MangaBolt,
               'kodokustudio': KodokuStudio, 'onepiecefans': OnePieceFans, 'mangade': MangaDE,
               'leslievictims': Leslie, 'explosm': Explosm}
    return tuple(classes[package](identity) for package, identity in PAYLOADS)
