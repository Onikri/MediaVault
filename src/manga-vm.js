import {getTranslation,putTranslation} from './translation-cache.js';

function abortReason(signal){return signal?.reason||new DOMException('Операция отменена','AbortError');}
function waitFor(promise,signal){
 if(!signal)return promise;if(signal.aborted)return Promise.reject(abortReason(signal));
 return new Promise((resolve,reject)=>{const abort=()=>{cleanup();reject(abortReason(signal));},cleanup=()=>signal.removeEventListener('abort',abort);signal.addEventListener('abort',abort,{once:true});promise.then(value=>{cleanup();resolve(value);},error=>{cleanup();reject(error);});});
}
async function readSseChunk(reader,signal,idleTimeoutMs){
 let timer,abort;
 try{return await new Promise((resolve,reject)=>{
  abort=()=>reject(abortReason(signal));signal.addEventListener('abort',abort,{once:true});
  timer=setTimeout(()=>{const error=Error('Нет событий от ВМ: соединение могло прерваться. Повтори перевод.');error.name='StreamIdleError';reject(error);},idleTimeoutMs);
  reader.read().then(resolve,reject);
 });}finally{clearTimeout(timer);signal.removeEventListener('abort',abort);}
}
export async function parseSse(response,onEvent,signal,{idleTimeoutMs=30000,initialTimeoutMs=90000}={}){
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',received=false;
 try{while(true){signal.throwIfAborted();const{done,value}=await readSseChunk(reader,signal,received?idleTimeoutMs:initialTimeoutMs);if(value?.length)received=true;buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});buffer=buffer.replaceAll('\r\n','\n');let boundary;
  while((boundary=buffer.indexOf('\n\n'))>=0){const block=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);let type='message',data=[];for(const line of block.split('\n')){if(line.startsWith('event:'))type=line.slice(6).trim();if(line.startsWith('data:'))data.push(line.slice(5).trimStart());}if(data.length)await onEvent(type,JSON.parse(data.join('\n')));}
  if(buffer.length>2*1024*1024)throw Error('Событие перевода превышает лимит.');if(done)break;
 }}finally{reader.cancel().catch(()=>{});reader.releaseLock();}
}
export async function chapterFingerprint(item,names){const value=[item.id,item.size,item.chunks.map(c=>[c.fileId,c.iv]),names],digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value)));return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');}

export class VmChapter {
 constructor({item,names,direction,scope,service,model,cache=true,policy,canStart=()=>true,streamIdleMs=30000}){
  Object.assign(this,{item,names,direction,scope,service,model,cache,policy,canStart,streamIdleMs});this.controller=new AbortController();this.waiters=new Map();this.pages=new Map();this.streams=new Map();this.id=null;this.opening=null;this.fingerprint=chapterFingerprint(item,names);this.worker=null;this.renderJobs=new Map();this.serial=0;this.statusListeners=new Map();this.progress=new Map();
 }
 cacheId(page){return 'manga-json:'+this.scope+':'+this.manifest+':'+this.policy+':'+this.direction+':'+page;}
 async open(){
  if(!this.opening)this.opening=(async()=>{const s=await this.service().openReaderChapter(this.item,this.names,this.direction,this.controller.signal,this.model);this.id=s.id;this.manifest=await this.fingerprint;if(this.manifest!==s.manifest)throw Error('Состав главы изменился. Открой её заново.');if(this.policy&&s.policy!==this.policy)throw Error('Версия перевода обновилась. Открой читалку заново.');this.policy=s.policy;})().catch(error=>{this.opening=null;if(this.id){const id=this.id;this.id=null;this.service().request('/api/v1/chapters/'+id,{method:'DELETE'}).catch(()=>{});}throw error;});
  return this.opening;
 }
 observe(page,callback){
  if(!callback)return()=>{};let listeners=this.statusListeners.get(page);if(!listeners){listeners=new Set();this.statusListeners.set(page,listeners);}listeners.add(callback);
  if(this.progress.has(page))callback(this.progress.get(page));
  return()=>{listeners.delete(callback);if(!listeners.size)this.statusListeners.delete(page);};
 }
 notify(page,value){
  const state={...(typeof value==='string'?{message:value}:value),page,clientReceivedAt:Date.now()};this.progress.set(page,state);
  while(this.progress.size>32)this.progress.delete(this.progress.keys().next().value);
  for(const callback of this.statusListeners.get(page)||[])callback(state);
 }
 async json(page,status,signal=this.controller.signal){
  this.controller.signal.throwIfAborted();signal.throwIfAborted();const unsubscribe=this.observe(page,status);
  try{
   this.manifest=await this.fingerprint;
   if(this.pages.has(page)){this.notify(page,{phase:'cache',message:'Перевод страницы получен из памяти'});return this.pages.get(page);}
   if(this.cache&&this.policy){const hit=await getTranslation(this.cacheId(page),this.scope);if(hit){this.pages.set(page,hit.page);this.notify(page,{phase:'cache',message:'Готовый перевод найден в кэше устройства'});return {...hit.page,cacheHit:true};}}
   if(!this.canStart())throw Error('Добавь ключ Google AI Studio в настройках ВМ.');
   if(!this.id)this.notify(page,{phase:'opening',message:'Открываем главу на ВМ…'});await waitFor(this.open(),signal);signal.throwIfAborted();
   let waiter=this.waiters.get(page);if(!waiter){waiter={};waiter.promise=new Promise((resolve,reject)=>Object.assign(waiter,{resolve,reject}));waiter.promise.catch(()=>{});this.waiters.set(page,waiter);}
   let stream=[...this.streams.values()].find(s=>page>=s.start&&page<s.start+9&&!s.failedPages.has(page));
   if(!stream)stream=this.stream(page);waiter.streamId=stream.id;
   return await waitFor(waiter.promise,signal);
  }finally{unsubscribe();}
 }
 stream(start){
  const entry={id:++this.serial,start,failedPages:new Set()};this.streams.set(entry.id,entry);
  const broadcast=value=>{for(const[page,w]of this.waiters)if(w.streamId===entry.id)this.notify(page,value);};
  entry.task=(async()=>{
   const response=await this.service().request('/api/v1/chapters/'+this.id+'/stream?currentPage='+start,{raw:true,signal:this.controller.signal});
   await parseSse(response,async(type,value)=>{
    if(type==='page_translated'){
     if(value.manifest!==this.manifest||value.policy!==this.policy||!Number.isInteger(value.page)||value.page<1||value.page>this.names.length)throw Error('Перевод относится к другой главе.');
     this.pages.set(value.page,value);while(this.pages.size>32)this.pages.delete(this.pages.keys().next().value);
     if(this.cache)await putTranslation(this.cacheId(value.page),this.scope,{kind:'manga-json',page:value});
     this.notify(value.page,{phase:'received',message:'Перевод получен с ВМ · готовим русский слой',completedRegions:value.regions?.length||0,totalRegions:value.regions?.length||0,retryAtMs:null});
     this.waiters.get(value.page)?.resolve(value);this.waiters.delete(value.page);
    }else if(type==='page_error'){
     entry.failedPages.add(value.page);const w=this.waiters.get(value.page);
     if(w?.streamId===entry.id){w.reject(Error(value.message));this.waiters.delete(value.page);}
    }else if(type==='status'||type==='progress'){
     if(Number.isInteger(value.page)){if(value.page>=start&&value.page<start+9)this.notify(value.page,value);}
     else broadcast(value);
    }else if(type==='ready')broadcast({phase:'queued',message:'ВМ приняла запрос · проверяем кэш и очередь'});
   },this.controller.signal,{idleTimeoutMs:this.streamIdleMs});
  })().catch(error=>{
   if(error.status===404){this.id=null;this.opening=null;}
   for(const[page,w]of this.waiters)if(w.streamId===entry.id){w.reject(error);this.waiters.delete(page);}
  }).finally(()=>{
   this.streams.delete(entry.id);
   for(const[page,w]of this.waiters)if(w.streamId===entry.id){w.reject(Error('Поток перевода завершился без страницы. Повтори.'));this.waiters.delete(page);}
  });
  return entry;
 }
 touch(page){if(this.id)this.service().request('/api/v1/chapters/'+this.id+'/touch',{method:'POST',body:{currentPage:page},signal:this.controller.signal}).catch(()=>{});}
 async render(blob,index,font,status,config={},signal=this.controller.signal){
  const page=await this.json(index+1,status,signal);this.controller.signal.throwIfAborted();signal.throwIfAborted();status?.({phase:'cleaning',message:'Устройство · очищаем фон и набираем русский текст',retryAtMs:null,completedRegions:page.regions.length,totalRegions:page.regions.length});
  if(['quality','moebius'].includes(config.inpaint)&&!config.allowDownloads)throw Error('Разреши загрузку выбранной модели восстановления.');
  if(!this.worker){this.worker=new Worker(new URL('./manga-canvas.worker.js',import.meta.url),{type:'module'});this.worker.onmessage=({data})=>{const j=this.renderJobs.get(data.id);if(j){if(data.status){j.status?.(data.status);return;}this.renderJobs.delete(data.id);data.error?j.reject(Error(data.error)):j.resolve(data.result);}};this.worker.onerror=()=>{for(const j of this.renderJobs.values())j.reject(Error('Обработчик страницы остановился.'));this.renderJobs.clear();this.worker?.terminate();this.worker=null;};}
  const id=++this.serial;return new Promise((resolve,reject)=>{this.renderJobs.set(id,{resolve,reject,status});this.worker.postMessage({id,blob,page,font,mode:config.inpaint||'fast'});});
 }
 close(){this.controller.abort();this.worker?.terminate();for(const w of [...this.waiters.values(),...this.renderJobs.values()])w.reject(new DOMException('Читалка закрыта','AbortError'));this.waiters.clear();this.renderJobs.clear();this.statusListeners.clear();this.progress.clear();if(this.id)this.service().request('/api/v1/chapters/'+this.id,{method:'DELETE'}).catch(()=>{});}
}
