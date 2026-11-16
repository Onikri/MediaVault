"""11toon forum-style catalogues with the reader's alternate image host."""

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Meta, SeriesPort, picture
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://www.11toon.com'
BOARD = '/bbs/board.php'
SCRIPT_LIST = tuple(re.compile(r'(?<![\w_])' + key + r'\s*=\s*(\[[^\]]*])', re.S)
                    for key in ('img_list', 'img_list_2'))
CHAPTER_URL = re.compile(r"""location\.href\s*=\s*['"]([^'"]+)['"]""")


@dataclass(frozen=True)
class ToonMirrorPage:
    fallback: str


class Toon11(SeriesPort):
    meta = Meta('h2.title', 'img.banner', 'span:-soup-contains-own("소개") + span',
                '', 'span:-soup-contains-own("장르") + span',
                '', 'span:-soup-contains-own("작가") + span', 'span:-soup-contains-own("분류") + span')

    def __init__(self):
        super().__init__(('8796296375202334266', '11toon', 'ko', ROOT, True),
                         r'(/bbs/board\.php)', r'(/bbs/(?:board|view|viewer)\.php)',
                         hosts=('11toon.com',), interval=.35)

    def title_key(self, url):
        return param(url, 'is') or param(url, 'mv_11toon_title')

    def is_title(self, url):
        return (super().is_title(url) and param(url, 'bo_table') == 'toons'
                and bool(re.fullmatch(SEGMENT, param(url, 'is'))) and param(url, 'mv_11toon_read') != '1'
                and not param(url, 'wr_id'))

    def is_chapter(self, url):
        return (super().is_chapter(url) and not self.is_title(url) and
                (param(url, 'mv_11toon_read') == '1' or bool(param(url, 'wr_id') or param(url, 'no'))))

    def title_for(self, url):
        key = self.title_key(url)
        return query_url(ROOT + BOARD, bo_table='toons', **{'is': key}) if re.fullmatch(SEGMENT, key) else ''

    def chapter_identity(self, value):
        return query_url(value, mv_11toon_title=[], mv_11toon_read=[]).partition('://')[-1].partition('/')[2]

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        old = row.get('realUrl') or row.get('url') or ''
        if old.startswith('/board.php?'):
            target = self.site_link(ROOT + '/bbs' + old)
            if target:
                return query_url(target, mv_11toon_read=1, mv_11toon_title=self.title_key(title))
        return ''

    def saved_chapter_matches(self, target, title):
        if not self.is_chapter(target):
            return False
        key = self.title_key(target)
        return key == self.title_key(title) if key else self.confirm_archive_membership(target, title)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            target = query_url(ROOT + '/bbs/search_stx.php', stx=query, page=page)
        else:
            args = {'bo_table': 'toon_c', 'page': page}
            if sort == 'updated':
                args.update(sord='', type='upd')
            else:
                args['is_over'] = '0'
            if tag and len(tag) <= 60:
                args['sca'] = tag
            target = query_url(ROOT + BOARD, **args)
        doc, final = self.document(http, target)
        rows = []
        for node in doc.select('li[data-id]'):
            key, title = node['data-id'], node_text(node.select_one('.homelist-title'))
            if not re.fullmatch(SEGMENT, key) or not title:
                continue
            url = query_url(ROOT + BOARD, bo_table='toons', **{'is': key})
            cover = picture(node.select_one('.homelist-thumb'), final, ('data-mobile-image',))
            rows.append(self.record(url, title, cover))
        next_page = doc.select_one('.pg_current ~ .pg_page, .pg_next, .pg_end[href]')
        return rows, bool(rows and next_page)

    def metadata(self, doc, final, spec):
        row = super().metadata(doc, final, spec)
        state = row['status']
        row['status'] = 'completed' if '완결' in state else 'ongoing' if any(word in state for word in ('주간', '월간', '연재', '격주')) else ''
        row['genres'] = [value.strip() for joined in row['genres'] for value in joined.split(',') if value.strip()]
        return row

    def chapters(self, http, doc, final):
        key = self.title_key(final)
        visited, result = set(), {}
        for _ in range(80):
            if final in visited:
                break
            visited.add(final)
            for row in doc.select('#comic-episode-list > li'):
                button = row.select_one('button[onclick]')
                match = CHAPTER_URL.search(button['onclick']) if button else None
                if not match:
                    continue
                route = self.site_link(match[1], final)
                if not route:
                    continue
                target = query_url(route, mv_11toon_read=1, mv_11toon_title=key)
                if self.is_chapter(target):
                    date = release_date(node_text(row.select_one('.free-date')), '%y.%m.%d')
                    result[target] = self.chapter(target, node_text(button.select_one('.episode-title')), date=date)
            next_link = doc.select_one('.pg_current ~ .pg_page[href]')
            if not next_link:
                return self.order(result), False
            target = self.site_link(next_link['href'], final)
            if not self.is_title(target) or self.title_key(target) != key:
                raise SourceError('11toon перенаправил список глав на другой тайтл.')
            doc, final = self.document(http, target)
        return self.order(result), True

    def pages(self, http, url):
        target = query_url(url, mv_11toon_title=[], mv_11toon_read=[])
        doc, final = self.document(http, target)
        if self.chapter_identity(final) != self.chapter_identity(url):
            raise SourceError('11toon перенаправил ридер на другой выпуск.')
        for script in doc.select('script'):
            raw = script.string or ''
            groups = tuple(pattern.search(raw) for pattern in SCRIPT_LIST)
            if not groups[0]:
                continue
            sources, copies = (json.loads(match[1]) if match else [] for match in groups)
            if not isinstance(sources, list) or not isinstance(copies, list):
                raise SourceError('11toon изменил формат списка страниц.')
            refs = []
            for index, value in enumerate(sources):
                main = image_url(value, final)
                mirror = image_url(copies[index], final) if index < len(copies) else ''
                if not main:
                    main, mirror = mirror, ''
                if not main:
                    raise SourceError('11toon вернул некорректную страницу.')
                refs.append((main, ToonMirrorPage(mirror)))
            return remember(refs, final)
        return []


SOURCES = (Toon11(),)
