"""Small franchise catalogues based on the Apache-2.0 Keiyoushi MangaCatalog family."""

import base64
import re
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from manga_madara import CHAPTER_NUMBER, SEGMENT, VOLUME_NUMBER, image_url, node_text, release_date
from manga_source_tags import unique
from source_parser import PublicHttp, SourceError, public_url


TITLE_PATH = re.compile(rf'/(?:manga/({SEGMENT})/?)?')
CHAPTER_PATH = re.compile(rf'/(?:chapter|manga)/({SEGMENT})(?:/{SEGMENT})?/?')
STRUCTURE = {
    'default': ('div.w-full > div.bg-bg-secondary > div.grid', '.col-span-4 > a[href]', '.text-xs:not(a)'),
    'snk': ('div.w-full div.grid div.col-span-4', 'a[href]', 'div.text-xs'),
    'berserk': ('tbody > tr', 'a.btn-primary[href]', ''),
    'opm': ('tbody > tr', 'a[href]', ''),
    'tower': ('a[href*="/manga/tower-of-god-chapter-"]', '', ''),
}
PAGES = {
    'default': 'img.js-page:not(noscript img), img.pages__img',
    'berserk': 'div.pages img.pages__img',
    'tower': 'img[src*="blogger.googleusercontent.com"], img[src*="bp.blogspot.com"]',
}


def lazy_placeholder(value):
    prefix = 'data:image/gif;base64,'
    if not value or not value.startswith(prefix) or len(value) > 120:
        return False
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
    except ValueError:
        return False
    return raw[:6] in {b'GIF87a', b'GIF89a'} and raw[6:10] == b'\x01\x00\x01\x00'


class MangaCatalog:
    TITLE_PATH = TITLE_PATH
    CHAPTER_PATH = CHAPTER_PATH
    LANGUAGE = 'en'

    def __init__(self, identity, works, layout='default'):
        self.SOURCE_ID, self.NAME, self.ROOT, self.IS_NSFW = identity
        self.host = urlsplit(self.ROOT).netloc
        self.layout = layout
        self.works = {}
        for label, path in works:
            self.works.setdefault(path.rstrip('/') or '/', []).append(label)

    def site_link(self, value, base=None):
        if not isinstance(value, str) or not value:
            return ''
        try:
            candidate = urljoin(base or self.ROOT, value)
            parsed = urlsplit(candidate)
            if parsed.scheme == 'https' and parsed.netloc == self.host:
                return public_url(candidate, resolve_dns=False)
        except (ValueError, SourceError):
            pass
        return ''

    def document(self, http, url):
        raw, final, _ = http.document(url, headers={'Referer': self.ROOT + '/'})
        if not self.site_link(final) or urlsplit(final).path.rstrip('/') != urlsplit(url).path.rstrip('/'):
            raise SourceError('MangaCatalog перенаправил запрос на другую страницу.')
        soup = BeautifulSoup(raw, 'html.parser')
        from manga_sources import guard
        guard(soup)
        return soup, final

    def row(self, path):
        from manga_sources import title_aliases
        labels = self.works[path]
        url = self.ROOT + path.rstrip('/') + '/'
        slug = path.rsplit('/', 1)[-1] or 'tower-of-god'
        return {'id': f'suwayomi:{self.SOURCE_ID}:native:{slug}', 'provider': 'suwayomi:' + self.SOURCE_ID,
                'providerName': self.NAME, 'sourceId': self.SOURCE_ID, 'sourceUrl': url, 'sourceURL': url, 'url': url,
                'kind': 'manga', 'language': self.LANGUAGE, 'title': labels[0], 'ids': {}, 'sourceOnly': True,
                'aliases': unique([*title_aliases(labels[0]), *labels[1:], slug.replace('-', ' ')]), 'cover': ''}

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        if page != 1 or tag:
            return [], False
        term = query.casefold().strip()
        return [self.row(path) for path, labels in self.works.items()
                if not term or any(term in label.casefold() for label in labels)
                or term.replace(' ', '-') in path.casefold()], False

    def vocabulary(self, http):
        return []

    def metadata(self, soup, url, path):
        result = self.row(path)
        if self.layout == 'tower':
            title = result['title']
            cover = soup.select_one('meta[property="og:image"]')
            description = soup.select_one('meta[property="og:description"]')
            thumbnail = cover.get('content', '') if cover else ''
            synopsis = description.get('content', '') if description else ''
        elif self.layout in {'berserk', 'opm'}:
            title = node_text(soup.select_one('h2 > span'))
            if self.layout == 'opm':
                title = title.removeprefix('Manga: ').strip()
            cover = soup.select_one('.card-img-right')
            thumbnail = cover.get('src', '') if cover else ''
            synopsis = ' '.join(node_text(node) for node in soup.select('div.card-body > p'))
        else:
            title = node_text(soup.select_one('div.container > h1'))
            cover = soup.select_one('div.flex > img')
            thumbnail = cover.get('src', '') if cover else ''
            synopsis = node_text(soup.select_one('div.bg-bg-secondary > div.px-6 > div.flex-col')).split('Description', 1)[-1].strip()
        if not title:
            raise SourceError('MangaCatalog не предоставил карточку произведения.')
        return {**result, 'title': title, 'aliases': unique([title, *result['aliases']]), 'genres': [],
                'tags': [], 'description': synopsis[:12000], 'cover': image_url(thumbnail, url)}

    def work_path(self, path):
        normalized = path.rstrip('/') or '/'
        if normalized in self.works:
            return normalized
        if self.layout == 'tower' and normalized.startswith('/manga/tower-of-god-chapter-'):
            return '/'
        if normalized.startswith('/chapter/'):
            if self.layout == 'opm' and normalized == '/chapter/one-punch-man-special-one-shot':
                return '/manga/one-punch-man'
            normalized = '/manga/' + normalized.removeprefix('/chapter/')
            if normalized in self.works:
                return normalized
        candidates = [entry for entry in self.works if normalized.startswith((entry + '/', entry + '-chapter-'))]
        return max(candidates, key=len) if candidates else None

    def details(self, http, value):
        target = self.site_link(value)
        path = urlsplit(target).path.rstrip('/') or '/'
        if not target or path not in self.works:
            raise SourceError('Некорректная ссылка на тайтл MangaCatalog.')
        soup, url = self.document(http, target)
        return self.metadata(soup, url, path)

    def saved_chapter_url(self, value, title, root):
        return self.site_link(value, root)

    def saved_chapter_matches(self, target, title):
        path = self.work_path(urlsplit(target).path)
        if path != (urlsplit(title).path.rstrip('/') or '/'):
            return False
        http = PublicHttp(timeout=(3, 6))
        try:
            soup, final = self.document(http, title)
            expected = urlsplit(target).path.rstrip('/')
            return any(urlsplit(row['url']).path.rstrip('/') == expected for row in self.chapters(soup, final, path))
        finally:
            http.close()

    def entry(self, target, label, date=''):
        path = unquote(urlsplit(target).path)
        number = CHAPTER_NUMBER.search(label) or CHAPTER_NUMBER.search(path)
        volume = VOLUME_NUMBER.search(label)
        return {'url': target, 'title': label or (f'Chapter {number[1]}' if number else path.rsplit('/', 1)[-1]),
                'publishedAt': date, 'number': float(number[1].replace(',', '.')) if number else 0,
                'season': int(volume[1]) if volume else 1, 'language': 'en', 'translator': ''}

    def chapters(self, soup, url, path):
        selector, link, subtitle = STRUCTURE[self.layout]
        found = {}
        for node in soup.select(selector):
            anchor = node.select_one(link) if link else node
            target = self.site_link(anchor.get('href'), url) if anchor else ''
            target_path = urlsplit(target).path.rstrip('/')
            if not CHAPTER_PATH.fullmatch(target_path) or target_path in self.works or self.work_path(target_path) != path:
                continue
            date = ''
            if self.layout in {'berserk', 'opm'}:
                label = node_text(node.select_one('td:first-child'))
                date = release_date(node_text(node.select_one('td:nth-child(2)')), '%b %d, %Y')
            elif self.layout == 'tower':
                label = ''
            else:
                label = node_text(anchor)
                if detail := node_text(node.select_one(subtitle)):
                    label += ' — ' + detail
            found[target_path] = self.entry(target, label, date)
        return sorted(found.values(), key=lambda row: (row['season'], row['number']))

    def pages(self, soup, url):
        selector = PAGES.get(self.layout, PAGES['default'])
        sources = [node.get('data-src') or node.get('src') for node in soup.select(selector)]
        pages = [image_url(value, url) for value in sources if not lazy_placeholder(value)]
        if self.layout == 'tower':
            pages = list(dict.fromkeys(pages))
        if not pages or len(pages) > 500 or not all(pages):
            raise SourceError('MangaCatalog не предоставил полный список изображений главы.')
        return pages

    def inspect(self, value, http):
        target = self.site_link(value)
        path = urlsplit(target).path
        parent = self.work_path(path) if target else None
        if parent is None:
            raise SourceError('MangaCatalog не распознал тайтл или главу.')
        soup, url = self.document(http, target)
        if (path.rstrip('/') or '/') == parent:
            result = self.metadata(soup, url, parent)
            chapters = self.chapters(soup, url, parent)
            pages = []
        else:
            result = self.row(parent)
            chapters = [self.entry(url, node_text(soup.select_one('h1, h2')))]
            pages = self.pages(soup, url)
        return {**result, 'url': url, 'episodes': chapters, 'pages': pages, 'available': bool(chapters),
                'truncated': False, 'seasons': [{'number': n, 'name': f'Том {n}'} for n in sorted({c['season'] for c in chapters})],
                'dubs': [], 'releases': [], 'translations': []}


SOURCES = (
    MangaCatalog(('8930801332831394412', 'Read Attack on Titan Shingeki no Kyojin Manga', 'https://ww12.readsnk.com', False), (
        ('Shingeki No Kyojin', '/manga/shingeki-no-kyojin/'),
        ('Colored', '/manga/shingeki-no-kyojin-colored/'),
        ('Before the Fall', '/manga/shingeki-no-kyojin-before-the-fall/'),
        ('Lost Girls', '/manga/shingeki-no-kyojin-lost-girls/'),
        ('No Regrets', '/manga/attack-on-titan-no-regrets/'),
        ('Junior High', '/manga/attack-on-titan-junior-high/'),
        ('Guidebook', '/manga/attack-on-titan-guidebook-inside-outside/'),
        ('Harsh Mistress', '/manga/attack-on-titan-harsh-mistress-of-the-city/'),
        ('Anthology', '/manga/attack-on-titan-anthology/'),
        ('Art Book', '/manga/attack-on-titan-exclusive-art-book/'),
        ('Spoof', '/manga/spoof-on-titan/'),
        ('No Regrets Colored', '/manga/attack-on-titan-no-regrets-colored/'),
        ('BTF Light Novel', '/manga/attack-on-titan-before-the-fall-light-novel/'),
        ('Best of SNK', '/manga/the-best-of-attack-on-titan-in-color/'),
    ), layout='snk'),
    MangaCatalog(('4917014756556380981', 'Read Berserk Manga', 'https://readberserk.com', False), (
        ('Berserk', '/manga/berserk/'),
        ('Guidebook', '/manga/berserk-official-guidebook/'),
        ('Colored', '/manga/berserk-colored/'),
        ('Duranki', '/manga/duranki/'),
        ('Gigantomakhia', '/manga/gigantomakhia/'),
        ('Futatabi', '/manga/futatabi/'),
        ('Berserk Spoilers & RAW', '/manga/berserk-spoilers-raw/'),
    ), layout='berserk'),
    MangaCatalog(('6485938153129890061', 'Read Black Clover Manga Online', 'https://ww10.readblackclover.com', False), (
        ('Black Clover', '/manga/black-clover/'),
        ('Fan Colored', '/manga/black-clover-colored/'),
        ('Hungry Joker', '/manga/hungry-joker/'),
        ('Gaiden', '/manga/black-clover-gaiden-quartet-knights/'),
    )),
    MangaCatalog(('6207801235158968822', 'Read Chainsaw Man Manga Online', 'https://ww6.readchainsawman.com', True), (
        ('Chainsaw Man', '/manga/chainsaw-man/'),
        ('17-21', '/manga/17-21-fujimoto-tatsuki-tanpenshuu/'),
        ('Fire Punch', '/manga/fire-punch/'),
        ('Nayuta', '/manga/yogen-no-nayuta/'),
        ('Look Back', '/manga/look-back/'),
        ('Light Novel', '/manga/chainsaw-man-buddy-stories/'),
        ('Colored', '/manga/chainsaw-man-colored/'),
        ('Listen to Song', '/manga/futsuu-ni-kiite-kure/'),
        ('Goodbye, Eri', '/manga/sayonara-eri-goodbye-eri/'),
        ('22-26', '/manga/22-26-fujimoto-tatsuki-tanpenshuu/'),
        ('Chainsaw Man Colored', '/manga/chainsaw-man-colored/'),
        ('Chainsaw Man: Buddy Stories', '/manga/chainsaw-man-buddy-stories/'),
    )),
    MangaCatalog(('1330793582354406642', 'Read Fairy Tail & Edens Zero Manga Online', 'https://ww9.readfairytail.com', False), (
        ("Eden's Zero", '/manga/edens-zero/'),
        ('Fairy Tail', '/manga/fairy-tail/'),
        ('FT Zero', '/manga/fairy-tail-zero/'),
        ('FT City Hero', '/manga/fairy-tail-city-hero/'),
        ('Hero’s', '/manga/heros/'),
        ('FT Happy Adv', '/manga/fairy-tail-happys-grand-adventure/'),
        ('FT 100 Year', '/manga/fairy-tail-100-years-quest/'),
        ('FT Ice Trail', '/manga/fairy-tail-ice-trail/'),
        ('FT x Taizai', '/manga/fairy-tail-x-nanatsu-no-taizai-christmas-special/'),
        ('Parasyte x FT', '/manga/parasyte-x-fairy-tail/'),
        ('Gaiden 1', '/manga/fairy-tail-gaiden-raigo-issen/'),
        ('FT x Rave', '/manga/fairy-tail-x-rave/'),
        ('Monster Hunter', '/manga/monster-hunter-orage/'),
        ('Rave Master', '/manga/rave-master/'),
        ('Dead Rock', '/manga/dead-rock/'),
        ('Fairy Girls', '/manga/fairy-girls/'),
        ('Gaiden 4', '/manga/fairy-tail-gaiden-raigo-issen/'),
        ('Gaiden 2', '/manga/fairy-tail-gaiden-kengami-no-souryuu/'),
        ('Gaiden 3', '/manga/fairy-tail-gaiden-road-knight/'),
        ('FT x 7DS', '/manga/fairy-tail-x-nanatsu-no-taizai-christmas-special/'),
    )),
    MangaCatalog(('808850989053853006', 'Read Jujutsu Kaisen Manga Online', 'https://ww6.readjujutsukaisen.com', False), (
        ('Jujutsu Kaisen', '/manga/jujutsu-kaisen/'),
        ('Jujutsu Kaisen 0', '/manga/jujutsu-kaisen-0/'),
        ('JJK Colored', '/manga/jujutsu-kaisen-colored/'),
        ('Fan Scan', '/manga/jujutsu-kaisen-fan-scan/'),
        ('JJK Light Novel', '/manga/jujutsu-kaisen-first-light-novel/'),
        ('2nd Light Novel', '/manga/jujutsu-kaisen-second-light-novel/'),
        ('No.9', '/manga/no-9/'),
        ('Fanbook', '/manga/jujutsu-kaisen-official-fanbook/'),
    )),
    MangaCatalog(('7952360835727640966', 'Read Kingdom Manga Online', 'https://ww6.readkingdom.com', False), (
        ('Kingdom', '/manga/kingdom/'),
        ('Li Mu', '/manga/li-mu/'),
        ('Meng Wu & Chu Zi', '/manga/meng-wu-and-chu-zi-one-shot/'),
    )),
    MangaCatalog(('3945031984510180731', 'Read Nanatsu no Taizai 7 Deadly Sins Manga Online', 'https://ww8.read7deadlysins.com', False), (
        ('Four Horsemen of the Apocalypse', '/manga/four-horsemen-of-the-apocalypse/'),
        ('7DS: School', '/manga/mayoe-nanatsu-no-taizai-gakuen/'),
        ('7DS:7 Days', '/manga/nanatsu-no-taizai-seven-days/'),
        ('7DS:Vampires', '/manga/nanatsu-no-taizai-vampires-of-edinburgh/'),
        ('Queen of Altar', '/manga/the-queen-of-the-altar/'),
        ('7DS: 7 Colors', '/manga/nanatsu-no-taizai-nanairo-no-tsuioku/'),
        ('7DS x FT', '/manga/fairy-tail-x-nanatsu-no-taizai-christmas-special/'),
        ('Kongou Banchou', '/manga/kongou-banchou/'),
        ('7DS:7 Scars', '/manga/nanatsu-no-taizai-the-seven-scars-which-they-left-behind/'),
        ('7 Deadly Sins', '/manga/nanatsu-no-taizai/'),
        ('Mokushiroku no Yonkishi', '/manga/four-horsemen-of-the-apocalypse/'),
    )),
    MangaCatalog(('1061544757733451419', 'Read One Piece Manga Online', 'https://ww13.readonepiece.com', False), (
        ('One Piece', '/manga/one-piece/'),
        ('Colored', '/manga/one-piece-digital-colored-comics/'),
        ('Soma x Sanji', '/manga/shokugeki-no-sanji-one-shot/'),
        ('OP x Toriko', '/manga/one-piece-x-toriko/'),
        ('Party', '/manga/one-piece-party/'),
        ('DB x OP', '/manga/dragon-ball-x-one-piece/'),
        ('Wanted!', '/manga/wanted-one-piece/'),
        ("Ace's Story", '/manga/one-piece-ace-s-story/'),
        ('Omake', '/manga/one-piece-omake/'),
        ('Vivre Card', '/manga/vivre-card-databook/'),
        ('Pirate Recipes', '/manga/one-piece-pirate-recipes/'),
        ('Databook', '/manga/one-piece-databook/'),
        ("Ace's Story Manga", '/manga/one-piece-ace-story-manga/'),
        ('OP Academy', '/manga/one-piece-academy/'),
        ('MONSTERS', '/manga/monsters/'),
        ('Zoro Novel', '/manga/one-piece-novel-zoro/'),
        ('OP in Love', '/manga/one-piece-in-love/'),
        ('Heroines', '/manga/one-piece-novel-heroines/'),
    )),
    MangaCatalog(('8254209929759906152', 'Read One-Punch Man Manga Online', 'https://ww7.readopm.com', False), (
        ('One Punch Man', '/manga/one-punch-man/'),
        ('Official', '/manga/one-punch-man-official/'),
        ('Onepunch-Man (ONE)', '/manga/onepunch-man-one/'),
        ('Colored', '/manga/one-punch-man-colored/'),
        ('Mob Psycho 100', '/manga/mob-psycho-100/'),
        ('Reigen', '/manga/reigen/'),
        ('Versus (ONE)', '/manga/versus/'),
        ('Bug Ego', '/manga/bug-ego/'),
        ('Eyeshield 21', '/manga/eyeshield-21/'),
    ), layout='opm'),
    MangaCatalog(('1374366734159205648', 'Read Solo Leveling Manga Manhwa Online', 'https://ww4.readsololeveling.org', False), (
        ('Solo Leveling Manhwa', '/manga/solo-leveling/'),
        ('Solo Leveling Light Novel', '/manga/solo-leveling-light-novel/'),
        ('Solo Leveling : Ragnarok', '/manga/solo-leveling-ragnarok/'),
        ('SL: Ragnarok Novel', '/manga/solo-leveling-ragnarok-novel/'),
    )),
    MangaCatalog(('6468833665354206027', 'Read Tokyo Ghoul Re & Tokyo Ghoul Manga Online', 'https://ww12.tokyoghoulre.com', False), (
        ('Tokyo Ghoul', '/manga/tokyo-ghoul/'),
        ('Tokyo Ghoul Jack', '/manga/tokyo-ghoul-jack/'),
        ('Tokyo Ghoul: re Colored', '/manga/tokyo-ghoulre-colored/'),
        ('Gorilla', '/manga/this-gorilla-will-die-in-1-day/'),
        ('Zakki', '/manga/tokyo-ghoul-zakki/'),
        ('Light Novel', '/manga/tokyo-ghoul-re-light-novels/'),
        ('Choujin X', '/manga/choujin-x/'),
        ('Tokyo Ghoul re', '/manga/tokyo-ghoulre/'),
    )),
    MangaCatalog(('7174981474350393136', 'Tower Of God Manga Online', 'https://w85.thetowerofgod.com', False), (
        ('Tower of God', '/'),
    ), layout='tower'),
)

ENABLED = {
    '8930801332831394412',  # Attack on Titan
    '1330793582354406642',  # Fairy Tail / Edens Zero
    '808850989053853006',   # Jujutsu Kaisen
    '7952360835727640966',  # Kingdom
    '3945031984510180731',  # Seven Deadly Sins
    '1061544757733451419',  # One Piece
    '1374366734159205648',  # Solo Leveling
    '6468833665354206027',  # Tokyo Ghoul
    '7174981474350393136',  # Tower of God
}
ACTIVE_SOURCES = tuple(source for source in SOURCES if source.SOURCE_ID in ENABLED)
