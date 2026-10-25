"""Release order from exact franchise IDs; no invented chronology for alternate routes."""
from metadata_catalog import get_json


def watch_order(identity):
    data=get_json('https://shikimori.io/api/animes/'+identity+'/franchise')
    nodes=data.get('nodes') or [];edges=data.get('links') or []
    # Franchise edges do not define a single mandatory route for Fate or alternate adaptations.
    # Present the factual release sequence and preserve every relation as source evidence.
    values=[]
    for node in nodes:
        identifier=str(node.get('id',''))
        if not identifier.isdigit():continue
        raw=node.get('date') or 0
        if not isinstance(raw,(int,float)):raw=0
        values.append({'id':identifier,'title':node.get('russian') or node.get('name') or 'Название уточняется',
                       'date':raw,'year':node.get('year'),'current':identifier==identity,
                       'url':'https://shikimori.io/animes/'+identifier,'kind':node.get('kind')})
    try:
        from poster_assets import posters
        art=posters([v['id'] for v in values])
        for value in values:
            if art.get(value['id'],{}).get('title'):value['title']=art[value['id']]['title']
    except Exception:pass
    values.sort(key=lambda n:(n['date'] or float('inf'),n['id']))
    return {'items':values,'links':edges,'mode':'release','source':'Shikimori','message':'Порядок выхода. Альтернативные адаптации и ответвления не образуют единственную обязательную хронологию.'}
