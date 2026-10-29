import {translateLmt} from './lmt-client.js';
import {callDirectGoogle} from './manga-direct-api.js';
import {directKey,restoreDirectKey,directKeys,restoreDirectKeys} from './manga-direct-key.js';
import {DIRECT_DETECTORS} from './manga-direct-profiles.js';
import {compareDirectInputs} from './manga-direct-comparison.js';
import {translationCacheKey,getTranslation,putTranslation} from './translation-cache.js';

const cancelled=()=>new DOMException('Читалка закрыта','AbortError');
function waitFor(promise,signal){
 if(!signal)return promise;signal.throwIfAborted();
 return new Promise((resolve,reject)=>{
  const abort=()=>{cleanup();reject(signal.reason);},cleanup=()=>signal.removeEventListener('abort',abort);
  signal.addEventListener('abort',abort,{once:true});promise.then(v=>{cleanup();resolve(v);},e=>{cleanup();reject(e);});
 });
}
// Three consecutive pages per credential; at most three credentials in flight.
// Cache hits and preparation failures are isolated before building each pack.
export class DirectChapter{
 constructor({entries,scope,keyScope,config,direction='rtl',prepare,google=callDirectGoogle,cacheKey=translationCacheKey,readCache=getTranslation,writeCache=putTranslation,renderPage,getKey=directKey,service,serverSlots=[]}){
  Object.assign(this,{entries,scope,keyScope,config,direction,google,cacheKey,readCache,writeCache,getKey,service,serverSlots});
  this.prepare=prepare||((blob,index,status,inputMode=config.directInput)=>inputMode!=='vision'&&DIRECT_DETECTORS.some(v=>v.id===config.directDetector&&v.model)?translateLmt(blob,{...config,directInput:inputMode,allowDownloads:true,mode:'gemma',operation:'gemma-prepare',fastDirect:true,pageIndex:index,direction},this.controller.signal,status):this.canvasTask({operation:'direct-prepare',blob,index,direction,inputMode},status));
  this.renderPage=renderPage||this.renderCanvas.bind(this);this.controller=new AbortController();this.jobs=new Map();this.listeners=new Map();this.progress=new Map();this.context=new Map();this.active=0;this.keyBusy=new Set();this.worker=null;this.renders=new Map();this.serial=0;this.bypass=new Set();
 }
 notify(index,value){this.progress.set(index,value);for(const fn of this.listeners.get(index)||[])fn(value);}
 request(index,blob,background=false){
  this.controller.signal.throwIfAborted();let job=this.jobs.get(index);
  if(job){if(!background)job.background=false;return job;}
  job={index,blob,background,state:'queued',started:performance.now()};
  job.promise=new Promise((resolve,reject)=>Object.assign(job,{resolve,reject}));job.promise.catch(()=>{});
  this.jobs.set(index,job);this.notify(index,{phase:'queued',message:background?'Готовим следующую страницу заранее':'Быстрый режим · готовим страницу на устройстве'});
  if(!background&&this.batchSize()===3){const capacity=this.serverSlots.length||(this.getKey===directKey?Math.max(1,directKeys(this.keyScope).length):1),start=Math.floor(index/3)*3,end=Math.min(this.entries.length,start+(this.config.saveData?3:Math.min(3,capacity)*3));for(let n=start;n<end;n++)if(!this.jobs.has(n))this.request(n,null,true);}
  queueMicrotask(()=>this.drain());return job;
 }
 batchSize(){return this.config.directBatchPages===1?1:3;}
 async jsonCacheId(blob,index){return await this.cacheKey(blob,{...this.config,direction:this.direction,font:'auto',inpaint:'fast'},this.scope)+':chapter='+encodeURIComponent(this.config.contextKey||'chapter')+':page='+index;}
 async cached(job){
  const sourceStart=performance.now(),blob=job.blob||await waitFor(this.entries[job.index].async('blob'),AbortSignal.any([this.controller.signal,AbortSignal.timeout(30000)]));job.sourceReadMs=Math.round(performance.now()-sourceStart);const cacheStart=performance.now();this.controller.signal.throwIfAborted();job.blob=blob;
  job.cacheId=await this.jsonCacheId(blob,job.index);
  if(this.config.cache&&!this.bypass.has(job.index)){const hit=await this.readCache(job.cacheId,this.scope);if(hit?.kind==='manga-json'&&hit.page)return {...hit.page,cacheHit:true};}
  job.cacheMs=Math.round(performance.now()-cacheStart);return null;
 }
 async drain(){
  const capacity=this.serverSlots.length||(this.getKey===directKey?Math.max(1,directKeys(this.keyScope).length):1);if(this.active>=Math.min(3,capacity)||this.controller.signal.aborted)return;this.active++;
  try{while(!this.controller.signal.aborted){
   const pending=[...this.jobs.values()].filter(j=>j.state==='queued'),first=pending.find(j=>!j.background)||pending[0];if(!first)break;
   const block=Math.floor(first.index/this.batchSize());let group=pending.filter(j=>Math.floor(j.index/this.batchSize())===block).sort((a,b)=>a.index-b.index);
   for(const job of group){job.state='running';job.queueMs=Math.round(performance.now()-job.started);}
   try{
    await Promise.all(group.map(async job=>{try{const hit=await this.cached(job);if(hit)this.finish(job,hit);}catch(error){this.fail(job,error);job.state='failed';}}));group=group.filter(j=>j.state==='running');if(!group.length)continue;
    const available=this.serverSlots.length?this.serverSlots.map(slot=>'oracle-slot:'+slot):this.getKey===directKey?await restoreDirectKeys(this.keyScope):[this.getKey(this.keyScope)];const key=available.find(k=>!this.keyBusy.has(k));if(key){this.keyBusy.add(key);first.keyLease=key;}if(!key)throw Error('Введи ключ Google AI Studio в настройках перевода.');
    const prepare=async job=>{
     this.notify(job.index,{phase:'detecting',message:this.config.directInput==='vision'?'Чистая страница · координаты и текст определит Google':DIRECT_DETECTORS.find(v=>v.id===this.config.directDetector)?.label||'Подготовка страницы'});
     const begin=performance.now();const page=await this.prepare(job.blob,job.index,message=>this.notify(job.index,{phase:'detecting',message}));
     job.prepareMs=Math.round(performance.now()-begin);job.prepared=page;
     return {...page,page:job.index+1};
    };
    const results=await Promise.allSettled(group.map(prepare));const prepared=[];group=group.filter((job,i)=>{if(results[i].status==='fulfilled'){prepared.push(results[i].value);return true;}this.fail(job,results[i].reason);return false;});if(!group.length)continue;this.controller.signal.throwIfAborted();
    const nonempty=prepared.filter(p=>p.regions.length||p.inputMode==='vision');
    if(!nonempty.length&&this.config.directDetector!=='rtdetr')throw Error('Лёгкий поиск не нашёл реплики. Выбери другой детектор или самостоятельный поиск Google.');
    let translated=[],cloudMs=0,usage,diagnostics;
    if(nonempty.length){
     const regions=nonempty.reduce((n,p)=>n+p.regions.length,0);
     if(regions>300)throw Error('Слишком много реплик для пакета. Уменьши область поиска текста.');
     for(const job of group)this.notify(job.index,{phase:'translating',message:'Напрямую в Google · '+nonempty.length+' стр., минимальные размышления',model:this.config.directModel,totalRegions:prepared.find(p=>p.page===job.index+1)?.regions.length,completedRegions:0,attempt:1});
     const start=performance.now();const options={key,model:this.config.directModel,language:this.config.language,direction:this.direction,gemmaProfile:this.config.gemmaProfile||'native',context:[...this.context].filter(([i])=>i<group[0].index).sort((a,b)=>a[0]-b[0]).map(([,text])=>text).join('\n').slice(-1200),signal:this.controller.signal,timeoutMs:this.config.directTimeoutMs,onDiagnostic:value=>{
      const names={prepared:'Запрос подготовлен',sending:'Отправляем в Google · соединение и CORS',uploading:'Отправляем изображение в Google',waiting:'Изображение отправлено · ждём Google',headers:'Google начал отвечать',streaming:'Gemma присылает перевод · поток активен',receiving:'Получаем ответ Google',received:'Ответ получен · проверяем JSON',complete:'JSON проверен',error:'Ошибка Google'};
      const local={batchPages:nonempty.map(p=>p.page),sourceBytes:group.reduce((sum,j)=>sum+(j.blob?.size||0),0),queueMs:first.queueMs,sourceReadMs:first.sourceReadMs,fingerprintAndCacheMs:first.cacheMs,clientPreparationMs:first.prepareMs,...first.prepared?.prepareTimings};
      first.diagnostics={...value,local};for(const job of group)this.notify(job.index,{phase:'translating',message:names[value.stage]||'Google · обработка',model:this.config.directModel,completedRegions:value.metrics?.completedRegions||0,totalRegions:job.prepared?.regions.length,diagnostics:first.diagnostics});
     }};const packs=[];let pack=[],count=0,bytes=0;for(const page of nonempty){const size=page.image?.length||0;if(pack.length&&(count+page.regions.length>100||bytes+size>18*1024*1024)){packs.push(pack);pack=[];count=0;bytes=0;}pack.push(page);count+=page.regions.length;bytes+=size;}if(pack.length)packs.push(pack);
     const answer={pages:[],usage:[]};for(const pack of packs){const result=await this.callGoogle(pack,options);answer.pages.push(...result.pages);answer.usage.push(result.usage);answer.diagnostics=result.diagnostics;}
     diagnostics=first.diagnostics||answer.diagnostics;cloudMs=Math.round(performance.now()-start);translated=answer.pages;usage=answer.usage.length===1?answer.usage[0]:answer.usage;
    }
    this.controller.signal.throwIfAborted();
    if(nonempty.some(source=>!translated.some(p=>p.page===source.page)))throw Error('Google пропустил страницу пакета. Оригинал сохранён.');
    for(const job of group){
     const source=prepared.find(p=>p.page===job.index+1),page=translated.find(p=>p.page===job.index+1)||{page:source.page,width:source.width,height:source.height,regions:[],timings:{detectionMs:source.detectionMs,ocrMs:0}};
     page.timings={...page.timings,translationMs:cloudMs};page.usage=usage;page.engine=this.config.directViaOracle?'Google через Oracle → Canvas Worker':'Google → Canvas Worker';page.diagnostics=diagnostics;
     this.context.set(job.index,page.regions.map(r=>r.ru_translation).filter(Boolean).join(' '));while(this.context.size>6)this.context.delete(this.context.keys().next().value);
     if(this.config.cache){const {diagnostics,...cachedPage}=page;await this.writeCache(job.cacheId,this.scope,{kind:'manga-json',page:cachedPage});}
     this.finish(job,page);
    }
   }catch(error){for(const job of group)if(job.state!=='done')this.fail(job,error);}finally{if(first.keyLease)this.keyBusy.delete(first.keyLease);}
  }}finally{this.active--;if([...this.jobs.values()].some(j=>j.state==='queued')&&!this.controller.signal.aborted)queueMicrotask(()=>this.drain());}
 }
 finish(job,page){this.bypass.delete(job.index);this.context.set(job.index,page.regions.map(r=>r.ru_translation).filter(Boolean).join(' '));while(this.context.size>6)this.context.delete(this.context.keys().next().value);job.state='done';job.blob=null;job.resolve(page);for(const old of [...this.jobs.values()].filter(j=>j.state==='done').slice(0,-12)){this.jobs.delete(old.index);this.progress.delete(old.index);}}
 fail(job,error){this.jobs.delete(job.index);const raw=job.diagnostics||error.diagnostics,diagnostics=raw?{...raw,local:{...raw.local,totalMs:Math.round(performance.now()-job.started)}}:undefined;job.reject(error);this.notify(job.index,{phase:'error',message:error.message,diagnostics});}
 async render(blob,index,font,status,config={},signal,background=false){
  const renderStarted=performance.now(),fromMemory=this.jobs.get(index)?.state==='done';
  signal?.throwIfAborted();const listeners=this.listeners.get(index)||new Set();if(status)listeners.add(status);this.listeners.set(index,listeners);
  const last=this.progress.get(index);if(last)status?.(last);
  try{
   const renderCacheId=(await this.jsonCacheId(blob,index))+':render-v5:'+this.config.inpaint+':'+font;
   if(this.config.cache&&!this.bypass.has(index)){const cached=await this.readCache(renderCacheId,this.scope);if(cached?.renderedImage)return {...cached,cacheHit:true,timings:{...cached.timings,directTotalMs:Math.round(performance.now()-renderStarted)}};}
   const job=this.request(index,blob,background),stored=await waitFor(job.promise,signal),page=fromMemory?{...stored,cacheHit:true,diagnostics:undefined}:stored;signal?.throwIfAborted();
   this.notify(index,{phase:'cleaning',message:page.cacheHit?'Из кэша устройства · вставляем русский текст':'Лёгкая очистка и русский набор',completedRegions:0,totalRegions:page.regions.length,diagnostics:page.diagnostics});
   const painting=this.renderPage(blob,page,font,value=>this.notify(index,{...value,completedRegions:value.cleanedRegions||0,totalRegions:page.regions.filter(r=>r.ru_translation?.trim()).length,diagnostics:page.diagnostics})).then(result=>{if(signal?.aborted){result.renderedBitmap?.close();throw signal.reason;}return result;});
   let result;try{result=await waitFor(painting,signal);}catch(error){error.stage='render';throw error;}signal?.throwIfAborted();
   if(this.config.cache&&result.cacheImage){const {renderedBitmap,cacheImage,diagnostics,...save}=result;await this.writeCache(renderCacheId,this.scope,{...save,renderedImage:cacheImage,renderedMime:'image/webp'});}delete result.cacheImage;
   result.timings={...result.timings,directTotalMs:Math.round(performance.now()-(fromMemory?renderStarted:job.started))};
   if(page.diagnostics)result.diagnostics={...page.diagnostics,stage:'ready',cleanup:result.inpaint,typesetting:result.typesetting,local:{...page.diagnostics.local,inpaintMs:result.timings.inpaintMs,typesetMs:result.timings.typesetMs,renderMs:result.timings.renderMs,totalMs:result.timings.directTotalMs}};
   return result;
  }finally{if(status)listeners.delete(status);if(!listeners.size)this.listeners.delete(index);}
 }
 invalidate(index){if(this.jobs.get(index)?.state==='running')return;this.jobs.delete(index);this.progress.delete(index);this.bypass.add(index);}
 async callGoogle(pages,options){
  const oracle=this.config.directViaOracle&&this.service?.();
  if(this.config.directViaOracle&&this.google===callDirectGoogle&&!oracle)throw Error('Для перевода личным ключом подключи Oracle в профиле.');
  const slot=this.serverSlots.find(slot=>options.key==='oracle-slot:'+slot);
  if(this.serverSlots.length&&!oracle)throw Error('Для серверных ключей нужен Oracle.');
  return this.google(pages,{...options,...(oracle?{gemmaProfile:'compat',transport:async({json,signal})=>{const data=await oracle.request('/reader/google/generate',{method:'POST',body:{...(slot===undefined?{key:options.key}:{slot}),model:options.model,request:JSON.parse(json)},signal});return {status:200,text:JSON.stringify(data)};}}:{})});
 }
 async compare(blob,index,{signal,onProgress}={}){const key=this.getKey(this.keyScope)||(this.getKey===directKey?await restoreDirectKey(this.keyScope):'');return compareDirectInputs({blob,index,prepare:this.prepare,google:(pages,options)=>this.callGoogle(pages,options),key,config:this.config,direction:this.direction,signal:signal||this.controller.signal,onProgress});}
 prefetch(index){const count=this.serverSlots.length||(this.getKey===directKey?Math.max(1,directKeys(this.keyScope).length):1);if(!this.jobs.has(index-1))return;for(let n=index;n<Math.min(this.entries.length,index+count*this.batchSize());n++)if(!this.jobs.has(n))this.request(n,null,true);}
 renderCanvas(blob,page,font,status){
  return this.canvasTask({blob,page,font,mode:this.config.inpaint||'hybrid',cache:this.config.cache},status);
 }
 canvasTask(message,status){
  this.controller.signal.throwIfAborted();
  if(!this.worker){
   this.worker=new Worker(new URL('./manga-canvas.worker.js',import.meta.url),{type:'module'});
   this.worker.onmessage=({data})=>{const job=this.renders.get(data.id);if(job){if(data.status){job.status?.(data.status);return;}this.renders.delete(data.id);data.error?job.reject(Error(data.error)):job.resolve(data.result);}};
   this.worker.onerror=()=>{for(const job of this.renders.values())job.reject(Error('Не удалось отрисовать страницу. Повтори перевод.'));this.renders.clear();this.worker?.terminate();this.worker=null;};
  }
  const id=++this.serial;return new Promise((resolve,reject)=>{this.renders.set(id,{resolve,reject,status});this.worker.postMessage({id,...message});});
 }
 close(){this.controller.abort(cancelled());this.worker?.terminate();for(const job of [...this.jobs.values(),...this.renders.values()])job.reject(this.controller.signal.reason);this.jobs.clear();this.renders.clear();this.listeners.clear();this.progress.clear();this.context.clear();}
}
