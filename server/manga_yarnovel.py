"""Luminare Translations public YarNovel browse API and HTML reader."""

import json
import re
from urllib.parse import parse_qs, urlsplit

from manga_direct_catalogues import DirectCatalogue, Layout, SERIES, SLUG, Browse
from manga_direct_payloads import items, segment
from manga_madara import image_url, node_text
from manga_series_port import Archive, Cards, Meta, number, picture
from manga_source_tags import unique
from manga_webcomics import query_url
from source_parser import SourceError


HOST = 'luminaretranslations.com'
API = '/wp-json/yarnovel/v1'
ID = r'[1-9]\d{0,13}'
PAGE_SIZE = 24
NOVELS = {'novel', 'light_novel', 'web_novel'}


def public_api(host, path, query):
    if host != HOST:
        return False
    if path == API + '/explore/filters':
        return not query
    if path != API + '/series':
        return False
    args = parse_qs(query)
    return (set(args) <= {'page', 'per_page', 'type', 'sort', 'search', 'genres', 'tags'}
            and args.get('type') == ['manga'] and args.get('per_page') == ['24']
            and args.get('sort') in (['popular'], ['latest']) and len(args.get('page', [])) == 1
            and bool(re.fullmatch(ID, args['page'][0]))
            and all(len(v) == 1 and len(v[0]) <= 160 for v in args.values()))


class Luminare(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            SERIES, rf'/series/{SLUG}/{ID}/?', Cards('', ''), Meta('h1', 'meta[property="og:image"]', '#series-description'),
            Archive(''), 'img.reader-page[data-src]', Browse('/'), title_path='/series/',
        ))
        self._vocabulary = {}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        options = {'page': page, 'per_page': PAGE_SIZE, 'type': 'manga', 'sort': 'latest' if sort == 'updated' else 'popular'}
        if query:
            options['search'] = query
        if tag:
            if not segment(tag):
                raise SourceError('Некорректная метка каталога.')
            if not self._vocabulary:
                self.vocabulary(http)
            options['tags' if self._vocabulary.get(tag) == 'tag' else 'genres'] = tag
        data = self.json(http, query_url(self.ROOT + API + '/series', **options))
        rows = []
        for item in items(data, 'data'):
            if not isinstance(item, dict) or str(item.get('type')) in NOVELS:
                continue
            slug, title = segment(item.get('slug')), item.get('title')
            if not slug or not isinstance(title, str) or not title.strip():
                continue
            url = self.ROOT + '/series/' + slug
            rows.append(self.record(url, title, image_url(item.get('cover_image'), url)))
        return rows, PAGE_SIZE * page < (number((data.get('meta') or {}).get('total')) or 0)

    def vocabulary(self, http):
        data = self.json(http, self.ROOT + API + '/explore/filters')
        rows = []
        for category in ('genre', 'tag'):
            for item in items(data, category + 's'):
                if not isinstance(item, dict):
                    continue
                key, label = item.get('slug') or item.get('value'), item.get('name') or item.get('label')
                if segment(key) and isinstance(label, str) and label.strip():
                    rows.append({'label': label, 'sourceId': key, 'category': category})
        self._vocabulary = {row['sourceId']: row['category'] for row in rows}
        return rows

    def chapter_data(self, doc, key):
        block = doc.select_one('section[x-data*="chapters:"]')
        if block is None:
            raise SourceError('Luminare не предоставил оглавление.')
        marker = re.search(r'(?m)^\s*' + re.escape(key) + r'\s*:\s*(?=\[)', block['x-data'])
        if marker is None:
            raise SourceError('Luminare изменил формат полей карточки.')
        try:
            value, _ = json.JSONDecoder().raw_decode(block['x-data'], marker.end())
            if isinstance(value, list):
                return value
        except ValueError:
            pass
        raise SourceError('Luminare изменил формат оглавления.')

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        values = {item['label']: item['value'] for item in self.chapter_data(doc, 'infoRows') if isinstance(item, dict)
                  and isinstance(item.get('label'), str) and isinstance(item.get('value'), str)}
        row.update(genres=unique(values.get('Genre', '').split(',')), tags=unique(values.get('Tags', '').split(',')),
                   authors=unique([values.get('Author')]), artists=unique([values.get('Artist')]),
                   status=values.get('Status', '').casefold())
        return row

    def chapters(self, http, doc, url):
        chapters = {}
        for item in self.chapter_data(doc, 'chapters'):
            if not isinstance(item, dict) or not re.fullmatch(ID, chapter := str(item.get('id', ''))):
                continue
            n = number(item.get('number'))
            title = item.get('title') or f'Chapter {n or 0:g}'
            if item.get('subtitle'):
                title += ' - ' + item['subtitle']
            target = f'{url.rstrip("/")}/{chapter}'
            chapters[target] = self.chapter(target, title, n, str(item.get('published_at') or '')[:10])
        return self.order(chapters), False

    def saved_chapter(self, row, root, title):
        value = row.get('realUrl') or row.get('url') or ''
        if isinstance(value, str) and re.fullmatch(ID, value) and self.is_title(title):
            return title.rstrip('/') + '/' + value
        return super().saved_chapter(row, root, title)

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        nodes = doc.select(self.layout.reader)
        server = nodes[0].get('data-server-id') if nodes else None
        return [picture(node, final, ('data-src',)) for node in nodes if node.get('data-server-id') == server]
