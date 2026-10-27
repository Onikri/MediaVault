// The AGPL translation engine stays in a separate, lazily loaded iframe.
import {TRANSLATION_VERSION} from './manga-translation.js';
let instance=null,sequence=0;const pending=new Map();
export function stopLmt(reason=Error('LMT остановлен.')){
 const old=instance;instance=null;old?.frame.remove();old?.port.close();old?.cancelReady(reason);
 for(const task of pending.values())task.reject(reason);pending.clear();
}
async function connect(){
 if(instance)return instance.ready;
 const frame=document.createElement('iframe');frame.title='Локальный переводчик Libre Manga Translator';frame.hidden=true;
 const channel=new MessageChannel();let rejectReady;
 const ready=new Promise((resolve,reject)=>{
  rejectReady=reject;const timer=setTimeout(()=>stopLmt(Error('Не удалось запустить модуль LMT. Обнови страницу.')),20000);
  channel.port1.onmessage=({data})=>{
   if(data.ready){clearTimeout(timer);resolve(channel.port1);return;}
   const task=pending.get(data.id);if(!task)return;
   if(data.status){task.status?.(data.status);return;}
   pending.delete(data.id);data.error?task.reject(Error(data.error)):task.resolve(data.result);
  };
  frame.onload=()=>frame.contentWindow.postMessage({type:'mv-lmt-connect'},location.origin,[channel.port2]);
  frame.onerror=()=>{clearTimeout(timer);stopLmt(Error('Не удалось загрузить LMT.'));};
  frame.addEventListener('mv-dispose',()=>clearTimeout(timer),{once:true});
 });
 instance={frame,port:channel.port1,ready,cancelReady:reason=>{frame.dispatchEvent(new Event('mv-dispose'));rejectReady(reason);}};
 const url=new URL('lmt/index.html',new URL(import.meta.env.BASE_URL,location.href));
 // HTML has a stable path on Pages. Tie it to this hashed app bundle so a
 // freshly updated selector cannot start an older, cached translation engine.
 url.searchParams.set('engine',TRANSLATION_VERSION+':'+new URL(import.meta.url).pathname);
 frame.src=url.href;document.body.append(frame);return ready;
}
export async function translateLmt(blob,config,signal,status){
 if(!config.allowDownloads)throw Error('Разреши загрузку моделей в настройках LMT.');
 signal?.throwIfAborted();const port=await connect();signal?.throwIfAborted();
 const bytes=await blob.arrayBuffer();signal?.throwIfAborted();const id=++sequence;
 return new Promise((resolve,reject)=>{
  // Terminating the iframe cancels active inference/downloads and frees its GPU.
  // The next queued page gets a fresh engine, rather than a permanently busy one.
  const abort=()=>stopLmt(new DOMException('Отменено','AbortError'));
  signal?.addEventListener('abort',abort,{once:true});
  const finish=fn=>v=>{signal?.removeEventListener('abort',abort);fn(v);};
  pending.set(id,{resolve:finish(resolve),reject:finish(reject),status});
  try{port.postMessage({type:'translate',id,bytes,config},[bytes]);}catch(e){pending.delete(id);finish(reject)(e);}
 });
}
globalThis.addEventListener?.('mediavault-locked',()=>stopLmt());
