"""VyvyManga maintains stable chapter identifiers and refreshes expiring links."""

import hashlib
import re
from urllib.parse import urlsplit

from manga_madara import SEGMENT, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://mangavyvy.net'
HOSTS = ('mangavyvy.com', 'www.mangavyvy.net', 'www.mangavyvy.com')
LEGACY = ('vyvymanga.net', 'vyvymanga.com', 'vyvymanga.org', 'www.vyvymanga.net', 'www.vyvymanga.com')
TITLE = rf'/manga/({SEGMENT})/?'
STABLE = re.compile(rf'/manga/({SEGMENT})/mv-chapter/([a-f\d]{{16}})/?')
DIRECT = re.compile(rf'/(?:chapter|read|manga)/({SEGMENT}(?:/{SEGMENT}){{0,3}})/?')
BOOKMARK = re.compile(r'[a-f\d]{10}')


class VyvyManga(SeriesPort):
    cards = Cards('.comic-item', 'a[href]', '.comic-title', '.comic-image img.image.lozad')
    meta = Meta('h1', '.img-manga img', '.summary > .content', 'h1.title + p:not(.text-info)',
                '.pre-title:-soup-contains-own("Genres") ~ a', '',
                '.pre-title:-soup-contains-own("Artist") ~ a, .pre-title:-soup-contains-own("Author") ~ a',
                '.pre-title:-soup-contains-own("Status") ~ span:not(.space)')

    def __init__(self):
        super().__init__(('6958928548959982041', 'VyvyManga', 'en', ROOT, True), TITLE,
                         DIRECT.pattern, hosts=HOSTS, legacy_hosts=LEGACY, interval=.35)

    def is_chapter(self, url):
        return super().is_chapter(url) and not self.is_title(url)

    def title_for(self, url):
        parts = urlsplit(url)
        match = STABLE.fullmatch(parts.path)
        if match:
            return parts.scheme + '://' + parts.netloc + '/manga/' + match[1]
        value = param(url, 'mv_vyvy_title')
        if re.fullmatch(SEGMENT, value):
            return ROOT + '/manga/' + value
        return ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        params = {'page': page} if page > 1 else {}
        if query:
            params['q'] = query
        if sort == 'updated':
            params['sort'] = 'updated_at'
        if re.fullmatch(r'[\w-]{1,80}', tag):
            params['genre[]'] = tag
        return self.card_rows(*self.document(http, query_url(ROOT + '/search', **params)), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        label = node_text(doc.select_one(spec.aliases))
        row['aliases'] = [value.strip() for value in re.split('[,;]', label) if value.strip() and value.strip() != row['title']]
        return row

    def vocabulary(self, http):
        result = {}
        doc, _ = self.document(http, ROOT + '/search')
        for wrapper in doc.select('.check-genre div div:has(.checkbox-genre)'):
            node = wrapper.select_one('.checkbox-genre[data-value]')
            label = node_text(wrapper.select_one('label'))
            if node and label and re.fullmatch(r'[\w-]{1,80}', node['data-value']):
                result[node['data-value']] = {'key': node['data-value'], 'label': label, 'kind': 'genre'}
        return list(result.values())

    def chapter_rows(self, doc, final):
        for node in doc.select('.list-group > a[href]'):
            leaf = node.select_one('span')
            title = node_text(leaf)
            url = self.site_link(node['href'], final)
            if not title or not self.is_chapter(url):
                continue
            section = node.select_one('p')
            texts = section.find_all(string=True, recursive=False) if section else []
            stamp = next((value.strip() for value in reversed(texts) if value.strip()), '')
            date = release_date(stamp, '%b %d, %Y')
            group = node_text(section.select_one('span.font-weight-bold')) if section else ''
            n = number(node.get('id', '').removeprefix('chapter-'))
            identity = hashlib.sha256(f'{title}\n{group}\n{n!s}'.encode()).hexdigest()[:16]
            target = final.split('?', 1)[0].rstrip('/') + '/mv-chapter/' + identity
            old = hashlib.md5(f'{date}:{title}'.encode(), usedforsecurity=False).hexdigest()[-10:]
            yield self.chapter(target, title, n, date, translator=group), url, old

    def chapters(self, http, doc, final):
        result = {row['url']: row for row, _, _ in self.chapter_rows(doc, final)}
        return self.order(result), False

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        key = urlsplit(target).path.strip('/')
        if BOOKMARK.fullmatch(key) and self.is_title(title):
            ordinal = number(row.get('number'))
            if ordinal is not None or row.get('title') or row.get('name'):
                label = str(row.get('title') or row.get('name') or '')[:200]
                return query_url(title.rstrip('/') + '/mv-chapter/' + '0' * 16,
                                 mv_vyvy_legacy=key, mv_vyvy_name=label, mv_vyvy_number=ordinal or '')
        return ''

    def saved_chapter_matches(self, target, title):
        bound = self.title_for(target)
        return bool(self.is_chapter(target) and (self.title_key(bound) == self.title_key(title)
                                                if bound else self.confirm_archive_membership(target, title)))

    def refresh(self, http, url):
        match = STABLE.fullmatch(urlsplit(url).path)
        if not match:
            return url
        doc, final = self.title_document(http, self.title_for(url))
        candidates = list(self.chapter_rows(doc, final))
        target = {STABLE.fullmatch(urlsplit(self.site_link(row['url'])).path)[2]: actual for row, actual, _ in candidates}
        if match[2] in target:
            return target[match[2]]
        legacy = param(url, 'mv_vyvy_legacy')
        if BOOKMARK.fullmatch(legacy):
            direct = [actual for row, actual, old in candidates if old == legacy]
            if len(direct) == 1:
                return direct[0]
            label = param(url, 'mv_vyvy_name')
            ordinal = number(param(url, 'mv_vyvy_number'))
            matches = [actual for row, actual, _ in candidates if (label and row['title'] == label)
                       or (not label and ordinal is not None and row['number'] == ordinal)]
            if len(matches) == 1:
                return matches[0]
        raise SourceError('VyvyManga не предоставил новую ссылку выбранной главы.')

    def pages(self, http, url):
        target = self.refresh(http, url)
        doc, final = self.document(http, target)
        if not self.is_chapter(final) or self.chapter_identity(target) != self.chapter_identity(final):
            raise SourceError('VyvyManga перенаправил на другую главу.')
        pages = [src for node in doc.select('img.d-block[data-src]') if (src := picture(node, final, ('data-src',)))]
        if not pages:
            raise SourceAccessError('VyvyManga не предоставил открытые изображения главы.')
        return pages


SOURCES = (VyvyManga(),)
