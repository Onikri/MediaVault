"""Public Riot Universe comics, based on the Apache-2.0 Keiyoushi extension."""

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import image_url
from manga_source_tags import unique
from manga_source_urls import reader_url, split_reader_url
from source_parser import SourceError, public_url


ORIGIN = 'https://universe.leagueoflegends.com'
INDEX = 'https://universe-meeps.leagueoflegends.com/v1'
READER = 'https://universe-comics.leagueoflegends.com/comics'
SLUG = r'[a-z0-9][a-z0-9-]{0,119}'
KEY = re.compile(rf'{SLUG}(?:/{SLUG})?')
PROFILES = (
    ('241129525014815798', 'cs', 'cs_cz'),
    ('380479987909263478', 'de', 'de_de'),
    ('1617144019668124895', 'ja', 'ja_jp'),
    ('1822275077186160208', 'ko', 'ko_kr'),
    ('2505034801993260082', 'es', 'es_es'),
    ('2993141237027207546', 'it', 'it_it'),
    ('3236903197935016602', 'es-419', 'es_mx'),
    ('3431750855616467337', 'el', 'el_gr'),
    ('4102855915741272173', 'pl', 'pl_pl'),
    ('4983763186502997670', 'tr', 'tr_tr'),
    ('5421383187922044761', 'en', 'en_us'),
    ('6359895141227528344', 'ru', 'ru_ru'),
    ('7646731134152168219', 'pt-BR', 'pt_br'),
    ('8175862906648984382', 'ro', 'ro_ro'),
    ('8553752347472368081', 'hu', 'hu_hu'),
    ('8921189687191630727', 'fr', 'fr_fr'),
)


def request(http, url):
    raw, final, _ = http.document(url, headers={'Origin': ORIGIN, 'Referer': ORIGIN + '/'})
    if final != url:
        raise SourceError('Riot Universe перенаправил запрос на другой адрес.')
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise SourceError('Riot Universe не предоставил данные комикса.') from None
    if not isinstance(data, dict):
        raise SourceError('Riot Universe вернул некорректные данные.')
    return data


def rows(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SourceError('Riot Universe вернул некорректный список.')
    return value


def key_from_item(item):
    raw = item.get('url')
    if isinstance(raw, str):
        key = urlsplit(raw).path.partition('/comic/')[2].strip('/')
        if KEY.fullmatch(key):
            return key
    raise SourceError('Riot Universe не указал адрес комикса.')


class LeagueOfLegends:
    NAME = 'League of Legends'
    IS_NSFW = False
    scoped_urls = True

    def __init__(self, sid, language, locale):
        self.SOURCE_ID, self.LANGUAGE, self.locale = sid, language, locale
        self.prefix = f'/{locale}/comic/'
        self.ROOT = ORIGIN + self.prefix
        self.TITLE_PATH = re.compile(rf'{self.prefix}({KEY.pattern})/?')
        self.CHAPTER_PATH = re.compile(rf'{self.prefix}({SLUG}/{SLUG})/?')

    def reader_url(self, value):
        return reader_url(value, self.SOURCE_ID)

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            selected, raw = split_reader_url(urljoin(base or self.ROOT, value))
            parts = urlsplit(raw)
            if (selected not in {None, self.SOURCE_ID} or parts.netloc != urlsplit(ORIGIN).netloc
                    or not parts.path.startswith(self.prefix) or parts.query not in {'', 'issue=1'}):
                return ''
            return public_url(raw, resolve_dns=False)
        except (SourceError, ValueError):
            return ''

    def row(self, item):
        key = key_from_item(item)
        title = item['title'].strip()
        description = item.get('description')
        background = item.get('background')
        champions = item.get('featured-champions') or []
        tags = unique([item.get('subtitle'), *(champion.get('name') for champion in champions
                                              if isinstance(champion, dict))])
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{key}', 'sourceId': self.SOURCE_ID,
                'provider': f'suwayomi:{self.SOURCE_ID}', 'providerName': self.NAME, 'sourceOnly': True,
                'url': self.reader_url(self.ROOT + key), 'sourceUrl': self.reader_url(self.ROOT + key),
                'kind': 'manga', 'format': 'comic', 'language': self.LANGUAGE, 'title': title,
                'aliases': [title], 'cover': image_url(background.get('uri'), self.ROOT) if isinstance(background, dict) else '',
                'description': BeautifulSoup(description, 'html.parser').get_text('\n', strip=True)[:12000]
                if isinstance(description, str) else '', 'genres': [], 'tags': tags, 'ids': {}}

    def records(self, http):
        sections = request(http, f'{INDEX}/{self.locale}/comics/index.json').get('sections')
        if not isinstance(sections, dict):
            raise SourceError('Riot Universe не предоставил каталог комиксов.')
        result = {}
        for name in ('series', 'one-shots'):
            section = sections.get(name)
            if not isinstance(section, dict):
                raise SourceError('Riot Universe не предоставил раздел комиксов.')
            for item in rows(section.get('data')):
                if isinstance(item.get('title'), str) and item['title'].strip():
                    result.setdefault(key_from_item(item), self.row(item))
        return result

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if page != 1:
            return [], False
        query, tag = query.casefold().strip(), tag.casefold().strip()
        return [row for row in self.records(http).values()
                if (not query or any(query in label.casefold() for label in [row['title'], *row['tags']]))
                and (not tag or any(tag == label.casefold() for label in row['tags']))], False

    def vocabulary(self, http):
        terms = unique(tag for row in self.records(http).values() for tag in row['tags'])
        return [{'sourceId': term, 'label': term, 'category': 'tag'} for term in terms]

    def details(self, http, value):
        path = urlsplit(self.site_link(value)).path
        title = self.TITLE_PATH.fullmatch(path)
        result = self.records(http).get(title[1]) if title else None
        if result is None:
            raise SourceError('Riot Universe не нашёл комикс в этой локали.')
        return result

    def episodes(self, http, key):
        issues = ([{'title': 'One Shot', 'url': '/comic/' + key, 'index': 0}] if '/' in key else
                  reversed(rows(request(http, f'{INDEX}/{self.locale}/comics/{key}/index.json').get('issues'))))
        result = []
        for issue in issues:
            identity, number = key_from_item(issue), issue.get('index')
            if not self.CHAPTER_PATH.fullmatch(self.prefix + identity) or identity.split('/')[0] != key.split('/')[0]:
                raise SourceError('Riot Universe вернул выпуск другого комикса.')
            result.append({'url': self.reader_url(self.ROOT + identity + '?issue=1'), 'number': number
                           if type(number) in (int, float) and 0 <= number <= 10000 else 0,
                           'season': 1, 'title': issue.get('title') or 'Выпуск', 'language': self.LANGUAGE})
        return result

    def inspect(self, value, http):
        target = self.site_link(value)
        parts = urlsplit(target)
        match = self.TITLE_PATH.fullmatch(parts.path)
        if not match:
            raise SourceError('Некорректная ссылка Riot Universe.')
        key, pages = match[1], []
        records = self.records(http)
        chapter = bool(parts.query)
        if chapter and not self.CHAPTER_PATH.fullmatch(parts.path):
            raise SourceError('Некорректная ссылка на выпуск Riot Universe.')
        work = key if key in records else key.split('/')[0] if chapter else key
        if work not in records:
            raise SourceError('Riot Universe не нашёл комикс в этой локали.')
        episodes = self.episodes(http, work)
        if chapter:
            episodes = [entry for entry in episodes if self.site_link(entry['url']) == self.ROOT + key + '?issue=1']
            if len(episodes) != 1:
                raise SourceError('Выпуск отсутствует в оглавлении Riot Universe.')
            data = request(http, f'{READER}/{self.locale}/{key}/index.json')
            spreads = data.get('desktop-pages')
            if not isinstance(spreads, list) or any(not isinstance(spread, list) for spread in spreads):
                raise SourceError('Riot Universe не предоставил страницы выпуска.')
            pages = [image_url(image.get('uri'), READER + '/') for spread in spreads for image in rows(spread)]
            if not pages or len(pages) > 500 or not all(pages):
                raise SourceError('Riot Universe вернул неполный список страниц.')
            date = data.get('staging-date')
            if isinstance(date, str) and re.match(r'\d{4}-\d{2}-\d{2}T', date):
                episodes[0]['publishedAt'] = date[:10]
        return {**records[work], 'url': self.reader_url(target), 'episodes': episodes, 'pages': pages,
                'available': bool(episodes), 'truncated': False, 'translations': [], 'dubs': [], 'releases': [],
                'seasons': [{'number': 1, 'name': 'Том 1'}] if episodes else []}

    def saved_chapter_url(self, value, key, root):
        if not isinstance(value, str) or not value:
            return ''
        target = self.site_link(value, root)
        if not target or not self.CHAPTER_PATH.fullmatch(urlsplit(target).path):
            return ''
        return target.split('?', 1)[0].rstrip('/') + '?issue=1'

    def saved_chapter_matches(self, chapter, title):
        work = self.TITLE_PATH.fullmatch(urlsplit(title).path)[1]
        issue = self.CHAPTER_PATH.fullmatch(urlsplit(chapter).path)[1]
        return issue == work if '/' in work else issue.startswith(work + '/')


SOURCES = tuple(LeagueOfLegends(*profile) for profile in PROFILES)
