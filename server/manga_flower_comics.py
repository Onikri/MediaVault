"""Flower Comics public React Flight catalogue and free reader."""

from datetime import datetime
import re
from urllib.parse import urlsplit

from manga_clipstudio_sources import flight_item
from manga_direct_payloads import JsonSeries
from manga_japanese_next import AesCbcPage, HEX_IV, HEX_KEY
from manga_madara import image_url, node_text, release_date
from manga_mangaone import TOKYO
from manga_series_port import Meta, SeriesPort
from manga_speedbinb import remember
from manga_vinetheme import flight_models, flight_stream, resolve_fields
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

ROOT = 'https://flowercomics.jp'
ID = r'[1-9]\d{0,12}'
TITLE = rf'/title/({ID})/?'
CHAPTER = rf'/chapter/({ID})/viewer/?'
DAYS = dict(zip(('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'), '月 火 水 木 金 土 日'.split()))
CHAPTER_FIELDS = ('earlyChapters', 'omittedMiddleChapters', 'latestChapters')
LABELS = {'3': 'Ｓｈｏ－Ｃｏｍｉ', '6': 'Sho-ComiX', '12': 'Ｃｈｅｅｓｅ！', '15': 'プレミアCheese！',
          '21': 'ベツコミ', '30': 'プチコミック', '36': 'デジプチ', '39': '月刊ｆｌｏｗｅｒｓ',
          '42': 'flowers増刊', '51': 'モバフラ', '57': 'オリジナル'}


def ordered_page_lists(raw):
    models = flight_models(flight_stream(raw))
    for value in models.values():
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                stack.extend(reversed(list(item.values())))
            elif isinstance(item, list):
                if item and all(isinstance(page, dict) and 'src' in page and 'crypto' in page for page in item):
                    try:
                        yield resolve_fields(item, models, [60000])
                    except SourceError:
                        continue
                else:
                    stack.extend(reversed(item))


class FlowerComics(JsonSeries):
    meta = Meta('h1', 'section img.object-cover', 'div.whitespace-pre-wrap p',
                genres='ul[aria-label="ジャンルタグ一覧"] p', author='a[href^="/author/"] p')

    def __init__(self):
        super().__init__(('6525907185900913523', 'Flower Comics', 'ja', ROOT, True), TITLE, CHAPTER, interval=.35)

    def title_for(self, url):
        key = param(url, 'mv_flower_title')
        return ROOT + '/title/' + key if self.is_chapter(url) and re.fullmatch(ID, key) else ''

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def saved_chapter_matches(self, target, title):
        return bool(self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title))

    def saved_title_url(self, value):
        url = self.canonical(value)
        key = urlsplit(url).path.strip('/')
        return ROOT + '/title/' + key if re.fullmatch(ID, key) else url if self.is_title(url) else self.title_for(url)

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        key = urlsplit(url).path.strip('/')
        if re.fullmatch(ID, key):
            url = ROOT + f'/chapter/{key}/viewer'
        return query_url(url, mv_flower_title=self.title_key(title)) if self.is_title(title) and self.is_chapter(url) else ''

    def get_raw(self, http, url):
        self.origin.wait(getattr(http, 'deadline', None))
        raw, final, _ = http.document(url, headers={'Referer': ROOT + '/'})
        if final != url:
            raise SourceError('Flower Comics перенаправил на другую страницу.')
        return raw

    def from_flight(self, http, rank, day=''):
        if rank:
            raw = self.get_raw(http, ROOT + '/ranking')
            node = flight_item(raw, ('rankingTypeName', 'titles'), lambda item: item['rankingTypeName'] == '総合')
            items = node.get('titles') or []
        else:
            raw = self.get_raw(http, ROOT + '/rensai')
            weekdays = flight_item(raw, ('weekdays',)).get('weekdays') or {}
            items = weekdays.get(day) or []
        rows = {}
        for item in items:
            if isinstance(item, dict) and re.fullmatch(ID, key := str(item.get('id') or '')) and item.get('name'):
                target = ROOT + '/title/' + key
                rows[target] = self.record(target, item['name'], image_url((item.get('thumbnail') or {}).get('src'), target))
        return list(rows.values())

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if page != 1:
            return [], False
        if query:
            url = query_url(ROOT + '/search', keyword=query)
        elif tag in DAYS or sort == 'updated' and not tag:
            return self.from_flight(http, False, tag or tuple(DAYS)[datetime.now(TOKYO).weekday()]), False
        elif tag in ('completed', 'one-shot'):
            url = ROOT + '/rensai/' + tag
        elif re.fullmatch(r'(?:label|genre):[1-9]\d{0,9}', tag):
            kind, key = tag.split(':')
            url = ROOT + '/tag/' + key + '/' + kind
        else:
            return self.from_flight(http, True), False
        doc, final = self.document(http, url)
        rows = {}
        for anchor in doc.select('div.grid > a[href^="/title/"]'):
            target = self.site_link(anchor['href'], final)
            label = node_text(anchor.select_one('p.text-black'))
            if self.is_title(target) and label:
                rows[target] = self.record(target, label, image_url((anchor.img or {}).get('src'), final))
        return list(rows.values()), False

    def vocabulary(self, http):
        return [{'key': key, 'label': value, 'kind': 'category'} for key, value in DAYS.items()] + [
            {'key': 'label:' + key, 'label': value, 'kind': 'category'} for key, value in LABELS.items()]

    def series(self, http, url):
        from bs4 import BeautifulSoup

        raw = self.get_raw(http, url)
        doc = BeautifulSoup(raw, 'html.parser')
        row = self.metadata(doc, url, self.meta)
        text = ' '.join(node_text(el) for el in doc.select('div.bg-main-blue p'))
        row['status'] = 'completed' if '完結' in text else 'ongoing' if '連載' in text or '更新予定' in text else ''
        payload = flight_item(raw, CHAPTER_FIELDS)
        episodes = {}
        for field in CHAPTER_FIELDS:
            for item in payload.get(field) or []:
                if not isinstance(item, dict) or not re.fullmatch(ID, key := str(item.get('id') or '')):
                    continue
                label = ' '.join(str(item[name]) for name in ('title', 'subTitle') if item.get(name))
                if item.get('chapterType') in (2, 3, 4):
                    label = '🔒 ' + label
                target = query_url(ROOT + f'/chapter/{key}/viewer', mv_flower_title=self.title_key(url))
                date = release_date(str(item.get('updated') or ''), '%Y/%m/%d')
                episodes[target] = self.chapter(target, label, date=date)
        return row, self.order(episodes)

    def inspect(self, value, http):
        url = self.canonical(value)
        if self.is_chapter(url) and not self.title_for(url):
            return SeriesPort.inspect(self, url, http)
        return super().inspect(url, http)

    def pages(self, http, url):
        target = ROOT + urlsplit(url).path.rstrip('/')
        raw = self.get_raw(http, target)
        items = next(ordered_page_lists(raw), ())
        refs = []
        for page in items:
            crypto = page.get('crypto')
            if not isinstance(crypto, dict):
                continue
            key, iv = str(crypto.get('key') or ''), str(crypto.get('iv') or '')
            link = image_url(page['src'], url)
            if not link or not HEX_KEY.fullmatch(key) or not HEX_IV.fullmatch(iv):
                raise SourceError('Flower Comics вернул неполные данные страницы.')
            refs.append((link, AesCbcPage(bytes.fromhex(key), bytes.fromhex(iv))))
        if not refs:
            raise SourceAccessError('Flower Comics не передал открытые страницы.')
        return remember(refs, target)


SOURCES = (FlowerComics(),)
