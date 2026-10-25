import {translateLmt} from './lmt-client.js';

const MAX_BYTES=10*1024*1024;
export function encodeImage(bytes){
 const data=new Uint8Array(bytes);let binary='';
 for(let i=0;i<data.length;i+=8192)binary+=String.fromCharCode(...data.subarray(i,i+8192));
 return btoa(binary);
}
export function decodeImage(text){return Uint8Array.from(atob(text),c=>c.charCodeAt(0)).buffer;}
function pause(ms,signal){return new Promise((resolve,reject)=>{
 signal?.throwIfAborted();
 const abort=()=>{clearTimeout(timer);reject(signal.reason||new DOMException('Отменено','AbortError'));};
 const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},ms);
 signal?.addEventListener('abort',abort,{once:true});
});}
export async function processOnBackend(blob,options,service,signal,status=()=>{},pollDelay=700){
 if(!service||service.status!=='connected')throw Error('Для обработки подключи backend в профиле владельца.');
 if(blob.size>MAX_BYTES)throw Error('Для обработки страница должна быть меньше 10 МБ.');
 signal?.throwIfAborted();
 const image=encodeImage(await blob.arrayBuffer());signal?.throwIfAborted();
 let id,finished=false,cancelled=false;
 const cancel=()=>{cancelled=true;if(id&&!finished)void service.request('/reader/jobs/'+id+'/cancel',{method:'POST',body:{},signal:AbortSignal.timeout(10000)}).catch(()=>{});};
 signal?.addEventListener('abort',cancel,{once:true});
 try{
  // Keep the bounded submission alive so a late response can still be cancelled.
  const submission=service.request('/reader/jobs',{method:'POST',body:{image,options},signal:AbortSignal.timeout(30000)});
  const created=await submission;id=created.id;
  if(typeof id!=='string'||!id)throw Error('Backend не вернул идентификатор задания.');
  if(cancelled){cancel();signal?.throwIfAborted();}
  const deadline=Date.now()+16*60*1000;
  while(Date.now()<deadline){
   signal?.throwIfAborted();
   const job=await service.request('/reader/jobs/'+id,{signal:AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(15000)])});
   status(job.status||'Обрабатываем страницу…');
   if(job.state==='done'){
    finished=true;
    const result={...job.result};
    for(const field of ['renderedImage','cleanedImage'])if(result[field])result[field]=decodeImage(result[field]);
    return result;
   }
   if(job.state==='error'||job.state==='cancelled'){finished=true;throw Error(job.status||'Обработка остановлена.');}
   await pause(pollDelay,signal);
  }
  throw Error('Backend не завершил страницу за отведённое время.');
 }finally{
  signal?.removeEventListener('abort',cancel);
  if(id&&!finished&&!cancelled)cancel();
 }
}

export function createPageProcessor({getConfig,getService,getChapter}){
 let queue=Promise.resolve();const cache=new Map();
 const remember=(key,result)=>{
  cache.set(key,result);const size=value=>(value.renderedImage?.byteLength||0)+(value.cleanedImage?.byteLength||0);
  let bytes=0;for(const value of cache.values())bytes+=size(value);
  while(cache.size>5||bytes>64*1024*1024){const first=cache.keys().next().value;bytes-=size(cache.get(first));cache.delete(first);}
 };
 const process=(blob,signal,status,pageIndex)=>{
  const config=structuredClone(getConfig()),chapter=getChapter();
  const key=chapter.id+':'+pageIndex+':'+JSON.stringify(config);
  const run=async()=>{
   signal.throwIfAborted();
   if(cache.has(key))return cache.get(key);
   const {translate,upscale,...lmt}=config;
   const until=Date.now()+20000;
   while(getService()?.status==='connecting'&&Date.now()<until)await pause(200,signal);
   const service=getService(),upscaling=!!upscale?.enabled;
   let result={regions:[]};
   const backendOptions={translate:!!translate&&lmt.engine==='backend',upscale:upscaling,
    language:lmt.language||'English',targetLanguage:lmt.targetLanguage||'Russian',ocr:lmt.ocr||'paddle',
    detector:lmt.detector||'comic-bubble',inpaint:lmt.inpaint||'fast',allowDownloads:!!lmt.allowDownloads,
    contextKey:chapter.collectionId||chapter.id,scale:upscale?.scale||2,model:upscale?.model||'auto',
    content:upscale?.content||'auto',tile:upscale?.tile||256};
   if(translate&&lmt.engine==='lmt')result=await translateLmt(blob,{...lmt,contextKey:backendOptions.contextKey},signal,status);
   else if(translate&&lmt.engine!=='backend'){
    if(!service||service.status!=='connected')throw Error('Для перевода подключи сервер в профиле владельца.');
    if(blob.size>MAX_BYTES)throw Error('Страница превышает 10 МБ.');
    result=await service.request('/reader/translate',{method:'POST',body:{image:encodeImage(await blob.arrayBuffer())},signal:AbortSignal.any([signal,AbortSignal.timeout(90000)])});
   }
   if(backendOptions.translate||upscaling){
    const input=result.renderedImage?new Blob([result.renderedImage],{type:result.renderedMime}):blob;
    const processed=await processOnBackend(input,backendOptions,service,signal,status);
    result={...result,...processed,regions:backendOptions.translate?processed.regions:result.regions};
   }
   signal.throwIfAborted();
   remember(key,result);
   return result;
  };
  const task=queue.catch(()=>{}).then(run);queue=task;return task;
 };
 process.remember=(pageIndex,result,patch={})=>{const config={...getConfig(),...patch},chapter=getChapter();remember(chapter.id+':'+pageIndex+':'+JSON.stringify(config),result);};
 return process;
}
