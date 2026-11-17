"""Localized gallery lists, metadata and ordered page links."""

import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_articles import Article
from manga_direct_catalogues import Browse, DirectCatalogue, Layout
from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Archive, Cards, Meta
from manga_webcomics import query_url


ROOT = 'https://www.pornpics.com'
PROFILE_IDS = (
    ('1459635082044256286', 'en'), ('1811020652695548403', 'fr'), ('1918812460576284253', 'ja'),
    ('2780049974046464526', 'es'), ('5665224319388354154', 'it'), ('6286909977307030053', 'ru'),
    ('7079014519404224786', 'zh'), ('7525122656976466135', 'de'),
)
LANG = {'jp' if lang == 'ja' else lang for _, lang in PROFILE_IDS}
LOCALE = '|'.join(sorted(LANG - {'en'}))
PATH = rf'/(?:({LOCALE})/)?galleries/({SEGMENT})/?'
LISTING = re.compile(rf'/(?:({LOCALE})/)?(?:tags|categories)/{SEGMENT}/(?:recent/)?')
LIST_LINK = '#main li.thumbwook > a.rel-link[href]'
SIZE = 20
PAGES = 2000


def public_api(host, path, query):
    if host != 'www.pornpics.com':
        return False
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=6)
    except ValueError:
        return False
    args = dict(pairs)
    if (len(args) != len(pairs) or args.get('limit') != str(SIZE)
            or not re.fullmatch(r'\d{1,5}', args.get('offset', ''))
            or not 0 <= int(args['offset']) < SIZE * PAGES
            or int(args['offset']) % SIZE):
        return False
    if path == '/popular/api/galleries/list/':
        return (set(args) == {'limit', 'offset', 'lang', 'period', 'category_id'}
                and args.get('lang') in LANG and {'1': '2586', '2': '2587'}.get(args['period']) == args['category_id'])
    if path == '/search/srch.php':
        return (set(args) <= {'limit', 'offset', 'q', 'lang', 'date'} and 0 < len(args.get('q', '')) <= 160
                and args.get('lang') in LANG and args.get('date', 'latest') == 'latest')
    return bool(LISTING.fullmatch(path)) and set(args) == {'limit', 'offset'}


class PornPics(Article):
    def __init__(self, sid, lang):
        self.package = 'pornpics'
        self.locale = 'jp' if lang == 'ja' else lang
        self.section = '' if lang == 'en' else '/' + self.locale
        DirectCatalogue.__init__(self, (sid, 'PornPics', lang, ROOT, True), Layout(
            PATH, PATH, Cards(LIST_LINK, '', 'img', 'img', '', 'alt', ('data-src',)),
            Meta('.gallery-title h1', LIST_LINK + ' img', 'div.gallery-info.to-gall-info .info-views',
                 tags='div.gallery-info__item:not(:nth-child(2)) a',
                 author='div.gallery-info__item:nth-child(2) a'),
            Archive(''), LIST_LINK, Browse('/'),
        ))

    def site_link(self, value, base=None):
        target = super().site_link(value, base)
        parts = urlsplit(target)
        if match := self.TITLE_PATH.fullmatch(parts.path):
            return ROOT + self.section + '/galleries/' + match[2] + '/' + ('?' + parts.query if parts.query else '')
        return target

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        options = {'limit': SIZE, 'offset': (page - 1) * SIZE}
        if query:
            path = '/search/srch.php'
            options.update(lang=self.locale, q=query)
            if sort == 'updated':
                options['date'] = 'latest'
        elif tag:
            match = re.fullmatch(r'(tags|categories):(' + SEGMENT + ')', tag)
            if not match:
                return [], False
            path = f'{self.section}/{match[1]}/{match[2]}/'
            if sort == 'updated':
                path += 'recent/'
            if page == 1:
                rows, _ = self.card_rows(*self.document(http, query_url(ROOT + path, **options)), self.layout.cards)
                return rows, len(rows) >= SIZE
        else:
            path = '/popular/api/galleries/list/'
            period = 2 if sort == 'updated' else 1
            options.update(lang=self.locale, period=period, category_id=2585 + period)
        data = self.json(http, query_url(ROOT + path, **options))
        rows = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and self.is_title(url := self.site_link(item.get('g_url'))):
                    slug = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
                    sid = slug.rsplit('-', 1)[-1]
                    title = str(item.get('desc') or '')
                    title = (title.removesuffix(sid) if sid.isdecimal() else title).strip() or slug.replace('-', ' ')
                    rows.append(self.record(url, title, image_url(item.get('t_url'), url)))
        return rows, isinstance(data, list) and len(data) >= SIZE

    def vocabulary(self, http):
        doc, final = self.document(http, ROOT + self.section + '/tags/')
        found = {}
        for anchor in doc.select('#main-list .list-item:not(.view-all) > a[href]'):
            target = self.site_link(anchor['href'], final)
            fields = urlsplit(target).path.strip('/').split('/')[-2:]
            name = anchor.get('title') or node_text(anchor)
            if name and len(fields) == 2 and fields[0] in {'tags', 'categories'} and re.fullmatch(SEGMENT, fields[1]):
                key = ':'.join(fields)
                found[key] = {'key': key, 'label': name, 'kind': 'tag' if fields[0] == 'tags' else 'genre'}
        return list(found.values())

    def article_pages(self, http, doc, final):
        return [image_url(anchor['href'], final) for anchor in doc.select(LIST_LINK)]


SOURCES = tuple(PornPics(sid, lang) for sid, lang in PROFILE_IDS)
