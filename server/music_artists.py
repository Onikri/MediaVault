"""On-demand musician credits from MusicBrainz and Russian Wikipedia, key-free."""
import re,threading,time,unicodedata
from urllib.parse import urlencode,urlsplit,unquote
from metadata_catalog import get_json
from source_parser import SourceError
cache={};lock=threading.Lock();next_request=0
norm=lambda s:re.sub(r'[^\w]','',unicodedata.normalize('NFKC',str(s)).casefold())
def musicbrainz(path,params=None):
    global next_request
    # The public MusicBrainz service requests at most one call per second.
    with lock:
        delay=max(0,next_request-time.monotonic())
        if delay:time.sleep(min(delay,1.1))
        next_request=time.monotonic()+1.05
    return get_json('https://musicbrainz.org/ws/2/'+path,params={**(params or {}),'fmt':'json'})
def artist(name):
    name=name.strip()[:180]
    with lock:hit=cache.get(name)
    if hit and hit[0]>time.monotonic():return hit[1]
    value={'name':name,'description':'','biography':'','links':[],'source':'MusicBrainz'}
    try:
        # Escape the Lucene syntax rather than accepting search operators.
        query=re.sub(r'[+\-!(){}\[\]^"~*?:\\/]',' ',name)
        rows=musicbrainz('artist',{'query':'artist:"'+query+'"','limit':5}).get('artists',[])
        candidate=next((a for a in rows if int(a.get('score',0))>=90 and norm(name) in {norm(a.get('name')),norm(a.get('sort-name')),*[norm(v.get('name')) for v in a.get('aliases',[])]}),None)
        if candidate:
            detail=musicbrainz('artist/'+candidate['id'],{'inc':'url-rels'});value.update({'id':candidate['id'],'name':detail.get('name') or name,'type':{'Group':'Группа','Person':'Исполнитель','Orchestra':'Оркестр','Choir':'Хор'}.get(detail.get('type'),''),'country':detail.get('country',''),'begin':detail.get('life-span',{}).get('begin',''),'end':detail.get('life-span',{}).get('end','')})
            value['links']=[{'name':'MusicBrainz','url':'https://musicbrainz.org/artist/'+candidate['id']}]
            wiki=None
            for relation in detail.get('relations',[]):
                url=relation.get('url',{}).get('resource','');p=urlsplit(url)
                if p.scheme=='https' and p.hostname=='ru.wikipedia.org' and p.path.startswith('/wiki/'):wiki=unquote(p.path[6:])
                if p.scheme=='https' and p.hostname in {'www.wikidata.org','wikidata.org'} and re.fullmatch(r'/wiki/Q\d+',p.path):
                    entity=get_json('https://www.wikidata.org/wiki/Special:EntityData/'+p.path.split('/')[-1]+'.json').get('entities',{}).get(p.path.split('/')[-1],{})
                    value['description']=entity.get('descriptions',{}).get('ru',{}).get('value','');wiki=entity.get('sitelinks',{}).get('ruwiki',{}).get('title') or wiki
            if wiki:
                data=get_json('https://ru.wikipedia.org/w/api.php',params={'action':'query','format':'json','prop':'extracts','exintro':1,'explaintext':1,'titles':wiki});pages=data.get('query',{}).get('pages',{})
                value['biography']=next((v.get('extract','')[:4500] for v in pages.values() if v.get('extract')),'');value['links'].append({'name':'Википедия','url':'https://ru.wikipedia.org/wiki/'+wiki.replace(' ','_')})
    except (SourceError,ValueError,TypeError,KeyError):pass
    with lock:
        if len(cache)>128:cache.clear()
        cache[name]=(time.monotonic()+(86400 if value.get('id') else 120),value)
    return value
def install(app):
    @app.get('/music/artist')
    def musician(name:str=''):
        from fastapi import HTTPException
        if not name.strip() or len(name)>180:raise HTTPException(422,'Укажи имя исполнителя.')
        return artist(name)
