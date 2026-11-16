"""HTML catalogue and reader routes for Acomics and Yagami Project."""

import re
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from manga_direct_catalogues import Browse, DirectCatalogue, Layout, SERIES, SLUG
from manga_direct_payloads import JsonSeries
from manga_madara import SEGMENT, image_url, node_text, release_date
from manga_series_port import Archive, Cards, MAX_CHAPTERS, MAX_PAGES, Meta, picture
from manga_source_tags import unique
from manga_webcomics import param, query_url
from source_parser import SourceError


ID = r'[1-9]\d{0,8}'
AC_TITLE = rf'/~{SLUG}/about/?'
AC_CHAPTER = rf'/~{SLUG}/{ID}/?'
YAGAMI = 'https://read.yagami.me'
Y_CHAPTER = re.compile(rf'/(?:reader|series|read|chapter)/(?:{SEGMENT}/){{0,5}}{SEGMENT}/?')
Y_CARDS = Cards('.list .group', '.title a[href]', next='.panel_nav .button > a:last-child')
Y_META = Meta('title', '.cover img', '.large.comic .info li:-soup-contains("Описание:")',
              genres='.large.comic .info li:-soup-contains("Жанры:") a',
              status='.large.comic .info li:-soup-contains("Статус перевода:") span')


class Acomics(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, Layout(
            AC_TITLE, AC_CHAPTER, Cards('section.serial-card', 'h2 > a', cover='a > img', next='a.infinite-scroll'),
            Meta('.page-header-with-menu h1', 'article.common-article img.cover', 'section.serial-about-text',
                 genres='p.serial-about-badges a.category', author='p.serial-about-authors a'),
            Archive(''), 'img.issue', Browse('/comics'), title_path='/~', suffix='/about',
        ))

    def saved_title_url(self, value):
        url = self.canonical(value)
        path = urlsplit(url).path
        if re.fullmatch(rf'/~{SEGMENT}/?', path):
            return url.split('?', 1)[0].rstrip('/') + '/about'
        return url

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query and len(query) < 3:
            return [], False
        if query:
            target = self.ROOT + '/search'
            args = [('keyword', query)]
        else:
            target = self.ROOT + '/comics'
            args = [('sort', 'last_update' if sort == 'updated' else 'subscr_count'), ('type', '0'),
                    ('updatable', '0'), ('subscribe', '0'), ('issue_count', '2')]
            args.extend(('ratings[]', rating) for rating in range(1, 6))
            if tag:
                args.append(('categories[]', tag[:120]))
        if page > 1:
            args.append(('skip', (page - 1) * 10))
        doc, final = self.document(http, target + '?' + urlencode(args))
        rows = []
        for card in doc.select(self.layout.cards.rows):
            anchor = card.select_one('h2 > a[href]')
            target = self.site_link(anchor['href'], final) if anchor else ''
            title = node_text(anchor)
            if not target or not title:
                continue
            url = self.saved_title_url(target)
            if self.is_title(url):
                rows.append(self.record(url, title, picture(card.select_one('a > img'), final, ('data-real-src',))))
        return rows, bool(doc.select_one('a.infinite-scroll'))

    def vocabulary(self, http):
        doc, _ = self.document(http, self.ROOT + '/comics')
        rows = {}
        for node in doc.select('select[name="categories[]"] option[value], input[name="categories[]"][value]'):
            label = node_text(node if node.name == 'option' else node.parent)
            key = node['value']
            if label and key and len(key) <= 120:
                rows[key] = {'label': label, 'sourceId': key, 'category': 'genre'}
        return list(rows.values())

    def metadata(self, doc, url, spec):
        row = super().metadata(doc, url, spec)
        row['status'] = 'completed' if doc.select_one('p.serial-about-badges span.completed') else 'ongoing'
        return row

    def chapters(self, http, doc, url):
        node = doc.select_one('p:has(b:-soup-contains("Количество выпусков:"))')
        count = re.search(r'\b\d{1,7}\b', node_text(node))
        if count is None:
            raise SourceError('Acomics не предоставил количество выпусков.')
        base, total = urlsplit(url).path.split('/about', 1)[0], int(count[0])
        return [self.chapter(self.ROOT + base + '/' + str(n), str(n), n)
                for n in range(1, min(total, MAX_CHAPTERS) + 1)], total > MAX_CHAPTERS


class YagamiProject(JsonSeries):
    def __init__(self, identity):
        super().__init__(identity, SERIES, Y_CHAPTER.pattern, interval=.35)

    def is_chapter(self, url):
        return super().is_chapter(url) and bool(self.title_for(url))

    def title_for(self, url):
        parent = param(url, 'mv_parent')
        return self.ROOT + parent if re.fullmatch(SERIES, parent) else ''

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        query = self.catalogue_params(page, query, tag)
        if query:
            path = query_url(self.ROOT + '/reader/search/', s=query, p=page)
        elif tag:
            from manga_direct_payloads import segment
            if not (genre := segment(tag)):
                raise SourceError('Некорректный жанр каталога.')
            path = f'{self.ROOT}/tags/{genre}' + (f'/{page}' if page > 1 else '')
        else:
            path = f'{self.ROOT}/{"latest" if sort == "updated" else "list-new"}/{page}'
        doc, final = self.document(http, path)
        rows = []
        for node in doc.select(Y_CARDS.rows):
            anchor = node.select_one(Y_CARDS.link)
            url = self.site_link(anchor['href'], final) if anchor else ''
            if not self.is_title(url):
                continue
            aliases = unique((anchor.get('title') or node_text(anchor)).split(' / '))
            cover = picture(node.select_one('.cover_mini > img'), final).replace('thumb_', '')
            if aliases:
                rows.append(self.record(url, aliases[0], cover, aliases=aliases))
        return rows, bool(doc.select_one(Y_CARDS.next))

    def parsed_details(self, http, url):
        if not self.is_title(url):
            raise SourceError('Некорректная ссылка на тайтл Yagami.')
        doc, final = self.title_document(http, url)
        detail = self.metadata(doc, final, Y_META)
        names = unique(detail['title'].split(' :: Yagami')[0].split(' :: '))
        if not names:
            raise SourceError('Yagami не предоставил название.')
        detail['title'], detail['aliases'] = names[0], names
        detail['description'] = detail['description'].removeprefix('Описание:').strip()
        fields = {key: node_text(doc.select_one(f'.large.comic .info li:-soup-contains("{label}")')).partition(':')[2].strip()
                  for key, label in (('authors', 'Автор(ы):'), ('artists', 'Художник(и):'))}
        detail.update({key: unique(part for part in value.split(' / ') if part.strip() != 'N/A')
                       for key, value in fields.items()})
        return detail, doc, final

    def details(self, http, url):
        return self.parsed_details(http, self.saved_title_url(url))[0]

    def series(self, http, url):
        detail, doc, final = self.parsed_details(http, url)
        parent = urlsplit(final).path
        chapters = {}
        for node in doc.select('.list .element'):
            anchor = node.select_one('.title a[href]')
            href = self.site_link(anchor['href'], final) if anchor else ''
            if not href or not Y_CHAPTER.fullmatch(urlsplit(href).path):
                continue
            title = anchor.get('title') or node_text(anchor)
            stamp = node.select_one('.meta_r')
            label = node_text(stamp)
            teams = unique(node_text(team) for team in stamp.select('a')) if stamp else []
            target = query_url(href, mv_parent=parent)
            chapters[target] = self.chapter(target, title, date=release_date(label.rsplit(', ', 1)[-1], '%d.%m.%Y'),
                                            translator=' / '.join(teams))
        return detail, self.order(chapters)

    def saved_chapter(self, row, root, title):
        target = super().saved_chapter(row, root, title)
        if Y_CHAPTER.fullmatch(urlsplit(target).path) and self.is_title(title):
            return query_url(target, mv_parent=urlsplit(title).path)
        return ''

    def saved_chapter_matches(self, target, title):
        return self.title_key(title) == self.title_key(self.title_for(target))

    def pages(self, http, url):
        from urllib.parse import parse_qsl, urlunsplit
        parts = urlsplit(url)
        wire = urlunsplit(parts._replace(query=urlencode([(key, value) for key, value in parse_qsl(parts.query)
                                                          if key != 'mv_parent'])))
        doc, final = self.document(http, wire)
        if 'mature contents' in node_text(doc.select_one('.info')).casefold():
            text, target, _ = http.document(wire, method='POST', action='native-series-form',
                                            headers={'Referer': final}, data={'adult': 'true'})
            if target != wire:
                raise SourceError('Yagami перенаправил запрос на другой выпуск.')
            doc = BeautifulSoup(text, 'html.parser')
        if images := doc.select('.web_pictures img.web_img'):
            return [picture(img, final) for img in images]
        parent = urlsplit(final)
        links = {}
        for anchor in doc.select('.dropdown li a[href]'):
            from manga_series_port import label_number
            target = self.site_link(anchor['href'], final)
            parts = urlsplit(target)
            number = label_number(node_text(anchor), re.compile(r'(?:Стр\.\s*)(\d{1,5})'))
            if number is not None and target and (parts.path == parent.path or parts.path.startswith(parent.path.rstrip('/') + '/')):
                links[number] = target
        if len(links) > MAX_PAGES:
            raise SourceError('Слишком много страниц в выпуске Yagami.')
        result = []
        for _, link in sorted(links.items()):
            page, location = self.document(http, link)
            url = picture(page.select_one('#page img'), location)
            if not url or 'string(1)' in url:
                download = page.select_one('#get_download[href]')
                url = image_url(download['href'], location) if download else ''
            result.append(url)
        return result


def public_form(url, data):
    parts = urlsplit(url)
    return (parts.scheme == 'https' and parts.netloc == 'read.yagami.me'
            and not parts.query and Y_CHAPTER.fullmatch(parts.path) is not None and data == {'adult': 'true'})
