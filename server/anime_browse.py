"""Bounded, key-free anime facets and published entity biographies."""
import re,time,threading
from metadata_catalog import get_json
from source_parser import SourceError

_cache={};_lock=threading.RLock()
def browse(kind,value='',identity='',label='',page=1):
    if kind not in {'genre','year','season','status','studio','person','character'}:raise SourceError('Неизвестный раздел каталога.')
    if identity and not re.fullmatch(r'[1-9]\d{0,11}',identity):raise SourceError('Некорректный идентификатор.')
    page=max(1,min(int(page),100));value=str(value)[:80];label=str(label)[:160]
    key=(kind,value,identity,label,page)
    with _lock:hit=_cache.get(key)
    if hit and hit[0]>time.monotonic():return hit[1]
    params={'limit':24,'page':page,'order':'popularity'};entity={'name':label or value,'description':'','facts':[]}
    provider='shikimori';items=[]
    if kind in {'person','character'}:
        if not identity:raise SourceError('Нужен идентификатор участника или героя.')
        resource='people' if kind=='person' else 'characters'
        try:base=get_json(f'https://shikimori.io/api/{resource}/{identity}')
        except SourceError:base={}
        try:details=get_json(f'https://api.jikan.moe/v4/{resource}/{identity}/full').get('data',{})
        except SourceError:details={}
        if not base and not details:raise SourceError('Сведения об участнике пока недоступны. Повтори позже.')
        entity.update(name=base.get('russian') or label or details.get('name',''),description=base.get('description') or details.get('about') or '',image=(base.get('image') or {}).get('original') or (details.get('images',{}).get('jpg') or {}).get('image_url',''),sourceUrl=details.get('url','') or f'https://shikimori.io/{resource}/{identity}')
        rows=details.get('anime',[]);items=[r.get('anime',{}) for r in rows if r.get('anime',{}).get('mal_id')]
        # Jikan entity anime references are not full catalogue records.
        items=[{'id':r['mal_id'],'name':r.get('title',''),'image':{'original':(r.get('images',{}).get('jpg') or {}).get('image_url','')}} for r in items]
        if not items:items=base.get('animes',[]) or [r['anime'] for r in base.get('works',[]) if r.get('anime')]
        total=len(items);items=items[(page-1)*24:page*24]
        about=re.sub(r'<br\s*/?>','\n',details.get('about') or entity['description'],flags=re.I)
        about=re.sub(r'<[^>]+>|\[/?[a-z][^\]]*\]','',about,flags=re.I)
        for key_,name in [('Age','Возраст'),('Height','Рост'),('Gender','Пол'),('Birthday','День рождения'),('Weight','Вес')]:
            match=re.search(r'(?im)^\s*(?:'+key_+'|'+name+r')\s*[:：]\s*([^\n\r]+)',about)
            if match:
                text=match[1].strip()[:100];entity['facts'].append([name,{'Male':'Мужской','Female':'Женский'}.get(text,text)])
        if details.get('birthday'):entity['facts'].append(['Дата рождения',str(details['birthday'])[:10]])
        elif isinstance(base.get('birth_on'),dict):
            birth=base['birth_on']
            if all(birth.get(k) for k in ('year','month','day')):entity['facts'].append(['Дата рождения',f'{birth["year"]:04}-{birth["month"]:02}-{birth["day"]:02}'])
        if not entity['description'] and kind=='person':
            from anime_biography import biography
            entity.update(biography(base.get('name'),birth=base.get('birth_on')))
        more=page*24<total
    else:
        if kind=='genre':
            if not identity:
                from metadata_helpers import taxonomy_ids
                ids=taxonomy_ids(value,'anime');identity=ids[0] if ids else ''
            if not identity:raise SourceError('Жанр пока не найден в каталоге.')
            params['genre']=identity
        elif kind=='year':
            if not re.fullmatch(r'(?:19|20)\d{2}',value):raise SourceError('Некорректный год.')
            params['season']=value
        elif kind=='season':
            if not re.fullmatch(r'(?:winter|spring|summer|fall)_(?:19|20)\d{2}',value):raise SourceError('Некорректный сезон.')
            params['season']=value
        elif kind=='status':
            if value not in {'released','ongoing','anons'}:raise SourceError('Некорректный статус.')
            params['status']=value
        elif kind=='studio':
            studios=get_json('https://shikimori.io/api/studios') if label else []
            published=next((s for s in studios if str(s.get('id'))==identity),None)
            if not identity and label:
                found=next((s for s in studios if re.sub(r'\W+','',s.get('name','').casefold())==re.sub(r'\W+','',label.casefold())),None)
                if found:identity=str(found['id']);published=found
            if published:entity['name']=published['name']
            if not identity:raise SourceError('Нужен идентификатор студии.')
            params['studio']=identity
            try:
                producers=get_json('https://api.jikan.moe/v4/producers',params={'q':label,'limit':10}).get('data',[]) if label else []
                normalize=lambda s:re.sub(r'\W+','',s.casefold())
                found=next((p for p in producers if any(normalize(t.get('title',''))==normalize(label) for t in p.get('titles',[]))),None)
                if found:
                    p=get_json(f'https://api.jikan.moe/v4/producers/{found["mal_id"]}/full').get('data',{})
                    entity.update(description=p.get('about') or '',sourceUrl=p.get('url',''),image=(p.get('images',{}).get('jpg') or {}).get('image_url',''))
                    if p.get('established'):entity['facts'].append(['Основана',p['established'][:10]])
            except SourceError:pass
            if not entity['description'] and published:
                from anime_biography import biography
                entity.update(biography(published.get('name'),website=published.get('website') or published.get('url') or '',studio=True))
        items=get_json('https://shikimori.io/api/animes',params=params);more=len(items)==24
    result={'provider':provider,'items':items,'entity':entity,'page':page,'hasMore':more}
    with _lock:
        if len(_cache)>256:_cache.clear()
        _cache[key]=(time.monotonic()+3600,result)
    return result
