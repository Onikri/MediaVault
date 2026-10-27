import {getTranslation,putTranslation} from './translation-cache.js';

export async function parseSse(response,onEvent,signal){
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
 try{while(true){signal.throwIfAborted();const{done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});buffer=buffer.replaceAll('\r\n','\n');let boundary;
  while((boundary=buffer.indexOf('\n\n'))>=0){const block=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);let type='message',data=[];for(const line of block.split('\n')){if(line.startsWith('event:'))type=line.slice(6).trim();if(line.startsWith('data:'))data.push(line.slice(5).trimStart());}if(data.length)await onEvent(type,JSON.parse(data.join('\n')));}
  if(buffer.length>2*1024*1024)throw Error('Событие перевода превышает лимит.');if(done)break;
 }}finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
export async function chapterFingerprint(item,names){const value=[item.id,item.size,item.chunks.map(c=>[c.fileId,c.iv]),names],digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value)));return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');}

export class VmChapter {
 constructor({item,names,direction,scope,service,cache=true,policy}){
  Object.assign(this,{item,names,direction,scope,service,cache,policy});this.controller=new AbortController();this.waiters=new Map();this.pages=new Map();this.streams=new Map();this.id=null;this.opening=null;this.fingerprint=chapterFingerprint(item,names);this.worker=null;this.renderJobs=new Map();this.serial=0;
 }
 cacheId(page){return 'manga-json:'+this.scope+':'+this.manifest+':'+this.policy+':'+this.direction+':'+page;}
 async open(){
  if(!this.opening)this.opening=(async()=>{const s=await this.service().openReaderChapter(this.item,this.names,this.direction,this.controller.signal);this.id=s.id;this.manifest=await this.fingerprint;if(this.manifest!==s.manifest)throw Error('Состав главы изменился. Открой её заново.');if(this.policy&&s.policy!==this.policy)throw Error('Версия перевода обновилась. Открой читалку заново.');this.policy=s.policy;})();
  return this.opening;
 }
 async json(page,status){
  this.controller.signal.throwIfAborted();this.manifest=await this.fingerprint;
  if(this.pages.has(page))return this.pages.get(page);
  if(this.cache&&this.policy){const hit=await getTranslation(this.cacheId(page),this.scope);if(hit){this.pages.set(page,hit.page);return {...hit.page,cacheHit:true};}}
  status?.('ВМ · получаем перевод с координатами');await this.open();
  let waiter=this.waiters.get(page);if(!waiter){waiter={};waiter.promise=new Promise((resolve,reject)=>Object.assign(waiter,{resolve,reject}));this.waiters.set(page,waiter);}
  if(![...this.streams.keys()].some(start=>page>=start&&page<start+12))this.stream(page);
  return waiter.promise;
 }
 stream(start){
  const task=(async()=>{
   const response=await this.service().request('/api/v1/chapters/'+this.id+'/stream?currentPage='+start,{raw:true,signal:this.controller.signal});
   await parseSse(response,async(type,value)=>{
    if(type==='page_translated'){
     if(value.manifest!==this.manifest||value.policy!==this.policy||!Number.isInteger(value.page)||value.page<1||value.page>this.names.length)throw Error('Перевод относится к другой главе.');
     this.pages.set(value.page,value);while(this.pages.size>32)this.pages.delete(this.pages.keys().next().value);
     if(this.cache)await putTranslation(this.cacheId(value.page),this.scope,{kind:'manga-json',page:value});
     this.waiters.get(value.page)?.resolve(value);this.waiters.delete(value.page);
    }else if(type==='page_error'){this.waiters.get(value.page)?.reject(Error(value.message));this.waiters.delete(value.page);}
   },this.controller.signal);
  })().catch(error=>{if(error.status===404){this.id=null;this.opening=null;}for(const[p,w]of this.waiters)if(p>=start&&p<start+12){w.reject(error);this.waiters.delete(p);}}).finally(()=>{this.streams.delete(start);for(const[p,w]of this.waiters)if(p>=start&&p<start+12){w.reject(Error('Поток перевода завершился без страницы. Повтори.'));this.waiters.delete(p);}});
  this.streams.set(start,task);
 }
 touch(page){if(this.id)this.service().request('/api/v1/chapters/'+this.id+'/touch',{method:'POST',body:{currentPage:page},signal:this.controller.signal}).catch(()=>{});}
 async render(blob,index,font,status,config={}){
  const page=await this.json(index+1,status);this.controller.signal.throwIfAborted();status?.('Устройство · очищаем фон и набираем русский текст');
  if(config.inpaint==='quality'){
   if(!config.allowDownloads)throw Error('Разреши загрузку LaMa или выбери быструю очистку без весов.');
   const {translateLmt}=await import('./lmt-client.js');
   const regions=page.regions.map(r=>({id:r.uid,bbox:r.text_bbox,layout_bbox:r.layout_bbox,class:r.detection_class}));
   const prepared={id:'P'+page.page,width:page.width,height:page.height,regions,detectionMs:page.timings.detectionMs};
   const translation={...prepared,regions:page.regions.map((r,i)=>({...regions[i],translation:r.ru_translation,source_text:r.source_text,status:r.ru_translation?'translated':'non_text',font_style:r.font_style,speech_style:r.speech_register,appearance:{bold:r.font_style==='bold_scream',italic:false,fill_color:'#151515',stroke_color:['sfx','sign','whisper_aside'].includes(r.text_category)?'#ffffff':'none',stroke_width:2,alignment:'center',rotation:0}}))};
   return translateLmt(blob,{...config,mode:'gemma',operation:'gemma-render',prepared,translation},this.controller.signal,status);
  }
  if(!this.worker){this.worker=new Worker(new URL('./manga-canvas.worker.js',import.meta.url),{type:'module'});this.worker.onmessage=({data})=>{const j=this.renderJobs.get(data.id);if(j){this.renderJobs.delete(data.id);data.error?j.reject(Error(data.error)):j.resolve(data.result);}};this.worker.onerror=()=>{for(const j of this.renderJobs.values())j.reject(Error('Обработчик страницы остановился.'));this.renderJobs.clear();};}
  const id=++this.serial;return new Promise((resolve,reject)=>{this.renderJobs.set(id,{resolve,reject});this.worker.postMessage({id,blob,page,font});});
 }
 close(){this.controller.abort();this.worker?.terminate();for(const w of [...this.waiters.values(),...this.renderJobs.values()])w.reject(new DOMException('Читалка закрыта','AbortError'));this.waiters.clear();this.renderJobs.clear();if(this.id)this.service().request('/api/v1/chapters/'+this.id,{method:'DELETE'}).catch(()=>{});}
}
