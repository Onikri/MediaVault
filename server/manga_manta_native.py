"""Manta's public English and Spanish catalogue, with preview status."""

import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries, items
from manga_madara import image_url, node_text
from manga_series_port import number
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


HOST = 'manta.net'
API = 'https://' + HOST
ID = r'[1-9]\d{0,12}'
ART = ('1280x1840_480', '1280x1840_720', '1440x3072', '1440x1440_480')


def public_api(host, path, query):
    if host != HOST:
        return False
    fields = parse_qsl(query)
    args = dict(fields)
    if len(fields) != len(args) or args.get('lang') not in ('en', 'es') or any(len(value) > 160 for value in args.values()):
        return False
    if path == '/manta/v1/search/series':
        other = set(args) - {'lang'}
        return other == {'q'} or args.get('cat') == 'New' and other == {'cat'} or (
            other == {'tagId'} and bool(re.fullmatch(ID, args['tagId'])))
    return set(args) == {'lang'} and bool(re.fullmatch(rf'/front/v1/(?:series|episodes)/{ID}', path))


class Manta(JsonSeries):
    def __init__(self, sid, language):
        super().__init__((sid, 'Manta', language, f'{API}/{language}', True),
                         rf'/{language}/series/({ID})/?', rf'/{language}/episodes/({ID})/?',
                         hosts=('www.manta.net',), interval=.35)

    def title_for(self, url):
        key = param(url, 'mv_title')
        return self.ROOT + '/series/' + key if re.fullmatch(ID, key) else ''

    def saved_title_url(self, url):
        value = self.canonical(url)
        if self.is_title(value):
            return value
        key = urlsplit(value).path.strip('/')
        return self.ROOT + '/series/' + key if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.chapter_key(url) or urlsplit(url).path.strip('/')
        if re.fullmatch(ID, key) and self.is_title(title):
            return query_url(self.ROOT + '/episodes/' + key, mv_title=self.title_key(title))
        return ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title))

    def local_name(self, value):
        if isinstance(value, dict):
            return value.get(self.LANGUAGE) or value.get('en') or value.get('es') or ''
        return value if isinstance(value, str) else ''

    def cover(self, data):
        if isinstance(data, dict):
            for kind in ART:
                info = data.get(kind)
                if isinstance(info, dict) and (image := image_url(info.get('downloadUrl'), API)):
                    return image
        return ''

    def request(self, http, path, **args):
        data = self.json(http, query_url(API + path, lang=self.LANGUAGE, **args), self.ROOT)
        return data.get('data') if isinstance(data, dict) else None

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        args = {'q': query} if query else {'tagId': tag} if re.fullmatch(ID, tag) else {'cat': 'New'}
        values = self.request(http, '/manta/v1/search/series', **args)
        if not isinstance(values, list):
            raise SourceError('Manta не предоставил список тайтлов.')
        rows = []
        for value in values:
            identity = str(value.get('id') or '') if isinstance(value, dict) else ''
            body = value.get('data') if identity else None
            if not isinstance(body, dict) or not re.fullmatch(ID, identity) or not (title := self.local_name(body.get('title'))):
                continue
            url = self.ROOT + '/series/' + identity
            rows.append(self.record(url, title, self.cover(value.get('image'))))
        return rows, False

    def record(self, url, title, cover='', **metadata):
        row = super().record(url, title, cover, **metadata)
        row.update(format='webtoon', readingMode='scroll')
        return row

    def series(self, http, url):
        key = self.title_key(url)
        series = self.request(http, '/front/v1/series/' + key)
        if not isinstance(series, dict) or str(series.get('id')) != key or not isinstance(series.get('data'), dict):
            raise SourceError('Manta не подтвердил карточку тайтла.')
        details = series['data']
        title = self.local_name(details.get('title')) or self.local_name(series.get('title'))
        if not title:
            doc, _ = self.title_document(http, url)
            node = doc.select_one('meta[property="og:title"][content]')
            title = node['content'] if node else node_text(doc.select_one('main h1, h1'))
        if not title:
            raise SourceError('Manta не предоставил название тайтла.')
        desc = details.get('description')
        desc = desc if isinstance(desc, dict) else {'short': desc}
        row = self.record(url, title, self.cover(series.get('image')),
                          description='\n\n'.join(desc[key] for key in ('short', 'long') if isinstance(desc.get(key), str) and desc[key]),
                          tags=[self.local_name(tag.get('name')) for tag in items(details, 'tags') if isinstance(tag, dict)],
                          authors=[item['name'] for item in items(details, 'creators') if isinstance(item, dict) and item.get('name')],
                          status='completed' if details.get('isCompleted') else 'ongoing')
        chapters = {}
        for item in items(series, 'episodes'):
            cid = str(item.get('id') or '') if isinstance(item, dict) else ''
            order = number(item.get('ord')) if cid else None
            if not re.fullmatch(ID, cid) or order is None:
                continue
            target = query_url(self.ROOT + '/episodes/' + cid, mv_title=key)
            title = (item.get('data') or {}).get('title') or f'Episode {order:g}'
            state = (item.get('lockData') or {}).get('state')
            if state is not None and state not in (110, 130):
                title += ' · превью'
            date = str(item.get('openAt') or item.get('createdAt') or '')[:10]
            chapters[target] = self.chapter(target, title, order, date)
        return row, self.order(chapters)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            data = self.episode_data(http, url)
            parent = str(data.get('seriesId') or '')
            if re.fullmatch(ID, parent):
                url = query_url(url.split('?')[0], mv_title=parent)
            else:
                title = (data.get('data') or {}).get('title') or f'Episode {data.get("ord") or self.chapter_key(url)}'
                row = self.record(url, title)
                return self.reader_result(row, url, [self.chapter(url, title, number(data.get('ord')) or 0)], self.images(data, url))
        return super().inspect(url, http)

    def episode_data(self, http, url):
        data = self.request(http, '/front/v1/episodes/' + self.chapter_key(url))
        if not isinstance(data, dict) or str(data.get('id')) != self.chapter_key(url):
            raise SourceAccessError('Manta не предоставил открытую версию главы.')
        parent = param(url, 'mv_title')
        if parent and data.get('seriesId') and str(data['seriesId']) != parent:
            raise SourceError('Manta подменил выбранную главу.')
        return data

    @staticmethod
    def images(data, url):
        values = [image_url(item.get('downloadUrl'), url) for item in items(data, 'cutImages') if isinstance(item, dict)]
        return [value for value in values if value and 'just-black.jpg' not in value]

    def pages(self, http, url):
        return self.images(self.episode_data(http, url), url)


SOURCES = (Manta('8753096034341798862', 'en'), Manta('2857546552946901153', 'es'))
