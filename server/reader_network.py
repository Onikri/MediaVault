"""Owner-scoped observed translation activity; never serialize credentials."""
import ipaddress,secrets,time
import httpx

class ReaderNetwork:
 def __init__(self):self.jobs={};self.address=None;self.checked=0
 def begin(self,subject,slot,model,personal=False):
  now=time.time()
  for key,row in list(self.jobs.items()):
   if row['updated']<now-600:self.jobs.pop(key,None)
  while len(self.jobs)>=64:self.jobs.pop(next(iter(self.jobs)))
  identity=secrets.token_urlsafe(12);self.jobs[identity]={'subject':subject,'slot':slot,'personal':personal,'model':model,'phase':'queued','updated':now};return identity
 def update(self,identity,phase,http_status=None):
  row=self.jobs.get(identity)
  if row is not None:
   row.update(phase=phase,updated=time.time())
   if http_status is not None:row['httpStatus']=http_status
 def snapshot(self,subject):
  rows=[{k:v for k,v in row.items() if k!='subject'} for row in self.jobs.values() if row['subject']==subject and row['updated']>time.time()-600]
  return {'egressIP':self.address,'ipCheckedAt':self.checked or None,'jobs':rows,'active':sum(r['phase'] in {'counting','translating','quota'} for r in rows),'queued':sum(r['phase']=='queued' for r in rows)}
 async def observe_address(self):
  if time.time()-self.checked<900:return
  self.checked=time.time()
  try:
   async with httpx.AsyncClient(timeout=3,trust_env=False,follow_redirects=False) as client:r=await client.get('https://api.ipify.org?format=json')
   r.raise_for_status();self.address=str(ipaddress.ip_address(r.json()['ip']))
  except Exception:self.address=None
