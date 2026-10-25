"""Exact-ID Russian labels and free catalogue taxonomy filters."""
import threading
import time
names,lock={},threading.RLock()
taxonomy={}
def taxonomy_ids(label,kind):
    from metadata_catalog import get_json
    if not label:return []
    with lock:values=taxonomy.get('genres')
    if not values:
        try:values=get_json('https://shikimori.io/api/genres')
        except Exception:return []
        with lock:taxonomy['genres']=values
    return [str(x['id']) for x in values if str(x.get('entry_type','')).lower()==kind and label.casefold() in {str(x.get('russian','')).casefold(),str(x.get('name','')).casefold()}]

def localize(provider,value,kind):
    from metadata_catalog import get_json
    if provider=='anilist':
        items=([value['data']['Media']] if value.get('data',{}).get('Media') else value.get('data',{}).get('Page',{}).get('media',[]));pairs=[(str(x.get('idMal')),x) for x in items if x.get('idMal')]
    elif provider=='jikan':
        items=value.get('data',[]);items=items if isinstance(items,list) else [items];pairs=[(str(x['mal_id']),x) for x in items if x.get('mal_id')]
    elif provider=='kitsu':
        mappings={x['id']:x.get('attributes',{}).get('externalId') for x in value.get('included',[]) if x.get('type')=='mappings' and 'myanimelist' in x.get('attributes',{}).get('externalSite','')};items=value.get('data',[]);items=items if isinstance(items,list) else [items]
        pairs=[(str(mappings[r['id']]),x.setdefault('attributes',{})) for x in items for r in x.get('relationships',{}).get('mappings',{}).get('data',[]) if mappings.get(r['id'])]
    else:return value
    with lock:missing=[identity for identity,_ in pairs if names.get((kind,identity),(0,{}))[0]<time.monotonic()]
    if missing:
        try:
            found=get_json('https://shikimori.io/api/'+('mangas' if kind=='manga' else 'animes'),params={'ids':','.join(dict.fromkeys(missing)),'limit':50})
            with lock:
                for x in found:names[(kind,str(x['id']))]=(time.monotonic()+21600,{'title':x.get('russian'),'description':x.get('description')})
                while len(names)>2048:names.pop(next(iter(names)))
        except Exception:pass
    for identity,item in pairs:
        with lock:local=names.get((kind,identity),(0,{}))[1]
        if local.get('title'):
            if provider=='kitsu':item.setdefault('titles',{})['ru_ru']=local['title']
            else:item['russian']=local['title']
    return value
