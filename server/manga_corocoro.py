"""Corocoro Online guest catalogues and published Protobuf chapters."""

import re
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries
from manga_japanese_next import AesCbcPage
from manga_madara import image_url, node_text
from manga_mangaone import TOKYO
from manga_mangaplus import protobuf
from manga_rayuba import uploaded
from manga_series_port import SeriesPort
from manga_speedbinb import remember
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://www.corocoro.jp'
API = ROOT + '/api/csr'
ID = r'[1-9]\d{0,9}'
WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
LABELS = {'17': '完結', '32': 'ギャグ・コメディ', '2': 'バトル', '35': 'ゲーム', '41': 'ヒューマンドラマ',
          '44': '異世界・ファンタジー', '38': 'ホビー', '170': 'デュエル・マスターズ', '20': 'アニメ化',
          '47': 'スポーツ', '125': 'ベイブレード', '140': 'ポケモン'}


def public_api(host, path, query):
    url = 'https://' + host + path + '?' + query
    return transport(url, 'GET', None) or transport(url, 'PUT', b'')


def transport(url, method, body):
    parts = urlsplit(url)
    if parts.netloc != 'www.corocoro.jp' or parts.path != '/api/csr':
        return False
    pairs = parse_qsl(parts.query)
    args = dict(pairs)
    if len(pairs) != len(args):
        return False
    route = args.pop('rq', '')
    if route == 'chapter/viewer':
        return method == 'PUT' and body == b'' and set(args) == {'chapter_id'} and bool(re.fullmatch(ID, args['chapter_id']))
    if method != 'GET' or body is not None:
        return False
    if route == 'title/list/ranking':
        return not args
    if route == 'title/list/update_day':
        return set(args) == {'day'} and args['day'] in WEEKDAYS
    return route == 'title/detail' and set(args) == {'title_id'} and bool(re.fullmatch(ID, args['title_id']))


class Corocoro(JsonSeries):
    def __init__(self):
        super().__init__(('7153368437486297689', 'Corocoro Online', 'ja', ROOT, False),
                         rf'/title/({ID})/?', rf'/chapter/({ID})/?', hosts=('corocoro.jp',), interval=.4)

    def endpoint(self, http, route, **args):
        self.origin.wait(getattr(http, 'deadline', None))
        target = query_url(API, rq=route, **args)
        return protobuf(http, target, self.NAME, {'Referer': ROOT + '/'}, 'corocoro-proto',
                        empty_put=route == 'chapter/viewer')

    def title_for(self, url):
        key = param(url, 'mv_title')
        return ROOT + '/title/' + key if self.is_chapter(url) and re.fullmatch(ID, key) else ''

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/title/' + key if re.fullmatch(ID, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = self.title_key(title)
        chapter = urlsplit(url).path.strip('/')
        if re.fullmatch(ID, chapter):
            url = ROOT + '/chapter/' + chapter
        return query_url(url, mv_title=key) if key and self.is_chapter(url) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def entry(self, data, **extra):
        key, name = str(data.integer(1)), data.string(3)
        if not name or not re.fullmatch(ID, key):
            return None
        url = ROOT + '/title/' + key
        thumbnail = next(data.messages(5), None)
        return self.record(url, name, image_url(thumbnail.string(1), url) if thumbnail else '', **extra)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        if query or tag in ('completed', 'one-shot'):
            target = query_url(ROOT + '/search', keyword=query) if query else ROOT + '/rensai/' + tag
            doc, final = self.document(http, target)
            rows = [self.record(url, name, image_url((node.img or {}).get('src'), final))
                    for node in doc.select('div.grid > a[href^="/title/"]')
                    if self.is_title(url := self.site_link(node.get('href'), final))
                    and (name := node_text(node.select_one('p.text-black, p')))]
            return rows, False
        if sort == 'updated' or tag in WEEKDAYS:
            day = tag if tag in WEEKDAYS else WEEKDAYS[datetime.now(TOKYO).weekday()]
            group = next(self.endpoint(http, 'title/list/update_day', day=day).messages(1), None)
            entries = group.messages(2) if group else ()
        else:
            rankings = self.endpoint(http, 'title/list/ranking').messages(2)
            ranking = next((item for item in rankings if not tag or tag == ':'.join(
                (item.message(1).string(1), item.message(1).string(2)))), None)
            entries = ()
            if ranking:
                titles = next(ranking.messages(2), None)
                likes = next(ranking.messages(3), None)
                entries = titles.messages(1) if titles else (item.message(2) for item in likes.messages(1)) if likes else ()
        rows = {}
        for entry in entries:
            if row := self.entry(entry):
                rows[row['url']] = row
        return list(rows.values()), False

    def vocabulary(self, http):
        return [{'key': key + ':tag', 'label': label, 'kind': 'genre'} for key, label in LABELS.items()]

    def series(self, http, url):
        key = self.title_key(url)
        details = self.endpoint(http, 'title/detail', title_id=key)
        row = self.entry(details.message(2), description=details.string(6),
                         authors=[author.string(2) for author in details.messages(3)])
        if not row or self.title_key(row['url']) != key:
            raise SourceError('Corocoro Online вернул данные другого тайтла.')
        episodes = {}
        for item in details.messages(8):
            identifier, title = str(item.integer(1)), item.string(2)
            if not re.fullmatch(ID, identifier):
                continue
            match = re.search(r'第(\d+(?:\.\d+)?)話', title)
            points = next(item.messages(5), None)
            locked = points is not None and bool(points.fields.get(2))
            target = query_url(ROOT + '/chapter/' + identifier, mv_title=key, mv_locked='1' if locked else [])
            episodes[target] = self.chapter(target, ('🔒 ' if locked else '') + title,
                                            float(match[1]) if match else None, uploaded(item.integer(9)))
        return row, self.order(episodes)

    def pages(self, http, url):
        if param(url, 'mv_locked'):
            raise SourceAccessError('Издатель Corocoro Online ограничивает доступ к главе.')
        data = self.endpoint(http, 'chapter/viewer', chapter_id=self.chapter_key(url))
        key, iv = data.string(19), data.string(20)
        if not re.fullmatch(r'(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{48}|[a-fA-F0-9]{64})', key) or not re.fullmatch(r'[a-fA-F0-9]{32}', iv):
            raise SourceAccessError('Corocoro Online не предоставил открытые страницы.')
        decoder = AesCbcPage(bytes.fromhex(key), bytes.fromhex(iv))
        return remember([(page, decoder) for item in data.messages(2) if (page := image_url(item.string(1), url))], url)


SOURCES = (Corocoro(),)
