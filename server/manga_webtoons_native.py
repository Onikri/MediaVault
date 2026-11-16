"""Native multilingual WEBTOON Originals and Canvas (Keiyoushi, Apache-2.0)."""

from datetime import datetime, timedelta, timezone
from html import unescape
import json
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from manga_madara import SEGMENT, image_url
from manga_series_port import Cards, MAX_CHAPTERS, Meta, SeriesPort, number, picture
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError


ROOT = 'https://www.webtoons.com'
MOBILE = 'https://m.webtoons.com'
ID = r'[1-9][0-9]{0,9}'
RANKINGS = ('trending', 'popular', 'originals', 'canvas')
LANGUAGES = {'en', 'id', 'th', 'es', 'fr', 'zh-hant', 'de'}
PAID = ('locked', 'isLocked', 'charge', 'isPaid', 'paywalled')
EPISODE = re.compile(r'(?:(?:season|saison|part|vol(?:ume)?)\s*\.?\s*(\d{1,3}).*?)?'
                     r'(?:ep(?:isode)?|ch(?:apter)?)\s*\.?\s*(\d{1,5}(?:[.,]\d{1,3})?)', re.I)
DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


def public_api(host, path, query):
    match = re.fullmatch(rf'/api/v1/(webtoon|canvas)/{ID}/episodes', path)
    if host != 'm.webtoons.com' or not match:
        return False
    fields = parse_qsl(query)
    params = dict(fields)
    expected = {'pageSize', 'readingLanguageCode'} if match[1] == 'canvas' else {'pageSize'}
    return (len(fields) == len(params) and set(params) == expected
            and params.get('pageSize') == str(MAX_CHAPTERS)
            and (match[1] == 'webtoon' or params.get('readingLanguageCode') in LANGUAGES))


class WebtoonLocale(SeriesPort):
    cards = Cards('.webtoon_list li a[href]', '', '.title', 'img', next='a.pagination[aria-current=true] + a')
    meta = Meta('h1.subj, h3.subj', '', '#_asideDetail p.summary', genres='.detail_header .info .genre',
                author='.detail_header .info :is(.author, .author_area)', status='#_asideDetail p.day_info')

    def __init__(self, identity):
        self.locale = identity[2].lower()
        section = rf'/{self.locale}/({SEGMENT}/{SEGMENT})'
        super().__init__(identity, section + r'/list/?', section + rf'/{SEGMENT}/viewer/?',
                         hosts=('webtoons.com', 'm.webtoons.com'), interval=.4)

    def title_identity(self, value):
        key = self.title_key(value)
        return f'title:{key}' if key else super().title_identity(value)

    def title_key(self, url):
        value = param(url, 'title_no') or param(url, 'titleNo')
        return value if re.fullmatch(ID, value) else ''

    def chapter_identity(self, url):
        return self.title_key(url), param(url, 'episode_no')

    def is_title(self, url):
        return super().is_title(url) and bool(self.title_key(url)) and not param(url, 'episode_no')

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_key(url) and re.fullmatch(ID, param(url, 'episode_no')))

    def title_for(self, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        return self.list_url(match[1], self.title_key(url)) if match else ''

    def list_url(self, slug, key):
        return query_url(f'{self.ROOT}/{self.locale}/{slug}/list', title_no=key)

    def saved_title_url(self, value):
        url = self.canonical(value)
        if self.is_title(url):
            return url
        path = urlsplit(url).path
        key = self.title_key(url)
        if key and path in {'/episodeList', '/challenge/episodeList'}:
            prefix = f'/{self.locale}/canvas' if path.startswith('/challenge/') else '/' + self.locale
            return query_url(self.ROOT + prefix + '/list', title_no=key)
        return ''

    def title_document(self, http, url):
        doc, final = self.document(http, url)
        if not self.is_title(final) or self.title_key(final) != self.title_key(url):
            raise SourceError('WEBTOON перенаправил на другой тайтл.')
        return doc, final

    def details(self, http, value):
        url = self.saved_title_url(value)
        if not url:
            raise SourceError('Некорректная ссылка WEBTOON.')
        doc, final = self.title_document(http, url)
        return self.metadata(doc, final, self.meta)

    def inspect(self, value, http):
        url = self.canonical(value)
        if not self.is_chapter(url):
            url = self.saved_title_url(url)
            if not url:
                raise SourceError('Некорректная ссылка WEBTOON.')
            doc, final = self.title_document(http, url)
            row = self.metadata(doc, final, self.meta)
            chapters, truncated = self.chapters(http, doc, final)
            return self.reader_result(row, final, chapters, [], truncated)
        return super().inspect(url, http)

    def record(self, url, title, cover='', **metadata):
        row = super().record(url, title, cover, **metadata)
        row.update(format='webtoon', readingMode='scroll')
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        suffix = False
        if query or tag in {'originals', 'canvas'}:
            kind = f'/{tag}' if tag in {'originals', 'canvas'} else ''
            args = {'keyword': query}
            if page > 1 and kind:
                args['page'] = page
            elif page > 1:
                return [], False
            url = query_url(f'{self.ROOT}/{self.locale}/search{kind}', **args)
            suffix = bool(kind)
        elif sort == 'updated':
            if page != 1:
                return [], False
            day = DAYS[datetime.now(timezone(timedelta(hours=9))).weekday()]
            url = f'{self.ROOT}/{self.locale}/originals/{day}?sortOrder=UPDATE'
        elif page <= len(RANKINGS):
            url = f'{self.ROOT}/{self.locale}/ranking/{RANKINGS[page-1]}'
            suffix = page < len(RANKINGS)
        else:
            return [], False
        rows, more = self.card_rows(*self.document(http, url), self.cards)
        return rows, bool(rows and (suffix if not query else suffix and more))

    def vocabulary(self, http):
        return [{'label': label, 'sourceId': key, 'category': 'tag'}
                for label, key in (('Originals', 'originals'), ('Canvas', 'canvas'))]

    def chapters(self, http, doc, final):
        title = self.title_key(final)
        canvas = urlsplit(final).path.startswith(f'/{self.locale}/canvas/')
        source = 'canvas' if canvas else 'webtoon'
        args = {'pageSize': MAX_CHAPTERS}
        if canvas:
            args['readingLanguageCode'] = self.locale
        data = self.json(http, query_url(f'{MOBILE}/api/v1/{source}/{title}/episodes', **args), MOBILE + '/')
        records = (data.get('result') or {}).get('episodeList') if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise SourceError('WEBTOON не предоставил публичный список глав.')
        rows = {}
        maximum, season, offset = 0, 1, 0
        for row in records[:MAX_CHAPTERS]:
            if not isinstance(row, dict) or any(row.get(key) for key in PAID):
                continue
            href = self.site_link(row.get('viewerLink'), final)
            if not self.is_chapter(href) or self.title_key(href) != title:
                continue
            label = unescape(str(row.get('episodeTitle') or ''))
            match = EPISODE.search(label)
            sequence = number(param(href, 'episode_no'))
            n, available_season = (number(match[2]), int(match[1] or season)) if match else (sequence, season)
            if available_season > season:
                season = available_season
                offset = maximum if n is not None and n <= maximum else 0
            if n is not None:
                n += offset
                maximum = max(maximum, n)
            published = row.get('exposureDateMillis')
            date = datetime.fromtimestamp(published / 1000, tz=timezone.utc).date().isoformat() if (
                type(published) is int and 0 < published <= 4_102_444_800_000) else ''
            rows[href] = self.chapter(href, label, n, date, season)
        return self.order(rows), len(records) >= MAX_CHAPTERS

    def saved_chapter_matches(self, target, title):
        key = self.title_key(target)
        return bool(self.is_chapter(target) and key and key == self.title_key(title))

    def pages(self, http, url):
        doc, final = self.page_document(http, url)
        images = [picture(node, final, ('data-url', 'data-src')) for node in doc.select('#_imageList > img[data-url], #_imageList > img[data-src]')]
        if images:
            return images
        # MotionToon assets are advertised by the episode, with one image file per layer.
        scripts = '\n'.join(node.string or '' for node in doc.select('script'))
        manifest = re.search(r"""documentURL:\s*['"]([^'"]+)['"]""", scripts)
        directory = re.search(r"""jpg:\s*['"]([^'"]+)\{""", scripts)
        if manifest and directory:
            target = image_url(manifest[1], final)
            base = image_url(directory[1], final)
            provider = ('webtoons.com', 'pstatic.net', 'naver.net')
            if target and base and all(any(host == domain or host.endswith('.' + domain) for domain in provider)
                                       for host in (urlsplit(target).hostname or '', urlsplit(base).hostname or '')):
                raw, final_manifest, _ = http.document(target, headers={'Referer': final})
                if final_manifest != target:
                    raise SourceError('WEBTOON перенаправил манифест главы.')
                try:
                    assets = json.loads(raw)['assets']['images']
                    return [image_url(urljoin(base, image), final) for key, image in assets.items()
                            if 'layer' in key and isinstance(image, str) and re.fullmatch(r'[\w.-]{1,240}', image)]
                except (AttributeError, TypeError, ValueError, KeyError, RecursionError):
                    raise SourceError('WEBTOON изменил формат MotionToon.') from None
        raise SourceAccessError('WEBTOON не предоставил открытые страницы главы.')


SOURCES = tuple(WebtoonLocale((sid, 'Webtoons.com', language, ROOT, False)) for sid, language in (
    ('2522335540328470744', 'en'), ('8749627068478740298', 'id'), ('3330861233813615504', 'th'),
    ('8664735734660636295', 'es'), ('8251758253314457060', 'fr'), ('2959982438613576472', 'zh-Hant'),
    ('1486822823904297379', 'de'),
))
