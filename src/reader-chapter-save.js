// Saves the open chapter on this device from the reader's own translation
// chain: rendered-page cache → cached Google JSON + local typesetting → new
// Google requests only for pages that were never translated. Nothing is sent
// to the VM for re-translation, and no page can block the file forever.
import {crc32,createPdf,createZip,imageExtension} from './chapter-archive.js';
import {retryAfterSeconds,setupGoogleError,transientGoogleError} from './google-transient.js';

export const SAVE_FORMATS={cbz:{label:'CBZ',type:'application/vnd.comicbook+zip'},zip:{label:'ZIP',type:'application/zip'},pdf:{label:'PDF',type:'application/pdf'}};
export class PageStall extends Error{constructor(message){super(message);this.name='PageStall';}}

const phaseLabel={
 queued:'Ждёт очереди перевода',detecting:'Ищем реплики',detected:'Ищем реплики',preparing:'Готовим страницу',
 translating:'Переводим в Google',cleaning:'Рисуем русский текст',rendering:'Рисуем русский текст',ready:'Готово',partial:'Готово с пропусками'
};
export function activityLabel(value={}){
 if(value.cacheHit)return 'Берём готовую страницу из кэша';
 if(value.phase==='cleaning'&&/кэш/i.test(value.message||''))return 'Перевод из кэша · рисуем русский текст';
 return phaseLabel[value.phase]||'Готовим страницу';
}
export function plural(n,[one,few,many]){const a=Math.abs(n)%100,b=a%10;return a>10&&a<20?many:b>1&&b<5?few:b===1?one:many;}
export const pagesWord=n=>n+' '+plural(n,['страница','страницы','страниц']);
export function formatDuration(ms){
 if(!Number.isFinite(ms)||ms<0)return '';
 const s=Math.max(1,Math.round(ms/1000));
 if(s<60)return 'около '+(s<10?s:Math.round(s/5)*5)+' с';
 const m=Math.floor(s/60),rest=Math.round((s%60)/10)*10;
 return 'около '+m+' мин'+(m<5&&rest&&rest<60?' '+rest+' с':'');
}
export function safeFileName(value){return String(value||'Глава').replace(/[\\/:*?"<>|\u0000-\u001f]+/g,' ').replace(/\s+/g,' ').trim().slice(0,150)||'Глава';}

async function bytesOf(value){
 if(!value)return null;
 if(value instanceof Uint8Array)return value;
 if(value instanceof ArrayBuffer)return new Uint8Array(value);
 if(ArrayBuffer.isView(value))return new Uint8Array(value.buffer,value.byteOffset,value.byteLength);
 if(typeof value.arrayBuffer==='function')return new Uint8Array(await value.arrayBuffer());
 return null;
}
// Browser encoder; tests inject their own.
export async function encodeImage(source,{type='image/webp',quality=.94}={}){
 const bitmap=source instanceof Blob?await createImageBitmap(source):source;
 try{
  const canvas=new OffscreenCanvas(bitmap.width,bitmap.height),context=canvas.getContext('2d');
  if(type==='image/jpeg'){context.fillStyle='#fff';context.fillRect(0,0,bitmap.width,bitmap.height);}
  context.drawImage(bitmap,0,0);
  return {bytes:new Uint8Array(await(await canvas.convertToBlob({type,quality})).arrayBuffer()),width:bitmap.width,height:bitmap.height};
 }finally{if(source!==bitmap)bitmap.close();}
}
async function imageSize(bytes){const bitmap=await createImageBitmap(new Blob([bytes]));try{return {width:bitmap.width,height:bitmap.height};}finally{bitmap.close();}}

// result → {bytes,width,height} in a format the chosen archive accepts.
export async function pageImage(result,format,encode=encodeImage){
 const pdf=format==='pdf';
 if(result?.renderedBitmap){
  const bitmap=result.renderedBitmap;
  try{return await encode(bitmap,pdf?{type:'image/jpeg',quality:.92}:{type:'image/webp',quality:.94});}finally{bitmap.close?.();}
 }
 const bytes=await bytesOf(result?.renderedImage??result?.blob??result);
 if(!bytes?.length)throw Error('Переводчик не вернул готовую страницу.');
 const extension=imageExtension(bytes);
 if(!pdf)return extension?{bytes}:encode(new Blob([bytes]),{type:'image/webp',quality:.94});
 if(extension==='jpg')return {bytes,...await imageSize(bytes)};
 return encode(new Blob([bytes]),{type:'image/jpeg',quality:.92});
}

const sleep=(ms,signal)=>new Promise((resolve,reject)=>{signal?.throwIfAborted();const done=()=>{signal?.removeEventListener('abort',stop);resolve();},timer=setTimeout(done,ms),stop=()=>{clearTimeout(timer);reject(signal.reason);};signal?.addEventListener('abort',stop,{once:true});});

export async function saveReaderChapter({total,translate=true,format='cbz',name='Глава',source,signal,onProgress=()=>{},onPage=()=>{},now=()=>performance.now(),stallMs=90000,busyLimit=10*60000,concurrency=2,encode=encodeImage,tick=5000,wait=sleep,backoff=[3,10,20,40,60,90,120],maxWaitMs=30*60000}){
 if(!total)throw Error('В главе нет страниц.');
 if(!SAVE_FORMATS[format])throw Error('Выбери формат файла.');
 signal?.throwIfAborted();
 const started=now(),pages=new Array(total),problems=new Map(),counts={cached:0,rendered:0,original:0},current=new Map();
 let done=0,interval=0,lastDone=started,phase='pages',waitInfo=null;
 const remainingTranslation=()=>{const state=source.state?.();return state&&Number.isFinite(state.translated)?Math.max(0,total-state.translated-(state.partial||0)):null;};
 const emit=()=>{
  const left=total-done,active=[...current.entries()].sort((a,b)=>a[0]-b[0])[0];
  onProgress({phase,done,total,counts:{...counts},problems:[...problems.values()].sort((a,b)=>a.page-b.page),
   current:active?{page:active[0]+1,label:active[1].label}:null,
   etaMs:phase==='pages'&&done>=3&&left?interval*left:null,untranslated:remainingTranslation(),...(waitInfo?{wait:waitInfo}:{})});
 };
 const finishPage=(index,value)=>{
  pages[index]=value;current.delete(index);done++;onPage(index,problems.has(index)?'problem':'saved');
  const at=now(),gap=at-lastDone;lastDone=at;interval=interval?interval*.75+gap*.25:gap;emit();
 };
 async function renderOne(index,blob){
  const controller=new AbortController(),abort=()=>controller.abort(signal.reason);
  signal?.addEventListener('abort',abort,{once:true});
  const begin=now();let last=begin;
  const status=value=>{last=now();current.set(index,{label:activityLabel(value)});emit();};
  // A fallback model on the VM may legitimately answer after minutes; while the
  // source says it is busy the page is not stalled, up to a hard ceiling.
  const watch=setInterval(()=>{
   const at=now(),activity=Math.max(last,source.lastActivity?.()||0,source.busy?.()&&at-begin<busyLimit?at:0);
   if(now()-activity>stallMs)controller.abort(new PageStall('Перевод не продвигался '+Math.round(stallMs/1000)+' с'));
  },Math.min(tick,stallMs));
  try{
   const result=await source.render(index,blob,controller.signal,status);
   controller.signal.throwIfAborted();return result;
  }catch(error){
   if(signal?.aborted)throw signal.reason;
   throw controller.signal.reason instanceof PageStall?controller.signal.reason:error;
  }finally{clearInterval(watch);signal?.removeEventListener('abort',abort);}
 }
 // Keep finished pages in the browser's blob store, not as JS ArrayBuffers.
 const store=({bytes,width,height})=>({blob:new Blob([bytes]),crc:format==='pdf'?0:crc32(bytes),extension:imageExtension(bytes),width,height});
 async function processPage(index,{retry=false}={}){
  signal?.throwIfAborted();
  current.set(index,{label:retry?'Повторяем страницу':'Загружаем страницу'});emit();
  const blob=await source.blob(index,signal);
  if(!translate){
   const image=store(await pageImage(await bytesOf(blob),format,encode));counts.original++;return {image,kind:'original'};
  }
  let result;
  try{result=await renderOne(index,blob);}
  catch(error){
   if(signal?.aborted)throw signal.reason;
   const stalled=error instanceof PageStall;
   // Wrong keys or a missing Oracle connection fail every page alike: stop and
   // say so instead of producing a file of originals.
   if(!stalled&&setupGoogleError(error))throw Object.assign(Error((error.message||'Google отклонил запрос')+'. Проверь ключи в настройках перевода и сохрани главу снова.'),{name:'SaveBlocked'});
   problems.set(index,{page:index+1,kind:stalled?'stalled':'failed',retryAfter:stalled?0:retryAfterSeconds(error),final:!stalled&&!transientGoogleError(error),message:stalled?'Перевод не дождались · сохранён оригинал':(error.message||'Ошибка перевода')+' · сохранён оригинал'});
   counts.original++;
   return {image:store(await pageImage(await bytesOf(blob),format,encode)),kind:'original',failed:true};
  }
  const untranslated=result?.unresolvedRegions?.length||0;
  const image=store(await pageImage(result,format,encode));
  if(untranslated)problems.set(index,{page:index+1,kind:'partial',untranslated,message:untranslated+' '+plural(untranslated,['реплика','реплики','реплик'])+' без перевода'});
  else problems.delete(index);
  if(result?.cacheHit&&result?.renderedImage)counts.cached++;else counts.rendered++;
  return {image,kind:'translated',partial:!!untranslated};
 }
 async function pool(indices,options){
  let cursor=0;
  const worker=async()=>{while(cursor<indices.length){const index=indices[cursor++];const page=await processPage(index,options);finishPage(index,page);}};
  await Promise.all(Array.from({length:Math.max(1,Math.min(concurrency,indices.length))},worker));
 }
 emit();
 if(translate){await pool([0]);await pool(Array.from({length:total-1},(_,i)=>i+1));}
 else await pool(Array.from({length:total},(_,i)=>i));
 if(translate){
  // Overload, quota and network errors pass: wait, then send every unfinished
  // page again (the translator moves each request to a key with free quota).
  // Only Google's own permanent answers keep the original page.
  let round=0,waited=0;
  for(;;){
   const failed=[...problems.values()].filter(p=>(p.kind==='failed'||p.kind==='stalled')&&!p.final);
   if(!failed.length||waited>=maxWaitMs)break;
   round++;
   const delay=Math.min(maxWaitMs-waited,Math.max(backoff[Math.min(round,backoff.length)-1]*1000,...failed.map(p=>p.retryAfter*1000)));
   phase='wait';current.clear();
   for(let left=delay;left>0;left-=1000){waitInfo={pages:failed.length,round,seconds:Math.ceil(left/1000),reason:failed.some(p=>p.kind==='failed')?'busy':'stalled'};emit();await wait(Math.min(1000,left),signal);}
   waited+=delay;waitInfo=null;
   phase='retry';for(const p of failed){source.retry?.(p.page-1);done--;counts.original--;}emit();
   await pool(failed.map(p=>p.page-1),{retry:true});
  }
  for(const p of problems.values())if((p.kind==='failed'||p.kind==='stalled')&&!p.final)p.message=(p.kind==='stalled'?'Перевод зависал':'Google не отвечал')+' '+formatDuration(waited).replace('около ','')+' · сохранён оригинал';
  const partial=[...problems.values()].filter(p=>p.kind==='partial').map(p=>p.page-1);
  if(partial.length&&source.recover){
   phase='recover';emit();
   const changed=await source.recover(partial,{signal,onStatus:value=>{current.set(value?.index??partial[0],{label:value?.label||'Проверяем пропущенные реплики'});emit();}}).catch(error=>{if(signal?.aborted)throw signal.reason;return [];});
   current.clear();
   const again=(Array.isArray(changed)?changed:partial).filter(index=>partial.includes(index));
   if(again.length){for(const index of again){done--;counts.rendered--;}await pool(again,{retry:true});}
  }
 }
 signal?.throwIfAborted();
 phase='pack';current.clear();emit();
 const archive=format==='pdf'?createPdf():createZip(SAVE_FORMATS[format].type),digits=String(total).length<3?3:String(total).length;
 for(let index=0;index<total;index++){
  signal?.throwIfAborted();const {image}=pages[index];
  if(format==='pdf'){if(!image.width||!image.height)throw Error('Не удалось определить размер страницы '+(index+1)+'.');archive.add(image.blob,image.width,image.height);}
  else archive.add(String(index+1).padStart(digits,'0')+'.'+(image.extension||'webp'),image.blob,image.crc);
  pages[index]=null;
 }
 const blob=archive.finish(SAVE_FORMATS[format].type);
 phase='done';emit();
 return {blob,filename:safeFileName(name)+'.'+format,size:blob.size,total,counts,problems:[...problems.values()].sort((a,b)=>a.page-b.page),elapsedMs:now()-started};
}

// A save keeps running after the reader closes or switches chapters. While the
// reader's own translator is alive it is shared (same cache, no duplicate
// requests); afterwards pages go to a private translator made on demand.
export function relaySource({blob,live,alive,fallback,release}){
 let pending=null,backup=null,closed=false;
 const own=()=>{
  if(closed)return Promise.reject(new DOMException('Сохранение закрыто','AbortError'));
  return pending||=Promise.resolve().then(fallback).then(value=>{
   if(!value)throw Error('Читалка закрыта, а перевод без неё недоступен.');
   if(closed){value.close?.();throw new DOMException('Сохранение закрыто','AbortError');}
   return backup=value;
  });
 };
 const pick=()=>alive()?live:null;
 return {
  live:false,blob,
  render:async(index,source,signal,status)=>{
   const current=pick();
   // The reader closed mid-page: finish that page on the private translator.
   if(current)try{return await current.render(index,source,signal,status);}catch(error){if(signal?.aborted||alive())throw error;}
   return (await own()).render(index,source,signal,status);
  },
  retry:index=>{const current=pick()||backup;current?.retry?.(index);},
  recover:async(indices,options)=>{const current=pick()||await own();return current.recover?current.recover(indices,options):[];},
  state:()=>(pick()||backup)?.state?.()||null,
  lastActivity:()=>Math.max(live.lastActivity?.()||0,backup?.lastActivity?.()||0),
  busy:()=>!!(pick()?.busy?.()||backup?.busy?.()),
  get switched(){return !!pending;},
  close(){if(closed)return;closed=true;try{release?.();}catch{}backup?.close?.();}
 };
}

export function downloadBlob(blob,filename){
 const url=URL.createObjectURL(blob),anchor=document.createElement('a');
 anchor.href=url;anchor.download=filename;anchor.rel='noopener';document.body.append(anchor);anchor.click();anchor.remove();
 setTimeout(()=>URL.revokeObjectURL(url),120000);
}
