"""Tapas (keiyoushi ``src/en/tapastic`` at 6f345a8).

Rankings and the newest list come from ``story-api.tapas.io``; search,
series cards and episode pages are public HTML on ``tapas.io``, and the
episode list is the site's own XHR. Only free or guest-unlocked comic
episodes open; the others stay listed as paid (``locked``): a locked episode page has no images, and a novel
episode is not a comic. Both requests carry the extension's birth date
cookies so that mature series answer the same way as in the app.
"""

from datetime import datetime
import json
import re
import time
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from manga_direct_payloads import JsonSeries
from manga_madara import image_url, node_text
from manga_ninth_routes import Route, register
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://tapas.io'
API = 'https://story-api.tapas.io/cosmos/api/v1/landing/'
ID = r'[1-9][0-9]{0,11}'
SLUG = r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}'
COOKIE = 'birthDate=1990-01-01; adjustedBirthDate=1990-01-01'
HIGHLIGHT = re.compile(r'#/?_h_i_g_h_L_i_g_h_t_#')
MAX_EPISODE_PAGES = 60


def fields(query):
    try:
        rows = parse_qsl(query, keep_blank_values=True, max_num_fields=10, strict_parsing=True)
    except ValueError:
        return None
    args = dict(rows)
    return args if len(args) == len(rows) else None


def route(url, method, data, headers):
    if method != 'GET' or data is not None:
        return None
    args = fields(url.query) if url.query else {}
    if args is None:
        return None
    page = args.get('page', '')
    html = {'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8', 'Cookie': COOKIE, 'Referer': 'https://m.tapas.io'}
    xhr = {'Accept': 'application/json, text/javascript, */*; q=0.01', 'X-Requested-With': 'XMLHttpRequest',
           'Cookie': COOKIE, 'Referer': 'https://m.tapas.io'}
    if url.netloc == 'story-api.tapas.io' and re.fullmatch(r'[0-9]{1,4}', page):
        if url.path.endswith('/landing/ranking') and args == {'category_type': 'COMIC', 'subtab_id': '17', 'size': '25', 'page': page}:
            return Route(headers=xhr, redirect=False)
        if url.path.endswith('/landing/genre') and args == {'category_type': 'COMIC', 'sort_option': 'NEWEST_EPISODE',
                                                            'subtab_id': '17', 'pageSize': '25', 'page': page}:
            return Route(headers=xhr, redirect=False)
        return None
    if url.netloc != 'tapas.io':
        return None
    if url.path == '/search' and set(args) == {'pageNumber', 'q', 't'} and args['t'] == 'COMICS' \
            and re.fullmatch(r'[1-9][0-9]{0,3}', args['pageNumber']) and 1 <= len(args['q']) <= 160:
        return Route(headers=html, redirect=False)
    if re.fullmatch(rf'/series/(?:{ID}|{SLUG})/info', url.path) and not url.query:
        # The numeric card redirects to the slug card on the same host.
        return Route(headers=html)
    if re.fullmatch(rf'/series/{ID}/episodes', url.path) and set(args) == {'page', 'sort', 'since', 'large', 'last_access', ''} \
            and re.fullmatch(r'[1-9][0-9]{0,3}', page) and args['sort'] == 'OLDEST' and re.fullmatch(r'[0-9]{13}', args['since']) \
            and args['large'] == 'true' and args['last_access'] == '0' and args[''] == '':
        return Route(headers=xhr, redirect=False)
    if re.fullmatch(rf'/episode/{ID}', url.path) and not url.query:
        return Route(headers=html, redirect=False)
    return None


register('tapas', route)


def date_of(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        return ''


class Tapas(JsonSeries):
    def __init__(self):
        super().__init__(('5554748812413853237', 'Tapas', 'en', ROOT, True), rf'/series/({ID})/?', rf'/episode/({ID})',
                         interval=.25)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(ID, param(url, 'mv_series')))

    def title_for(self, url):
        return f'{ROOT}/series/{param(url, "mv_series")}'

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def saved_title_url(self, value):
        target = self.canonical(value)
        match = re.fullmatch(rf'/series/({ID})(?:/info)?/?', urlsplit(target).path)
        return f'{ROOT}/series/{match[1]}' if match else ''

    def saved_chapter(self, row, root, title):
        # Suwayomi stored "/episode/<id>".
        target = super().saved_chapter(row, root, title)
        key = self.title_key(title)
        found = re.fullmatch(rf'/episode/({ID})/?', urlsplit(target).path)
        return query_url(f'{ROOT}/episode/{found[1]}', mv_series=key) if found and key else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and param(target, 'mv_series') == self.title_key(title)

    def fetch(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={}, action='n9:tapas')
        return raw, final

    def api(self, http, url):
        raw, _ = self.fetch(http, url)
        try:
            return json.loads(raw)
        except ValueError:
            raise SourceError('Tapas изменил формат API.') from None

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag:
            return [], False
        if query:
            raw, final = self.fetch(http, query_url(ROOT + '/search', pageNumber=str(page), q=query, t='COMICS'))
            doc = BeautifulSoup(raw, 'html.parser')
            rows = {}
            for node in doc.select('.search-item-wrap'):
                link = node.select_one('.item__thumb a[data-series-id], .title-section .title a[data-series-id], a[data-series-id]')
                key = link.get('data-series-id', '') if link else ''
                if not re.fullmatch(ID, key) or link.get('data-series-type', 'COMICS') != 'COMICS':
                    continue
                image = node.select_one('.item__thumb img, .thumb-wrap img')
                name = node_text(node.select_one('.title-section .title a')) or HIGHLIGHT.sub('', image.get('alt', '') if image else '')
                if not name:
                    continue
                row = self.record(f'{ROOT}/series/{key}', name.strip(), image_url(image.get('src'), final) if image else '',
                                  description=node_text(node.select_one('.desc.force.mbm')))
                rows[row['id']] = row
            return list(rows.values()), bool(doc.select_one('a[class*=paging__button--next]'))
        if sort == 'updated':
            target = query_url(API + 'genre', category_type='COMIC', sort_option='NEWEST_EPISODE', subtab_id='17',
                               pageSize='25', page=str(page - 1))
        else:
            target = query_url(API + 'ranking', category_type='COMIC', subtab_id='17', size='25', page=str(page - 1))
        data = self.api(http, target)
        items = ((data.get('data') or {}).get('items') if isinstance(data, dict) else None)
        if not isinstance(items, list):
            raise SourceError('Tapas изменил формат каталога.')
        rows = []
        for item in items:
            if not isinstance(item, dict) or type(item.get('seriesId')) is not int or not isinstance(item.get('title'), str):
                continue
            covers = ((item.get('assetProperty') or {}).get('bookCoverImage') or {}) if isinstance(item.get('assetProperty'), dict) else {}
            cover = next((value + '.png' for value in covers.values() if isinstance(value, str)), '') if isinstance(covers, dict) else ''
            genres = [genre.get('value') for genre in item.get('genreList') or [] if isinstance(genre, dict)]
            row = self.record(f'{ROOT}/series/{item["seriesId"]}', item['title'].strip(), cover,
                              description=str(item.get('description') or ''), genres=genres,
                              authors=[name for name in item.get('authorList') or [] if isinstance(name, str)],
                              status='completed' if item.get('issueStatus') == 'COMPLETED' else 'ongoing')
            if item.get('mature'):
                row['adult'] = True
            rows.append(row)
        pagination = (data.get('meta') or {}).get('pagination') or {}
        return rows, pagination.get('last') is False

    def series(self, http, url):
        key = self.title_key(url)
        if not key:
            raise SourceError('Некорректная ссылка на серию Tapas.')
        raw, final = self.fetch(http, f'{ROOT}/series/{key}/info')
        doc = BeautifulSoup(raw, 'html.parser')
        marker = doc.select_one('meta[content^="tapastic://series/"]')
        if not marker or not re.fullmatch(rf'tapastic://series/{key}(?:/info)?', marker['content']):
            raise SourceError('Tapas вернул карточку другой серии.')
        name = node_text(doc.select_one('.info__right .title'))
        if not name:
            raise SourceError('Tapas не предоставил карточку серии.')
        cover = doc.select_one('.thumb.js-thumbnail img')
        schedule = node_text(doc.select_one('.schedule-ico:has(.sp-ico-updated-line-pwt) + .schedule-label')).casefold()
        row = self.record(f'{ROOT}/series/{key}', name, image_url(cover.get('src'), final) if cover else '',
                          description=node_text(doc.select_one('.description__body')),
                          genres=[node_text(node) for node in doc.select('.genre-btn')],
                          authors=[node_text(node) for node in doc.select('.creator-section .name')],
                          status='completed' if 'completed' in schedule else 'ongoing' if 'updates' in schedule else '')
        since = str(int(time.time() * 1000))
        chapters = {}
        for page in range(1, MAX_EPISODE_PAGES + 1):
            data = self.api(http, query_url(f'{ROOT}/series/{key}/episodes', page=str(page), sort='OLDEST', since=since,
                                            large='true', last_access='0') + '&=')
            body = data.get('data') if isinstance(data, dict) else None
            episodes = body.get('episodes') if isinstance(body, dict) else None
            if not isinstance(episodes, list):
                raise SourceError('Tapas не предоставил список эпизодов.')
            for item in episodes:
                if not isinstance(item, dict) or type(item.get('id')) is not int or item.get('scheduled'):
                    continue
                scene = item.get('scene')
                target = query_url(f'{ROOT}/episode/{item["id"]}', mv_series=key)
                chapters[target] = {**self.chapter(target, str(item.get('title') or f'Episode {scene}'),
                                                   float(scene) if isinstance(scene, (int, float)) else None,
                                                   date_of(item.get('publish_date'))),
                                    'locked': not (item.get('free') or item.get('unlocked'))}
            if not (body.get('pagination') or {}).get('has_next'):
                break
        return row, self.order(chapters)

    def pages(self, http, url):
        raw, final = self.fetch(http, f'{ROOT}/episode/{self.chapter_key(url)}')
        doc = BeautifulSoup(raw, 'html.parser')
        if doc.select_one('.toolbar a[data-type="style"]'):
            raise SourceAccessError('Это эпизод новеллы Tapas, а не комикса.')
        pages = [image_url(node.get('data-src') or node.get('src'), final) for node in doc.select('img.content__img')]
        if not pages:
            raise SourceAccessError('Эпизод Tapas закрыт для открытого чтения.')
        return pages


SOURCES = (Tapas(),)
