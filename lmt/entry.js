// SPDX-License-Identifier: AGPL-3.0-or-later
import './shim.js';
import {validateConfig} from './config.js';
import {renderTranslated} from './render.js';
const contexts=new Map();
let running=false;
async function pipeline(bytes,config,progress){
 const started=performance.now(),timings={};
 const measure=async(name,work)=>{const start=performance.now();try{return await work();}finally{timings[name]=performance.now()-start;}};
 const diagnostics=()=>({...timings,totalMs:performance.now()-started});
 validateConfig(config);
 if(bytes.byteLength>10*1024*1024)throw Error('Страница превышает 10 МБ.');
 if(config.mode!=='api'&&!navigator.gpu&&!['detect','inpaint'].includes(config.operation))throw Error('Для локального LMT нужен WebGPU. Используй совместимый браузер или режим своего LLM-сервера.');
 globalThis.lmtProgress=progress;
 const ort=await import('onnxruntime-web/all');ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=new URL('./',location.href).href;
 const [{detectTextBubble},{textRecognise},{translateLocal},{translateWithServer},{inpaintImageAuto,inpaintImageQuality}]=await Promise.all([import('./upstream/lib/detections/main.ts'),import('./upstream/lib/ocr/main.ts'),import('./upstream/lib/webllm.ts'),import('./upstream/lib/server/main.ts'),import('./upstream/lib/inpaint/ladder.ts')]);
 timings.initializationMs=performance.now()-started;
 const source=URL.createObjectURL(new Blob([bytes]));let bitmap;
 try{
  bitmap=await createImageBitmap(new Blob([bytes]));if(bitmap.width*bitmap.height>24000000)throw Error('Страница превышает 24 Мп.');
  progress('Определяем речевые области · при первом запуске загружаются модели');
  const boxes=config.boxes??await measure('detectionMs',()=>detectTextBubble(source,.5,config.detector||'comic-bubble'));
  for(const box of boxes)if(![box.x1,box.y1,box.x2,box.y2].every(Number.isFinite)||box.x1<0||box.y1<0||box.x2>bitmap.width||box.y2>bitmap.height||box.x2<=box.x1||box.y2<=box.y1)throw Error('Область выходит за границы страницы.');
  if(boxes.length>100)throw Error('Найдено слишком много областей. Раздели длинный вебтун на страницы.');
  if(config.operation==='detect')return {boxes,regions:[]};
  if(config.operation==='inpaint'){
   const clean=await(config.inpaint==='quality'?inpaintImageQuality:inpaintImageAuto)(source,boxes);
   return {cleanedImage:await(await fetch(clean.url)).arrayBuffer(),regions:[],inpaintRegions:clean.regions,timings:diagnostics()};
  }
  if(!boxes.length)return {regions:[],engine:'Libre Manga Translator',message:'Речевые области не найдены.'};
  progress('Распознаём текст · '+boxes.length+' областей');const ocr=await measure('ocrMs',()=>textRecognise(source,boxes,config.language||'English',.55,4,48,{enabled:true,force:!!config.gateForce},config.ocr||'paddle'));
  const texts=ocr.results.map(r=>r.gateSkip||r.failed?'':r.text);
  if(!texts.some(Boolean))return {regions:[],boxes,translations:texts.map(()=>''),sourceTexts:texts,gateSkip:ocr.results.map(r=>r.gateSkip||null),engine:'Libre Manga Translator',message:'OCR не распознал реплики. Проверь исходный язык и движок.'};
  const target=config.targetLanguage||'Russian';
  progress('Переводим полные реплики · '+target);let translated;const contextKey=config.contextKey||'default',context=contexts.get(contextKey);
  if(config.mode==='api'){
   const endpoint=new URL(config.host);if(endpoint.username||endpoint.password||!['https:','http:'].includes(endpoint.protocol))throw Error('Некорректный адрес своего сервера.');
   if(endpoint.protocol==='http:'&&!['localhost','127.0.0.1','[::1]'].includes(endpoint.hostname))throw Error('Для удалённого сервера нужен HTTPS.');
   translated=await measure('translationMs',()=>translateWithServer(texts,target,config.language||'English',context,{serverHost:endpoint.href,serverSchema:config.serverSchema||'openai',serverModel:config.serverModel,useServerApiKey:false,temperature:.2}));
  }else translated=await measure('translationMs',()=>translateLocal(texts,target,config.language||'English',context,config.model||'Qwen3.5-0.8B-q4f16_1-MLC',.2));
  if(translated.context){contexts.set(contextKey,translated.context);while(contexts.size>8)contexts.delete(contexts.keys().next().value);}
  if(config.operation==='translate')return {regions:[],boxes,translations:translated.translations,sourceTexts:texts,context:translated.context,gateSkip:ocr.results.map(r=>r.gateSkip||null)};
  const valid=boxes.map((b,i)=>({box:b,index:i,text:String(translated.translations?.[i]||'')})).filter(v=>texts[v.index]&&v.text);
  if(!valid.length)throw Error('Модель не вернула переведённые реплики. Попробуй другую модель.');
  progress('Восстанавливаем фон · '+(config.inpaint==='quality'?'LaMa':'Fast'));const cleaned=await measure('inpaintMs',()=>(config.inpaint==='quality'?inpaintImageQuality:inpaintImageAuto)(source,valid.map(v=>v.box)));
  const cleanedImage=await(await fetch(cleaned.url)).arrayBuffer();
  const regions=valid.map(v=>({x:v.box.x1/bitmap.width,y:v.box.y1/bitmap.height,w:(v.box.x2-v.box.x1)/bitmap.width,h:(v.box.y2-v.box.y1)/bitmap.height,original:texts[v.index],text:v.text,placement:'note'}));
  progress('Набираем переведённый текст');const renderedImage=await measure('typesetMs',()=>renderTranslated(cleanedImage,regions));
  const inpaintRegions=cleaned.regions.map(({index,method,ms,cluster,clusterBoxes,lamaStage})=>({index,method,ms,cluster,clusterBoxes,lamaStage}));
  return {engine:'Libre Manga Translator',sourceLanguage:config.language,targetLanguage:target,machineTranslation:true,renderedImage,cleanedImage,renderedMime:'image/webp',regions,inpaintRegions,timings:diagnostics()};
 }finally{globalThis.lmtProgress=null;bitmap?.close();URL.revokeObjectURL(source);}
}
// The private backend loads the same engine as the browser iframe.
globalThis.mangaTranslate=pipeline;
globalThis.mangaTypeset=renderTranslated;
addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='mv-lmt-connect'||event.ports.length!==1)return;
 const port=event.ports[0];port.onmessage=async({data})=>{if(data.type!=='translate')return;if(running){port.postMessage({id:data.id,error:'Предыдущая страница ещё обрабатывается.'});return;}running=true;
  try{const result=await pipeline(data.bytes,data.config,status=>port.postMessage({id:data.id,status}));port.postMessage({id:data.id,result},[result.renderedImage,result.cleanedImage].filter(Boolean));}catch(e){port.postMessage({id:data.id,error:e.message||String(e)});}finally{running=false;}
 };port.start();port.postMessage({ready:true,webgpu:!!navigator.gpu});
});
