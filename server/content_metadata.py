"""Bounded discovery using supported genre/subject filters and catalogue pages."""
import re
from urllib.parse import urlencode
from manga_tag_policy import current
from content_catalog import ingest

def english(rule):return next((s for s in rule['aliases'] if re.fullmatch(r'[\x20-\x7e]+',s) and re.search('[a-zA-Z]',s)),rule['label'])

def anilist_rows(payload,kind):
    rows=[]
    for item in payload.get('data',{}).get('Page',{}).get('media',[])[:40]:
        title=item.get('title') or {};name=title.get('english') or title.get('romaji') or title.get('native');identity=item.get('id')
        if not name or not isinstance(identity,int):continue
        rows.append({'id':'anilist:'+str(identity),'provider':'anilist','providerId':str(identity),'kind':kind,'title':name,
                     'aliases':[v for v in title.values() if isinstance(v,str)],'titles':{'en':name,'native':title.get('native','')},
                     'ids':{'anilist':str(identity),**({'mal':str(item['idMal'])} if item.get('idMal') else {})},
                     'sourceUrl':item.get('siteUrl') or 'https://anilist.co/'+('anime' if kind=='anime' else 'manga')+'/'+str(identity),
                     'genres':item.get('genres') or [],'tags':[v['name'] for v in item.get('tags') or [] if isinstance(v,dict) and isinstance(v.get('name'),str)],
                     'cover':(item.get('coverImage') or {}).get('large',''),'year':item.get('seasonYear') or (item.get('startDate') or {}).get('year'),
                     'format':item.get('format') or '', 'description':item.get('description') or ''})
    return rows

def movie_rows(payload,kind):
    rows=[]
    for item in payload.get('data',{}).get('items',[])[:60]:
        identity=str(item.get('id') or '');title=item.get('title') or {};name=title.get('russian')
        if not re.fullmatch(r'\d{1,12}',identity) or not name:continue
        actual='tv' if item.get('type')=='Series' else 'movie'
        if actual!=kind:continue
        rows.append({'id':'kinobox:'+identity,'provider':'kinobox','providerId':identity,'kind':kind,'title':name,
                     'aliases':[v for v in title.values() if isinstance(v,str)],'ids':{'kinopoisk':identity},
                     'sourceUrl':'https://www.kinopoisk.ru/'+('series' if kind=='tv' else 'film')+'/'+identity+'/',
                     'genres':[v['name'] for v in item.get('genres') or [] if isinstance(v,dict) and isinstance(v.get('name'),str)],
                     'tags':[v['name'] for v in item.get('countries') or [] if isinstance(v,dict) and isinstance(v.get('name'),str)],
                     'cover':(item.get('gallery') or {}).get('posterUrl',''),'year':item.get('year'),'description':item.get('synopsis') or ''})
    return rows

def scan(store,keys=None):
    from metadata_catalog import metadata,get_json
    selected=[rule for key,rule in current().rules.items() if key not in current().hidden and (keys is None or key in keys)]
    source_rules=None
    # One bounded first batch per type. Existing facts continue to match all
    # rules, and normal catalogue browsing feeds subsequent source metadata.
    for kind in ('anime','manga','ranobe','movie','tv','book'):
        result={'domain':'metadata:'+kind,'name':{'anime':'Аниме · AniList','manga':'Манга · AniList','ranobe':'Ранобэ · AniList','movie':'Фильмы · Kinobox','tv':'Сериалы · Kinobox','book':'Книги · Open Library'}[kind],'indexed':0,'matched':0,'status':'partial','limited':True}
        try:
            rows=[]
            if kind in {'anime','manga','ranobe'}:
                if source_rules is None:
                    catalogue=get_json('https://graphql.anilist.co',body={'query':'{GenreCollection MediaTagCollection{name}}'}).get('data',{})
                    source_rules=[('genre',name) for name in catalogue.get('GenreCollection',[])]+[('tag',row['name']) for row in catalogue.get('MediaTagCollection',[]) if isinstance(row.get('name'),str)]
                selected_keys={rule['key'] for rule in selected}
                grouped={}
                for field,name in source_rules:
                    key=current().key(name,'anilist.co')
                    if key in selected_keys:grouped.setdefault(key,(field,name))
                matches=list(grouped.values())
                for field,name in matches[:3]:
                    payload=metadata('anilist',kind=kind,**{field:name})
                    rows.extend(anilist_rows(payload,kind))
            elif kind in {'movie','tv'}:rows=movie_rows(metadata('kinobox',kind=kind),kind)
            else:
                for rule in selected[:3]:
                    payload=get_json('https://openlibrary.org/search.json',params={'subject':english(rule),'limit':20,'fields':'key,title,subject,first_publish_year,cover_i'})
                    for item in payload.get('docs',[])[:20]:
                        identity=str(item.get('key') or '').removeprefix('/works/')
                        if not re.fullmatch(r'OL\d{1,12}W',identity) or not item.get('title'):continue
                        rows.append({'id':'openlibrary:'+identity,'provider':'openlibrary','providerId':identity,'kind':'book','title':item['title'],
                                     'ids':{'openlibrary':identity},'sourceUrl':'https://openlibrary.org/works/'+identity,'genres':item.get('subject') or [],'tags':[],
                                     'year':item.get('first_publish_year'),'cover':'https://covers.openlibrary.org/b/id/'+str(item['cover_i'])+'-L.jpg' if isinstance(item.get('cover_i'),int) else ''})
            result['matched']=sum(bool(current().facts(row)['genres'] or current().facts(row)['tags']) for row in rows)
            with store.lock,store.db:result['indexed']=ingest(store.db,rows)
        except Exception:result.update(status='unavailable',reason='Каталог метаданных временно недоступен или не поддерживает выбранный фильтр.')
        yield result
