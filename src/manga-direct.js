import {translateLmt} from './lmt-client.js';
import {callDirectGoogle} from './manga-direct-api.js';
import {directKey} from './manga-direct-key.js';
import {translationCacheKey,getTranslation,putTranslation} from './translation-cache.js';

const cancelled=()=>new DOMException('Читалка закрыта','AbortError');
function waitFor(promise,signal){
 if(!signal)return promise;signal.throwIfAborted();
 return new Promise((resolve,reject)=>{
  const abort=()=>{cleanup();reject(signal.reason);},cleanup=()=>signal.removeEventListener('abort',abort);
  signal.addEventListener('abort',abort,{once:true});promise.then(v=>{cleanup();resolve(v);},e=>{cleanup();reject(e);});
 });
}
// One personal Google request at a time, exactly one page. The visible page
// outranks queued prefetch; a slow adjacent Drive download never holds it up.
export class DirectChapter{
 constructor({entries,scope,keyScope,config,direction='rtl',prepare,google=callDirectGoogle,cacheKey=translationCacheKey,readCache=getTranslation,writeCache=putTranslation,renderPage,getKey=directKey}){
  Object.assign(this,{entries,scope,keyScope,config,direction,google,cacheKey,readCache,writeCache,getKey});
  this.prepare=prepare||((blob,index,status)=>config.directDetector==='rtdetr'?translateLmt(blob,{...config,allowDownloads:true,mode:'gemma',operation:'gemma-prepare',fastDirect:true,pageIndex:index,direction},this.controller.signal,status):this.canvasTask({operation:'direct-prepare',blob,index,direction}));
  this.renderPage=renderPage||this.renderCanvas.bind(this);this.controller=new AbortController();this.jobs=new Map();this.listeners=new Map();this.progress=new Map();this.context=new Map();this.active=false;this.worker=null;this.renders=new Map();this.serial=0;this.bypass=new Set();
 }
 notify(index,value){this.progress.set(index,value);for(const fn of this.listeners.get(index)||[])fn(value);}
 request(index,blob,background=false){
  this.controller.signal.throwIfAborted();let job=this.jobs.get(index);
  if(job){if(!background)job.background=false;return job;}
  job={index,blob,background,state:'queued',started:performance.now()};
  job.promise=new Promise((resolve,reject)=>Object.assign(job,{resolve,reject}));job.promise.catch(()=>{});
  this.jobs.set(index,job);this.notify(index,{phase:'queued',message:background?'Готовим следующую страницу заранее':'Быстрый режим · готовим страницу на устройстве'});
  queueMicrotask(()=>this.drain());return job;
 }
 async cached(job){
  const sourceStart=performance.now(),blob=job.blob||await this.entries[job.index].async('blob');job.sourceReadMs=Math.round(performance.now()-sourceStart);const cacheStart=performance.now();this.controller.signal.throwIfAborted();job.blob=blob;
  job.cacheId=await this.cacheKey(blob,{...this.config,direction:this.direction},this.scope)+':chapter='+encodeURIComponent(this.config.contextKey||'chapter')+':page='+job.index;
  if(this.config.cache&&!this.bypass.has(job.index)){const hit=await this.readCache(job.cacheId,this.scope);if(hit?.kind==='manga-json'&&hit.page)return {...hit.page,cacheHit:true};}
  job.cacheMs=Math.round(performance.now()-cacheStart);return null;
 }
 async drain(){
  if(this.active||this.controller.signal.aborted)return;this.active=true;
  try{while(!this.controller.signal.aborted){
   const pending=[...this.jobs.values()].filter(j=>j.state==='queued'),first=pending.find(j=>!j.background)||pending[0];if(!first)break;
   first.state='running';first.queueMs=Math.round(performance.now()-first.started);let group=[first];
   try{
    const hit=await this.cached(first);if(hit){this.finish(first,hit);continue;}
    const key=this.getKey(this.keyScope);if(!key)throw Error('Введи личный ключ Google AI Studio в настройках быстрого режима.');
    const prepare=async job=>{
     this.notify(job.index,{phase:'detecting',message:this.config.directDetector==='rtdetr'?'Устройство · RT-DETR INT8, только координаты текста':'Устройство · лёгкий поиск английских текстовых блоков'});
     const begin=performance.now();const page=await this.prepare(job.blob,job.index,message=>this.notify(job.index,{phase:'detecting',message}));
     job.prepareMs=Math.round(performance.now()-begin);job.prepared=page;
     return {...page,page:job.index+1};
    };
    const prepared=[await prepare(first)];this.controller.signal.throwIfAborted();
    const nonempty=prepared.filter(p=>p.regions.length);
    if(!nonempty.length&&this.config.directDetector!=='rtdetr')throw Error('Лёгкий поиск не нашёл реплики. Выбери RT-DETR в настройках быстрого режима.');
    let translated=[],cloudMs=0,usage,diagnostics;
    if(nonempty.length){
     const regions=nonempty.reduce((n,p)=>n+p.regions.length,0);
     if(regions>100)throw Error('Слишком много реплик для быстрого запроса. Выбери одну страницу за запрос.');
     for(const job of group)this.notify(job.index,{phase:'translating',message:'Напрямую в Google · '+nonempty.length+' стр., минимальные размышления',model:this.config.directModel,totalRegions:prepared.find(p=>p.page===job.index+1)?.regions.length,completedRegions:0,attempt:1});
     const start=performance.now();const answer=await this.google(nonempty,{key,model:this.config.directModel,direction:this.direction,context:[...this.context].filter(([i])=>i<first.index).sort((a,b)=>a[0]-b[0]).map(([,text])=>text).join('\n').slice(-1200),signal:this.controller.signal,timeoutMs:this.config.directTimeoutMs,onDiagnostic:value=>{
      const names={prepared:'Запрос подготовлен',sending:'Отправляем в Google · соединение и CORS',uploading:'Отправляем изображение в Google',waiting:'Изображение отправлено · ждём Google',headers:'Google начал отвечать',receiving:'Получаем ответ Google',received:'Ответ получен · проверяем JSON',complete:'JSON проверен',error:'Ошибка Google'};
      const local={sourceBytes:first.blob?.size,queueMs:first.queueMs,sourceReadMs:first.sourceReadMs,fingerprintAndCacheMs:first.cacheMs,clientPreparationMs:first.prepareMs,...first.prepared?.prepareTimings};
      first.diagnostics={...value,local};for(const job of group)this.notify(job.index,{phase:'translating',message:names[value.stage]||'Google · обработка',model:this.config.directModel,diagnostics:first.diagnostics});
     }});
     diagnostics=first.diagnostics||answer.diagnostics;cloudMs=Math.round(performance.now()-start);translated=answer.pages;usage=answer.usage;
    }
    this.controller.signal.throwIfAborted();
    for(const job of group){
     const source=prepared.find(p=>p.page===job.index+1),page=translated.find(p=>p.page===job.index+1)||{page:source.page,width:source.width,height:source.height,regions:[],timings:{detectionMs:source.detectionMs,ocrMs:0}};
     page.timings={...page.timings,translationMs:cloudMs};page.usage=usage;page.engine='Google · напрямую → Canvas Worker';page.diagnostics=diagnostics;
     this.context.set(job.index,page.regions.map(r=>r.ru_translation).filter(Boolean).join(' '));while(this.context.size>6)this.context.delete(this.context.keys().next().value);
     if(this.config.cache){const {diagnostics,...cachedPage}=page;await this.writeCache(job.cacheId,this.scope,{kind:'manga-json',page:cachedPage});}
     this.finish(job,page);
    }
   }catch(error){for(const job of group)if(job.state!=='done')this.fail(job,error);}
  }}finally{this.active=false;}
 }
 finish(job,page){this.bypass.delete(job.index);this.context.set(job.index,page.regions.map(r=>r.ru_translation).filter(Boolean).join(' '));while(this.context.size>6)this.context.delete(this.context.keys().next().value);job.state='done';job.blob=null;job.resolve(page);for(const old of [...this.jobs.values()].filter(j=>j.state==='done').slice(0,-6)){this.jobs.delete(old.index);this.progress.delete(old.index);}}
 fail(job,error){this.jobs.delete(job.index);const raw=job.diagnostics||error.diagnostics,diagnostics=raw?{...raw,local:{...raw.local,totalMs:Math.round(performance.now()-job.started)}}:undefined;job.reject(error);this.notify(job.index,{phase:'error',message:error.message,diagnostics});}
 async render(blob,index,font,status,config={},signal,background=false){
  const renderStarted=performance.now(),fromMemory=this.jobs.get(index)?.state==='done';
  signal?.throwIfAborted();const listeners=this.listeners.get(index)||new Set();if(status)listeners.add(status);this.listeners.set(index,listeners);
  const last=this.progress.get(index);if(last)status?.(last);
  try{
   const job=this.request(index,blob,background),stored=await waitFor(job.promise,signal),page=fromMemory?{...stored,cacheHit:true,diagnostics:undefined}:stored;signal?.throwIfAborted();
   this.notify(index,{phase:'cleaning',message:page.cacheHit?'Из кэша устройства · вставляем русский текст':'Лёгкая очистка и русский набор',completedRegions:page.regions.length,totalRegions:page.regions.length,diagnostics:page.diagnostics});
   const painting=this.renderPage(blob,page,font).then(result=>{if(signal?.aborted){result.renderedBitmap?.close();throw signal.reason;}return result;});
   const result=await waitFor(painting,signal);signal?.throwIfAborted();
   result.timings={...result.timings,directTotalMs:Math.round(performance.now()-(fromMemory?renderStarted:job.started))};
   if(page.diagnostics)result.diagnostics={...page.diagnostics,stage:'ready',local:{...page.diagnostics.local,inpaintMs:result.timings.inpaintMs,typesetMs:result.timings.typesetMs,renderMs:result.timings.renderMs,totalMs:result.timings.directTotalMs}};
   return result;
  }finally{if(status)listeners.delete(status);if(!listeners.size)this.listeners.delete(index);}
 }
 invalidate(index){if(this.jobs.get(index)?.state==='running')return;this.jobs.delete(index);this.progress.delete(index);this.bypass.add(index);}
 prefetch(index){if(this.jobs.has(index-1)&&index<this.entries.length&&!this.jobs.has(index)&&this.getKey(this.keyScope))this.request(index,null,true);}
 renderCanvas(blob,page,font){
  return this.canvasTask({blob,page,font});
 }
 canvasTask(message){
  this.controller.signal.throwIfAborted();
  if(!this.worker){
   this.worker=new Worker(new URL('./manga-canvas.worker.js',import.meta.url),{type:'module'});
   this.worker.onmessage=({data})=>{const job=this.renders.get(data.id);if(job){this.renders.delete(data.id);data.error?job.reject(Error(data.error)):job.resolve(data.result);}};
   this.worker.onerror=()=>{for(const job of this.renders.values())job.reject(Error('Не удалось отрисовать страницу. Повтори перевод.'));this.renders.clear();this.worker?.terminate();this.worker=null;};
  }
  const id=++this.serial;return new Promise((resolve,reject)=>{this.renders.set(id,{resolve,reject});this.worker.postMessage({id,...message});});
 }
 close(){this.controller.abort(cancelled());this.worker?.terminate();for(const job of [...this.jobs.values(),...this.renders.values()])job.reject(this.controller.signal.reason);this.jobs.clear();this.renders.clear();this.listeners.clear();this.progress.clear();this.context.clear();}
}
