"""Hentai3z.CC's installed Manga18 layout recovered from the Keiyoushi history."""

from manga_direct_catalogues import DirectCatalogue, MANGA18


class Hentai3z(DirectCatalogue):
    def __init__(self, identity):
        super().__init__(identity, MANGA18)

    def catalogue(self, http, page=1, *, query='', sort='popular', tag=''):
        rows, more = super().catalogue(http, page, query=query, sort=sort, tag=tag)
        for row in rows:
            row['cover'] = row['cover'].replace('cover_thumb_2.webp', 'cover_250x350.jpg').replace(
                '//admin.manga18.us/', '//bk.18porncomic.com/')
        return rows, more
