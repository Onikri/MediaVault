"""Read published JSON hydration; never execute page JavaScript or call site APIs."""
import json
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def hydration(text):
    soup=BeautifulSoup(text,'html.parser');result=[]
    for script in soup.select('script[type="application/json"]')[:12]:
        try:raw=json.loads(script.string or script.get_text())
        except (ValueError,TypeError):continue
        if script.get('id')=='__NUXT_DATA__' and isinstance(raw,list):
            memo={}
            def read(index,depth=0):
                if depth>45:return None
                if not isinstance(index,int) or index<0 or index>=len(raw):return None
                if index in memo:return memo[index]
                value=raw[index]
                if isinstance(value,dict):
                    out={};memo[index]=out
                    for k,v in value.items():out[k]=read(v,depth+1)
                    return out
                if isinstance(value,list):
                    if len(value)==2 and isinstance(value[0],str) and value[0] in {'ShallowReactive','Reactive','Ref','ShallowRef'}:return read(value[1],depth+1)
                    out=[];memo[index]=out;out.extend(read(v,depth+1) for v in value);return out
                return value
            raw=read(0)
        result.append(raw)
    return result

def objects(text):
    seen=set();pending=hydration(text);count=0
    while pending and count<50000:
        value=pending.pop();count+=1
        if not isinstance(value,(dict,list)) or id(value) in seen:continue
        seen.add(id(value))
        if isinstance(value,dict):yield value;pending.extend(value.values())
        else:pending.extend(value)

def releases(text,base,query):
    from source_parser import public_url
    values=[];seen=set();terms=query.casefold().split()
    for value in objects(text):
        alias=value.get('alias');name=value.get('name') or value.get('names')
        if not isinstance(alias,str) or not isinstance(name,(dict,str)):continue
        title=(name.get('main') or name.get('ru') or name.get('english') or '') if isinstance(name,dict) else name
        if not title or alias in seen or not all(t in (title+' '+alias).casefold() for t in terms):continue
        try:url=public_url(urljoin(base,'/anime/releases/release/'+alias),resolve_dns=False)
        except Exception:continue
        seen.add(alias);poster=value.get('poster') or {};image=poster.get('optimized',{}).get('src') or poster.get('src') if isinstance(poster,dict) else ''
        values.append({'provider':'anilibria','providerName':'AniLiberty','kind':'anime','title':title,'url':url,'cover':urljoin(base,image) if image else None,'dubs':[],'releaseDates':[]})
    return values[:24]

def episode_streams(text,base):
    from source_parser import public_url
    result=[]
    for value in objects(text):
        number=value.get('ordinal') or value.get('episode') or value.get('number')
        if not isinstance(number,(int,float)) or int(number)!=number or number<1:continue
        url=next((value.get(key) for key in ('hls_1080','hls_720','hls_480','hls','file') if isinstance(value.get(key),str) and '.m3u8' in value[key]),None)
        if not url:continue
        try:url=public_url(urljoin(base,url),resolve_dns=False)
        except Exception:continue
        result.append({'number':int(number),'url':url,'title':value.get('name') or 'Серия '+str(int(number))})
    return sorted({v['number']:v for v in result}.values(),key=lambda value:value['number'])
