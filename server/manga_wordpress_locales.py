"""Multilingual WordPress chapter archives, following Keiyoushi's public readers."""

import re
from urllib.parse import urlsplit

from manga_direct_catalogues import SLUG
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_CHAPTERS, MAX_PAGES, Meta, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceError


ARTICLE = rf'/{SLUG}/?'
PART = rf'/{SLUG}/([1-9][0-9]{{0,4}})/?'
FORBIDDEN = {'page', 'tag', 'category', 'lang', 'genre', 'tags', 'cats', 'group',
             'pairing', 'search', 'feed', 'wp-admin', 'wp-content', 'wp-json'}
IMAGE_SUFFIX = re.compile(r'\.(?:jpe?g|png|webp|avif|gif)(?:[?&#]|$)', re.I)
SIZE = re.compile(r'-\d{1,5}x\d{1,5}(?=\.\w+(?:\?|$))')
MRM_FILTERS = {
    'genre': ('/', '.tagcloud a[href*="/genre/"]', 'ep_filter_genre'),
    'tags': ('/tags/', '.tag-groups-alphabetical-index a', 'ep_filter_post_tag'),
    'cats': ('/cats/', '.tag-groups-alphabetical-index a', 'ep_filter_category'),
    'pairing': ('/pairing/', '.tag-groups-alphabetical-index a', 'ep_filter_pairing'),
    'group': ('/group/', '.tag-groups-alphabetical-index a', 'ep_filter_group'),
}
MYREAD_LANG = {'ar': 'Arabic', 'id': 'Indonesia', 'zh': 'Chinese', 'en': 'English', 'de': 'German',
               'it': 'Italian', 'ja': 'Japanese', 'ko': 'Korean', 'pt-BR': 'Portuguese',
               'ru': 'Russian', 'es': 'Spanish', 'tr': 'Turkish', 'vi': 'Vietnamese'}
YMO_LANG = {'en': 'english-yaoi', 'ja': 'japanese-yaoi', 'zh': 'chinese-yaoi', 'ko': 'korean', 'es': 'spanish'}


class WordPressPosts(SeriesPort):
    def __init__(self, identity):
        super().__init__(identity, ARTICLE, PART, interval=.35)

    def is_title(self, url):
        return super().is_title(url) and not param(url, 'mv_part') and self.title_key(url) not in FORBIDDEN

    def is_chapter(self, url):
        if super().is_chapter(url):
            return self.chapter_key(url) not in FORBIDDEN
        return self.TITLE_PATH.fullmatch(urlsplit(url).path) is not None and param(url, 'mv_part') == '1'

    def title_for(self, url):
        key = self.chapter_key(url) or self.title_key(url)
        return self.ROOT + '/' + key + '/' if key and key not in FORBIDDEN else ''

    def chapter_identity(self, url):
        found = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return (found[1], int(found[2])) if found else (self.title_key(url), 1)

    def saved_chapter(self, row, root, title):
        target = self.canonical(row.get('realUrl') or row.get('url'))
        if self.is_chapter(target):
            return target
        if self.is_title(target) and self.title_key(target) == self.title_key(title):
            return self.first_part(target)
        return ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.chapter_identity(target)[0] == self.title_key(title))

    @staticmethod
    def first_part(url):
        return query_url(url.rstrip('/') + '/', mv_part=1)

    def pages(self, http, url):
        key, index = self.chapter_identity(url)
        wire = self.title_for(url) if index == 1 else url.split('?')[0]
        doc, final = self.document(http, wire)
        if (self.title_key(final), self.chapter_key(final)) not in ((key, ''), ('', key)) or (
                index != 1 and self.chapter_identity(final) != (key, index)):
            raise SourceError('Источником возвращена другая часть комикса.')
        images = []
        for entry in doc.select(self.reader):
            value = picture(entry, final, ('data-src', 'data-cfsrc', 'data-lazy-src'))
            if value and IMAGE_SUFFIX.search(value):
                images.append(value)
        if len(images) > MAX_PAGES:
            raise SourceError('В части комикса слишком много изображений.')
        return list(dict.fromkeys(images))

    @staticmethod
    def terms(doc, selector, section):
        result = []
        for node in doc.select(selector):
            path = urlsplit(node.get('href', '')).path.strip('/').split('/')
            if len(path) == 2 and re.fullmatch(SEGMENT, path[-1]):
                label = node_text(node)
                if label:
                    result.append({'label': label, 'sourceId': f'{section}:{path[-1]}',
                                   'category': 'genre' if section == 'genre' else 'tag'})
        return result


class MyReadingManga(WordPressPosts):
    cards = Cards('article:not(.category-video)', 'a[rel][href]', cover='a.entry-image-link img',
                  image_attrs=('data-src', 'data-cfsrc', 'data-lazy-src'), next='li.pagination-next, a.next')
    meta = Meta('h1', '', '.entry-content p:not(:has(img)):not(.chapter-class + p)',
                genres='.entry-header a[href*="/genre/"]',
                tags='.entry-header a[href*="/tag/"], span.entry-categories a',
                status='a[href*="/status/"]')
    reader = 'div.entry-content img, div.separator img[data-src]'
    index_sort = 'updated'

    def clean_title(self, title):
        return re.sub(r'\s*\([^()]*(?:\)|$)\s*$', '', re.sub(r'\[[^\]]*\]', '', title)).strip()

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        lang = MYREAD_LANG[self.LANGUAGE]
        if not query and not tag and sort == 'updated':
            path = '/lang/' + ('jp' if self.LANGUAGE == 'ja' else lang.lower())
            target = self.ROOT + path + (f'/page/{page}/' if page > 1 else '/')
        else:
            args = {'s': query, 'ep_sort': '' if query else 'date' if tag else 'rand', 'ep_filter_lang': lang}
            section, _, key = tag.partition(':')
            if section in MRM_FILTERS and re.fullmatch(SEGMENT, key):
                args[MRM_FILTERS[section][2]] = key
            target = query_url(self.ROOT + f'/page/{page}/', **args)
        doc, final = self.document(http, target)
        rows, more = self.card_rows(doc, final, self.cards)
        for row in rows:
            row['title'] = self.clean_title(row['title']) or row['title']
            row['aliases'] = list(dict.fromkeys((row['title'], *row['aliases'])))
            row['cover'] = SIZE.sub('', row['cover'])
        count = re.search(r'[0-9][0-9,]*', node_text(doc.select_one('.ep-search-count')))
        return rows, bool(rows and (more or count and page * len(doc.select('article')) < int(count[0].replace(',', ''))))

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        original = row['title']
        row['title'] = self.clean_title(original) or original
        row['aliases'] = list(dict.fromkeys((row['title'], original)))
        row['authors'] = [match[1]] if (match := re.match(r'\s*\[([^\]]{1,160})\]', original)) else []
        if not row['cover']:
            row['cover'] = picture(doc.select_one('.entry-content img'), url, ('data-src', 'data-cfsrc', 'data-lazy-src'))
        row['cover'] = SIZE.sub('', row['cover'])
        group = ', '.join(node_text(node) for node in doc.select('.entry-terms a[href*="/group/"]'))
        if group:
            row['translators'] = [group]
        return row

    def chapters(self, http, doc, final):
        date = release_date(node_text(doc.select_one('.entry-time')), '%B %d, %Y')
        translator = ', '.join(node_text(node) for node in doc.select('.entry-terms a[href*="/group/"]'))
        last = max((int(node_text(node)) for node in doc.select('a.page-numbers')
                    if re.fullmatch(r'[0-9]{1,5}', node_text(node))), default=1)
        rows = [self.chapter(self.first_part(final) if index == 1 else final.rstrip('/') + f'/{index}/',
                             f'Part {index}', index, date, translator=translator)
                for index in range(1, min(last, MAX_CHAPTERS) + 1)]
        return rows, last > MAX_CHAPTERS

    def vocabulary(self, http):
        result = []
        for section, (path, css, _) in MRM_FILTERS.items():
            doc, _ = self.document(http, self.ROOT + path)
            result.extend(self.terms(doc, css, section))
        return result


class YaoimangaOnline(WordPressPosts):
    cards = Cards('.post:not(.sticky):not(.category-gay-movies):not(.category-yaoi-anime) > div > a[title][href]',
                  '', cover='img', title_attr='title', next='.herald-pagination > .next')
    meta = Meta('h1.entry-title', '', '.entry-content > p:not(:has(img)):not(:-soup-contains("You need to login"))',
                genres='.meta-category a:not([href*="/mangaka/"]):not([href*="/yaoi-webtoons/"])',
                tags='.meta-tags > a', author='.meta-category a[href*="/mangaka/"]')
    reader = '.entry-content img'

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        language = YMO_LANG.get(self.LANGUAGE)
        if query or tag:
            args = {'s': query}
            group, _, key = tag.partition(':')
            if group == 'category' and key.isdecimal() and key not in ('3017', '2009'):
                args['cat'] = key
            filters = [language] if language else []
            if group == 'tag' and re.fullmatch(SEGMENT, key):
                filters.append(key)
            if filters:
                args['tag'] = '+'.join(filters)
            url = query_url(self.ROOT + f'/page/{page}/', **args)
        else:
            prefix = f'/tag/{language}' if language else ''
            url = self.ROOT + prefix + (f'/page/{page}/' if page > 1 else '/')
        rows, more = self.card_rows(*self.document(http, url), self.cards)
        for row in rows:
            row['cover'] = SIZE.sub('', row['cover'])
        return rows, more

    def metadata(self, doc, url, spec):
        if not doc.select_one('article.herald-single'):
            raise SourceError('Источник не предоставил карточку комикса.')
        row = super().metadata(doc, url, spec)
        row['title'] = row['title'].rsplit(' by ', 1)[0]
        article = doc.select_one('article.herald-single')
        classes = set(article.get('class', []))
        if classes & {'category-completed', 'tag-completed-yaoi-manga', 'tag-completed-yaoi-manhwa'}:
            row['status'] = 'completed'
        elif 'category-ongoing' in classes:
            row['status'] = 'ongoing'
        elif 'category-hiatus' in classes:
            row['status'] = 'hiatus'
        return row

    def chapters(self, http, doc, final):
        date = doc.select_one('meta[property="article:published_time"][content]')
        published = release_date(date['content'][:10], '%Y-%m-%d') if date else ''
        rows = {}
        for node in doc.select('.mpp-toc a[href]'):
            target = self.site_link(node['href'], final)
            if not target:
                continue
            if self.title_key(target) == self.title_key(final):
                target = self.first_part(final)
            if self.saved_chapter_matches(target, final):
                idx = self.chapter_identity(target)[1]
                rows[target] = self.chapter(target, node_text(node), idx, published if idx == 1 else '')
        if not rows:
            target = self.first_part(final)
            rows[target] = self.chapter(target, 'Chapter', 1, published)
        return self.order(rows), False

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/')
        result = self.terms(doc, '.tagcloud a', 'tag')
        for node in doc.select('select#cat option[value]'):
            value = node['value']
            if value.isdecimal() and value not in ('3017', '2009'):
                result.append({'label': node_text(node).rsplit('(', 1)[0].strip(),
                               'sourceId': 'category:' + value, 'category': 'genre'})
        return result


SOURCES = (
    *(MyReadingManga((sid, 'MyReadingManga', language, 'https://myreadingmanga.info', True)) for sid, language in (
        ('4864082317433034574', 'ar'), ('8842237058298566885', 'id'), ('8339625080404115366', 'zh'),
        ('6318378620301107421', 'en'), ('2084769296792806394', 'de'), ('3371822795753272045', 'it'),
        ('7616097631685192755', 'ja'), ('8341594492961776810', 'ko'), ('7097816699537539700', 'pt-BR'),
        ('4213491422253699699', 'ru'), ('3547244847403070407', 'es'), ('164535712016830416', 'tr'),
        ('4129272632455883902', 'vi'),
    )),
    *(YaoimangaOnline((sid, 'Yaoi Manga Online', language, 'https://yaoimangaonline.com', True)) for sid, language in (
        ('7988826691692266469', 'all'), ('9170758785588278310', 'en'), ('538554294784343580', 'ja'),
        ('5333366346732866061', 'zh'), ('5411991591973083095', 'ko'), ('6023955409820928295', 'es'),
    )),
)
