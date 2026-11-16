"""HentaiLoop public catalogue, search form and gallery reader."""

import json
import re
from urllib.parse import urlsplit

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, MANGA, SLUG
from manga_direct_payloads import items
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, Meta
from manga_webcomics import query_url
from source_parser import SourceError


ROOT = 'https://hentailoop.com'
SEARCH = ROOT + '/wp-admin/admin-ajax.php'
TAXONOMIES = frozenset({'genres', 'tag', 'parodies', 'characters', 'artists', 'languages'})


def public_form(url, data):
    return (url == SEARCH and isinstance(data, dict) and set(data) == {'action', 'subAction', 'query'}
            and data.get('action') == 'nativeSearch' and data.get('subAction') == 'search'
            and isinstance(data['query'], str) and 1 <= len(data['query']) <= 160)


class HentaiLoop(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            MANGA, rf'/manga/{SLUG}/read/?',
            Cards('div.manga-card a[href]', '', '.title', cover='img.attachment-manga_thumb', next='nav.navigation a.next'),
            Meta('.manga-title', '.manga-thumb img', aliases='.manga-subtitle',
                 tags='.manga-term-content a[href*="/tag/"], .manga-term-content a[href*="/characters/"]',
                 genres='.manga-term-content a[href*="/genres/"]', author='.manga-term-content a[href*="/artists/"]'),
            Archive(''), '.gallery-item > dt > img', Browse('/manga/'), title_path='/manga/', suffix='/',
        ))

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['status'] = 'completed'
        row['artists'] = row['authors'][:]
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if page != 1:
                return [], False
            data = {'action': 'nativeSearch', 'subAction': 'search', 'query': query}
            self.origin.wait(getattr(http, 'deadline', None))
            raw, final, _ = http.document(SEARCH, method='POST', action='native-series-form',
                                          headers={'Referer': self.ROOT + '/'}, data=data)
            if final != SEARCH:
                raise SourceError('Источник перенаправил запрос поиска.')
            try:
                items_data = items(json.loads(raw)['data'], 'posts')
            except (ValueError, KeyError, TypeError):
                raise SourceError('Источник изменил формат поиска.') from None
            rows = []
            for item in items_data:
                if not isinstance(item, dict) or not isinstance(title := item.get('title'), str):
                    continue
                url = self.site_link(item.get('link'))
                if self.is_title(url) and title.strip():
                    rows.append(self.record(url, title, image_url(item.get('thumb'), self.ROOT)))
            return rows, False
        section = '/manga'
        if tag:
            taxonomy, _, slug = tag.partition('/')
            if taxonomy not in TAXONOMIES or not re.fullmatch(SEGMENT, slug):
                raise SourceError('Некорректная метка каталога.')
            section = '/' + tag
        if page > 1:
            section += f'/page/{page}'
        target = query_url(self.ROOT + section + '/', sortmanga='date' if sort == 'updated' else 'views')
        return self.card_rows(*self.document(http, target), self.layout.cards)

    def vocabulary(self, http):
        doc, final = self.document(http, self.ROOT + '/manga/')
        rows = {}
        for node in doc.select('a[href]'):
            url = self.site_link(node['href'], final)
            route = urlsplit(url).path.strip('/')
            group, _, term = route.partition('/')
            if group in TAXONOMIES and re.fullmatch(SEGMENT, term) and (label := node_text(node)):
                rows[route] = {'label': label, 'sourceId': route, 'category': 'genre' if group == 'genres' else 'tag'}
        return list(rows.values())

    def saved_title_url(self, value):
        if isinstance(value, str) and re.fullmatch(SEGMENT, value):
            return self.ROOT + '/manga/' + value + '/'
        return super().saved_title_url(value)

    def saved_chapter(self, row, root, title):
        candidate = row.get('url') or ''
        if isinstance(candidate, str) and re.fullmatch(SEGMENT, candidate) and self.title_key(title) == candidate:
            return title.rstrip('/') + '/read/'
        return super().saved_chapter(row, root, title)

    def chapters(self, http, doc, url):
        chapter = self.chapter(url.rstrip('/') + '/read/', 'Глава', 1)
        return [chapter], False
