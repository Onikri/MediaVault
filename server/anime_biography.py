"""Wikipedia summaries only after matching a published birthday or studio domain."""
from urllib.parse import quote,urlsplit
import re
from metadata_catalog import get_json
from source_parser import SourceError

def biography(name,*,birth=None,website='',studio=False):
    if not name or not birth and not website and not studio:return {}
    try:
        summary=get_json('https://en.wikipedia.org/api/rest_v1/page/summary/'+quote(name.replace(' ','_'),safe=''))
        identity=summary.get('wikibase_item','')
        if not identity.startswith('Q') or not identity[1:].isdigit():return {}
        entity=get_json('https://www.wikidata.org/wiki/Special:EntityData/'+identity+'.json').get('entities',{}).get(identity,{})
        def values(key):return [v.get('mainsnak',{}).get('datavalue',{}).get('value') for v in entity.get('claims',{}).get(key,[])]
        verified=False
        if studio:
            normalize=lambda v:re.sub(r'\W+','',v.casefold())
            names=[v.get('value','') for v in entity.get('labels',{}).values()]+[v.get('value','') for rows in entity.get('aliases',{}).values() for v in rows]
            description=summary.get('description','')+' '+entity.get('descriptions',{}).get('en',{}).get('value','')
            verified=any(normalize(v)==normalize(name) for v in names) and bool(re.search(r'(?:animation|anime|film).*(?:studio|company)|(?:studio|company).*(?:animation|anime|film)',description,re.I))
        if birth and all(birth.get(k) for k in ('year','month','day')):
            day=f'{birth["year"]:04}-{birth["month"]:02}-{birth["day"]:02}'
            verified=any(isinstance(v,dict) and v.get('time','').startswith('+'+day) for v in values('P569'))
        if website:
            domain=lambda u:(urlsplit(u if '://' in u else 'https://'+u).hostname or '').lower().removeprefix('www.')
            verified=verified or any(isinstance(v,str) and domain(v)==domain(website) for v in values('P856'))
        if not verified:return {}
        russian=entity.get('sitelinks',{}).get('ruwiki',{}).get('title')
        if russian:summary=get_json('https://ru.wikipedia.org/api/rest_v1/page/summary/'+quote(russian.replace(' ','_'),safe=''))
        result={'description':str(summary.get('extract') or '')[:6000],'sourceUrl':summary.get('content_urls',{}).get('desktop',{}).get('page',''),'license':'CC BY-SA'}
        if studio:
            dates=[v.get('time','')[1:11] for v in values('P571') if isinstance(v,dict) and v.get('time','').startswith('+')]
            if dates:result['facts']=[['Основана',dates[0]]]
        return result
    except (SourceError,ValueError,TypeError,AttributeError):return {}
