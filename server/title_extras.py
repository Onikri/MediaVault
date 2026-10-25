"""Russian production credits and catalogue-published trailer metadata."""
import re
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup

def russian(value):
    value=BeautifulSoup(str(value or ''),'html.parser').get_text(' ',strip=True)
    return value[:6000] if re.search('[а-яё]',value,re.I) else ''

def staff_from_roles(roles):
    values=[]
    for row in roles:
        person=row.get('person') or {};name=russian(person.get('russian'))
        labels=[russian(v) for v in row.get('roles_russian',[]) if russian(v)]
        if name and labels:values.append({'id':str(person['id']),'name':name,'role':' · '.join(labels),'image':urljoin('https://shikimori.io',(person.get('image') or {}).get('original','')) if (person.get('image') or {}).get('original') and 'missing_' not in (person.get('image') or {}).get('original','') else ''})
    return values[:24]

def trailers_from_details(details):
    values=[]
    for video in details.get('videos',[]):
        if video.get('kind') not in {'pv','character_trailer','cm'}:continue
        url=video.get('url') or video.get('player_url') or ''
        if url.startswith('http://'):url='https://'+url[7:]
        if urlsplit(url).hostname not in {'youtu.be','youtube.com','www.youtube.com','www.youtube-nocookie.com','vk.com','vkvideo.ru','vimeo.com','www.vimeo.com','video.sibnet.ru'}:continue
        image=video.get('image_url') or ''
        if image.startswith('http://'):image='https://'+image[7:]
        values.append({'id':str(video['id']),'title':russian(video.get('name')) or 'Проморолик','url':url,'image':image,'hosting':video.get('hosting','')})
    return values[:12]
