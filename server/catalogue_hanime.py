"""The whole HanimeTV catalogue as indexed anime series, one page of series per call.

HanimeTV serves its full catalogue as one JSON feed (hanime_source.load_catalog,
cached for hours), so a crawl downloads it once and pages through the cached
feed. Episodes are grouped into series exactly like the live HanimeTV search,
and each row carries the same identity and link as that search result, so a
library card opens the same title page and our own player.
"""
import re

import hanime_source

# content_catalog.ingest writes at most 100 rows per call and the indexer
# treats a shorter write as an incomplete page.
PAGE = 100
DOMAIN = 'hanime.tv'

_HANGUL = re.compile(r'[가-힯ᄀ-ᇿ㄰-㆏]')
_CJK = re.compile(r'[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]')
_CYRILLIC = re.compile(r'[Ѐ-ӿ]')


def _script(token):
    if _HANGUL.search(token):return 'ko'
    if _CJK.search(token):return 'cjk'
    if _CYRILLIC.search(token):return 'cyr'
    return 'lat'


def alternative_titles(name, episode, search_titles):
    """Alternative titles from the feed's flat search string.

    search_titles is one space-joined string: the episode name, the English and
    romaji titles, then Japanese, Korean, Russian and Chinese titles. Runs of one
    script become separate titles; Latin text keeps only what is not the series
    name itself.
    """
    text = ' '.join(str(search_titles or '').split())
    if episode and text.casefold().startswith(episode.casefold()):text = text[len(episode):]
    runs = []
    for token in text.split():
        script = _script(token)
        if runs and runs[-1][0] == script:runs[-1][1].append(token)
        else:runs.append([script, [token]])
    # A single Latin word after a non-Latin title ("-복수・암흑 Site-") belongs to it.
    merged = []
    for run in runs:
        if run[0] == 'lat' and len(run[1]) == 1 and merged and merged[-1][0] != 'lat':merged[-1][1].extend(run[1])
        else:merged.append(run)
    titles = []
    for script, tokens in merged:
        if script == 'cjk':
            # Japanese and Chinese titles are separated by spaces; a piece that
            # starts with punctuation ("-復讐・闇サイト-") continues the previous one.
            pieces = []
            for token in tokens:
                if pieces and not token[0].isalnum():pieces[-1] += ' ' + token
                else:pieces.append(token)
            titles.extend(pieces)
        elif script == 'lat':
            value = ' '.join(tokens)
            if name:value = re.sub(re.escape(name), ' ', value, flags=re.I)
            titles.append(' '.join(value.split()).strip(' -–—|/:'))
        else:titles.append(' '.join(tokens))
    seen, result = {name.casefold()}, []
    for title in titles:
        if len(re.sub(r'\W+', '', title)) < 2 or len(title) > 120 or title.casefold() in seen:continue
        seen.add(title.casefold());result.append(title)
    return result[:12]


def series_row(name, episodes):
    first = episodes[0]
    url = hanime_source.VIDEO + first['slug']
    year = re.match(r'(\d{4})', str(first.get('released_at') or ''))
    tags = list(dict.fromkeys(tag for row in episodes for tag in row.get('tags') or [] if isinstance(tag, str)))
    # The same identity, link and fields as hanime_source.search and the
    # client's source result ("provider:url"); no providerId, so the title page
    # does not ask a catalogue API that HanimeTV does not have.
    row = {'id': 'hanime:' + url, 'provider': 'hanime', 'kind': 'anime', 'title': name,
           'aliases': alternative_titles(name, first['name'], first.get('search_titles')),
           'url': url, 'sourceUrl': url, 'cover': first.get('cover_url') or first.get('poster_url') or '',
           'episodes': len(episodes), 'tags': tags, 'genres': [], 'age': 18}
    if year:row['year'] = int(year[1])
    return row


def series(rows):
    groups = hanime_source.group_series(rows)
    # A stable order keeps page N the same series while the cached feed lasts.
    return sorted(((name, episodes) for name, episodes in groups.items() if name),
                  key=lambda item: (item[0].casefold(), item[1][0]['slug']))


def catalogue(cursor, http=None):
    page = max(1, int(cursor.get('page', 1)))
    own = http is None
    if own:
        from source_parser import PublicHttp
        http = PublicHttp(timeout=(4, 30))
    try:
        rows = hanime_source.load_catalog(http)
    finally:
        if own:http.close()
    groups = series(rows)
    chunk = groups[(page - 1) * PAGE:page * PAGE]
    return {'rows': [series_row(name, episodes) for name, episodes in chunk],
            'next': {'page': page + 1} if page * PAGE < len(groups) else None, 'total': len(groups)}
