"""Senkognito's public reader GraphQL operations, based on Keiyoushi Senkuro (Apache-2.0)."""
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from source_parser import PublicHttp, SourceError, public_url

ROOT='https://senkognito.com'
API='https://api.senkognito.com/graphql'
SLUG=r'[A-Za-z0-9_-]{1,200}'
ID=r'[A-Za-z0-9_-]{1,120}'
NAMES='titles{lang content} originalName{lang content} alternativeNames{lang content}'
QUERIES={
    'search':f'query($q:String){{mangaTachiyomiSearch(query:$q){{mangas{{id slug {NAMES} cover{{original{{url}}}}}}}}}}',
    'details':f'query($m:ID!){{mangaTachiyomiInfo(mangaId:$m){{id slug {NAMES}}}}}',
    'chapters':'query($m:ID!){mangaTachiyomiChapters(mangaId:$m){chapters{id name number volume teamIds} teams{id name}}}',
    'pages':'query($m:ID!,$c:ID!){mangaTachiyomiChapterPages(mangaId:$m,chapterId:$c){pages{url}}}',
}


def _api(operation, variables, http):
    def validate(url):
        if url!=API:raise SourceError('Неизвестный адрес API Senkognito.')
        return public_url(url,allow_api=True)
    client=PublicHttp(validate=validate,timeout=http.timeout,deadline=http.deadline)
    try:
        text,_,_=client.document(API,method='POST',action='senkognito-read',
            headers={'Accept':'application/json','Content-Type':'application/json','Referer':ROOT+'/'},
            data=json.dumps({'query':QUERIES[operation],'variables':variables}).encode())
        value=json.loads(text)
        if not isinstance(value.get('data'),dict) or value.get('errors'):
            raise SourceError('Senkognito не предоставил открытые данные читалки.')
        return value['data']
    except (ValueError,AttributeError):
        raise SourceError('Senkognito изменил формат ответа.') from None
    finally:
        client.close()


def _names(item):
    values=[*(item.get('titles') or []),item.get('originalName'),*(item.get('alternativeNames') or [])]
    values=[v for v in values if isinstance(v,dict) and isinstance(v.get('content'),str) and v['content'].strip()]
    values.sort(key=lambda v:str(v.get('lang')).lower() not in {'ru','russian'})
    return list(dict.fromkeys(v['content'].strip()[:300] for v in values))


def _matches(query, http):
    result=_api('search',{'q':query[:160]},http).get('mangaTachiyomiSearch') or {}
    return [item for item in (result.get('mangas') or [])[:40]
            if isinstance(item,dict) and re.fullmatch(SLUG,str(item.get('slug',''))) and re.fullmatch(ID,str(item.get('id','')))]


def search(query, http):
    results=[]
    for item in _matches(query,http):
        names=_names(item)
        if not names:continue
        url=ROOT+'/manga/'+item['slug']+'?'+urlencode({'mv_id':item['id']})
        cover=((item.get('cover') or {}).get('original') or {}).get('url') or ''
        try:cover=public_url(cover,resolve_dns=False) if cover else ''
        except SourceError:cover=''
        results.append({'provider':'senkognito','providerName':'Senkognito','title':names[0],'aliases':names,
                        'kind':'manga','language':'ru','format':'manga','url':url,'cover':cover})
    return results


def inspect(url,http):
    from manga_catalog_adapters import result
    from manga_sources import chapter_number
    parsed=urlsplit(url);route=re.fullmatch(r'/manga/('+SLUG+r')/?',parsed.path)
    if parsed.scheme!='https' or parsed.hostname!='senkognito.com' or not route:
        raise SourceError('Нужна ссылка на мангу Senkognito.')
    params=parse_qs(parsed.query);identity=params.get('mv_id',[''])[0];selected=params.get('mv_chapter',[''])[0]
    if not identity:
        identity=next((row['id'] for row in _matches(route[1].replace('-',' '),http) if row['slug']==route[1]),'')
    if not re.fullmatch(ID,identity) or selected and not re.fullmatch(ID,selected):
        raise SourceError('Не удалось подтвердить идентификатор манги или главы Senkognito.')
    item=_api('details',{'m':identity},http).get('mangaTachiyomiInfo') or {}
    if item.get('slug')!=route[1] or item.get('id')!=identity:
        raise SourceError('Senkognito вернул данные другого тайтла.')
    names=_names(item);chapters=[];pages=[]
    data=_api('chapters',{'m':identity},http).get('mangaTachiyomiChapters') or {}
    rows=data.get('chapters') or []
    teams={row['id']:row['name'] for row in data.get('teams') or []}
    for row in rows[:1500]:
        cid=str(row.get('id') or '')
        if not re.fullmatch(ID,cid) or selected and cid!=selected:continue
        try:number=chapter_number(row.get('number'))
        except SourceError:continue
        volume=str(row.get('volume') or '1')
        chapters.append({'number':number,'season':max(1,int(volume)) if volume.isdigit() else 1,
                         'title':row.get('name') or 'Глава '+str(number),'language':'ru',
                         'translator':', '.join(teams[team] for team in (row.get('teamIds') or []) if team in teams),
                         'url':ROOT+parsed.path+'?'+urlencode({'mv_id':identity,'mv_chapter':cid})})
    if selected:
        if not chapters:raise SourceError('Выбранная глава отсутствует в Senkognito.')
        source=_api('pages',{'m':identity,'c':selected},http).get('mangaTachiyomiChapterPages') or {}
        pages=[public_url(row['url'],resolve_dns=False) for row in (source.get('pages') or [])[:1500]]
    chapters.sort(key=lambda row:(row['season'],row['number']))
    return {**result('senkognito','Senkognito',names[0] if names else route[1],url,'ru',chapters,pages,len(rows)>1500),'aliases':names}
