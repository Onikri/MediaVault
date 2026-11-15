"""Direct HentaiHand API, based on Keiyoushi's Apache-2.0 multisrc."""

import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from manga_madara import OriginPace, image_url
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceError, public_url


SLUG = r'[A-Za-z0-9_-]{1,255}'
TITLE_PATH = re.compile(rf'/en/comic/({SLUG})/?')
CHAPTER_PATH = re.compile(rf'/en/comic/({SLUG})/read/?')
DETAIL_API = re.compile(rf'/api/comics/{SLUG}(?:/images)?')
FILTERS = ('tags', 'artists', 'characters')


def entries(values):
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        raise SourceError('HentaiHand вернул некорректный список.')
    return values


def names(values):
    return unique(item.get('name') for item in entries(values or []))


class HentaiHand:
    IS_NSFW = True
    scoped_urls = True
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH

    def __init__(self, root, name, sid, language, languages, pace):
        self.ROOT, self.NAME, self.SOURCE_ID, self.LANGUAGE = root, name, sid, language
        self.host = urlsplit(root).netloc
        self.languages = languages
        self.pace = pace

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, target = split_reader_url(urljoin(base or self.ROOT, value))
            parts = urlsplit(target)
            if selected in (None, self.SOURCE_ID) and parts.netloc == self.host and not parts.query:
                return public_url(target, resolve_dns=False)
        except (ValueError, SourceError):
            pass
        return ''

    def reader_url(self, target):
        return reader_url(target, self.SOURCE_ID)

    def saved_chapter_url(self, value, slug, root):
        if value == slug:
            return root.rstrip('/') + '/en/comic/' + slug + '/read'
        target = self.site_link(value, root)
        matched = TITLE_PATH.fullmatch(urlsplit(target).path)
        return target.rstrip('/') + '/read' if matched and matched[1] == slug else target

    def page_headers(self, value):
        match = CHAPTER_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        return {'Referer': self.ROOT + ('/en/comic/' + match[1] if match else '/')}

    def get(self, http, path, params=None):
        url = self.ROOT + '/api/' + path + ('?' + urlencode(params) if params else '')
        self.pace.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'}, action='hentaihand-json')
        if final != url:
            raise SourceError('HentaiHand перенаправил запрос API.')
        try:
            data = json.loads(raw)
        except ValueError:
            raise SourceError('HentaiHand вернул страницу вместо данных API.') from None
        if not isinstance(data, dict):
            raise SourceError('HentaiHand вернул неожиданные данные API.')
        return data

    def row(self, data, *, details=False):
        from manga_sources import title_aliases

        slug, title = data.get('slug'), data.get('title')
        if not isinstance(slug, str) or not re.fullmatch(SLUG, slug) or not isinstance(title, str) or not title.strip():
            raise SourceError('HentaiHand вернул карточку без названия или ссылки.')
        url = self.reader_url(self.ROOT + '/en/comic/' + slug)
        row = {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'sourceId': self.SOURCE_ID,
               'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME,
               'sourceUrl': url, 'sourceURL': url, 'url': url, 'kind': 'manga',
               'language': self.LANGUAGE, 'title': title.strip()[:500], 'ids': {}, 'sourceOnly': True,
               'aliases': title_aliases(title), 'cover': image_url(data.get('image_url'), self.ROOT)}
        if details:
            category = data.get('category') or {}
            row.update(aliases=unique([*row['aliases'], data.get('alternative_title')]),
                       description=(data.get('description') or '')[:12000],
                       genres=names([category]), tags=unique(names(data.get('tags')) + names(data.get('relationships'))),
                       authors=names(data.get('authors') or data.get('artists')), artists=names(data.get('artists')),
                       status=data.get('status') or '')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if type(page) is not int or not 1 <= page <= 2000 or not isinstance(query, str) or not isinstance(tag, str):
            raise SourceError('Некорректные параметры HentaiHand.')
        params = {'page': page, 'sort': 'uploaded_at' if sort == 'updated' else 'popularity',
                  'order': 'desc', 'duration': 'all'}
        params.update({f'languages[{-idx}]': lang for idx, lang in enumerate(self.languages, 1)})
        if tag:
            if not re.fullmatch(r'[1-9][0-9]{0,9}', tag):
                raise SourceError('Некорректный ID тега HentaiHand.')
            params['tags[0]'] = tag
        if query := query.strip()[:160]:
            params['q'] = query
        try:
            data = self.get(http, 'comics', params)
        except SourceError as error:
            if not query or tag or 'HTTP 500' not in str(error):
                raise
            # Some deployments reject a plain-text query for a tag or artist.
            for kind in FILTERS:
                options = entries(self.get(http, kind, {'q': query}).get('data'))
                match = next((item for item in options if str(item.get('name')).casefold() == query.casefold()
                              and type(item.get('id')) is int and 0 < item['id'] < 10**10), None)
                if match:
                    del params['q']
                    params[f'{kind}[0]'] = match['id']
                    data = self.get(http, 'comics', params)
                    break
            else:
                raise
        return [self.row(item) for item in entries(data.get('data'))], bool(data.get('next_page_url'))

    def details(self, http, value):
        match = TITLE_PATH.fullmatch(urlsplit(self.site_link(value)).path)
        if not match:
            raise SourceError('Некорректная ссылка на тайтл HentaiHand.')
        return self.title(http, match[1])

    def title(self, http, slug):
        data = self.get(http, 'comics/' + slug)
        if data.get('slug') != slug:
            raise SourceError('HentaiHand вернул другой тайтл.')
        return self.row(data, details=True)

    def inspect(self, value, http):
        path = urlsplit(self.site_link(value)).path
        chapter = CHAPTER_PATH.fullmatch(path)
        match = chapter or TITLE_PATH.fullmatch(path)
        if not match:
            raise SourceError('Некорректная ссылка на читалку HentaiHand.')
        slug = match[1]
        row = self.title(http, slug)
        target = self.reader_url(self.ROOT + f'/en/comic/{slug}/read')
        pages = []
        if chapter:
            images = entries(self.get(http, f'comics/{slug}/images').get('images'))
            positions = [item.get('page') for item in images]
            if not images or len(images) > 500 or any(type(n) is not int for n in positions):
                raise SourceError('HentaiHand не предоставил полный список страниц.')
            first = min(positions)
            if first not in (0, 1) or sorted(positions) != list(range(first, first + len(images))):
                raise SourceError('HentaiHand не предоставил полный список страниц.')
            pages = [image_url(item.get('source_url'), self.ROOT) for item in sorted(images, key=lambda item: item['page'])]
            if not all(pages):
                raise SourceError('HentaiHand вернул некорректные ссылки на страницы.')
        episode = {'url': target, 'number': 1, 'season': 1, 'title': 'Chapter',
                   'language': self.LANGUAGE, 'translator': ''}
        return {**row, 'url': target if chapter else row['url'], 'episodes': [episode], 'pages': pages,
                'available': True, 'truncated': False, 'seasons': [{'number': 1, 'name': 'Том 1'}],
                'dubs': [], 'releases': [], 'translations': []}


def profiles(root, name, languages):
    pace = OriginPace()
    pace.interval = 0.35
    return tuple(HentaiHand(root, name, sid, language, values, pace) for sid, language, values in languages)


def public_api(host, path, query):
    if host not in HOSTS:
        return False
    if DETAIL_API.fullmatch(path):
        return not query
    try:
        params = parse_qs(query, strict_parsing=True, max_num_fields=10)
    except ValueError:
        return False
    if path in {f'/api/{kind}' for kind in FILTERS}:
        return set(params) == {'q'} and len(params['q']) == 1 and 0 < len(params['q'][0]) <= 160
    if path != '/api/comics' or not params:
        return False
    for key, values in params.items():
        if len(values) != 1:
            return False
        value = values[0]
        if key == 'q' and 0 < len(value) <= 160:
            continue
        if key == 'page' and value.isascii() and value.isdecimal() and 0 < len(value) <= 4 and 1 <= int(value) <= 2000:
            continue
        if (key == 'sort' and value in {'popularity', 'uploaded_at'}
                or key == 'order' and value == 'desc' or key == 'duration' and value == 'all'):
            continue
        if re.fullmatch(r'(?:languages\[-[1-2]\]|(?:tags|artists|characters)\[0\])', key) and re.fullmatch(r'[1-9][0-9]{0,9}', value):
            continue
        return False
    return 'page' in params


SOURCES = (
    *profiles('https://hentaihand.com', 'HentaiHand', (
        ('1235047015955289468', 'all', ()),
        ('4992571563369273240', 'ja', (3, 29)),
        ('1438773694780928937', 'en', (2, 27)),
        ('866133291730804205', 'zh', (1, 50)),
        ('7561346598466986562', 'bg', (4,)),
        ('2136686110556284465', 'ceb', (5, 44)),
        ('7302549142935671434', 'other', (6,)),
        ('8205998909543626240', 'tl', (7, 55)),
        ('5494684486943087247', 'ar', (8, 49)),
        ('9098484674492839156', 'el', (9,)),
        ('259350817779848434', 'sr', (10,)),
        ('8174384290387590645', 'jv', (11, 51)),
        ('299569391162966579', 'uk', (12, 46)),
        ('6304497572870246566', 'tr', (13, 41)),
        ('4855613465785451164', 'fi', (14, 54)),
        ('3078530910469685147', 'la', (15,)),
        ('4197081087116305652', 'mn', (16,)),
        ('6189674531673390664', 'eo', (17, 47)),
        ('3548394435548008920', 'sk', (18,)),
        ('6818645358118704394', 'cs', (19, 52)),
        ('2772498967425526818', 'ko', (30, 39)),
        ('5788099943016900736', 'ru', (31,)),
        ('8272502917504358946', 'it', (32,)),
        ('1049245690865797006', 'es', (33, 37)),
        ('2516244587139644000', 'pt-BR', (34,)),
        ('392245224742696225', 'th', (35, 40)),
        ('2304134427430911086', 'fr', (36,)),
        ('202981519301875762', 'id', (38,)),
        ('474754362133655719', 'vi', (42,)),
        ('8300414741852788090', 'de', (43,)),
        ('6173663752022195918', 'pl', (45,)),
        ('6490746811386262494', 'hu', (48,)),
        ('7899387259192038112', 'nl', (53,)),
        ('1337874080374168573', 'hi', (56,)),
    )),
    *profiles('https://nhentai.com', 'nHentai.com (unoriginal)', (
        ('9165839893600661480', 'all', ()),
        ('8504927104562262528', 'zh', (1,)),
        ('5591830863732393712', 'en', (2,)),
        ('8148939977393580424', 'ja', (3,)),
        ('5817327335315373850', 'other', (4,)),
        ('1773653553472615327', 'ar', (5,)),
        ('4984830439465026319', 'jv', (6,)),
        ('5355858532116403799', 'bg', (7,)),
        ('1144495813995437124', 'cs', (8,)),
        ('1872394332504252034', 'uk', (9,)),
        ('8189813976393792973', 'sk', (10,)),
        ('5464986831390726554', 'eo', (11,)),
        ('3640686393110022124', 'mn', (12,)),
        ('6750311061190710079', 'la', (13,)),
        ('8306394815737846919', 'ceb', (14,)),
        ('4352420071178605258', 'tl', (15,)),
        ('6423038744951581148', 'tr', (17,)),
        ('1001519209586733699', 'sr', (18,)),
        ('6038464145206378323', 'el', (19,)),
    )),
)
HOSTS = frozenset(adapter.host for adapter in SOURCES)
