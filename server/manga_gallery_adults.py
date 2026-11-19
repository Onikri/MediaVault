"""Public gallery HTML protocols adapted from the pinned GalleryAdults multisrc."""

from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit, urlunsplit

from manga_madara import SEGMENT, image_url, node_text
from manga_series_port import Meta, SeriesPort, picture
from manga_webcomics import param, query_url
from source_parser import SourceError


LANGUAGES = {'all': '', 'en': 'english', 'ja': 'japanese', 'zh': 'chinese', 'ko': 'korean',
             'es': 'spanish', 'fr': 'french', 'de': 'german', 'ru': 'russian'}
EXTENSIONS = {'j': 'jpg', 'p': 'png', 'g': 'gif', 'b': 'bmp', 'w': 'webp'}
PAGE_LIMIT = 1500
IMAGE_FIELDS = ('data-src', 'data-original', 'data-lazy-src', 'data-cfsrc')
READER_IMAGE = 'img#gimg, img#fimg, img#readerImg'
# A gallery whose image list is only on its per-page reader pages: the chapter
# lists page markers and each image is resolved when that page is loaded (as the
# extension does), instead of fetching every reader page before the first one.
PAGE_MARKER = 'mv_gallery_page'


@dataclass(frozen=True)
class Layout:
    cards: str = 'div.thumb'
    anchor: str = '.inner_thumb a'
    label: str = '.caption'
    cover: str = '.inner_thumb img'
    details: str = '.gallery_top'
    detail_cover: str = '.cover img'
    tags: str = 'a[href*="/tag/"]'
    preview: str = '.gallery_thumb img'
    count: str = 'input#load_pages[value]'
    page_id: str = 'input#gallery_id[value]'
    id_prefix: str = 'gallery'
    page_prefix: str = 'g'
    search_key: str = 'q'
    language_flag: str = 'a[href*="/language/"]'
    lang_attr: str = ''
    per_page: bool = False
    tag_index: str = 'a.tag_btn[href]'
    server_prefix: str = 'm'
    latest_all: bool = True


LAYOUTS = {
    'asmhentai': Layout('.preview_item', '.image a', cover='.image img', details='.book_page',
                       tags='.tags a[href*="/tag/"]', preview='.preview_thumb img', count='input#t_pages[value]',
                       page_id='input#load_id[value]', id_prefix='g', page_prefix='gallery',
                       language_flag='a:has(.flag)', tag_index='.tags_page .tags a.tag[href]', latest_all=False),
    'hentaienvy': Layout('.hnv-gallery-card', 'a.hnv-gallery-card__cover', '.hnv-gallery-card__title',
                         'a.hnv-gallery-card__cover img', '.hnv-gallery-details', '.hnv-gallery-cover img',
                         'a.hnv-gallery-tag[href*="/tag/"]', count='[data-total-pages]', page_id='[data-gallery-id]',
                         language_flag='.hnv-gallery-card__flag', search_key='key', per_page=True,
                         tag_index='ul.hnv-legacy-taxonomy__items a[href]', latest_all=False),
    'hentaiera': Layout(label='.gallery_title', details='.gallery_first', detail_cover='.left_cover img',
                         tags='a.tag[href*="/tag/"]', preview='.gthumb img', page_prefix='view',
                         language_flag='a:has(.g_flag)'),
    'hentaifox': Layout(tags='ul.tags a', lang_attr='data-languages', latest_all=False),
    'hentairox': Layout('article.hr-gallery-card', '.hr-gallery-card__cover', '.hr-gallery-card__title',
                        '.hr-gallery-card__media img', '.hr-gallery-overview', '.hr-gallery-cover img',
                        '.hr-gallery-tag[href*="/tag/"]', count='#js-thumbs-grid[data-total-pages]',
                        language_flag='.hr-gallery-card__flag', search_key='key', tag_index='article.hr-taxonomy-card a[href]'),
    'hentaizap': Layout('.hz-gallery-card', '.hz-gallery-card__cover', '.hz-gallery-card__title a',
                        '.hz-gallery-card__media.thumb img', '.hz-gallery-details', '.hz-gallery-cover img',
                        'a.hz-gallery-tag[href*="/tag/"]', count='[data-total-pages]', page_id='[data-gallery-id]',
                        language_flag='.hz-gallery-card__flag', search_key='key', per_page=True,
                        tag_index='ul.hz-legacy-taxonomy__items a[href]'),
    'imhentai': Layout(details='.gallery_first', detail_cover='.left_cover img', tags='a.tag[href*="/tag/"]',
                       preview='.gthumb img', page_prefix='view', language_flag='a:has(.thumb_flag)'),
    'nhentaito': Layout('.gallery a:not([rel~=sponsored])', '', cover='img', details='#bigcontainer',
                        detail_cover='#cover img', tags='#info-block .tags a[href*="/tag/"]',
                        preview='#thumbnail-container .thumb-container img', count='#info-block .field-name:-soup-contains("Pages") .tags .name',
                        id_prefix='g', server_prefix='i'),
    'nhentaixxx': Layout('.galleries_box .gallery_item, .fav_item', 'a[href]', cover='img', id_prefix='g',
                         tags='.tags a.tag_btn[href*="/tag/"]', search_key='key', lang_attr='data-languages', server_prefix='i'),
}


def info_value(doc, selector):
    node = doc.select_one(selector)
    return (node.get('value') or node.get('data-total-pages') or node.get('data-gallery-id') or node_text(node)) if node else ''


def numbered(value, maximum=PAGE_LIMIT):
    match = re.search(r'\d{1,6}', value or '')
    return int(match[0]) if match and 1 <= int(match[0]) <= maximum else None


def thumbnail_full(value):
    url = urlsplit(value)
    return urlunsplit(url._replace(path=re.sub(r'(?<=\d)t(?=\.(?:jpg|jpeg|png|webp|gif|bmp)$)', '', url.path, flags=re.I)))


class GalleryAdults(SeriesPort):
    def __init__(self, identity, package):
        spec = LAYOUTS[package]
        path = rf'/{spec.id_prefix}/([0-9]{{1,14}})(?:/{SEGMENT})?/?'
        super().__init__(identity, path, path, interval=.35)
        self.layout, self.package = spec, package
        self.language = LANGUAGES[self.LANGUAGE]
        self.meta = Meta(
            f'{spec.details} h1, #info h1, h1', spec.detail_cover, f'{spec.details} .description',
            f'{spec.details} h2, {spec.details} .subtitle',
            f'{spec.details} a[href*="/category/"]', spec.tags,
            f'{spec.details} a[href*="/artist/"], {spec.details} a[href*="/group/"]',
        )

    def title_url(self, number):
        return f'{self.ROOT}/{self.layout.id_prefix}/{number}/'

    def stored_title(self, url):
        key = self.title_key(url)
        return self.title_url(key) if key else ''

    def saved_title_url(self, url):
        return self.stored_title(self.canonical(url))

    def saved_chapter(self, row, root, title):
        url = super().saved_chapter(row, root, title)
        bare = self.stored_title(url)
        if not bare:
            path = urlsplit(url).path
            match = re.fullmatch(rf'/{self.layout.page_prefix}/([0-9]{{1,14}})/\d+/?', path)
            bare = self.title_url(match[1]) if match else ''
        return query_url(bare, mv_gallery=1) if bare else ''

    def browse_url(self, page, query, sort, tag):
        popular = sort != 'updated'
        if self.package == 'nhentaito':
            return query_url(self.ROOT + '/search', q=' '.join(filter(None, (query, f'tag:{tag}' if tag else ''))) or '*',
                             lang=self.language, sort='relevance' if query else 'most-favorited' if popular else 'newest', page=page)
        if query or tag:
            if tag and not query:
                root = self.ROOT + '/tag/' + tag + '/'
                return root + f'pag/{page}/' if self.package == 'hentaifox' else query_url(root, page=page)
            if self.package == 'hentaifox':
                text = ' '.join(filter(None, (query, self.language)))
                text = re.sub(r'[^a-zA-Z0-9"]+(?=[a-zA-Z0-9"])', ' ', text)
            else:
                text = ','.join(filter(None, (tag, query)))
            return query_url(self.ROOT + '/search/', **{self.layout.search_key: text, 'page': page})
        if self.package in {'hentairox', 'hentaiera', 'nhentaixxx'} and not self.language and (popular or self.package == 'hentairox'):
            return query_url(self.ROOT + '/search/', **({'sort': 'popular', 'page': page} if popular else {'page': page}))
        root = self.ROOT + (f'/language/{self.language}/' if self.language else '/')
        if popular and (self.language or self.layout.latest_all):
            root += 'popular/'
        if self.package == 'hentaifox':
            return root + ('page' if root == self.ROOT + '/' and page == 2 else 'pag') + f'/{page}/'
        return query_url(root, page=page)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if tag and not re.fullmatch(SEGMENT, tag):
            raise SourceError('Некорректный тег галереи.')
        doc, final = self.document(http, self.browse_url(page, query, sort, tag))
        rows = {}
        s = self.layout
        for card in doc.select(s.cards):
            link = card.select_one(s.anchor) if s.anchor else card
            url = self.site_link(link.get('href'), final) if link else ''
            key = self.title_key(url)
            label = node_text(card.select_one(s.label)) or (link.get('title', '') if link else '')
            if not key or not label:
                continue
            flag = card.select_one(s.language_flag)
            languages = (card.get(s.lang_attr, '') if s.lang_attr else flag.get('href', '') if flag else '').casefold()
            if s.lang_attr:
                ids = {'1': 'english', '5': 'japanese', '6': 'chinese', '11': 'korean'} if self.package == 'hentaifox' else {
                    '1': 'english', '2': 'japanese', '3': 'chinese'}
                declared = [ids.get(value, 'other') for value in languages.split()]
            else:
                declared = [lang for lang in LANGUAGES.values() if lang and re.search(rf'\b{lang}\b', languages)]
            if self.language and declared and self.language not in declared:
                continue
            rows[key] = self.record(self.title_url(key), label, picture(card.select_one(s.cover), final, IMAGE_FIELDS))
        more = bool(doc.select_one('.pagination li.active + li:not(.disabled), a[rel=next], a.next'))
        return list(rows.values()), more

    def vocabulary(self, http):
        if self.package == 'nhentaito':
            return []
        doc, final = self.document(http, self.ROOT + '/tags/popular/')
        result = {}
        for a in doc.select(self.layout.tag_index):
            slug = urlsplit(self.site_link(a.get('href'), final)).path.rstrip('/').rsplit('/', 1)[-1]
            name = node_text(a.select_one('.list_tag, .tag_name')) or node_text(a)
            if name and re.fullmatch(SEGMENT, slug):
                result[slug] = {'label': name, 'sourceId': slug, 'category': 'tag'}
        return list(result.values())

    def metadata(self, doc, url, spec):
        record = super().metadata(doc, url, spec)
        record['status'] = 'completed'
        record['adult'] = True
        return record

    def inspect(self, value, http):
        target = self.canonical(value)
        title = self.stored_title(target)
        if not title:
            raise SourceError('Некорректная ссылка на галерею.')
        doc, final = self.title_document(http, title)
        row = self.metadata(doc, title, self.meta)
        chapter = self.chapter(query_url(title, mv_gallery=1), 'Галерея', 1)
        pages = []
        if param(target, 'mv_gallery') == '1':
            pages = self.pages(doc, final, http)
            if not pages or not all(pages) or len(pages) > PAGE_LIMIT:
                raise SourceError('Источник не предоставил полный список страниц галереи.')
        return self.reader_result(row, query_url(title, mv_gallery=1) if pages else title, [chapter], pages)

    def page_headers(self, value):
        return {'Referer': self.stored_title(self.site_link(value))}

    def page_url(self, gallery, index):
        return f'{self.ROOT}/{self.layout.page_prefix}/{gallery}/{index}/'

    def reader_pages(self, http, gid, count):
        return [self.page_url(gid, index) + '#' + PAGE_MARKER for index in range(1, count + 1)]

    def is_reader_page(self, url):
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname == self.hostname and not parts.query
                and bool(re.fullmatch(rf'/{re.escape(self.layout.page_prefix)}/[0-9]{{1,14}}/[1-9][0-9]{{0,3}}/', parts.path)))

    def reader_image(self, http, url):
        target = url.split('#', 1)[0]
        doc, final = self.document(http, target)
        if urlsplit(final).path.rstrip('/') != urlsplit(target).path.rstrip('/'):
            raise SourceError('Читалка переадресовала запрос на другую страницу.')
        image = picture(doc.select_one(READER_IMAGE), final, IMAGE_FIELDS)
        if not image:
            raise SourceError('Читалка галереи не предоставила изображение страницы.')
        return image

    def manifest_images(self, doc, final):
        for script in doc.select('script'):
            text = script.string or ''
            raw = re.search(r"""\$\.parseJSON\(\s*'([^']{1,150000})'\s*\)""", text)
            if not raw:
                continue
            try:
                data = json.loads(raw[1])
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get('fl'), dict):
                data = data['fl']
            if (not isinstance(data, dict) or not 1 <= len(data) <= PAGE_LIMIT or
                    any(not re.fullmatch(r'[1-9]\d{0,3}', key) for key in data) or
                    sorted(map(int, data)) != list(range(1, len(data) + 1))):
                continue
            directory = info_value(doc, 'input#load_dir[value]')
            identity = info_value(doc, 'input#load_id[value]')
            if not re.fullmatch(r'[\w-]{1,100}', directory) or not re.fullmatch(r'[\w-]{1,100}', identity):
                continue
            server = info_value(doc, 'input#load_server[value]')
            host = f'{self.layout.server_prefix}{server}.{self.hostname}' if re.fullmatch(r'\d{1,4}', server) else urlsplit(
                picture(doc.select_one(self.layout.detail_cover), final, IMAGE_FIELDS)).hostname
            if not host:
                continue
            result = []
            for key, item in sorted(data.items(), key=lambda pair: int(pair[0])):
                suffix = str(item).split(',')[0]
                ext = EXTENSIONS.get(suffix, 'jpg')
                result.append(image_url(f'https://{host}/{directory}/{identity}/{key}.{ext}', final))
            return result
        return []

    def rox_pages(self, http, gid):
        target = self.page_url(gid, 1)
        doc, final = self.document(http, target)
        manifest = doc.select_one('script#readerPagesJson')
        image = picture(doc.select_one('img#readerImg'), final, IMAGE_FIELDS)
        try:
            data = json.loads(manifest.string) if manifest and image else []
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list) or not data:
            return []
        result = {}
        root = image.rsplit('/', 1)[0]
        for item in data:
            idx = item.get('page') if isinstance(item, dict) else None
            ext = item.get('ext') if isinstance(item, dict) else None
            if type(idx) is not int or not 1 <= idx <= PAGE_LIMIT or ext not in {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}:
                raise SourceError('Источник предоставил некорректную нумерацию страниц.')
            result[idx] = f'{root}/{idx}.{ext}'
        return [result[i] for i in sorted(result)]

    def pages(self, doc, final, http):
        spec = self.layout
        gallery = info_value(doc, spec.page_id)
        key = self.title_key(final)
        gid = gallery if gallery.isdecimal() else key
        count = numbered(info_value(doc, spec.count))
        if self.package == 'hentairox':
            return self.rox_pages(http, gid)
        if pages := self.manifest_images(doc, final):
            if count is None or count == len(pages):
                return pages
        previews = [picture(node, final, IMAGE_FIELDS) for node in doc.select(spec.preview)]
        if not spec.per_page and previews and all(previews) and (not count or len(previews) >= count):
            return [thumbnail_full(value) for value in (previews[:count] if count else previews)]
        if count:
            return self.reader_pages(http, gid, count)
        return []


def sources():
    from manga_third_batch_profiles import GALLERY

    return tuple(GalleryAdults(identity, package) for package, identity in GALLERY)


def reader_page(value):
    """(adapter, page URL) for a deferred gallery page marker, or an error."""
    import manga_native_registry

    parts = urlsplit(value)
    if parts.fragment != PAGE_MARKER:
        raise SourceError('Некорректная страница галереи.')
    for adapter in dict(manga_native_registry.profiles()).values():
        if isinstance(adapter, GalleryAdults) and adapter.is_reader_page(value):
            return adapter, value.split('#', 1)[0]
    raise SourceError('Некорректная страница галереи.')
