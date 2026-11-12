// Bubbles Google still refuses after splitting (PROHIBITED_CONTENT and other
// safety blocks on adult or violent pages), and blanks its review could not
// fill, are read by the LMT OCR and translated by Hy-MT2 on the Oracle VM.
// The answer is merged into the same page JSON, so cleaning, Cyrillic
// typesetting and the page cache stay exactly the Google path.
import {unresolvedRegions} from './manga-empty-review.js';
import {bytesBase64} from './manga-translation.js';

export const FALLBACK_LANGUAGES=['Japanese','Korean','English'];
export const FALLBACK_LIMIT=40,HEARTBEAT_MS=20000;
const MAX_CROP_PIXELS=3_500_000,RETRY=new Set([429,502,503,504]);
const pause=(ms,signal)=>new Promise((resolve,reject)=>{const done=()=>{signal?.removeEventListener('abort',abort);resolve();},abort=()=>{clearTimeout(timer);reject(signal.reason);},timer=setTimeout(done,ms);signal?.addEventListener('abort',abort,{once:true});});

export const fallbackCandidates=page=>unresolvedRegions(page).filter(r=>!r.fallback?.attempted);
export function wantsFallback(page,config={}){
 return config.refusalFallback!==false&&FALLBACK_LANGUAGES.includes(config.language||'English')&&fallbackCandidates(page).length>0;
}
export const fallbackRegionIds=page=>(page.regions||[]).filter(r=>r.fallback?.status==='translated').map(r=>r.uid);

// Native-resolution crops of the text boxes only, never the whole page.
export async function cropRegions(blob,regions,{pad=6}={}){
 const bitmap=await createImageBitmap(blob);
 try{
  const out=[];
  for(const region of regions){
   const [a,b,c,d]=region.text_bbox||region.layout_bbox,x=Math.max(0,Math.floor(a-pad)),y=Math.max(0,Math.floor(b-pad)),w=Math.min(bitmap.width,Math.ceil(c+pad))-x,h=Math.min(bitmap.height,Math.ceil(d+pad))-y;
   if(!(w>1&&h>1))continue;
   const scale=Math.min(1,Math.sqrt(MAX_CROP_PIXELS/(w*h))),canvas=new OffscreenCanvas(Math.max(1,Math.round(w*scale)),Math.max(1,Math.round(h*scale)));
   canvas.getContext('2d').drawImage(bitmap,x,y,w,h,0,0,canvas.width,canvas.height);
   out.push({id:region.uid,image:bytesBase64(await(await canvas.convertToBlob({type:'image/png'})).arrayBuffer())});
  }
  return out;
 }finally{bitmap.close();}
}

async function requestFallback(service,body,signal){
 for(let attempt=0;;attempt++){
  try{return await service.request('/reader/lmt/fallback',{method:'POST',body,signal:AbortSignal.any([signal,AbortSignal.timeout(250000)].filter(Boolean))});}
  catch(error){
   signal?.throwIfAborted();
   if(attempt>=2||!RETRY.has(error.status))throw error;
   await pause(4000*(attempt+1),signal);
  }
 }
}

// Returns a new page; the caller writes the cache and finishes the job.
export async function translateFallback(page,blob,{service,language='English',signal,onStatus=()=>{}}={}){
 const targets=fallbackCandidates(page),started=performance.now();
 if(!targets.length)return page;
 const base={...page,regions:[...page.regions]};
 if(!service?.request)return {...base,fallback:{error:'Запасной перевод доступен после подключения к Oracle.',pending:targets.map(r=>r.uid)}};
 const crops=await cropRegions(blob,targets);signal?.throwIfAborted();
 const rows=new Map();let model='',ocr='',ocrMs=0;
 for(let offset=0;offset<crops.length;offset+=FALLBACK_LIMIT){
  const label='Запасная модель на ВМ · реплики '+(offset+1)+'–'+Math.min(crops.length,offset+FALLBACK_LIMIT)+' из '+crops.length,sent=performance.now();
  onStatus(label);
  // One VM request can outlast a 90 s inactivity watchdog (cold OCR start,
  // many Japanese bubbles): report progress while waiting.
  const pulse=setInterval(()=>onStatus(label+' · '+Math.round((performance.now()-sent)/1000)+' с'),HEARTBEAT_MS);
  let answer;try{answer=await requestFallback(service,{language,crops:crops.slice(offset,offset+FALLBACK_LIMIT)},signal);}finally{clearInterval(pulse);}
  model=answer.model||model;ocr=answer.ocr||ocr;ocrMs+=answer.timings?.ocrMs||0;
  for(const row of answer.rows||[])rows.set(row.id,row);
 }
 const info={model,ocr},report={model,ocr,translated:[],nonText:[],errors:[],ms:0,ocrMs};
 base.regions=page.regions.map(region=>{
  const row=rows.get(region.uid);
  if(!targets.includes(region)||!row)return region;
  const reason=region.refused?'refused':'empty';
  if(row.status==='translated'&&String(row.ru||'').trim()){
   report.translated.push(region.uid);
   const {empty_reason,...rest}=region;
   return {...rest,ru_translation:String(row.ru).trim(),font_style:region.font_style||'standard_comic',text_category:region.text_category||'dialogue',fallback:{...info,attempted:true,status:'translated',reason,source:row.source||''}};
  }
  if(row.status==='non_text'){report.nonText.push(region.uid);return {...region,empty_reason:'non_text',fallback:{...info,attempted:true,status:'non_text',reason}};}
  report.errors.push(region.uid);
  return {...region,fallback:{...info,attempted:true,status:'error',reason,error:String(row.error||'Запасная модель не перевела реплику.').slice(0,200)}};
 });
 report.ms=Math.round(performance.now()-started);
 base.fallback=report;
 const unresolved=unresolvedRegions(base);
 base.detectionReport={...base.detectionReport,translated:base.regions.filter(r=>r.ru_translation?.trim()).length,unresolved:unresolved.map(r=>r.uid),refused:base.regions.filter(r=>r.refused).map(r=>r.uid),fallback:base.regions.filter(r=>r.fallback?.status==='translated').map(r=>r.uid),fallbackModel:[model,ocr&&'OCR '+ocr].filter(Boolean).join(', '),nonText:base.regions.filter(r=>!r.ru_translation?.trim()&&r.empty_reason==='non_text').map(r=>r.uid)};
 return base;
}
