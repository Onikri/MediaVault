"""PandaChaika catalogue and the public ZIP reader described by Keiyoushi."""

from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urlsplit

from manga_direct_payloads import JsonSeries, items
from manga_madara import SEGMENT, image_url
from manga_public_zip import download_refs
from manga_webcomics import param, query_url
from source_parser import SourceError


HOST = 'panda.chaika.moe'
ROOT = 'https://' + HOST
ID = r'[1-9]\d{0,10}'
TITLE = rf'/archive/({ID})/?'
CHAPTER = rf'/archive/({ID})(?:/{SEGMENT})?/?'
DOWNLOAD = re.compile(rf'/archive/({ID})(?:/{SEGMENT})?/download/?')
LANGUAGES = {'all': '', 'en': 'english', 'zh': 'chinese', 'ja': 'japanese', 'id': 'indonesian'}


def public_api(host, path, query):
    if host != HOST:
        return False
    pairs = parse_qsl(query, keep_blank_values=True)
    data = dict(pairs)
    if len(pairs) != len(data) or any(len(value) > 300 for value in data.values()):
        return False
    if path == '/api':
        return set(data) == {'archive'} and bool(re.fullmatch(ID, data['archive']))
    if path in ('/search', '/search/'):
        filters = {'tags', 'sort', 'json', 'apply', 'page', 'title', 'qsearch'}
        return (set(data) <= filters and data.get('json') == '' and data.get('apply', '') == ''
                and data.get('sort', 'rating') in {'rating', 'public_date'}
                and ('page' not in data or bool(re.fullmatch(ID, data['page']))))
    return False


def date(value):
    return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat() if (
        type(value) in (int, float) and 0 < value <= 4_102_444_800) else ''


class PandaChaika(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, TITLE, CHAPTER, interval=.4)

    def is_title(self, target):
        return super().is_title(target) and not param(target, 'mv_zip')

    def is_chapter(self, target):
        return super().is_chapter(target) and (
            param(target, 'mv_zip') == '1' or not self.TITLE_PATH.fullmatch(urlsplit(target).path))

    def title_for(self, target):
        slug = self.chapter_key(target)
        return self.ROOT + '/archive/' + slug if slug else ''

    def chapter_identity(self, url):
        return self.chapter_key(url)

    def saved_title_url(self, url):
        target = self.canonical(url)
        slug = self.title_key(target) or urlsplit(target).path.strip('/')
        return self.ROOT + '/archive/' + slug if re.fullmatch(ID, slug) else ''

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if self.is_chapter(target):
            return target
        return query_url(title, mv_zip=1) if self.title_key(target) == self.title_key(title) and self.is_title(title) else ''

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.chapter_key(target) == self.title_key(title)

    def row_for(self, data, identity=None):
        key = str(data.get('id') or identity or '') if isinstance(data, dict) else ''
        name = data.get('title') if key else ''
        if not re.fullmatch(ID, key) or not isinstance(name, str) or not name:
            return None
        url = self.ROOT + '/archive/' + key
        tags, creators, genres = [], [], []
        for raw in data.get('tags') or ():
            if not isinstance(raw, str):
                continue
            prefix, _, label = raw.partition(':')
            if label:
                label = label.replace('_', ' ').strip()
                if prefix in ('artist', 'group'):
                    creators.append(label)
                elif prefix in ('genre', 'category'):
                    genres.append(label)
                else:
                    tags.append(label)
        return self.record(url, name, image_url(data.get('thumbnail'), url), aliases=(data.get('title_jpn') or '',),
                           genres=genres, tags=tags, authors=creators, status='completed')

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        language = LANGUAGES[self.LANGUAGE]
        options = {'tags': ','.join(item for item in (language, tag[:100]) if item),
                   'sort': 'public_date' if sort == 'updated' else 'rating', 'apply': '', 'json': '', 'page': page}
        if query:
            options['title'] = query
        result = self.json(http, query_url(self.ROOT + '/search/', **options))
        return [row for entry in items(result, 'archives') if (row := self.row_for(entry))], bool(
            result.get('hasNext') or result.get('has_next'))

    def series(self, http, url):
        identity = self.title_key(url)
        data = self.archive(http, identity, url)
        details = self.json(http, query_url(self.ROOT + '/search/', qsearch=data.get('title', ''), json=''), url)
        match = next((item for item in items(details, 'archives') if isinstance(item, dict) and
                      str(item.get('id')) == identity), data)
        row = self.row_for(match, identity)
        if not row:
            raise SourceError('PandaChaika не подтвердил карточку архива.')
        return row, [self.chapter(query_url(url.rstrip('/'), mv_zip=1), 'Chapter', 1, date(data.get('posted')))]

    def archive(self, http, key, referer):
        data = self.json(http, query_url(self.ROOT + '/api', archive=key), referer)
        target = self.site_link(data.get('download'), self.ROOT) if isinstance(data, dict) else ''
        if not (match := DOWNLOAD.fullmatch(urlsplit(target).path)) or match[1] != key:
            raise SourceError('PandaChaika не предоставил ZIP выбранного выпуска.')
        return {**data, 'download': target}

    def pages(self, http, url):
        target = self.title_for(url)
        data = self.archive(http, self.chapter_key(url), target)
        return download_refs(http, data['download'], target)


SOURCES = tuple(PandaChaika((sid, 'PandaChaika', lang, ROOT, True)) for sid, lang in (
    ('8212157560459310944', 'all'), ('3599272016034823454', 'en'), ('7139811400769884559', 'zh'),
    ('3512076228855715276', 'ja'), ('2553504349329211397', 'id'),
))
