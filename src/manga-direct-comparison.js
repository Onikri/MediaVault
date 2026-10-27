import {DIRECT_INPUTS} from './manga-direct-profiles.js';
import {geometryAgreement} from './manga-vision-geometry.js';
// Three explicit, sequential requests with one model, image size and context.
// Never writes production translation caches or shares the personal key.
export async function compareDirectInputs({blob,index,prepare,google,key,config,direction='rtl',signal,onProgress=()=>{}}){
 if(!key)throw Error('Введи личный ключ Google в настройках быстрого режима.');
 const started=performance.now(),results=[];
 onProgress({message:'Подготавливаем размеченную и чистую копии…',results:[]});
 signal?.throwIfAborted();const prepStart=performance.now(),marked=await prepare(blob,index,()=>{},'annotated');
 signal?.throwIfAborted();const raw=await prepare(blob,index,()=>{},'vision'),prepareMs=Math.round(performance.now()-prepStart);
 const inputs={annotated:marked,coordinates:{...raw,inputMode:'coordinates',regions:marked.regions,detector:marked.detector,detectionMs:marked.detectionMs},vision:raw};
 for(const variant of DIRECT_INPUTS){
  signal?.throwIfAborted();const start=performance.now();let row={input:variant.id,label:variant.label,state:'running'};
  onProgress({message:variant.label,results:[...results,row]});
  try{
   const page=inputs[variant.id];if(!page.regions.length&&variant.id!=='vision')throw Error('Локальный детектор не нашёл текст. Запрос не отправлен.');
   const answer=await google([page],{key,model:config.directModel,direction,context:'',gemmaProfile:config.gemmaProfile,signal,timeoutMs:config.directTimeoutMs,onDiagnostic:d=>onProgress({message:variant.label+' · '+(d.stage==='streaming'?'получаем перевод':d.stage==='waiting'?'ждём Google':d.stage),results:[...results,row]})});
   const p=answer.pages[0],d=answer.diagnostics||{};
   row={...row,state:'done',ms:Math.round(performance.now()-start),regions:p.regions,boxes:p.regions.length,requestBytes:d.requestBytes,metrics:d.metrics,usage:answer.usage,agreement:geometryAgreement(marked.regions.map(r=>r.bbox),p.regions.map(r=>r.text_bbox))};
  }catch(error){if(signal?.aborted)throw signal.reason;row={...row,state:'error',ms:Math.round(performance.now()-start),error:error.message,requestBytes:error.diagnostics?.requestBytes,metrics:error.diagnostics?.metrics};}
  results.push(row);onProgress({message:'Завершено '+results.length+' / 3',results:[...results]});
 }
 return {version:1,model:config.directModel,detector:marked.detector,page:index+1,width:raw.width,height:raw.height,sentWidth:raw.sentWidth,sentHeight:raw.sentHeight,prepareMs,totalMs:Math.round(performance.now()-started),results,notice:'Три варианта, без кэша и инпейнта. Координаты локального детектора одинаковы в первых двух запросах. Совпадение рамок — сравнение с детектором, не точность относительно ручной разметки. Загрузка моделей входит в подготовку; порядок запросов может влиять на задержку Google.'};
}
