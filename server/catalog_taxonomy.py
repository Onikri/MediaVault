"""Shared presentation taxonomy; retained source facts and owner rules stay intact."""
import hashlib,json,unicodedata
from pathlib import Path

DATA=json.loads(Path(__file__).with_name('catalog-taxonomy.json').read_text(encoding='utf-8'))
REVISION=hashlib.sha256(json.dumps(DATA,sort_keys=True).encode()).hexdigest()
def norm(value):return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().replace('_',' ').replace('-',' ').split())
GENRES={norm(alias):row for row in DATA['genres'] for alias in [row['label'],row['key'],*row['aliases']]}

def classify(label,field,kind,policy=None,source=''):
    if not isinstance(label,str) or not label.strip() or label.strip().isdecimal():return None
    rule=policy.rules.get(policy.identity(label,source),{}) if policy else {}
    genre=GENRES.get(norm(label)) or GENRES.get(norm(rule.get('label'))) or GENRES.get(norm(rule.get('key')))
    category={'genre':'genres','tag':'tags'}.get(rule.get('category')) or ('genres' if genre else 'tags')
    if kind=='book' and (category!='genres' or not genre and rule.get('category')!='genre'):return None
    if genre and genre.get('kinds') and kind not in genre['kinds']:return None
    return category,(rule.get('label') or (genre['label'] if genre and category=='genres' else label))

def project(policy,row,source=''):
    result={'genres':[],'tags':[]};kind=row.get('kind','manga')
    for field in result:
        for label in row.get(field) or []:
            if not policy.key(label,source):continue
            value=classify(label,field,kind,policy,source)
            if value and value[1] not in result[value[0]]:result[value[0]].append(value[1])
    return {k:v[:120] for k,v in result.items()}

def keys(value,policy,allow_hidden=False):
    if not allow_hidden and not policy.key(value):return []
    row=GENRES.get(norm(value)) or GENRES.get(norm(policy.label(policy.identity(value))))
    labels=[value,*([row['label'],row['key'],*row['aliases']] if row else [])]
    from manga_tag_policy import normalize
    return sorted({key for v in labels for key in (policy.identity(v),normalize(v))})

def clauses(db,*,kind,genre='',tag='',excludeGenre='',excludeTag='',manga=False):
    from manga_tag_policy import current
    policy=current()
    db.create_function('catalog_category',3,lambda label,field,k:(classify(label,field,k,policy) or ('',''))[0],deterministic=True)
    result=[];params=[]
    for field,raw,negative in [('genres',genre,False),('tags',tag,False),('genres',excludeGenre,True),('tags',excludeTag,True)]:
        try:values=raw if isinstance(raw,(list,tuple)) else json.loads(raw) if str(raw or '').startswith('[') else str(raw or '').split(',')
        except (ValueError,TypeError):
            from fastapi import HTTPException
            raise HTTPException(422,'Неверный список фильтров.') from None
        if not isinstance(values,(list,tuple)) or len(values)>64 or any(not isinstance(v,str) or len(v)>120 for v in values):
            from fastapi import HTTPException
            raise HTTPException(422,'Не больше 64 текстовых значений в группе фильтров.')
        values=list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if not values:continue
        wanted=sorted({k for v in values for k in keys(v,policy,allow_hidden=negative)})
        if not wanted:
            if not negative:result.append('0')
            continue
        if manga:
            query='SELECT 1 FROM catalog_titles peer JOIN catalog_tags x ON x.title_id=peer.id WHERE peer.work_key=t.work_key'
        else:
            from content_catalog import work_sql
            query='SELECT 1 FROM content_titles peer JOIN content_tags x ON x.title_id=peer.id WHERE '+work_sql('peer')+'='+work_sql('t')
        query+=' AND x.tag_key IN ('+','.join('?' for _ in wanted)+') AND catalog_category(x.tag_key,x.category,?)=?'
        result.append(('NOT ' if negative else '')+'EXISTS('+query+')');params.extend([*wanted,kind,field])
    return result,params

def format_label(value,kind):
    return DATA.get('formatAliases',{}).get(kind,{}).get(str(value).casefold(),value)

def maintain_books(store):
    """Resume derived book cleanup in short transactions; retain all raw facts/jobs."""
    import time
    from manga_tag_policy import current
    from content_catalog import _index,invalidate
    marker='taxonomy-books-v1';vmarker='taxonomy-book-vocabulary-v1'
    while not getattr(store,'stopping',False):
        with store.lock,store.db:
            if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='content_titles'").fetchone():return
            prior=store.db.execute('SELECT value FROM content_catalog_state WHERE name=?',(marker,)).fetchone()
            if not prior or prior[0]!='done':
                rows=store.db.execute("SELECT id,raw FROM content_titles WHERE kind='book' AND id>? ORDER BY id LIMIT 20",(prior[0] if prior else '',)).fetchall()
                for identity,raw in rows:_index(store.db,identity,json.loads(raw),current())
                store.db.execute('INSERT OR REPLACE INTO content_catalog_state VALUES(?,?)',(marker,rows[-1][0] if rows else 'done'))
            else:
                prior=store.db.execute('SELECT value FROM content_catalog_state WHERE name=?',(vmarker,)).fetchone()
                if prior and prior[0]=='done':return
                rows=store.db.execute("SELECT rowid,label,source,category FROM catalog_vocabulary WHERE kind='book' AND rowid>? ORDER BY rowid LIMIT 200",(int(prior[0]) if prior else 0,)).fetchall()
                for rowid,label,source,category in rows:
                    if not classify(label,category,'book',current(),source):store.db.execute('DELETE FROM catalog_vocabulary WHERE rowid=?',(rowid,))
                store.db.execute('INSERT OR REPLACE INTO content_catalog_state VALUES(?,?)',(vmarker,str(rows[-1][0]) if rows else 'done'))
                if not rows:invalidate(store.db);return
        time.sleep(.1)
