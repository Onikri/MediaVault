"""Unicode-preserving music identities; never invent transliterations."""
import hashlib,json,math,re,unicodedata

def clean(value):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(value or ''))).strip()[:300]

def name(value):
    return ''.join(c for c in clean(value).casefold() if c.isalnum())

def unique(values):
    return list({name(v):clean(v) for v in values if name(v)}.values())

def version(value):
    value=clean(value).casefold()
    return tuple(v for v in ('instrumental','karaoke','cover','remix','live','slowed','sped','nightcore','tv size','tv-size','short') if v in value)

def identity(titles,artists):
    artist_forms=[]
    for artist in artists:
        artist=re.sub(r'\s*[-–—]\s*Topic$','',clean(artist),flags=re.I)
        artist_forms += [artist,*re.findall(r'[（(]([^）)]+)[）)]',artist),re.sub(r'[（(][^）)]+[）)]','',artist)]
        artist_forms += re.findall(r'[A-Za-z][A-Za-z\s.\'’&-]*|[\u3040-\u30ff\u3400-\u9fffー]+',artist)
    artist_forms=unique(artist_forms)[:8]
    title_forms=[]
    for title in titles:
        title=clean(title).replace('「','').replace('」','').replace('『','').replace('』','')
        title=re.sub(r'\[(?:official[^\]]*|music video|MV|HD|4K)\]|\((?:official[^)]*|music video|MV|HD|4K)\)',' ',title,flags=re.I)
        for _ in range(8):
            old=title
            for artist in sorted(artist_forms,key=len,reverse=True):
                title=re.sub(r'^'+re.escape(artist)+r'(?:\s*[-–—:|/]+\s*|\s+)','',title,flags=re.I)
                title=re.sub(r'(?:\s*[-–—:|/]+\s*|\s+)[(（]?'+re.escape(artist)+r'[)）]?$','',title,flags=re.I)
            title=title.strip(' -–—:|/')
            if title==old:break
        title=re.sub(r'\s*\b(?:official\s+)?(?:music video|video|audio|lyrics|MV|HD|4K)\s*$','',title,flags=re.I).strip()
        parts=re.findall(r'[（(]([^）)]+)[）)]',title)
        # Alternate native/Latin spellings are aliases, version labels are not.
        alternatives=[p for p in parts if not version(p) and bool(re.search(r'[\u3040-\u9fff]',p))!=bool(re.search(r'[\u3040-\u9fff]',title.split('(')[0]))]
        title_forms += [re.sub(r'[（(][^）)]+[）)]','',title).strip() if alternatives else title,*alternatives,title]
    return {'titles':unique(title_forms)[:8],'artists':artist_forms}

def cache_key(query):
    value={'titles':sorted(name(t) for t in query['titles']),'artists':sorted(name(a) for a in query['artists']),
           'duration':round(query['duration'],2),'rich':query.get('rich',True)}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def match(query,title,artist,duration):
    row=identity([title],[artist])
    if not set(map(name,row['titles']))&set(map(name,query['titles'])):return None
    if not set(map(name,row['artists']))&set(map(name,query['artists'])):return None
    if not any(version(t)==version(title) for t in query['titles']):return None
    try:delta=abs(float(duration)-query['duration'])
    except (ValueError,TypeError):return None
    if not math.isfinite(delta) or delta>min(20,max(10,query['duration']*.08)):return None
    return {'timingMismatch':delta>2.5,'delta':delta}
