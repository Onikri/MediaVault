"""Three owner-supplied credentials, bounded parallelism and shared-project pacing."""
import asyncio,hashlib,json,time
from pathlib import Path
from .provider import GemmaBatchTranslator,ProviderUnavailable
from .quota import QuotaPacer
from .contracts import MODEL_IDS
class GooglePool:
 def __init__(self,pacer,key_file,settings):
  self.pacer=pacer;self.key_file=Path(key_file);self.settings=settings;self.workers={};self.gates={};self.groups={};self.cursor=0;self.partial={}
 def records(self):
  try:value=self.settings.setting('reader:google-keys')
  except Exception:return []
  if value is not None:return value.get('slots',[])
  if self.key_file.is_file():return [{'slot':0,'key':self.key_file.read_text('utf-8-sig').strip(),'project':'','models':list(MODEL_IDS)}]
  return []
 def configured(self):return bool(self.records())
 async def translate(self,pages):
  from google import genai
  from google.genai import types
  model=pages[0].get('model') or 'gemini-3.5-flash-lite';records=self.records()
  if model not in MODEL_IDS:raise ProviderUnavailable('Выбери поддерживаемую модель Google.')
  available=[r for r in records if model in r.get('models',MODEL_IDS)]
  if not available:raise ProviderUnavailable('Выбранная модель не доступна подключённым ключам.')
  # A quota pause on one parallel page must not throw away the successful
  # siblings and bill their translation again. Keep only bounded text results,
  # never image bytes, until the orchestrator's next attempt.
  def identity(page):
   scope=[model,[(r['slot'],hashlib.sha256(r['key'].encode()).hexdigest()) for r in available],page.get('page'),page.get('width'),page.get('height'),page.get('regions')]
   return hashlib.sha256(page.get('som',b'')+json.dumps(scope,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  now=time.monotonic();self.partial={k:v for k,v in self.partial.items() if now-v[0]<900}
  if len(pages)==1:
   previous=self.partial.pop(identity(pages[0]),None)
   if previous:return previous[1]
  if len(available)>1 and len(pages)>1:
   results=await asyncio.gather(*(self.translate([page]) for page in pages),return_exceptions=True)
   errors=[value for value in results if isinstance(value,BaseException)]
   if errors:
    for page,result in zip(pages,results):
     if not isinstance(result,BaseException):self.partial[identity(page)]=(now,result)
    while len(self.partial)>128:self.partial.pop(next(iter(self.partial)))
    raise errors[0]
   rows={}
   for values,_ in results:rows.update(values)
   metadata=[meta for _,meta in results]
   return rows,{'model':model,'pages':len(pages),'boxes':sum(len(p['regions']) for p in pages),'parallelRequests':metadata,'cloudMs':max(m.get('cloudMs',0) for m in metadata),'inputTokens':sum(m.get('inputTokens') or 0 for m in metadata),'outputTokens':sum(m.get('outputTokens') or 0 for m in metadata)}
  # A 429 is propagated through the existing orchestrator backoff, never retried
  # against another account. Independent projects are explicit owner metadata.
  self.cursor+=1;row=available[self.cursor%len(available)];key=row['key'];identity=hashlib.sha256(key.encode()).hexdigest();group=row.get('project') or 'shared-project'
  gate=self.gates.setdefault(identity,asyncio.Lock())
  if identity not in self.workers:
   pacer=self.groups.setdefault(group,QuotaPacer(tpm=self.pacer.tpm,rpm=self.pacer.rpm))
   client=genai.Client(api_key=key,vertexai=False,http_options=types.HttpOptions(timeout=90000,retry_options=types.HttpRetryOptions(attempts=1)))
   self.workers[identity]=GemmaBatchTranslator(pacer,self.key_file,client=client,models=[model])
  worker=self.workers[identity]
  async with gate:
   worker.pacer=self.groups.setdefault(group,QuotaPacer(tpm=self.pacer.tpm,rpm=self.pacer.rpm))
   worker.models=[model]
   return await worker.translate(pages)
