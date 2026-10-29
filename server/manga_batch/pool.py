"""Three owner-supplied credentials, bounded parallelism and shared-project pacing."""
import asyncio,hashlib
from pathlib import Path
from .provider import GemmaBatchTranslator,ProviderUnavailable
from .quota import QuotaPacer
from .contracts import MODEL_IDS
class GooglePool:
 def __init__(self,pacer,key_file,settings):
  self.pacer=pacer;self.key_file=Path(key_file);self.settings=settings;self.workers={};self.gates={};self.groups={};self.cursor=0
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
  if len(available)>1 and len(pages)>1:
   results=await asyncio.gather(*(self.translate([page]) for page in pages));rows={}
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
   worker.models=[model]
   return await worker.translate(pages)
