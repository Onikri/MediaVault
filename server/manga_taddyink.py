"""Taddy INK open comic feeds (keiyoushi ``src/all/taddyink`` at 6f345a8).

The directory lists comic series as Schema.org JSON feeds. A series feed
holds every issue with its story images, so chapters carry the issue UUID in
``mv_issue`` next to the series feed URL.
"""

from datetime import datetime
import re
from urllib.parse import urlsplit

from manga_direct_payloads import JsonSeries
from manga_ninth_routes import register_api
from manga_webcomics import param, query_url
from source_parser import SourceAccessError, SourceError

UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
FEED = rf'/feeds/sss/comicseries/({UUID})'
GENRES = (
    ('Action', 'COMICSERIES_ACTION'), ('Comedy', 'COMICSERIES_COMEDY'), ('Drama', 'COMICSERIES_DRAMA'),
    ('Educational', 'COMICSERIES_EDUCATIONAL'), ('Fantasy', 'COMICSERIES_FANTASY'),
    ('Historical', 'COMICSERIES_HISTORICAL'), ('Horror', 'COMICSERIES_HORROR'),
    ('Inspirational', 'COMICSERIES_INSPIRATIONAL'), ('Mystery', 'COMICSERIES_MYSTERY'),
    ('Romance', 'COMICSERIES_ROMANCE'), ('Sci-Fi', 'COMICSERIES_SCI_FI'), ('Slice Of Life', 'COMICSERIES_SLICE_OF_LIFE'),
    ('Superhero', 'COMICSERIES_SUPERHERO'), ('Supernatural', 'COMICSERIES_SUPERNATURAL'),
    ('Wholesome', 'COMICSERIES_WHOLESOME'), ('BL (Boy Love)', 'COMICSERIES_BL'), ('GL (Girl Love)', 'COMICSERIES_GL'),
    ('LGBTQ+', 'COMICSERIES_LGBTQ'), ('Thriller', 'COMICSERIES_THRILLER'), ('Zombies', 'COMICSERIES_ZOMBIES'),
    ('Post Apocalyptic', 'COMICSERIES_POST_APOCALYPTIC'), ('School', 'COMICSERIES_SCHOOL'),
    ('Sports', 'COMICSERIES_SPORTS'), ('Animals', 'COMICSERIES_ANIMALS'), ('Gaming', 'COMICSERIES_GAMING'),
)
GENRE_NAMES = {key: label for label, key in GENRES}
LIMIT = 25
DIRECTORY_KEYS = {'q', 'lang', 'taddyType', 'ua', 'page', 'limit', 'genre'}


def public_api(host, path, query):
    from urllib.parse import parse_qsl

    if host != 'taddy.org':
        return False
    if re.fullmatch(FEED, path):
        return not query
    if path not in {'/feeds/directory/list', '/feeds/directory/search'}:
        return False
    try:
        fields = parse_qsl(query, keep_blank_values=True, max_num_fields=8)
    except ValueError:
        return False
    args = dict(fields)
    return (len(args) == len(fields) and set(args) <= DIRECTORY_KEYS and args.get('taddyType') == 'comicseries'
            and args.get('ua') == 'tc' and args.get('limit') == str(LIMIT)
            and bool(re.fullmatch(r'[1-9][0-9]{0,3}', args.get('page', ''))) and len(args.get('q', '')) <= 160
            and args.get('genre', 'COMICSERIES_ACTION') in GENRE_NAMES)


register_api(public_api)


class TaddyInk(JsonSeries):
    def __init__(self):
        super().__init__(('2332326521515456967', 'Taddy INK (Webtoons)', 'all', 'https://taddy.org', False),
                         FEED, FEED, interval=.25)

    def is_title(self, url):
        return bool(self.TITLE_PATH.fullmatch(urlsplit(url).path)) and not param(url, 'mv_issue')

    def is_chapter(self, url):
        return bool(self.TITLE_PATH.fullmatch(urlsplit(url).path)) and bool(re.fullmatch(UUID, param(url, 'mv_issue')))

    def title_for(self, url):
        return self.ROOT + urlsplit(url).path

    def chapter_identity(self, url):
        return urlsplit(url).path + '#' + param(url, 'mv_issue')

    def saved_chapter(self, row, root, title):
        # Suwayomi stored "<series feed>#<issue UUID>".
        value = str(row.get('realUrl') or row.get('url') or '')
        feed, _, issue = value.partition('#')
        target = self.canonical(feed)
        if self.is_title(target) and re.fullmatch(UUID, issue):
            return query_url(target, mv_issue=issue)
        return super().saved_chapter(row, root, title)

    def saved_chapter_matches(self, target, title):
        return self.is_chapter(target) and self.title_key(self.title_for(target)) == self.title_key(title)

    def record_from(self, item):
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            return None
        url = self.canonical(item.get('url'))
        if not self.is_title(url):
            return None
        cover = item.get('coverImage') if isinstance(item.get('coverImage'), dict) else {}
        image = (cover.get('base_url') or '') + (cover.get('cover_md') or cover.get('cover_sm') or '')
        creators = [c.get('name') for c in item.get('creators') or [] if isinstance(c, dict) and isinstance(c.get('name'), str)]
        genres = [GENRE_NAMES[g] for g in item.get('genres') or [] if g in GENRE_NAMES]
        tags = [t for t in item.get('tags') or [] if isinstance(t, str)]
        row = self.record(url, item['name'].strip(), image if image.startswith('https://') else '',
                          description=(item.get('description') or '').strip(), genres=genres, tags=tags,
                          authors=creators, status={'ONGOING': 'ongoing', 'COMPLETED': 'completed',
                                                    'HIATUS': 'hiatus', 'CANCELLED': 'cancelled'}.get(
                              str(item.get('status') or '').removeprefix('COMICSERIES_'), ''))
        row['format'] = 'manhwa'
        return row

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and tag not in GENRE_NAMES:
            return [], False
        args = {'q': query, 'lang': '', 'taddyType': 'comicseries', 'ua': 'tc', 'page': page, 'limit': LIMIT}
        if tag:
            args['genre'] = tag
        route = 'search' if query or tag else 'list'
        if route == 'list':
            args.pop('q')
        data = self.json(http, query_url(f'{self.ROOT}/feeds/directory/{route}', **args))
        items = data.get('comicseries') if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceError('Taddy INK изменил формат каталога.')
        rows = [row for row in map(self.record_from, items) if row]
        return rows, len(items) == LIMIT

    def vocabulary(self, http):
        return [{'key': key, 'label': label, 'kind': 'genre'} for label, key in GENRES]

    def feed(self, http, url):
        data = self.json(http, self.ROOT + urlsplit(url).path)
        if not isinstance(data, dict) or self.canonical(data.get('url')) != self.ROOT + urlsplit(url).path:
            raise SourceError('Taddy INK не предоставил ленту серии.')
        return data

    def series(self, http, url):
        data = self.feed(http, url)
        row = self.record_from(data)
        if not row:
            raise SourceError('Taddy INK не предоставил карточку серии.')
        issues = [item for item in data.get('issues') or [] if isinstance(item, dict)
                  and isinstance(item.get('identifier'), str) and re.fullmatch(UUID, item['identifier'])]
        chapters = []
        for index, item in enumerate(reversed(issues), 1):
            date = ''
            try:
                date = datetime.fromisoformat(str(item.get('datePublished', '')).replace('Z', '+00:00')).date().isoformat()
            except ValueError:
                pass
            target = query_url(self.title_for(url), mv_issue=item['identifier'])
            chapters.append(self.chapter(target, str(item.get('name') or f'Issue {index}'), float(index), date))
        return row, chapters

    def pages(self, http, url):
        issue = param(url, 'mv_issue')
        data = self.feed(http, url)
        found = next((item for item in data.get('issues') or [] if isinstance(item, dict) and item.get('identifier') == issue), None)
        if found is None:
            raise SourceAccessError('Taddy INK больше не публикует этот выпуск.')
        pages = []
        for story in found.get('stories') or []:
            image = story.get('storyImage') if isinstance(story, dict) else None
            if isinstance(image, dict) and isinstance(image.get('base_url'), str) and isinstance(image.get('story'), str):
                pages.append(image['base_url'] + image['story'])
        return pages


SOURCES = (TaddyInk(),)
