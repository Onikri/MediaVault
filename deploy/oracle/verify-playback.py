"""Read-only release checks, run INSIDE the existing importer; no api/TaskStore import."""
import json,urllib.request
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_sources import inspect,search_title
from music_playback import recordings,skip_times
from online_sessions import install
from reader_translation import ready
h=json.load(urllib.request.urlopen('http://127.0.0.1:7860/health',timeout=5))
assert h['version']==11 and h['oauthConfigured'] and ready('/data')
print(json.dumps({'api':h['version'],'oauth':True,'translationModel':True}),flush=True)
r=recordings('Otonoke','Creepy Nuts')
assert r['results'],'No public YouTube recordings found'
print(json.dumps({'youtubeRecordings':len(r['results']),'matched':r['results'][0]['match'],'first':r['results'][0]['title']},ensure_ascii=False),flush=True)
t=skip_times('57334',1,1420)
print(json.dumps({'skipIntervals':len(t['intervals'])}),flush=True)
r=search_title({'title':'Дандадан','aliases':['Dandadan','Dan Da Dan'],'kind':'manga','year':2021,'ids':{'mal':'135496'}},'all')
assert any(v['language']=='en' for v in r['results']) and any(v['language']=='ru' for v in r['results'])
print(json.dumps({'mangaMatches':[(v['provider'],v['language']) for v in r['results']]},ensure_ascii=False),flush=True)
# A separate ephemeral app validates online page delivery without touching Drive,
# the running API's session map, users, task DB or worker queue.
app=FastAPI();install(app,lambda:'maintenance-read-only');client=TestClient(app)
r=client.post('/online/prepare',json={'url':'https://mangakatana.com/manga/dandadan.25818/c1','kind':'manga'})
assert r.status_code==200,r.status_code
session=r.json();page=client.get(session['pages'][0]);assert page.status_code==200 and page.headers.get('content-type','').startswith('image/')
assert client.delete('/online/'+session['id']).status_code==200
print(json.dumps({'onlineChapterPages':len(session['pages']),'firstPageBytes':len(page.content)}),flush=True)
