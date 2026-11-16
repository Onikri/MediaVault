"""Rinko Comics catalogue, public WordPress chapter pagination and reader."""

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from manga_madara import SEGMENT, node_text, release_date
from manga_series_port import Cards, Meta, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://rinkocomics.com'
AJAX = ROOT + '/wp-admin/admin-ajax.php'
TITLE = rf'/comic/({SEGMENT})/?'
READER = rf'/(?:comic/)?({SEGMENT}(?:/{SEGMENT}){{0,2}})/?'
NONCE = re.compile(r'comicworld_ajax\s*=\s*\{[^}]*"nonce"\s*:\s*"([a-zA-Z0-9_-]{6,64})"')


def public_form(url, data, referer):
    parts = urlsplit(referer)
    return (url == AJAX and parts.netloc == 'rinkocomics.com' and re.fullmatch(TITLE, parts.path)
            and set(data) == {'action', 'nonce', 'comic_id', 'offset'} and data['action'] == 'load_more_chapters'
            and re.fullmatch(r'[a-zA-Z0-9_-]{6,64}', str(data['nonce']))
            and re.fullmatch(r'[1-9]\d{0,11}', str(data['comic_id']))
            and re.fullmatch(r'\d{1,5}', str(data['offset'])))


class Rinko(SeriesPort):
    cards = Cards('article.ac-card', '.ac-title a', cover='.ac-thumb img', next='.ac-pagination a.next',
                  image_attrs=('data-src', 'data-lazy-src', 'data-original'))
    pinned = Cards('.comics-flex-pinned a.pinned-comic-card', ':scope', '.pinned-comic-title', '.comic-thumbnail img',
                   next='a[rel=next]', image_attrs=('data-src', 'data-lazy-src', 'data-original'))
    meta = Meta('.comic-info-upper h1, h1', 'meta[property="og:image"]', '.comic-synopsis', '',
                '.comic-genres .genres .genre', '', '.comic-graph > span', '.comic-status span:last-child')

    def __init__(self):
        super().__init__(('4915548839286527736', 'Rinko Comics', 'en', ROOT, True), TITLE, READER, interval=.35)

    def is_chapter(self, url):
        path = urlsplit(url).path.rstrip('/')
        return (super().is_chapter(url) and not self.is_title(url) and
                bool(re.search(r'(?:^|[/_-])(?:chapter|ch|episode|ep|chap)[-_/\d]', path, re.I)
                     or ('/' in path.strip('/') and re.match(r'^\d+(?:[.-]\d+)?$', path.rsplit('/', 1)[1]))))

    def title_for(self, url):
        value = param(url, 'mv_rinko_title')
        if re.fullmatch(SEGMENT, value):
            return ROOT + f'/comic/{value}/'
        match = re.match(rf'/comic/({SEGMENT})/', urlsplit(url).path)
        return ROOT + '/comic/' + match[1] + '/' if match else ''

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and (
            self.title_key(self.title_for(target)) == self.title_key(title) or self.confirm_archive_membership(target, title)))

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page == 1 and not query and not tag and sort == 'popular':
            doc, final = self.document(http, ROOT)
            rows = []
            for anchor in doc.select(self.pinned.rows):
                url = self.site_link(anchor.get('href'), final)
                if url and self.is_title(url):
                    rows.append(self.record(url, node_text(anchor.select_one(self.pinned.title)),
                                            picture(anchor.select_one(self.pinned.cover), final, self.pinned.image_attrs)))
            if rows:
                return rows, False
        target = ROOT + ('/comic/' if page == 1 else f'/comic/page/{page}/')
        params = {}
        if query:
            params['s'] = query
        if tag and re.fullmatch(SEGMENT, tag):
            params['genres[]'] = tag
        return self.card_rows(*self.document(http, query_url(target, **params)), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        cover = doc.select_one(spec.cover)
        row['cover'] = picture(cover, url, ('content',)) or row.get('cover', '')
        return row

    def vocabulary(self, http):
        doc, _ = self.document(http, ROOT + '/comic/')
        result = []
        for node in doc.select('.ac-filter-group.ac-genre input[name="genres[]"]'):
            key = node.get('value', '')
            label = node_text(node.parent.select_one('.ac-option-text'))
            if label and re.fullmatch(SEGMENT, key):
                result.append({'key': key, 'label': label, 'kind': 'genre'})
        return result

    def chapter_rows(self, doc, final, title):
        for node in doc.select('li.chapter'):
            anchor = node.select_one('a[href]')
            href = anchor.get('href', '') if anchor else ''
            target = self.site_link(node.get('data-permalink') or href, final)
            if not target or not self.is_chapter(target):
                continue
            label = node_text(node.select_one('.chapter-number')) or node.get('data-title', '')
            locked = (node.get('data-reason', '').casefold() not in ('', 'free') or
                      'locked-chapter' in node.get('class', ()) or href in ('', '#') or node.select_one('.chapter_price'))
            target = query_url(target, mv_rinko_title=self.title_key(title), mv_rinko_locked=int(bool(locked)))
            stamp = node_text(node.select_one('.chapter-date'))
            date = release_date(stamp, '%B %d, %Y') or release_date(stamp, '%b %d, %Y')
            chapter = self.chapter(target, label, date=date)
            if locked:
                chapter.update(available=False, title='🔒 ' + chapter['title'])
            yield chapter

    def chapters(self, http, doc, final):
        rows = {c['url']: c for c in self.chapter_rows(doc, final, final)}
        button = doc.select_one('#loadMoreChaptersBtn[data-comic-id]')
        nonce = NONCE.search(str(doc)) if button else None
        offset = min(int(button['data-offset']), len(rows)) if button and button.get('data-offset', '').isdigit() else len(rows)
        if not nonce:
            return self.order(rows), bool(button)
        for _ in range(100):
            form = {'action': 'load_more_chapters', 'nonce': nonce[1], 'comic_id': button['data-comic-id'], 'offset': str(offset)}
            raw, url, _ = http.document(AJAX, method='POST', data=form, headers={'Referer': final}, action='native-series-form')
            if url != AJAX:
                raise SourceError('Rinko Comics перенаправил запрос глав.')
            payload = json.loads(raw)
            if payload.get('success') is not True:
                return self.order(rows), True
            fragment = (payload.get('data') or {}).get('html') or ''
            batch = list(self.chapter_rows(BeautifulSoup(fragment, 'html.parser'), final, final))
            if not batch:
                return self.order(rows), False
            rows.update((c['url'], c) for c in batch)
            offset += 10
        return self.order(rows), True

    def pages(self, http, url):
        if param(url, 'mv_rinko_locked') == '1' or urlsplit(url).fragment == 'lock':
            raise SourceAccessError('Глава доступна на условиях Rinko Comics.')
        doc, final = self.page_document(http, url.split('?', 1)[0])
        return [value for image in doc.select('img.chapter-image') if (value := picture(image, final, ('data-src',)))]


SOURCES = (Rinko(),)
