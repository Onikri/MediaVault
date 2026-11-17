"""Direct Cubari manifests and translation groups for imported public links."""

from base64 import b64encode
import re
from urllib.parse import unquote, urlsplit

from manga_direct_payloads import JsonSeries, segment
from manga_madara import SEGMENT, image_url
from manga_rayuba import uploaded
from manga_series_port import number
from source_parser import SourceAccessError, SourceError


ROOT = 'https://cubari.moe'
PROVIDERS = r'imgur|reddit|imgchest|catbox|gist|mangadex|guya|mangasee|mangalife|weebcentral'
TITLE = rf'/(?:read|proxy)/((?:{PROVIDERS})/{SEGMENT})'
CHAPTER = TITLE + rf'/({SEGMENT})/({SEGMENT})/?'
API_SERIES = rf'/(?:read|proxy)/api/(?:{PROVIDERS})/series/{SEGMENT}/?'
API_CHAPTER = rf'/(?:read|proxy)/api/(?:{PROVIDERS})/chapter/{SEGMENT}/{SEGMENT}(?:/{SEGMENT})?/?'
STATUS = re.compile(r'^Status:[ \t]*([^\r\n]+)\s*$', re.M | re.I)
GALLERIES = {
    'imgur.com': ('imgur', {'a', 'gallery'}),
    'reddit.com': ('reddit', {'gallery'}),
    'imgchest.com': ('imgchest', {'p'}),
    'catbox.moe': ('catbox', {'c'}),
}


def public_api(host, path, query):
    return host == 'cubari.moe' and not query and any(
        re.fullmatch(spec, path) for spec in (API_SERIES, API_CHAPTER))


def page_src(row):
    return row.get('src', '') if isinstance(row, dict) else row if isinstance(row, str) else ''


class Cubari(JsonSeries):
    def __init__(self, sid, lang):
        super().__init__((sid, 'Cubari', lang, ROOT, False), TITLE + '/?', CHAPTER,
                         hosts=('www.cubari.moe',), interval=.35)

    def canonical(self, value):
        target = super().canonical(value)
        if target:
            parts = urlsplit(target)
            fields = parts.path.strip('/').split('/')
            if len(fields) >= 3 and fields[0] in {'proxy', 'read'} and fields[1] != 'api':
                return ROOT + '/read/' + '/'.join(fields[1:])
            return ''
        try:
            parts = urlsplit(value if isinstance(value, str) else '')
            if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443):
                return ''
            host = (parts.hostname or '').removeprefix('www.')
        except ValueError:
            return ''
        fields = parts.path.strip('/').split('/')
        if host in GALLERIES and len(fields) >= 2:
            provider, sections = GALLERIES[host]
            if fields[0] in sections and re.fullmatch(SEGMENT, fields[1]):
                return ROOT + '/read/' + provider + '/' + fields[1]
        if host == 'gist.githubusercontent.com' and '/raw' in parts.path:
            encoded = b64encode(('gist' + parts.path).encode()).decode().rstrip('=')
            if re.fullmatch(SEGMENT, encoded):
                return ROOT + '/read/gist/' + encoded
        return ''

    def title_for(self, url):
        key = self.chapter_key(url)
        return ROOT + '/read/' + key if key else ''

    def saved_title_url(self, value):
        target = self.canonical(value)
        return self.title_for(target) if self.is_chapter(target) else target if self.is_title(target) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        self.catalogue_params(page, query, tag)
        query = query.strip()
        if page != 1 or not query:
            return [], False
        value = ROOT + '/read/' + query[7:] if query.startswith('cubari:') else query
        target = self.saved_title_url(value)
        return ([self.series(http, target)[0]] if target else []), False

    def manifest(self, http, url):
        provider, key = self.title_key(url).split('/', 1)
        raw = self.json(http, f'{ROOT}/read/api/{provider}/series/{key}/', url)
        if not isinstance(raw, dict) or not isinstance(raw.get('chapters'), dict) or not raw.get('title'):
            raise SourceError('Cubari не предоставил открытый манифест серии.')
        return raw

    def series(self, http, url):
        url = self.saved_title_url(url)
        if not url:
            raise SourceError('Укажи публичную ссылку Cubari или поддерживаемой галереи.')
        raw = self.manifest(http, url)
        description, _, tags = str(raw.get('description') or '').partition('Tags: ')
        state = STATUS.search(description)
        status = state[1].strip().casefold() if state else ''
        row = self.record(url, str(raw['title']), image_url(raw.get('coverUrl') or raw.get('cover'), url),
                          description=STATUS.sub('', description).strip(), tags=tags.split(','),
                          authors=(raw.get('author'), raw.get('artist')),
                          status=status if status in {'ongoing', 'completed', 'cancelled'} else '')
        groups = raw.get('groups') if isinstance(raw.get('groups'), dict) else {}
        chapters = {}
        for ordinal, data in raw['chapters'].items():
            if not isinstance(data, dict) or not isinstance(data.get('groups'), dict) or not segment(ordinal):
                continue
            release = data.get('release_date') if isinstance(data.get('release_date'), dict) else {}
            vol = str(data.get('volume') or '').strip()
            label = ('Vol.' + vol + ' ' if vol.casefold() not in {'', 'null', 'uncategorized'} else '') + 'Ch.' + ordinal
            if data.get('title'):
                label += ' — ' + str(data['title'])
            for group, payload in data['groups'].items():
                if not segment(group) or not isinstance(payload, (list, str, dict)):
                    continue
                target = url.rstrip('/') + '/' + segment(ordinal) + '/' + segment(group)
                chapters[target] = self.chapter(target, label, number(ordinal), uploaded(release.get(group)),
                                                translator=str(groups.get(group) or ''))
        return row, self.order(chapters)

    def pages(self, http, url):
        match = self.CHAPTER_PATH.fullmatch(urlsplit(url).path)
        if not match:
            return []
        title = self.title_for(url)
        raw = self.manifest(http, title)
        series = raw['chapters'].get(unquote(match[2]))
        if not isinstance(series, dict) or not isinstance(groups := series.get('groups'), dict):
            return []
        payload = groups.get(unquote(match[3]))
        if not isinstance(payload, list):
            target = self.site_link(page_src(payload), ROOT + '/')
            if not public_api(urlsplit(target).hostname, urlsplit(target).path, urlsplit(target).query):
                raise SourceAccessError('Cubari не предоставил публичный маршрут страниц этой группы.')
            payload = self.json(http, target, title)
        return [image_url(page_src(entry), title) for entry in payload] if isinstance(payload, list) else []


SOURCES = tuple(Cubari(sid, lang) for sid, lang in (
    ('1470847599087460255', 'all'), ('2013845246758512290', 'other'), ('6338219619148105941', 'en'),
))
