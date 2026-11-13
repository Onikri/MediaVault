"""One versioned taxonomy shared by source ingestion, SQLite and the browser."""
from pathlib import Path
import hashlib
import json
import os
import threading
import unicodedata

MAX_BYTES=1_000_000
_lock=threading.RLock()
_cache=None
_stamp=None


def normalize(value):
    text=unicodedata.normalize('NFKC',str(value or '')).casefold().replace('ё','е')
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in text).split())


def canonical_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def alias_domains(domain):
    from content_source_routes import HTML,LIB
    from urllib.parse import urlsplit
    result={domain}
    for canonical,(_,hosts) in HTML.items():
        group={canonical,*hosts}
        if domain in group:result.update(group)
    for canonical,(_,referer) in LIB.items():
        group={canonical,urlsplit(referer).hostname}
        if domain in group:result.update(group)
    return sorted(result)


class Policy:
    def __init__(self,data):
        if not isinstance(data,dict) or set(data)!={'schemaVersion','tags','excludedTerms','excludedPrefixes'} or data['schemaVersion']!=1:
            raise ValueError('Invalid manga tag policy schema')
        if len(canonical_json(data))>MAX_BYTES:raise ValueError('Tag policy too large')
        for field in ('excludedTerms','excludedPrefixes'):
            if not isinstance(data[field],list) or len(data[field])>256 or any(not isinstance(v,str) or not normalize(v) or len(v)>120 for v in data[field]):
                raise ValueError('Invalid tag exclusion list')
        if not isinstance(data['tags'],list) or len(data['tags'])>5000:raise ValueError('Invalid tag list')
        self.data=json.loads(json.dumps(data));self.rules={};self.aliases={};self.scoped={};self.expanded={}
        self.terms=[normalize(v) for v in data['excludedTerms']]
        self.prefixes=[normalize(v) for v in data['excludedPrefixes']]
        self.hidden=set()
        valid=lambda value:isinstance(value,str) and 1<=len(value.strip())<=120
        for row in data['tags']:
            if not isinstance(row,dict) or set(row)-{'key','label','aliases','sourceAliases','category'} or not {'key','label','aliases'}<=set(row):
                raise ValueError('Invalid tag entry')
            if row.get('category') not in (None,'tag','genre'):raise ValueError('Invalid tag category')
            key=normalize(row['key'])
            if not key or row['key']!=key or key in self.rules or not valid(row['label']):raise ValueError('Invalid or duplicate tag key/label')
            aliases=row['aliases']
            if not isinstance(aliases,list) or len(aliases)>120 or any(not valid(v) for v in aliases):raise ValueError('Invalid tag aliases')
            if any(not self.clean(v) for v in [key,row['label'],*aliases]):self.hidden.add(key)
            self.rules[key]=row
            for alias in [key,row['label'],*aliases]:
                token=normalize(alias)
                if token in self.aliases and self.aliases[token]!=key:raise ValueError('Ambiguous tag alias: '+alias)
                self.aliases[token]=key
            scoped=row.get('sourceAliases',{})
            if not isinstance(scoped,dict) or len(scoped)>100:raise ValueError('Invalid source aliases')
            for domain,values in scoped.items():
                if not isinstance(domain,str) or not domain or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in domain):raise ValueError('Invalid source alias domain')
                if not isinstance(values,list) or len(values)>120 or any(not valid(v) for v in values):raise ValueError('Invalid source alias values')
                if any(not self.clean(v) for v in values):self.hidden.add(key)
                for actual in alias_domains(domain):
                    expanded=self.expanded.setdefault(key,{}).setdefault(actual,[])
                    expanded.extend(value for value in values if value not in expanded)
                    for alias in values:
                        token=(actual,normalize(alias))
                        if token in self.scoped and self.scoped[token]!=key:raise ValueError('Ambiguous source alias')
                        self.scoped[token]=key
        self.revision=hashlib.sha256(canonical_json(self.data)).hexdigest()

    def clean(self,value):
        if not isinstance(value,str):return ''
        text=' '.join(unicodedata.normalize('NFKC',value).split()).strip(' ,;|')
        if not 1<=len(text)<=120:return ''
        token=normalize(text)
        if any(' '+term+' ' in ' '+token+' ' for term in self.terms):return ''
        if any(word.startswith(prefix) for word in token.split() for prefix in self.prefixes):return ''
        return text

    def key(self,value,source=''):
        if not self.clean(value):return ''
        key=self.scoped.get((source,normalize(value))) or self.aliases.get(normalize(value),'')
        return key if key not in self.hidden else ''

    def project(self,values,source=''):
        found={}
        for value in values if isinstance(values,(list,tuple)) else []:
            key=self.key(value,source)
            if key:found[key]=self.rules[key]['label']
        return list(found.values())[:120]

    def facts(self,row,source=''):
        result={'tags':[],'genres':[]}
        for field in result:
            values=row.get(field) or []
            for value in values if isinstance(values,(list,tuple)) else []:
                key=self.key(value,source)
                if not key:continue
                rule=self.rules[key];target={'tag':'tags','genre':'genres'}.get(rule.get('category'),field)
                if rule['label'] not in result[target]:result[target].append(rule['label'])
        return {field:values[:120] for field,values in result.items()}

    def public(self):
        # The public catalogue needs only visible matching rules. Moderation
        # exclusions and hidden entries are exclusively owner data.
        return {'schemaVersion':1,'tags':[{**row,**({'sourceAliases':self.expanded[key]} if key in self.expanded else {})} for key,row in self.rules.items() if key not in self.hidden],
                'excludedTerms':[],'excludedPrefixes':[]}


def policy_path():
    override=os.getenv('MANGA_TAG_POLICY_FILE')
    if override:return Path(override)
    runtime=Path(os.getenv('DATA_DIR','/data'))/'manga-tag-policy.json'
    return runtime if runtime.is_file() else Path(__file__).with_name('manga-tag-policy.json')


def current():
    global _cache,_stamp
    path=policy_path();stat=path.stat();stamp=(str(path),stat.st_mtime_ns,stat.st_size)
    with _lock:
        if _stamp!=stamp:
            if stat.st_size>MAX_BYTES:raise ValueError('Tag policy too large')
            value=Policy(json.loads(path.read_text(encoding='utf-8')))
            _cache=value;_stamp=stamp
        return _cache


def project_row(row,policy=None):
    from urllib.parse import urlsplit
    policy=policy or current()
    source=urlsplit(row.get('sourceUrl') or row.get('url') or '').hostname or ''
    return {**row,**policy.facts(row,source)}
