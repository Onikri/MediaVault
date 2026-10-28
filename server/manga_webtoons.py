"""Public WEBTOON Originals/Canvas reader, without account cookies.

Protocol reference: Keiyoushi extensions-source, Apache-2.0, Webtoons.kt
(blob 9d422e737f17ac4fbf4c50c9aa8c79e48f96298a). No subscription endpoints.
"""
import json
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup
from source_parser import PublicHttp, SourceError, public_url

ROOT = 'https://www.webtoons.com'


def public_api(url):
    p = urlsplit(url)
    if (p.hostname != 'm.webtoons.com' or
            not re.fullmatch(r'/api/v1/(?:webtoon|canvas)/[1-9]\d{0,9}/episodes', p.path)):
        raise SourceError('Адрес не относится к публичному списку глав WEBTOON.')
    return public_url(url, allow_api=True)


def get_episodes(identity, canvas, http):
    url = 'https://m.webtoons.com/api/v1/' + ('canvas' if canvas else 'webtoon') + '/' + identity + '/episodes?'
    url += urlencode({'pageSize': 1500, **({'readingLanguageCode': 'en'} if canvas else {})})
    client = PublicHttp(validate=public_api, timeout=getattr(http, 'timeout', (3, 7)),
                        deadline=getattr(http, 'deadline', time.monotonic() + 25))
    try:
        text, _, _ = client.document(url, headers={'Referer': 'https://m.webtoons.com/'})
        data = json.loads(text)
        if not data.get('success') or not isinstance(data.get('result', {}).get('episodeList'), list):
            raise SourceError('WEBTOON не предоставил публичный список глав.')
        return data['result']['episodeList']
    finally:
        client.close()


def reader_url(url):
    p = urlsplit(public_url(url, resolve_dns=False))
    if (p.hostname not in {'www.webtoons.com', 'm.webtoons.com', 'webtoons.com'} or
            not re.fullmatch(r'/en/[\w-]+/[\w-]+/(?:[\w-]+/)?(?:list|viewer)/?', p.path)):
        raise SourceError('Нужна английская ссылка WEBTOON на тайтл или опубликованную главу.')
    q = parse_qs(p.query)
    identity = q.get('title_no', [''])[0]
    episode = q.get('episode_no', [''])[0]
    if not re.fullmatch(r'[1-9]\d{0,9}', identity) or episode and not re.fullmatch(r'[1-9]\d{0,9}', episode):
        raise SourceError('В ссылке WEBTOON отсутствует номер тайтла или главы.')
    return ROOT + p.path + '?' + urlencode({'title_no': identity, **({'episode_no': episode} if episode else {})})


def search(query, site, http):
    from manga_sources import clean, safe_link
    text, final, _ = http.document(ROOT + '/en/search?' + urlencode({'keyword': query}))
    if urlsplit(final).hostname != 'www.webtoons.com':
        raise SourceError('WEBTOON перенаправил поиск на другой сайт.')
    soup = BeautifulSoup(text, 'html.parser')
    results = {}
    for anchor in soup.select('.webtoon_list li a')[:60]:
        heading, image = anchor.select_one('.title'), anchor.select_one('img')
        if not heading:
            continue
        try:
            url = reader_url(safe_link(anchor.get('href'), final))
        except SourceError:
            continue
        title = clean(heading.get_text(' ', strip=True))
        results[url] = {'provider': site.id, 'providerName': site.name, 'title': title,
                        'aliases': [title], 'url': url, 'language': 'en', 'kind': 'manga',
                        'format': 'webtoon', 'readingMode': 'scroll',
                        'cover': safe_link(image.get('data-src') or image.get('src'), final) if image else ''}
    return list(results.values())


def inspect(url, site, http):
    from manga_sources import clean, safe_link, guard, chapter_number
    from manga_catalog_adapters import result
    url = reader_url(url)
    p = urlsplit(url)
    q = parse_qs(p.query)
    text, final, _ = http.document(url)
    reader_url(final)  # Reject login/age/subscription redirects; never add cookies.
    soup = BeautifulSoup(text, 'html.parser')
    guard(soup)
    heading = soup.select_one('h1.subj,h3.subj,.subj_info .subj,.subj')
    title = clean(heading.get_text(' ', strip=True)) if heading else 'Вебтун'
    cover = soup.select_one('meta[property="og:image"]')
    chapters, pages = [], []
    if q.get('episode_no'):
        pages = list(dict.fromkeys(safe_link(i.get('data-url') or i.get('data-src'), final)
                                  for i in soup.select('#_imageList > img')))
        pages = [v for v in pages if v]
        if not pages:
            raise SourceError('WEBTOON не предоставил открытые страницы. Глава может требовать входа или покупки.')
        label = soup.select_one('.subj_episode')
        label = clean(label.get_text(' ', strip=True)) if label else 'Глава ' + q['episode_no'][0]
        rows = [{'viewerLink': url, 'episodeNo': int(q['episode_no'][0]), 'episodeTitle': label}]
    else:
        rows = get_episodes(q['title_no'][0], p.path.startswith('/en/canvas/'), http)
    for row in rows[:1500]:
        if any(row.get(k) for k in ('locked', 'isLocked', 'charge', 'isPaid', 'paywalled')):
            continue
        try:
            target = reader_url(safe_link(row.get('viewerLink'), ROOT))
            if parse_qs(urlsplit(target).query)['title_no'] != q['title_no']:
                continue
            label = clean(row.get('episodeTitle'))
            season = re.search(r'(?:season|part)\s*(\d{1,3})', label, re.I)
            ordinal = re.search(r'(?:ep(?:isode)?\.?|ch(?:apter)?\.?)\s*(\d{1,4}(?:\.\d{1,3})?)', label, re.I)
            number = chapter_number(ordinal[1] if ordinal else row['episodeNo'])
            chapters.append({'url': target, 'number': number, 'season': int(season[1]) if season else 1,
                             'title': label or 'Глава ' + str(number), 'language': 'en', 'translator': ''})
        except (SourceError, KeyError, TypeError):
            continue
    chapters = sorted({c['url']: c for c in chapters}.values(), key=lambda c: (c['season'], c['number'], c['url']))
    return {**result(site.id, site.name, title, url, 'en', chapters, pages, len(rows) >= 1500),
            'format': 'webtoon', 'readingMode': 'scroll', 'aliases': [title],
            'cover': safe_link(cover.get('content'), final) if cover else ''}
