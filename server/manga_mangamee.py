"""Native MangaMee React Flight catalogue and public Protobuf viewer."""

import re
from urllib.parse import parse_qsl, quote, urlsplit

from manga_additional_catalogues import flight_objects
from manga_direct_payloads import JsonSeries, items
from manga_madara import SEGMENT, image_url
from manga_mangaplus import KEY, XorPage, protobuf
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


HOST = 'manga-mee.jp'
ROOT = 'https://' + HOST
API_HOST = 'prod2-android.' + HOST
API_PATH = '/web/v1/title_detail'
API = 'https://' + API_HOST + API_PATH
ID = r'[1-9]\d{0,12}'
TITLE = rf'/detail/({ID})/?'


def public_api(host, path, query):
    pairs = parse_qsl(query)
    args = dict(pairs)
    return (host == API_HOST and path == API_PATH and len(pairs) == len(args)
            and set(args) in ({'title_id'}, {'title_id', 'episode_id'})
            and all(re.fullmatch(ID, key) for key in args.values()))


def public_rsc(host, path, query):
    return host == HOST and not query and (path in ('/title-list/ranking', '/title-list/todaysupdate')
        or bool(re.fullmatch(rf'/(?:all-episodes/{ID}|search-result/keyword/{SEGMENT})', path)))


class MangaMee(JsonSeries):
    def __init__(self):
        super().__init__(('5152016637336953348', 'MangaMee', 'ja', ROOT, False), TITLE, TITLE, interval=.4)

    def is_title(self, url):
        return super().is_title(url) and not param(url, 'episodeId')

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(re.fullmatch(ID, param(url, 'episodeId')))

    def chapter_identity(self, url):
        return self.chapter_key(url), param(url, 'episodeId')

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/detail/' + key if key else ''

    def saved_title_url(self, url):
        target = self.canonical(url)
        key = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/detail/' + key if re.fullmatch(ID, key) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        key = urlsplit(target).path.strip('/')
        return query_url(title, episodeId=key) if self.is_title(title) and re.fullmatch(ID, key) else ''

    def flight(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'}, action='native-series-rsc')
        if final != url:
            raise SourceError('MangaMee перенаправил каталог.')
        return flight_objects(raw)

    def data(self, http, title_id, episode_id=''):
        self.origin.wait(getattr(http, 'deadline', None))
        arguments = {'title_id': title_id}
        if episode_id:
            arguments['episode_id'] = episode_id
        return protobuf(http, query_url(API, **arguments), 'MangaMee', {'Referer': ROOT + '/'}, 'mangamee-proto')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        if query:
            path = '/search-result/keyword/' + quote(query, safe='')
        elif sort == 'updated':
            path = '/title-list/todaysupdate'
        else:
            path = '/title-list/ranking'
        payload = self.flight(http, ROOT + path)
        if query:
            group = next((item['popularTitles'] for item in payload if isinstance(item.get('popularTitles'), dict)), {})
        elif sort == 'updated':
            group = next((item['titleGroup'] for item in payload if isinstance(item.get('titleGroup'), dict)), {})
        else:
            group = next((item for item in payload if item.get('name') == '総合' and isinstance(item.get('titles'), list)), {})
        rows = {}
        for item in items(group, 'titles'):
            key = str(item.get('id') or '') if isinstance(item, dict) else ''
            title = item.get('name') if key else ''
            if re.fullmatch(ID, key) and isinstance(title, str) and title:
                url = ROOT + '/detail/' + key
                rows[url] = self.record(url, title, image_url((item.get('largeImage') or {}).get('src'), url))
        return list(rows.values()), False

    def series(self, http, url):
        key = self.title_key(url)
        entry = self.data(http, key)
        title = entry.message(1)
        if not title.string(2):
            raise SourceError('MangaMee не предоставил карточку произведения.')
        row = self.record(url, title.string(2), image_url(title.string(9), url), aliases=[title.string(17)],
                          description=title.string(4), authors=[title.string(6)], genres=[x.string(2) for x in entry.messages(3)])
        episodes = next((item['allEpisodes'] for item in self.flight(http, ROOT + '/all-episodes/' + key)
                         if isinstance(item.get('allEpisodes'), dict)), {})
        chapters = {}
        for index, item in enumerate(items(episodes, 'episodes'), 1):
            cid = str(item.get('id') or '') if isinstance(item, dict) else ''
            if not re.fullmatch(ID, cid) or item.get('isFree') is False:
                continue
            target = query_url(url.split('?')[0], episodeId=cid)
            chapters[target] = self.chapter(target, item.get('title') or f'第{index}話', index)
        return row, self.order(chapters)

    def pages(self, http, url):
        key, chapter = self.chapter_identity(url)
        data = self.data(http, key, chapter)
        images = []
        for value in data.messages(13):
            page = next(value.messages(1), None)
            if page is not None:
                url_image, key = image_url(page.string(2), url), page.string(7)
                if not url_image or key and not KEY.fullmatch(key):
                    raise SourceError('MangaMee вернул некорректное изображение.')
                images.append((url_image, XorPage(bytes.fromhex(key) if key else b'')))
        if not images:
            raise SourceAccessError('MangaMee не предоставил страницы в веб-читалке.')
        return remember(images, url)


SOURCES = (MangaMee(),)
