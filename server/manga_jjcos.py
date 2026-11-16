"""JJCOS public post catalogue and gallery pages."""

import re
from urllib.parse import parse_qsl, urlsplit

from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Meta, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceError

ROOT = 'https://jjcos.com'
HOSTS = ('jjcos.com', 'www.jjcos.com')
POST = rf'/post/({SEGMENT}(?:/{SEGMENT}){{0,3}})/?'
SIZE = 20


def public_api(host, path, query):
    if host not in HOSTS or path != '/api/index.html':
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    return (len(args) == len(pairs) and {'page'} <= set(args) <= {'page', 'query'}
            and bool(re.fullmatch(r'[1-9]\d{0,3}', args['page'])) and len(args.get('query', '')) <= 160)


class JJCos(SeriesPort):
    meta = Meta('h1.fh5co-article-title', '#post-content img, article img', '', '',
                '', '.tag-container a.tag')

    def __init__(self):
        super().__init__(('5763134940669279175', 'JJCOS', 'all', ROOT, True),
                         POST, POST, hosts=HOSTS[1:], interval=.35)

    def is_title(self, url):
        return super().is_title(url) and param(url, 'mv_jjcos_gallery') != '1'

    def title_for(self, url):
        target = query_url(url, mv_jjcos_gallery=[])
        return target if self.is_title(target) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        return query_url(target, mv_jjcos_gallery=1) if self.is_chapter(target) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        params = {'page': page}
        if query or tag:
            params['query'] = query or tag[:160]
        payload = self.json(http, query_url(ROOT + '/api/index.html', **params))
        rows = payload.get('posts')
        if not isinstance(rows, list):
            raise SourceError('JJCOS изменил структуру каталога.')
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            link = self.site_link(row.get('link'))
            title = row.get('title')
            if not self.is_title(link) or not isinstance(title, str) or not title:
                continue
            body = str(row.get('content') or '')
            if query and query.casefold() not in (title + ' ' + body).casefold():
                continue
            cover = image_url(row.get('feature'), link)
            result.append(self.record(link, title, cover, status='completed'))
        start = (page - 1) * SIZE
        if len(rows) > start and page > 1 and len(rows) >= SIZE * 2:
            return result[start:start + SIZE], start + SIZE < len(result)
        return result[:SIZE], len(result) >= SIZE

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['title'] = row['title'].removesuffix(' - JJCOS').strip()
        row['tags'] = [label.removeprefix('#').strip() for label in row['tags']]
        row.update(format='gallery', status='completed')
        return row

    def chapters(self, http, doc, final):
        time = doc.select_one('meta[property="article:published_time"][content]')
        label = time['content'] if time else node_text(doc.select_one('.breadcrumb-item.date-overlay'))
        date = release_date(label[:10], '%Y-%m-%d')
        target = query_url(final, mv_jjcos_gallery=1)
        return [self.chapter(target, 'Gallery', 1, date=date)], False

    def pages(self, http, url):
        target = self.title_for(url)
        doc, final = self.page_document(http, target)
        images = doc.select('#post-content img, article #post-content img, article p img')
        return list(dict.fromkeys(src for node in images if (src := picture(node, final))))


SOURCES = (JJCos(),)
