#!/usr/bin/env python3
"""Actual local translators, independent of OCR; resumable immutable inputs."""
import argparse,hashlib,json,platform,resource,time
from pathlib import Path
import ctranslate2,sentencepiece,requests
from sacrebleu.metrics import CHRF
from translation_inputs import inputs_for
p=argparse.ArgumentParser();p.add_argument('--profile',choices=['json','segments'],default='json');p.add_argument('--model',choices=['argos','opus','nllb','openai'],required=True);p.add_argument('--model-dir');p.add_argument('--url');p.add_argument('--name');p.add_argument('--label',required=True);p.add_argument('--output',required=True);p.add_argument('--cases',default=str(Path(__file__).with_name('translation-cases.json')));p.add_argument('--runs',type=int,default=2);p.add_argument('--threads',type=int,default=2);a=p.parse_args();cases=json.loads(Path(a.cases).read_text());output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
if a.model in ['argos','opus']:cases=[c for c in cases if c['language']=='en']
key=hashlib.sha256(Path(a.cases).read_bytes()+(a.name or a.model).encode()).hexdigest()
if output.exists():
 previous=json.loads(output.read_text())
 if previous.get('key')==key and len(previous.get('runs',[]))>=a.runs:print('RESUME',output);raise SystemExit()
 raise SystemExit('Existing incomplete/different report; preserve it and select a new output.')
out={'key':key,'executionLabel':a.label,'machine':platform.machine(),'model':a.name or a.model,'profile':a.profile,'threads':a.threads,'runs':[]};start=time.perf_counter()
if a.model!='openai':
 root=Path(a.model_dir);out['modelFiles']=[{'name':f.name,'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(root.iterdir()) if f.is_file()]
 engine=ctranslate2.Translator(str(root/'model' if a.model=='argos' else root),device='cpu',compute_type='int8',inter_threads=1,intra_threads=a.threads)
 if a.model=='argos':source=target=sentencepiece.SentencePieceProcessor(model_file=str(root/'sentencepiece.model'))
 elif a.model=='opus':source=sentencepiece.SentencePieceProcessor(model_file=str(root/'source.spm'));target=sentencepiece.SentencePieceProcessor(model_file=str(root/'target.spm'))
 else:source=target=sentencepiece.SentencePieceProcessor(model_file=str(root/'sentencepiece.bpe.model'))
out['loadMs']=round((time.perf_counter()-start)*1000)
for run in range(a.runs):
 start=time.perf_counter();hypotheses=[];valid=True;error=None
 try:
  if a.model=='openai':
   if a.profile=='segments':
    for c in cases:
     body={'model':a.name,'temperature':0,'seed':42,'max_tokens':512,'chat_template_kwargs':{'enable_thinking':False},'messages':[{'role':'system','content':'Translate manga dialogue into natural Russian. Preserve names, negation and meaning. Return only the translated dialogue, no explanations.'},{'role':'user','content':c['source']}]}
     response=requests.post(a.url.rstrip('/')+'/chat/completions',json=body,timeout=300);response.raise_for_status();choice=response.json()['choices'][0]
     if choice.get('finish_reason')=='length':raise ValueError('A segment reached its token budget')
     text=choice['message']['content'].strip()
     if not text:raise ValueError('An empty translated segment')
     hypotheses.append(text)
   else:
    body={'model':a.name,'temperature':0,'seed':42,'max_tokens':1800,'chat_template_kwargs':{'enable_thinking':False},'response_format':{'type':'json_object'},'messages':[{'role':'system','content':'Translate the numbered manga dialogue into natural Russian. Preserve negations, names and meaning. Return JSON {"translations":[string,...]} with exactly one string for every input, in input order. No explanations.'},{'role':'user','content':json.dumps([{'id':c['id'],'text':c['source']} for c in cases],ensure_ascii=False)}]}
    response=requests.post(a.url.rstrip('/')+'/chat/completions',json=body,timeout=900);response.raise_for_status();content=response.json()['choices'][0]['message']['content'];out.setdefault('rawOutputs',[]).append(content);obj=json.loads(content);hypotheses=obj['translations'];valid=len(hypotheses)==len(cases) and all(isinstance(x,str) and x.strip() for x in hypotheses)
    if not valid:raise ValueError('Wrong count or invalid translation type')
  else:
   tokens,kwargs=inputs_for(a.model,cases,source)
   results=engine.translate_batch(tokens,beam_size=4,max_decoding_length=256,max_input_length=512,**kwargs)
   for r in results:
    hypothesis=r.hypotheses[0]
    if len(hypothesis)>=256:raise ValueError('Translation reached token budget; result is incomplete')
    if a.model=='nllb' and hypothesis and hypothesis[0]=='rus_Cyrl':hypothesis=hypothesis[1:]
    hypotheses.append(target.decode(hypothesis))
 except Exception as e:valid=False;error=str(e)[:500]
 rows=[]
 if valid:
  for c,h in zip(cases,hypotheses):rows.append({**c,'translation':h,'chrFpp':round(CHRF(word_order=2).sentence_score(h,[c['reference']]).score,2),'checks':{term:term.casefold() in h.casefold() for term in c.get('checks',[])}})
 record={'run':run,'ms':round((time.perf_counter()-start)*1000),'valid':valid,'error':error,'cases':rows}
 if valid:record['chrFpp']=round(CHRF(word_order=2).corpus_score(hypotheses,[[c['reference'] for c in cases]]).score,2)
 out['runs'].append(record);out['maxRssKiB']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'model':out['model'],'run':run,'ms':record['ms'],'valid':valid,'chrFpp':record.get('chrFpp'),'error':error}),flush=True)
