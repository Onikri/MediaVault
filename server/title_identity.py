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
    text=re.sub(r'\s+все серии(?: и сезоны)?\s*$', '',text)
    # Release counters are decoration, not part of the work's title. Removing
    # only the trailing published counter keeps numbered sequels distinct.
    text=re.sub(r'\s*\[\s*\d+[^\]]*(?:из|серия|серий|эпизод)[^\]]*\]\s*$', '',text)
    text=re.sub(r'\([^)]*(?:серий|эпизод|озвуч|субтит|20\d\d|19\d\d)[^)]*\)', '',text)
    text=re.sub(r'\(\s*(?:фильм|movie|ova|ona)\s*\)', '',text)
    text=re.sub(r'(?:\d+(?:st|nd|rd|th)?\s*(?:-?й\s*)?(?:сезон|season)|(?:сезон|season|tv|тв|part)\s*[-:]?\s*\d+)','',text)
    return normalized(re.sub(r'\s+\d{1,2}\s*$','',text))


def counterless(value):
    """The name without a trailing published-episode counter («[1-24 из 24]»)."""
    return normalized(re.sub(r'\s*\[\s*\d+[^\]]*(?:из|серия|серий|эпизод)[^\]]*\]\s*$', '', str(value or '')))


def match_title(selected, candidate, *, year_slack=0):
    wanted,found=aliases(selected),aliases(candidate)
    if not wanted or not found:return False,'missing_title'
    left,right=selected.get('ids') or {},candidate.get('ids') or {}
    for namespace in ('mal','shikimori','anilist','kitsu','imdb'):
        if left.get(namespace) and right.get(namespace):
            return (True,'external_id') if str(left[namespace])==str(right[namespace]) else (False,'different_id')
    if selected.get('kind') and candidate.get('kind') and selected['kind']!=candidate['kind']:
        return False,'different_kind'
    if selected.get('year') and candidate.get('year') and str(selected['year'])[:4]!=str(candidate['year'])[:4]:
        try:gap=abs(int(str(selected['year'])[:4])-int(str(candidate['year'])[:4]))
        except ValueError:gap=None
        if not year_slack or gap is None or gap>year_slack:
            return False,'different_year'
        # A neighbouring year (a TV season across New Year, another catalogue's
        # premiere date) is the same work only under the very same name:
        # a «(фильм)», «2 сезон» or subtitle variant still needs the exact year.
        if any(counterless(a) and counterless(a)==counterless(b) for a in wanted for b in found):
            return True,'exact_title_near_year'
        return False,'different_year'
    for a in wanted:
        for b in found:
            if normalized(a)==normalized(b):return True,'exact_title'
            if len(base_title(a))>=4 and base_title(a)==base_title(b) and season_of(a)==season_of(b):
                return True,'title_and_season'
    # «Sagurare Otome THE ANIMATION» and «Sagurare Otome» name one adaptation:
    # the suffix marks a game's or manga's anime, never another work. Numbered
    # sequels keep their number («… 2 The Animation» is not «… The Animation»).
    for a in wanted:
        for b in found:
            stem_a,stem_b=animation_stem(a),animation_stem(b)
            if (stem_a!=normalized(a) or stem_b!=normalized(b)) and len(stem_a)>=6 and stem_a==stem_b:
                return True,'title_without_animation'
    # Light-novel titles are often listed by sites without their long subtitle
    # ("Main title: I can also ..."). A long enough headline is the same work;
    # short ones ("Атака титанов: Финал") stay distinct. Year/ID checks above
    # and the post-inspection verification still apply.
    heads=lambda values:[h for h in (headline(v) for v in values) if h]
    for a,b in [(x,y) for x in heads(wanted) for y in found]+[(x,y) for x in wanted for y in heads(found)]:
        if normalized(a)==normalized(b) or base_title(a)==base_title(b) and season_of(a)==season_of(b):
            return True,'headline'
    return False,'different_title_or_season'


def without_animation(value):
    """The name without a trailing «(The) Animation» marker."""
    return re.sub(r'[\s\-–—:~]*\b(?:the\s+)?animation\s*$','',str(value or '').strip(),flags=re.I)


def animation_stem(value):
    return normalized(without_animation(value))


def headline(value):
    text=str(value or '').strip()
    head=re.split(r'\s*[:：]\s+|\.\s+(?=\S)',text,maxsplit=1)[0].strip(' .')
    if head==text.strip(' .') or len(head.split())<4 or len(normalized(head))<20:return ''
    return head
