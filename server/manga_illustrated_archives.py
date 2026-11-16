"""Native MangaDraft and Pepper&Carrot archives."""

import json
import re
from collections import Counter
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from manga_direct_payloads import items, segment, strings
from manga_html_archives import LinkedArchive, PAGE_PATH
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import MAX_CHAPTERS, picture
from manga_source_tags import labels
from manga_webcomics import query_url
from source_parser import SourceError


DRAFT_HOST = 'www.mangadraft.com'
PEPPER_HOST = 'www.peppercarrot.com'
LANG = r'[A-Za-z][A-Za-z0-9_-]{0,20}'
ARTWORK = ('artworks', 'wallpapers', 'sketchbook', 'misc', 'book-publishing', 'comissions',
           'eshop', 'framasoft', 'press', 'references', 'wiki')
WEB = r'(?:peppercarrot|miniFantasyTheater)'
WEB_TITLE = rf'/({LANG}/webcomics/{WEB}\.html|en/files/(?:{"|".join(ARTWORK)})\.html)'
AUTHOR = 'David Revoy'
PEPPER_COVER = '/0_sources/0ther/artworks/low-res/2016-02-24_vertical-cover_remake_by-David-Revoy.jpg'
MINI_COVER = '/0_sources/0ther/artworks/low-res/2018-11-22_vertical-cover-book-three_by-David-Revoy.jpg'
ART_COVER = '/0_sources/0ther/press/low-res/2015-10-12_logo_by-David-Revoy.jpg'


def public_api(host, path, query):
    if host == PEPPER_HOST:
        return not query and path in {'/0_sources/langs.json', '/0_sources/episodes.json'}
    if host != DRAFT_HOST:
        return False
    args = parse_qs(query)
    if path == '/api/catalog/projects':
        return ({'order', 'type', 'page', 'number'} <= set(args) <= {'order', 'type', 'page', 'number', 'genre'}
                and args['number'] == ['20'] and args['type'] == ['all'] and args['order'] in (['news'], ['popular'])
                and len(args['page']) == 1 and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'][0]))
                and (len(args.get('genre', [])) <= 1) and all(segment(v) for v in args.get('genre', [])))
    if path == '/api/reader/listPages':
        return bool(re.fullmatch(r'first_page=[1-9]\d{0,13}&grouped_by_category=true', query))
    return False


class MangaDraft(LinkedArchive):
    def __init__(self, identity):
        super().__init__(identity, PAGE_PATH, PAGE_PATH, interval=.3)

    def is_title(self, url):
        return (super().is_title(url) and not self.is_chapter(url)
                and not urlsplit(url).path.startswith(('/api/', '/reader/', '/search', '/catalog')))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        args = {'order': 'news' if sort == 'updated' else 'popular', 'type': 'all', 'page': page, 'number': 20}
        if tag:
            if not segment(tag):
                raise SourceError('Некорректная метка каталога MangaDraft.')
            args['genre'] = tag
        data = self.json(http, query_url(self.ROOT + '/api/catalog/projects', **args))
        projects = items(data, 'data')
        rows = []
        for item in projects:
            if not isinstance(item, dict) or not isinstance(name := item.get('name'), str):
                continue
            target = self.site_link(item.get('url'))
            if not self.is_title(target) or query not in name.casefold() or not name.strip():
                continue
            rows.append(self.record(target, name, image_url(item.get('avatar'), self.ROOT),
                                    description=item.get('description') or '', genres=labels(item.get('genres'))))
        return rows, len(projects) >= 20

    def project(self, http, url):
        doc, final = self.title_document(http, url)
        for script in doc.select('script'):
            text = script.string or ''
            if not (marker := re.search(r'\bwindow\.project\s*=\s*(?=\{)', text)):
                continue
            try:
                row, _ = json.JSONDecoder().raw_decode(text, marker.end())
            except (ValueError, RecursionError):
                break
            if isinstance(row, dict) and isinstance(name := row.get('name'), str) and name.strip():
                result = self.record(final, name, description=row.get('description') or '', genres=labels(row.get('genres')),
                                     authors=[node_text(node) for node in doc.select('[title="Auteur"]')],
                                     status={0: 'ongoing', 1: 'completed', 2: 'hiatus'}.get(row.get('project_status_id'), ''))
                result['artists'] = [node_text(node) for node in doc.select('[title="créateur"]')]
                return result, doc, final
        raise SourceError('MangaDraft не предоставил карточку тайтла.')

    def details(self, http, url):
        return self.project(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        record, doc, final = self.project(http, url)
        links = doc.select('div.mt-7 div a[href]:not(:has(img))')
        if links and 'c.' not in links[0]['href']:
            links = links[:1]
        rows = {}
        for n, node in enumerate(links):
            target = self.site_link(node['href'], final)
            if not target or not self.CHAPTER_PATH.fullmatch(urlsplit(target).path):
                continue
            target = query_url(target, mv_title=urlsplit(final).path)
            label = node_text(node.select_one('[class~="group-hover:text-secondary"]')) or node_text(node)
            rows[target] = self.chapter(target, label, n)
        return record, self.order(rows)

    def pages(self, http, url):
        wire = self.upstream(url)
        if 'c.' in urlsplit(wire).path:
            _, wire = self.document(http, wire)
        name = urlsplit(wire).path.rstrip('/').rsplit('/', 1)[-1]
        match = re.fullmatch(r'(?:p\.)?([1-9]\d{0,13})', name)
        if match is None:
            raise SourceError('MangaDraft не предоставил ID первой страницы.')
        first = int(match[1])
        manifest = query_url(self.ROOT + '/api/reader/listPages', first_page=first, grouped_by_category='true')
        data = self.json(http, manifest, wire)
        if not isinstance(data, dict):
            raise SourceError('MangaDraft изменил формат списка страниц.')
        pages = next((rows for rows in data.values() if isinstance(rows, list)
                      and any(isinstance(row, dict) and row.get('id') == first for row in rows)), [])
        if any(not isinstance(row, dict) or not isinstance(row.get('url'), str) for row in pages):
            raise SourceError('MangaDraft вернул неполный список страниц.')
        return [image_url(query_url(row['url'], size='full'), self.ROOT) for row in pages]


class PepperCarrot(LinkedArchive):
    def __init__(self, identity):
        super().__init__(identity, WEB_TITLE, PAGE_PATH, interval=.25)
        self._langs = ({}, 0)
        self._langs_lock = Lock()

    def languages(self, http):
        with self._langs_lock:
            langs, expiry = self._langs
            if expiry > monotonic():
                return langs
            episodes = self.json(http, self.ROOT + '/0_sources/episodes.json')
            data = self.json(http, self.ROOT + '/0_sources/langs.json')
            if not isinstance(episodes, list) or not isinstance(data, dict):
                raise SourceError('Pepper&Carrot изменил список языков.')
            counts = Counter(language for row in episodes if isinstance(row, dict) for language in strings(row.get('translated_languages')))
            langs = {key: (str(row.get('local_name') or key), str(row.get('iso_code') or key), counts[key], len(episodes),
                           strings(row.get('translators'))) for key, row in data.items()
                     if isinstance(row, dict) and re.fullmatch(LANG, key) and counts[key]}
            self._langs = langs, monotonic() + 900
            return langs

    def saved_title_url(self, value):
        if isinstance(value, str):
            if re.fullmatch(LANG, value):
                return f'{self.ROOT}/{value}/webcomics/peppercarrot.html'
            if value.startswith('miniFantasyTheater#') and re.fullmatch(LANG, key := value.split('#', 1)[1]):
                return f'{self.ROOT}/{key}/webcomics/miniFantasyTheater.html'
            if value.removeprefix('#') in ARTWORK and value.startswith('#'):
                return self.ROOT + '/en/files/' + value[1:] + '.html'
        return super().saved_title_url(value)

    def vocabulary(self, http):
        return [{'label': meta[0], 'sourceId': key, 'category': 'tag'} for key, meta in self.languages(http).items()]

    def all_titles(self, http, tag=''):
        data = self.languages(http)
        for key, (name, code, count, total, credits) in data.items():
            if tag and key != tag:
                continue
            suffix = '' if key == 'en' else f' ({key.upper()})'
            description = f'{name} · {count}/{total}'
            if credits:
                description += '\n' + ', '.join(credits)
            for series, label, cover in (('peppercarrot', 'Pepper&Carrot', PEPPER_COVER),
                                         ('miniFantasyTheater', 'Mini Fantasy Theater', MINI_COVER)):
                target = f'{self.ROOT}/{key}/webcomics/{series}.html'
                row = self.record(target, label + suffix, self.ROOT + cover, description=description, authors=[AUTHOR])
                row['language'], row['format'] = code, 'comic'
                yield row
        if not tag:
            for key in ARTWORK:
                label = {'comissions': 'Commissions', 'eshop': 'Shop'}.get(key, key.title())
                target = self.ROOT + '/en/files/' + key + '.html'
                row = self.record(target, label, self.ROOT + ART_COVER, authors=[AUTHOR])
                row['format'] = 'comic'
                yield row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag).casefold()
        if page != 1:
            return [], False
        return [row for row in self.all_titles(http, tag) if query in (row['title'] + ' ' + row['description']).casefold()], False

    def details(self, http, url):
        target = self.saved_title_url(url)
        key = self.title_key(target)
        row = next((row for row in self.all_titles(http) if self.title_key(row['sourceUrl']) == key), None) if key else None
        if row is None:
            raise SourceError('Pepper&Carrot не предоставил карточку издания.')
        return row

    def series(self, http, url):
        record = self.details(http, url)
        original = urlsplit(url)
        is_art = original.path.startswith('/en/files/')
        folder = original.path.rsplit('/', 1)[-1].removesuffix('.html')
        request = f'{self.ROOT}/0_sources/0ther/{folder}/low-res/' if is_art else url
        doc, final = self.document(http, request)
        if urlsplit(final).path.rstrip('/') != urlsplit(request).path.rstrip('/'):
            raise SourceError('Pepper&Carrot перенаправил запрос на другой архив.')
        rows = {}
        if is_art:
            for n, anchor in enumerate(reversed(doc.select('a[href$=".jpg"]')), 1):
                target = self.site_link(anchor['href'], final)
                if not urlsplit(target).path.startswith(urlsplit(final).path):
                    continue
                label = urlsplit(target).path.rsplit('/', 1)[-1].removesuffix('.jpg').removesuffix('_by-David-Revoy')
                date = label[:10] if re.match(r'\d{4}-\d{2}-\d{2}', label) else ''
                label = label.removeprefix(date).replace('-', ' ').replace('_', ' ').strip().capitalize()
                target = query_url(target, mv_title=original.path)
                rows[target] = self.chapter(target, label, n, date)
        else:
            groups = doc.select('figure')
            for n, group in zip(range(len(groups), 0, -1), groups):
                if 'translated' not in group.get('class', ()):
                    continue
                anchor = group.select_one('a[href]')
                image = group.select_one('img[title]')
                target = self.site_link(anchor['href'], final) if anchor else ''
                if not target:
                    continue
                label = re.split(r'[（(]', image['title'], maxsplit=1)[0].rstrip() if image else node_text(anchor)
                stamp = re.search(r'\b\d{4}-\d{2}-\d{2}\b', node_text(group.select_one('figcaption')))
                target = query_url(target, mv_title=original.path)
                rows[target] = self.chapter(target, label, n, stamp[0] if stamp else '')
        return record, self.order(rows)[:MAX_CHAPTERS]

    def pages(self, http, url):
        wire = self.upstream(url)
        if urlsplit(wire).path.startswith('/0_sources/0ther/') and urlsplit(wire).path.endswith('.jpg'):
            return [wire]
        doc, final = self.chapter_document(http, url)
        images = [picture(node, final) for node in doc.select('.webcomic-page img, .mft-cv-image')]
        if images and not any('minifantasytheater' in page.casefold() for page in images):
            cover = images[0].replace('P00.jpg', '.jpg')
            if cover != images[0]:
                images.insert(0, cover)
        return images
