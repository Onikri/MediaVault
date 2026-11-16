"""Korean profiles with separate source IDs and catalogue paths."""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote_plus, urlsplit

from manga_direct_payloads import items
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Cards, MAX_CHAPTERS, Meta, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceError

NAVER = 'https://comic.naver.com'
NAVER_MOBILE = 'https://m.comic.naver.com'
NAVER_TYPES = ('webtoon', 'bestChallenge', 'challenge')
NEWX = 'https://newxtoon5.com'
WOLF = 'https://wfwf507.com'
NUMBER = r'[1-9]\d{0,10}'
PAGE = r'[1-9]\d{0,3}'
SEOUL = timezone(timedelta(hours=9))


def public_api(host, path, query):
    if host not in {'comic.naver.com', 'newxtoon5.com'}:
        return False
    pairs = parse_qsl(query)
    args = dict(pairs)
    if len(args) != len(pairs) or any(len(value) > 160 for value in args.values()):
        return False
    valid_page = bool(re.fullmatch(PAGE, args.get('page', '')))
    if host == 'newxtoon5.com':
        return (bool(re.fullmatch(rf'/comics/{NUMBER}/chapters', path)) and set(args) == {'sort', 'page'}
                and args['sort'] == 'latest' and valid_page)
    if path in ('/api/article/list', '/api/article/list/info'):
        identity = bool(re.fullmatch(NUMBER, args.get('titleId', '')))
        return identity and (set(args) == {'titleId'} if path.endswith('info') else set(args) == {'titleId', 'page'} and valid_page)
    if path in {f'/api/search/{kind}' for kind in NAVER_TYPES}:
        return set(args) == {'keyword', 'page'} and bool(args['keyword']) and valid_page
    return (path in {f'/api/{kind}/list' for kind in NAVER_TYPES[1:]}
            and set(args) == {'page', 'order'} and args['order'] in {'VIEW', 'UPDATE'} and valid_page)


class NaverComic(SeriesPort):
    def __init__(self, sid, name, kind):
        self.kind = kind
        super().__init__((sid, name, 'ko', NAVER, False), rf'(/{kind}/list)', rf'(/{kind}/detail)',
                         hosts=('m.comic.naver.com',), interval=.35)

    def is_title(self, url):
        return super().is_title(url) and bool(re.fullmatch(NUMBER, self.title_key(url)))

    def is_chapter(self, url):
        return (super().is_chapter(url) and bool(re.fullmatch(NUMBER, self.title_key(url)))
                and bool(re.fullmatch(NUMBER, param(url, 'no'))))

    def title_key(self, url):
        return param(url, 'titleId')

    def title_url(self, key):
        return query_url(NAVER + '/' + self.kind + '/list', titleId=key)

    def title_for(self, url):
        key = self.title_key(url)
        return self.title_url(key) if re.fullmatch(NUMBER, key) else ''

    def chapter_identity(self, url):
        return self.kind, self.title_key(url), param(url, 'no')

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url) or self.is_chapter(url):
            return self.title_for(url)
        key = urlsplit(url).path.strip('/')
        return self.title_url(key) if re.fullmatch(NUMBER, key) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def summary(self, item):
        identity, name = str(item.get('titleId') or ''), item.get('titleName')
        if not re.fullmatch(NUMBER, identity) or not isinstance(name, str) or not name:
            return None
        url = self.title_url(identity)
        authors = [p.get('name') for p in item.get('communityArtists') or [] if isinstance(p, dict)]
        row = self.record(url, name, image_url(item.get('thumbnailUrl'), url), authors=authors,
                          status='hiatus' if item.get('rest') else 'completed' if item.get('finished') else 'ongoing',
                          description=item.get('synopsis') or '')
        row['format'] = 'webtoon'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query or self.kind != 'webtoon':
            path = '/api/search/' + self.kind if query else '/api/' + self.kind + '/list'
            params = {'keyword': query} if query else {'order': 'UPDATE' if sort == 'updated' else 'VIEW'}
            data = self.json(http, query_url(NAVER + path, page=page, **params))
            rows = [row for item in items(data, 'searchList' if query else 'list') if (row := self.summary(item))]
            next_page = (data.get('pageInfo') or {}).get('nextPage')
            return rows, bool(rows and (next_page or next_page is None))
        if page != 1:
            return [], False
        url = query_url(NAVER_MOBILE + '/webtoon/weekday', sort='UPDATE' if sort == 'updated' else 'ALL_READER')
        doc, final = self.document(http, url)
        rows = {}
        for node in doc.select('.list_toon > .item'):
            anchor = node.select_one('a[href]')
            target = self.site_link(anchor['href'], final) if anchor else ''
            name = node_text(node.select_one('strong'))
            if self.is_title(target) and name:
                row = self.record(self.title_for(target), name, picture(node.select_one('img'), final),
                                  authors=node_text(node.select_one('span.author')).split(' / '))
                row['format'] = 'webtoon'
                rows[row['url']] = row
        return list(rows.values()), False

    def details(self, http, value):
        url = self.saved_title_url(value)
        if not self.is_title(url):
            raise SourceError('Некорректная карточка Naver Webtoon.')
        key = self.title_key(url)
        data = self.json(http, query_url(NAVER + '/api/article/list/info', titleId=key), url)
        if str(data.get('titleId')) != key or not (row := self.summary(data)):
            raise SourceError('Naver Webtoon не предоставил указанный тайтл.')
        return row

    def chapter_rows(self, http, url):
        key = self.title_key(url)
        page, result, seen = 1, {}, set()
        while page not in seen and 1 <= page <= 2000:
            seen.add(page)
            target = query_url(NAVER + '/api/article/list', titleId=key, page=page)
            data = self.json(http, target, url)
            if str(data.get('titleId')) != key:
                raise SourceError('Naver Webtoon подменил оглавление.')
            for row in items(data, 'articleList'):
                cid = str(row.get('no', ''))
                if re.fullmatch(NUMBER, cid):
                    stamp = str(row.get('serviceDateDescription') or '')
                    date = datetime.now(SEOUL).date().isoformat() if ':' in stamp else release_date(stamp, '%y.%m.%d')
                    chapter = query_url(NAVER + '/' + self.kind + '/detail', titleId=key, no=cid)
                    result[chapter] = self.chapter(chapter, str(row.get('subtitle') or ''), int(cid), date=date)
            page = (data.get('pageInfo') or {}).get('nextPage', 0)
            if type(page) is not int or not page:
                return self.order(result), False
            if len(result) >= MAX_CHAPTERS:
                break
        return self.order(result)[:MAX_CHAPTERS], True

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        images = doc.select('.wt_viewer img') or doc.select('.toon_view_lst img.toon_image')
        return [src for node in images if (src := picture(node, final, ('data-src',)))]

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_title(url):
            return super().inspect(url, http)
        row = self.details(http, url)
        chapters, truncated = self.chapter_rows(http, url)
        return self.reader_result(row, url, chapters, [], truncated)


class NewXToon(SeriesPort):
    cards = Cards('a.comic-link[href*="/comics/"]:not([data-cover-ad])', '', 'h3',
                  'img.cover-image', next='nav[data-site-pagination] a[aria-label="다음 페이지"]')
    meta = Meta('section[aria-labelledby="comic-title"] #comic-title',
                'section[aria-labelledby="comic-title"] img[alt$="표지"]', '[data-comic-description]', '',
                'a[href*="/comics?category="]', '', '#comic-title + p a')

    def __init__(self):
        super().__init__(('1562897350957827542', 'NewXToon', 'ko', NEWX, True), rf'/comics/({NUMBER})/?',
                         rf'/comics/({NUMBER})/chapters/{NUMBER}/?', interval=.35)

    def title_for(self, url):
        key = self.chapter_key(url)
        return NEWX + '/comics/' + key if key else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        key = urlsplit(url).path.strip('/')
        return NEWX + '/comics/' + key if re.fullmatch(NUMBER, key) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            target = query_url(NEWX + '/search', q=query, page=page)
        else:
            args = {'sort': 'latest' if sort == 'updated' else 'popular', 'page': page}
            if re.fullmatch(SEGMENT, tag):
                args['category'] = tag
            target = query_url(NEWX + '/comics', **args)
        return self.card_rows(*self.document(http, target), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        states = {'완결': 'completed', '연재중': 'ongoing', '휴재': 'hiatus'}
        row['status'] = next((states[label] for node in doc.select('section[aria-labelledby="comic-title"] strong')
                              if (label := node_text(node)) in states), '')
        row['format'] = 'webtoon'
        return row

    def chapters(self, http, doc, final):
        chapters = {}
        base = final.split('?', 1)[0].rstrip('/') + '/chapters'
        for page in range(1, 81):
            data = self.json(http, query_url(base, sort='latest', page=page), final)
            for entry in items(data, 'chapters'):
                chapter = str(entry.get('id', ''))
                if re.fullmatch(NUMBER, chapter):
                    target = base + '/' + chapter
                    label = str(entry.get('title') or '')
                    date = str(entry.get('date') or '').strip().replace('.', '-').rstrip('-')
                    chapters[target] = self.chapter(target, label, date=date[:10])
            if not data.get('has_more'):
                return self.order(chapters), False
        return self.order(chapters), True

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return [src for node in doc.select('[data-reader-canvas] [data-reader-page] img[data-reader-image]')
                if (src := picture(node, final))]


class Wolf(SeriesPort):
    meta = Meta('h1.w-title', '.thumb-wrap img', '.summary', '', '.genre-tags a.gtag')
    cards = Cards('a.t-card[href]', '', '.t-title', '.t-img img', next='.pagi .pg-btn.on + a.pg-btn')

    def __init__(self, sid, name, mode):
        self.mode = mode
        self.entry = 'cl' if mode == 'cm' else 'list'
        self.reader = 'cv' if mode == 'cm' else 'view'
        super().__init__((sid, '늑대닷컴 - ' + name, 'ko', WOLF, True), rf'(/(?:{self.entry}))/?',
                         rf'(/(?:{self.reader}))/?', interval=.35)

    def title_key(self, url):
        return param(url, 'toon')

    def is_title(self, url):
        return super().is_title(url) and bool(re.fullmatch(SEGMENT, self.title_key(url)))

    def is_chapter(self, url):
        return (super().is_chapter(url) and bool(re.fullmatch(SEGMENT, self.title_key(url)))
                and bool(re.fullmatch(SEGMENT, param(url, 'num'))))

    def title_url(self, key):
        return query_url(WOLF + '/' + self.entry, toon=key)

    def title_for(self, url):
        key = self.title_key(url)
        return self.title_url(key) if re.fullmatch(SEGMENT, key) else ''

    def chapter_identity(self, url):
        return self.title_key(url), param(url, 'num')

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        if self.is_chapter(url):
            return self.title_for(url)
        key = urlsplit(url).path.strip('/')
        return self.title_url(key) if re.fullmatch(SEGMENT, key) else ''

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        if self.is_chapter(url):
            return url
        try:
            data = json.loads(row.get('realUrl') or row.get('url') or '')
            decoded = {k: str(data.get(k, '')) for k in ('toon', 'num')}
        except (ValueError, TypeError, AttributeError):
            return ''
        if not all(re.fullmatch(SEGMENT, v) for v in decoded.values()):
            return ''
        return query_url(WOLF + '/' + self.reader, **decoded)

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(target) == self.title_key(title)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            if len(query) < 2:
                return [], False
            try:
                encoded = quote_plus(query.encode('euc-kr'))
            except UnicodeEncodeError:
                return [], False
            target = WOLF + f'/sh?q={encoded}&pg={page}'
        else:
            args = {'pg': page, 's': 'n' if sort == 'updated' else 'f'}
            field, _, value = tag.partition(':')
            if field in ('t1', 't2', 't3') and value:
                args[field] = value[:160]
            target = query_url(WOLF + ('/end' if tag == 'completed' and self.mode == 'ing' else '/' + self.mode), **args)
        return self.card_rows(*self.document(http, target), self.cards)

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['genres'] = [tag.lstrip('#') for tag in row['genres']]
        row['format'] = {'cm': 'manga', 'ing': 'webtoon', 'pt': 'gallery'}[self.mode]
        return row

    def vocabulary(self, http):
        if self.mode == 'pt':
            return []
        doc, final = self.document(http, WOLF + '/' + self.mode)
        values = {}
        for anchor in doc.select('.f-row a.ftag[href]'):
            url = self.site_link(anchor['href'], final)
            for field in ('t1', 't2', 't3'):
                item = param(url, field)
                if item:
                    key = field + ':' + item
                    values[key] = {'key': key, 'label': node_text(anchor), 'kind': 'genre'}
        return list(values.values())

    def chapters(self, http, doc, final):
        key = self.title_key(final)
        result = {}
        for index in range(1, 81):
            for anchor in doc.select('a.ep-item[href]'):
                source = self.site_link(anchor['href'], final)
                slot = param(source, 'num')
                if self.title_key(source) != key or not re.fullmatch(SEGMENT, slot):
                    continue
                target = query_url(WOLF + '/' + self.reader, toon=key, num=slot)
                date = release_date(node_text(anchor.select_one('.ep-date')), '%Y-%m-%d')
                label = node_text(anchor.select_one('.ep-title'))
                result[target] = self.chapter(target, label, number(slot), date=date)
            if not doc.select_one('.pagi .pg-btn.on + a.pg-btn'):
                return self.order(result), False
            target = query_url(self.title_url(key), s='n', pg=index + 1)
            doc, final = self.document(http, target)
            if self.title_key(final) != key:
                raise SourceError('늑대닷컴 перенаправил список глав.')
        return self.order(result), True

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        return [src for image in doc.select('#vimg-area img[data-src]')
                if (src := picture(image, final, ('data-src',)))]


SOURCES = (
    NaverComic('1311262507446028482', 'Naver Webtoon', 'webtoon'),
    NaverComic('3983114856627782141', 'Naver Webtoon Best Challenge', 'bestChallenge'),
    NaverComic('4487676425355815867', 'Naver Webtoon Challenge', 'challenge'),
    NewXToon(),
    Wolf('4225505094399546613', '포토툰', 'pt'),
    Wolf('5583626852311652499', '웹툰', 'ing'),
    Wolf('7074060458114951398', '만화책', 'cm'),
)
