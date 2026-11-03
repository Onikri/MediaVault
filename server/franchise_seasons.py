"""Main television continuity from catalogue prequel/sequel edges, not spin-offs."""
import re

def television(value):return bool(re.search(r'^(?:tv|тв|телесериал)',str(value or ''),re.I))

def main_seasons(identity,items,links):
    by_id={str(v['id']):v for v in items};identity=str(identity)
    if identity not in by_id or not television(by_id[identity].get('kind')):return []
    graph={key:set() for key in by_id}
    for edge in links:
        if str(edge.get('relation','')).casefold() not in {'sequel','prequel'}:continue
        a,b=str(edge.get('source_id','')),str(edge.get('target_id',''))
        if a in graph and b in graph:graph[a].add(b);graph[b].add(a)
    seen={identity};pending=[identity]
    while pending:
        for target in graph[pending.pop()]-seen:seen.add(target);pending.append(target)
    rows=sorted((by_id[key] for key in seen if television(by_id[key].get('kind'))),key=lambda v:(v.get('date') or float('inf'),str(v['id'])))
    result=[];previous=0
    for row in rows:
        title=str(row.get('title') or '');aliases=' '.join([title,*row.get('aliases',[])])
        explicit=re.search(r'(\d{1,2})(?:st|nd|rd|th)\s+season|(?:сезон|season)\s*(\d{1,2})',aliases,re.I)
        suffix=re.search(r'\s(\d{1,2})(?:\.\s*(?:часть|part)\s*\d+)?$',title,re.I)
        part=re.search(r'(?:часть|part)\s*(\d{1,2})',aliases,re.I)
        number=int(next(v for v in explicit.groups() if v)) if explicit else int(suffix[1]) if suffix and previous else previous if part and previous else previous+1
        label='Сезон '+str(number)+((' · часть '+part[1]) if part else '')
        result.append({**row,'number':number,'name':label,'part':int(part[1]) if part else None})
        previous=number
    return result
