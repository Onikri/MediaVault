import {readChapterBlob,writeChapterBlob,removeChapterBlob,encodeCleanPage,decodeCleanPage} from './reader-chapter-cache.js';
import {directKey,restoreDirectKeys} from './manga-direct-key.js';
import {linkPageBlocks,packBlockSheets,unpackBlockTranslations,BLOCK_LIMITS} from './manga-blocks.js';
import {needsEmptyReview,reviewEmptyTranslations,unresolvedRegions} from './manga-empty-review.js';

const pause=(ms,signal)=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(signal.reason);};const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();});
const deferred=()=>{const r={};r.promise=new Promise((resolve,reject)=>Object.assign(r,{resolve,reject}));r.promise.catch(()=>{});return r;};
export class RequestPacer{
 constructor({now=Date.now,wait=pause}={}){this.now=now;this.wait=wait;this.starts=new Map();this.locks=new Map();}
 reserve(key,signal){const task=(this.locks.get(key)||Promise.resolve()).catch(()=>{}).then(()=>this.reserveOne(key,signal));this.locks.set(key,task);task.finally(()=>{if(this.locks.get(key)===task)this.locks.delete(key);}).catch(()=>{});return task;}
 async reserveOne(key,signal){signal?.throwIfAborted();const history=this.starts.get(key)||[],now=this.now();while(history.length&&now-history[0]>=60000)history.shift();const ms=Math.max(0,history.length?history.at(-1)+4000-now:0,history.length>=15?history[0]+60000-now:0);if(ms)await this.wait(ms,signal);signal?.throwIfAborted();history.push(this.now());this.starts.set(key,history);}
}
export const sharedRequestPacer=new RequestPacer();
// Dense pages still travel together. Partition label IDs, never silently turn
// a two-page packet into independent one-image calls.
export function labelPackets(pages,limit=100){
 if(pages.some(p=>p.inputMode==='vision'||p.inputMode==='blocks'))return [pages];
 const counts=pages.map(()=>0),out=[];let remaining=pages.reduce((n,p)=>n+p.regions.length,0);
 while(remaining){let budget=limit;out.push(pages.map((p,i)=>{const regions=p.regions.slice(counts[i],counts[i]+budget);counts[i]+=regions.length;budget-=regions.length;remaining-=regions.length;return {...p,regions};}));}return out;
}
export class ChapterPreparation{
 constructor(chapter){this.c=chapter;this.tasks=chapter.entries.map(()=>deferred());this.sources=chapter.entries.map(()=>deferred());this.cleaned=chapter.entries.map(()=>deferred());this.held=new Map();this.getting=new Map();this.memory=new Map();this.scanPending=new Set(chapter.entries.map((_,i)=>i));this.cleanPending=new Set(this.scanPending);this.nextSource=0;this.done=0;this.downloaded=0;this.cleanDone=new Set();this.cleanFailed=new Set();this.started=false;}
 start(){if(this.started)return;this.started=true;for(let n=0;n<(this.c.config.saveData?1:4);n++)this.load();for(let n=0;n<(this.c.config.saveData?1:2);n++)this.scan();this.cleanLoop();}
 async load(){const c=this.c;while(!c.controller.signal.aborted){const index=this.nextSource++;if(index>=this.sources.length)return;try{const blob=c.jobs.get(index)?.blob||await c.entries[index].async('blob');c.controller.signal.throwIfAborted();this.sources[index].resolve({blob});this.downloaded++;}catch(error){this.sources[index].reject(error);}}}
 take(pending){const focus=this.c.focusWindow||[],index=focus.find(i=>pending.has(i))??pending.values().next().value;pending.delete(index);return index;}
 async scan(){const c=this.c;while(!c.controller.signal.aborted&&this.scanPending.size){const index=this.take(this.scanPending);
  try{
   const cell=await this.sources[index].promise,blob=cell.blob;delete cell.blob;c.controller.signal.throwIfAborted();
   const key=await c.cacheKey(blob,{...c.config,engine:'direct',directBatchPages:2,directModel:'gemini-3.5-flash-lite',directInput:c.config.directInput==='blocks'?'annotated':c.config.directInput,font:'auto',inpaint:'fast'},c.scope)+':detected-v3:'+index;
   const hit=await readChapterBlob(c.scope,key,index,'detection');
   const page=hit?JSON.parse(await hit.text()):await c.prepare(blob,index,message=>c.notify(index,{phase:'detecting',message}));
   const saved=hit||await writeChapterBlob(c.scope,key,index,'detection',new Blob([JSON.stringify(page)],{type:'application/json'}));
   if(!saved)this.memory.set(index,page); // private mode/quota: explicit RAM fallback
   const{image,...meta}=page;this.tasks[index].resolve({...meta,key});
   this.done++;c.notify(index,{phase:'detected',message:'Размечено '+this.done+' / '+this.tasks.length+' страниц',detected:{width:page.width,height:page.height,regions:page.regions.map(r=>({id:r.id,bbox:r.bbox}))},preparation:{downloaded:this.downloaded,detected:this.done,total:this.tasks.length,buffer:9}});
  }catch(error){this.tasks[index].reject(error);if(!c.controller.signal.aborted)c.notify(index,{phase:'error',message:error.message});}
 }}
 async get(index){
  this.start();if(this.held.has(index))return this.held.get(index);
  if(!this.getting.has(index)){const task=(async()=>{const meta=await this.tasks[index].promise,c=this.c,stored=await readChapterBlob(c.scope,meta.key,index,'detection'),blob=await c.entries[index].async('blob');
   const page=stored?JSON.parse(await stored.text()):this.memory.get(index)||await c.prepare(blob,index);const source={...page,page:index+1,blob};this.held.set(index,source);while(this.held.size>9)this.held.delete(this.held.keys().next().value);return source;
  })();this.getting.set(index,task);task.finally(()=>this.getting.delete(index)).catch(()=>{});}return this.getting.get(index);
 }
 async cleanLoop(){const c=this.c;while(this.cleanPending.size&&!c.controller.signal.aborted){const index=this.take(this.cleanPending);try{
  const meta=await this.tasks[index].promise,stage='clean-v9-'+(c.config.inpaint||'fast'),hit=await readChapterBlob(c.scope,meta.key,index,stage);
  if(hit){const summary=await decodeCleanPage(hit);if(summary.regions?.some(r=>!r.painted))this.cleanFailed.add(index);else this.cleanDone.add(index);this.c.notify(index,{phase:'cleaning',message:'Подготовленный фон найден в кэше'});this.cleaned[index].resolve({key:meta.key,stage,fromCache:true});continue;}
  const source=await this.get(index);if(!source.regions.length){this.cleanDone.add(index);this.cleaned[index].resolve(null);continue;}
  const result=await c.canvasTask({channel:'clean',operation:'clean-prepare',blob:source.blob,allowDownloads:c.config.allowDownloads===true,mode:c.config.inpaint||'fast',page:{width:source.width,height:source.height,regions:source.regions.map(r=>({uid:r.id,text_bbox:r.bbox,layout_bbox:r.layout_bbox||r.bbox,text_category:'text'}))}},value=>{this.cleanProgress={page:index+1,message:value.message||'Фон готовится параллельно переводу'};c.notify(index,{...value,phase:'cleaning',message:this.cleanProgress.message});});
  if(result.regions?.some(r=>!r.painted))this.cleanFailed.add(index);else this.cleanDone.add(index);
  this.cleanProgress=null;c.notify(index,{phase:'cleaning',message:'Фон подготовлен · ожидаем перевод'});const saved=result.regions?.some(r=>!r.painted)?false:await writeChapterBlob(c.scope,meta.key,index,stage,await encodeCleanPage(result));this.cleaned[index].resolve(saved?{key:meta.key,stage}:{result});
 }catch(error){this.cleanProgress=null;this.cleanFailed.add(index);this.cleaned[index].reject(error);}}}
 async cleanFor(index){this.start();const value=await this.cleaned[index].promise;if(!value)return null;if(value.result)return value.result;const hit=await readChapterBlob(this.c.scope,value.key,index,value.stage);return hit?{...await decodeCleanPage(hit),cacheHit:!!value.fromCache}:null;}
 retryClean(index){
  const next=deferred();this.cleanDone.delete(index);this.cleanFailed.delete(index);this.cleaned[index]=next;
  (async()=>{const c=this.c,meta=await this.tasks[index].promise,stage='clean-v9-'+(c.config.inpaint||'fast');await removeChapterBlob(c.scope,meta.key,index,stage);const source=await this.get(index);
   const result=await c.canvasTask({channel:'clean',operation:'clean-prepare',blob:source.blob,allowDownloads:c.config.allowDownloads===true,mode:c.config.inpaint||'fast',page:{width:source.width,height:source.height,regions:source.regions.map(r=>({uid:r.id,text_bbox:r.bbox,layout_bbox:r.layout_bbox||r.bbox,text_category:'text'}))}},value=>c.notify(index,value));
   if(result.regions?.some(r=>!r.painted))this.cleanFailed.add(index);else this.cleanDone.add(index);const saved=result.regions?.some(r=>!r.painted)?false:await writeChapterBlob(c.scope,meta.key,index,stage,await encodeCleanPage(result));next.resolve(saved?{key:meta.key,stage}:{result});
  })().catch(next.reject);
 }
 release(index){this.held.delete(index);this.memory.delete(index);}
 close(reason){for(const task of [...this.tasks,...this.sources,...this.cleaned])task.reject(reason);this.held.clear();this.memory.clear();}
}

// A single dispatcher establishes request order. Inference/completion are
// concurrent; a slow detector can never make pages 7/10 overtake pages 1/2.
export async function drainOrderedChapter(c){
 if(c.dispatching||c.controller.signal.aborted)return;c.dispatching=true;
 const inFlight=c.inFlight||(c.inFlight=new Set());
 try{
  c.preparation.start();
  while(!c.controller.signal.aborted){
   if(c.priorityBarrier){if(inFlight.size){await Promise.allSettled([...inFlight]);continue;}c.priorityBarrier=false;}
   if(inFlight.size>=3||(c.activePages||0)+c.batchSize()>9&&inFlight.size){await Promise.race(inFlight);continue;}
   const pending=c.pendingJobs();if(!pending.length)break;
   const first=pending[0],group=[],sources=[],epoch=c.priorityEpoch,priority=c.priorityPages.has(first.index);let key;
   try{
    const blocks=c.config.directInput==='blocks',max=blocks?9-(c.activePages||0):c.packetRange(first.index).count;let pixels=0,regions=0;
    if(!blocks&&(c.activePages||0)+max>9&&inFlight.size){await Promise.race(inFlight);continue;}
    for(const job of pending){
     if(c.priorityPages.has(job.index)!==priority||group.length>=max||group.length&&job.index!==group.at(-1).index+1)break;
     const source=await c.preparation.get(job.index);
     if(blocks&&sources.length&&(pixels+source.width*source.height>BLOCK_LIMITS.pixels||regions+source.regions.length>100))break;
     job.state='running';c.pageStates.set(job.index,{page:job.index+1,state:'running'});group.push(job);sources.push(source);job.prepared=source;job.blob=source.blob;pixels+=source.width*source.height;regions+=source.regions.length;
     if(blocks&&packBlockSheets(linkPageBlocks(sources,{direction:c.direction,webtoon:c.config.webtoon})).length>1)break;
    }
    if(!group.length)continue;
    const hits=await Promise.all(group.map(job=>c.cached(job)));
    if(hits.every(Boolean)&&!hits.some(needsEmptyReview)){for(let n=0;n<group.length;n++)c.finish(group[n],hits[n]);continue;}
    const active=group.filter(j=>j.state==='running');if(!active.length)continue;
    // Wait for a free credential; rotate slots instead of repeatedly choosing #1.
    const available=c.serverSlots.length?c.serverSlots.map(slot=>'oracle-slot:'+slot):c.getKey===directKey?await restoreDirectKeys(c.keyScope):[c.getKey(c.keyScope)];
    if(!available.length||!available.some(Boolean)){
     if(hits.every(Boolean)){for(let n=0;n<group.length;n++){hits[n].emptyReview={attempted:false,error:'Нет ключа для проверки пропущенных реплик'};c.finish(group[n],hits[n]);}continue;}
     throw Error('Добавь ключ Google в настройках перевода.');
    }
    while(!key){for(let n=0;n<available.length;n++){const i=((c.keyCursor||0)+n)%available.length;if(available[i]&&!c.keyBusy.has(available[i])&&(!priority||!c.priorityKey||available[i]===c.priorityKey)&&(priority||available[i]!==c.priorityKey)){key=available[i];c.keyCursor=(i+1)%available.length;break;}}if(!key){if(!inFlight.size)throw Error('Нет свободного ключа перевода');await Promise.race(inFlight);}}
    if(priority)c.priorityKey=key;c.keyBusy.add(key);const slot=available.indexOf(key);for(const job of active){job.keySlot=c.serverSlots.length?c.serverSlots[slot]+1:c.personalSlot(key)+1;job.serverKey=!!c.serverSlots.length;}
    await c.pacer.reserve(key,c.controller.signal);
    if(epoch!==c.priorityEpoch){c.keyBusy.delete(key);key=null;for(const job of group)job.state='queued';continue;}
    const local=sources.filter(p=>active.some(j=>j.index+1===p.page));
    if(!blocks&&local.length===1&&c.entries.length>1){const neighbour=local[0].page<c.entries.length?local[0].page:local[0].page-2;try{local.push(await c.preparation.get(neighbour));local.sort((a,b)=>a.page-b.page);}catch{}}
    c.activePages=(c.activePages||0)+active.length;const leasedKey=key;
    const task=translatePacket(c,active,local,leasedKey,hits.every(Boolean)?hits:null).then(completed=>{c.keyBusy.delete(leasedKey);for(const[job,page]of completed)c.finish(job,page);}).catch(error=>{c.keyBusy.delete(leasedKey);for(const job of active)if(job.state!=='done')c.fail(job,error);}).finally(()=>{c.keyBusy.delete(leasedKey);c.activePages-=active.length;inFlight.delete(task);c.active=inFlight.size;});
    inFlight.add(task);c.active=inFlight.size;key=null;
   }catch(error){if(key)c.keyBusy.delete(key);if(!group.length)c.fail(first,error);for(const job of group)if(job.state==='running')c.fail(job,error);}
  }
 }finally{c.dispatching=false;if(!c.controller.signal.aborted&&[...c.jobs.values()].some(j=>j.state==='queued'))queueMicrotask(()=>c.drain());}
}
async function translatePacket(c,jobs,sources,key,cachedPages){
 const start=performance.now(),blocks=c.config.directInput==='blocks';let sheets,send=sources.some(p=>p.regions.length||p.inputMode==='vision')?sources:[];
 if(blocks){sheets=packBlockSheets(linkPageBlocks(sources,{direction:c.direction,webtoon:c.config.webtoon}));send=await c.canvasTask({operation:'blocks-pack',channel:'prepare',sheets,pages:sources});}
 let translated=cachedPages||[],diagnostics,usage,options;
 if(send.length){
  for(const job of jobs)c.notify(job.index,{phase:'translating',message:blocks?'Блоки · '+sources.length+' исходных страниц на '+send.length+' листах':'Перевод по порядку · страницы '+sources.map(p=>p.page).join(', '),totalRegions:job.prepared.regions.length});
  options={key,paced:true,model:c.config.directModel,language:c.config.language,direction:c.direction,gemmaProfile:c.config.gemmaProfile||'compat',context:[...c.context].filter(([i])=>i<jobs[0].index).sort((a,b)=>a[0]-b[0]).map(([,s])=>s).join('\n').slice(-1200),signal:c.controller.signal,timeoutMs:c.config.directTimeoutMs,onDiagnostic:value=>{diagnostics={...value,local:{batchPages:sources.map(p=>p.page),buffer:9},transport:{viaOracle:!!c.config.directViaOracle,keySlot:jobs[0].keySlot,serverKey:jobs[0].serverKey}};for(const job of jobs)c.notify(job.index,{phase:'translating',message:({prepared:'Запрос подготовлен',sending:'Отправляем пакет в Google',uploading:'Отправляем изображения в Google',waiting:'Пакет отправлен · ждём Google',headers:'Google начал отвечать',receiving:'Получаем ответ Google',streaming:'Google присылает перевод',complete:'JSON проверен'}[value.stage]||'Пакет · '+value.stage),diagnostics});}};
  if(!cachedPages){
  const answer={pages:[],usage:[]};for(const[part,packet]of labelPackets(send).entries()){const result=await c.callGoogle(packet,{...options,paced:part===0});answer.pages.push(...result.pages);answer.usage.push(result.usage);}
  if(!blocks){const merged=new Map();for(const p of answer.pages){const prior=merged.get(p.page);merged.set(p.page,prior?{...p,regions:[...prior.regions,...p.regions]}:p);}answer.pages=[...merged.values()];}
  translated=blocks?unpackBlockTranslations(answer.pages,sheets,sources):answer.pages;usage=answer.usage;
  }
  if(translated.some(needsEmptyReview)){
   for(const job of jobs)c.notify(job.index,{phase:'translating',message:'Проверяем пропущенные реплики · увеличенные вырезки одним пакетом'});
   translated=await reviewEmptyTranslations(c,translated,sources,options);
  }
 }
 const completed=[];for(const job of jobs){
  const source=sources.find(p=>p.page===job.index+1),page=translated.find(p=>p.page===source.page)||(!source.regions.length&&source.inputMode!=='vision'?{page:source.page,width:source.width,height:source.height,regions:[]}:null);
  if(!page)throw Error('Google пропустил страницу пакета.');
  page.detected={...page.detected,width:source.width,height:source.height,regions:source.regions.map(r=>({id:r.id,bbox:r.bbox}))};page.detectionReport={found:source.regions.length,translated:page.regions.filter(r=>r.ru_translation?.trim()).length,rejected:page.regions.filter(r=>!r.ru_translation?.trim()).map(r=>r.uid),unresolved:unresolvedRegions(page).map(r=>r.uid),nonText:page.regions.filter(r=>!r.ru_translation?.trim()&&r.empty_reason==='non_text').map(r=>r.uid),review:page.emptyReview,missed:'unknown'};page.timings={...page.timings,translationMs:performance.now()-start};page.usage=usage||page.usage;page.diagnostics=diagnostics;
  if(c.config.cache){const{diagnostics,...cachedPage}=page;await c.writeCache(job.cacheId,c.scope,{kind:'manga-json',page:cachedPage});}completed.push([job,page]);
 }return completed;
}
