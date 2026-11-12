// Saves the open chapter on this device from the reader's own translation
// chain: rendered-page cache → cached Google JSON + local typesetting → new
// Google requests only for pages that were never translated. Nothing is sent
// to the VM for re-translation, and no page can block the file forever.
import {crc32,createPdf,createZip,imageExtension} from './chapter-archive.js';

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

export async function saveReaderChapter({total,translate=true,format='cbz',name='Глава',source,signal,onProgress=()=>{},onPage=()=>{},now=()=>performance.now(),stallMs=90000,concurrency=2,encode=encodeImage,tick=5000}){
 if(!total)throw Error('В главе нет страниц.');
 if(!SAVE_FORMATS[format])throw Error('Выбери формат файла.');
 signal?.throwIfAborted();
 const started=now(),pages=new Array(total),problems=new Map(),counts={cached:0,rendered:0,original:0},current=new Map();
 let done=0,interval=0,lastDone=started,phase='pages';
 const remainingTranslation=()=>{const state=source.state?.();return state&&Number.isFinite(state.translated)?Math.max(0,total-state.translated-(state.partial||0)):null;};
 const emit=()=>{
  const left=total-done,active=[...current.entries()].sort((a,b)=>a[0]-b[0])[0];
  onProgress({phase,done,total,counts:{...counts},problems:[...problems.values()].sort((a,b)=>a.page-b.page),
   current:active?{page:active[0]+1,label:active[1].label}:null,
   etaMs:phase==='pages'&&done>=3&&left?interval*left:null,untranslated:remainingTranslation()});
 };
 const finishPage=(index,value)=>{
  pages[index]=value;current.delete(index);done++;onPage(index,problems.has(index)?'problem':'saved');
  const at=now(),gap=at-lastDone;lastDone=at;interval=interval?interval*.75+gap*.25:gap;emit();
 };
 async function renderOne(index,blob){
  const controller=new AbortController(),abort=()=>controller.abort(signal.reason);
  signal?.addEventListener('abort',abort,{once:true});
  let last=now();
  const status=value=>{last=now();current.set(index,{label:activityLabel(value)});emit();};
  const watch=setInterval(()=>{
   const activity=Math.max(last,source.lastActivity?.()||0);
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
   problems.set(index,{page:index+1,kind:stalled?'stalled':'failed',message:stalled?'Перевод не дождались · сохранён оригинал':(error.message||'Ошибка перевода')+' · сохранён оригинал'});
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
 await pool(Array.from({length:total},(_,i)=>i));
 if(translate){
  // A failed request often succeeds on the second try; a stall does not repeat
  // forever because the second attempt is bounded by the same watchdog.
  const failed=[...problems.values()].filter(p=>p.kind==='failed'||p.kind==='stalled').map(p=>p.page-1);
  if(failed.length){
   phase='retry';for(const index of failed){source.retry?.(index);done--;counts.original--;}emit();
   await pool(failed,{retry:true});
  }
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

export function downloadBlob(blob,filename){
 const url=URL.createObjectURL(blob),anchor=document.createElement('a');
 anchor.href=url;anchor.download=filename;anchor.rel='noopener';document.body.append(anchor);anchor.click();anchor.remove();
 setTimeout(()=>URL.revokeObjectURL(url),120000);
}
