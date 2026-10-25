"""Conservative title identity: a search hit is a candidate, never proof of a match."""
import re
import unicodedata


def normalized(value):
    return re.sub(r'[^\w]+', '', unicodedata.normalize('NFKC', str(value or '')).casefold().replace('_',''))


def aliases(item):
    values = [item.get('title'), item.get('originalTitle'), item.get('original_title')]
    titles = item.get('titles') or {}
    values.extend(titles.values() if isinstance(titles, dict) else titles)
    values.extend(item.get('aliases') or [])
    result=[]
    for value in values:
        if isinstance(value,str):
            result.extend(part.strip() for part in re.split(r'\s/\s|\s\|\s',value) if len(part.strip())>1)
    return list(dict.fromkeys(result))[:30]


def season_of(value):
    text=str(value).casefold()
    for pattern in [r'(\d+)\s*(?:-?й\s*)?(?:сезон|season)',r'(?:сезон|season|tv|тв)\s*[-:]?\s*(\d+)',r'(\d+)(?:st|nd|rd|th)\s+season',r'\bpart\s+(\d+)']:
        match=re.search(pattern,text)
        if match:return int(match[1])
    match=re.search(r'\s+(\d{1,2})\s*$',text)
    return int(match[1]) if match else 1


def base_title(value):
    text=re.split(r'\s+(?:смотреть|watch)\b',str(value).casefold())[0]
    text=re.sub(r'\([^)]*(?:серий|эпизод|озвуч|субтит|20\d\d|19\d\d)[^)]*\)', '',text)
    text=re.sub(r'(?:\d+(?:st|nd|rd|th)?\s*(?:-?й\s*)?(?:сезон|season)|(?:сезон|season|tv|тв|part)\s*[-:]?\s*\d+)','',text)
    return normalized(re.sub(r'\s+\d{1,2}\s*$','',text))


def match_title(selected, candidate):
    wanted,found=aliases(selected),aliases(candidate)
    if not wanted or not found:return False,'missing_title'
    left,right=selected.get('ids') or {},candidate.get('ids') or {}
    for namespace in ('mal','shikimori','anilist','kitsu','imdb'):
        if left.get(namespace) and right.get(namespace):
            return (True,'external_id') if str(left[namespace])==str(right[namespace]) else (False,'different_id')
    if selected.get('kind') and candidate.get('kind') and selected['kind']!=candidate['kind']:
        return False,'different_kind'
    if selected.get('year') and candidate.get('year') and str(selected['year'])[:4]!=str(candidate['year'])[:4]:
        return False,'different_year'
    for a in wanted:
        for b in found:
            if normalized(a)==normalized(b):return True,'exact_title'
            if len(base_title(a))>=4 and base_title(a)==base_title(b) and season_of(a)==season_of(b):
                return True,'title_and_season'
    return False,'different_title_or_season'
