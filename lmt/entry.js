// SPDX-License-Identifier: AGPL-3.0-or-later
import './shim.js';
import {serializePipeline} from './pipeline-queue.js';
import {loadRoleFace,registerPrivateFonts} from '../reader-fonts/catalog.js';
import {typesetPage,TYPESETTER} from './typeset/index.js';
import {getRtDetrLayout} from './upstream/lib/detections/rtdetr.ts';
import {resolveMangaOcr} from '../src/ocr-profiles.js';
import {validateConfig} from './config.js';
import {getCachedSegmentation} from './upstream/lib/detections/segmentation.ts';
const contexts=new Map();
// The owner's server runs this page in its own headless browser and serves the
// owner's private typefaces next to it; the public site has no such folder.
let privateFontsLoad;
const privateFonts=()=>privateFontsLoad||=(async()=>{
 if(typeof globalThis.mvProgress!=='function')return;
 const names=await(await fetch('./private-fonts/index.json')).json();
 registerPrivateFonts(await Promise.all(names.map(async(name,i)=>({name,data:await(await fetch('./private-fonts/'+i)).arrayBuffer()}))));
})().catch(()=>{});
async function pipeline(bytes,config,progress){
 if(config.operation==='gemma-prepare'||config.operation==='gemma-render'){
  const{prepareGemmaPage,renderGemmaPage}=await import('./gemma-device.js');
  return await(config.operation==='gemma-prepare'?prepareGemmaPage:renderGemmaPage)(bytes,config,progress);
 }
 validateConfig(config);
 if(bytes.byteLength>10*1024*1024)throw Error('Страница превышает 10 МБ.');
 if(config.mode!=='api'&&config.deviceTranslator==='webllm'&&!navigator.gpu)throw Error('Для локального LMT нужен WebGPU. Используй совместимый браузер или режим своего LLM-сервера.');
 globalThis.lmtProgress=progress;
 const ort=await import('onnxruntime-web/all');ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=new URL('./',location.href).href;
 const [{detectTextBubble},{inpaintImageAuto,inpaintImageQuality}]=await Promise.all([import('./upstream/lib/detections/main.ts'),import('./upstream/lib/inpaint/ladder.ts')]);
 const source=URL.createObjectURL(new Blob([bytes]));let bitmap;const timings={},started=performance.now();
 try{
  bitmap=await createImageBitmap(new Blob([bytes]));if(bitmap.width*bitmap.height>24000000)throw Error('Страница превышает 24 Мп.');
  progress('Определяем речевые области · при первом запуске загружаются модели');let t=performance.now();const {detectManga}=await import('./detection.js');const detection=await detectManga(source,config),boxes=detection.boxes;timings.detectionMs=Math.round(performance.now()-t);
  if(boxes.length>100)throw Error('Найдено слишком много областей. Раздели длинный вебтун на страницы.');
  for(const box of boxes)if(![box.x1,box.y1,box.x2,box.y2].every(Number.isFinite)||box.x1<0||box.y1<0||box.x2>bitmap.width||box.y2>bitmap.height||box.x2<=box.x1||box.y2<=box.y1)throw Error('Область текста выходит за границы страницы. Попробуй другой детектор.');
  const detected={width:bitmap.width,height:bitmap.height,regions:boxes.map((b,i)=>({id:'B'+(i+1),bbox:[b.x1,b.y1,b.x2,b.y2]}))};
  if(!boxes.length){const header=new Uint8Array(bytes);return {detected,regions:[],engine:'Libre Manga Translator',renderedImage:bytes,renderedMime:header[0]===137?'image/png':header[0]===82?'image/webp':'image/jpeg',message:'На этой странице речевые области не найдены.'};}
  const contextKey=config.contextKey||'default',context=contexts.get(contextKey);let translated,texts;
  if(config.mode==='api'&&config.apiInput==='vision'){
   progress('VLM читает страницу и переводит реплики с визуальным контекстом');const{translateVision}=await import('./vision.js');t=performance.now();translated=await translateVision(bitmap,boxes,config,context);timings.translationMs=Math.round(performance.now()-t);timings.ocrMs=0;texts=translated.sourceTexts;
  }else{
   progress('Распознаём текст · '+boxes.length+' областей');const{textRecognise}=await import('./upstream/lib/ocr/main.ts');t=performance.now();const ocr=resolveMangaOcr(config.language,config.ocr)==='ppocrv6-manga'?await(await import('./ppocrv6.js')).recognizePpManga(source,boxes):await textRecognise(source,boxes,config.language||'English',.55,4,48,{enabled:true},resolveMangaOcr(config.language,config.ocr));timings.ocrMs=Math.round(performance.now()-t);
   texts=ocr.results.map(r=>r.gateSkip||r.failed?'':r.text);if(!texts.some(Boolean))return {regions:[],engine:'Libre Manga Translator',message:'OCR не распознал реплики. Проверь исходный язык и движок.'};
   progress('Переводим полные реплики на русский');t=performance.now();
   if(typeof globalThis.mvTranslate==='function'){translated=await globalThis.mvTranslate({texts,target:'Russian',source:config.language||'English',context});}
   else if(config.mode==='api'){const{translateWithServer}=await import('./upstream/lib/server/main.ts');translated=await translateWithServer(texts,'Russian',config.language||'English',context,{serverHost:new URL(config.host).href,serverSchema:'openai',serverModel:config.serverModel,useServerApiKey:!!config.apiKey,serverApiKey:config.apiKey,temperature:.1});}
   else if(config.deviceTranslator!=='webllm'){const{translateHymt2}=await import('./hymt2.js');translated=await translateHymt2(texts,config,context,progress);}
   else{const{translateLocal}=await import('./upstream/lib/webllm.ts');translated=await translateLocal(texts,'Russian',config.language||'English',context,config.model||'Qwen3.5-4B-q4f16_1-MLC',.1);}
   timings.translationMs=Math.round(performance.now()-t);
  }
  if(!Array.isArray(translated.translations)||translated.translations.length!==texts.length||texts.some((t,i)=>t&&(!String(translated.translations[i]||'').trim())))throw Error('Перевод неполный: модель пропустила реплику. Страница не изменена.');
  if(translated.context){contexts.set(contextKey,translated.context);while(contexts.size>8)contexts.delete(contexts.keys().next().value);}
  const valid=boxes.map((b,i)=>({box:b,index:i,text:String(translated.translations?.[i]||'')})).filter(v=>texts[v.index]&&v.text);
  if(!valid.length)throw Error('Модель не вернула переведённые реплики. Попробуй другую модель.');
  progress('Восстанавливаем фон и набираем русский текст');t=performance.now();const segmentation=getCachedSegmentation(source);const cleaned=await(config.inpaint==='quality'?inpaintImageQuality:inpaintImageAuto)(source,valid.map(v=>v.box),{segmentation});timings.inpaintMs=Math.round(performance.now()-t);
  const cleanBitmap=await createImageBitmap(await(await fetch(cleaned.url)).blob()),canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(cleanBitmap,0,0);cleanBitmap.close();t=performance.now();
  const debug=config.captureDebug?{cleanedImage:await(await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.94))).arrayBuffer()}:undefined;
  const blocked=new Set(cleaned.regions.filter(r=>['declined','skipped'].includes(r.method)).map(r=>r.index));const warnings=[];if(valid.length<boxes.length)warnings.push('Часть областей не распознана; выбери другой OCR или проверь исходный язык.');if(blocked.size)warnings.push('Часть областей оставлена в оригинале; полный текст доступен под страницей.');if(config.inpaint==='quality'&&cleaned.regions.some(r=>r.lamaStage==='failed'))warnings.push('LaMa не выполнила часть редро: использован быстрый клининг.');
  // Balloon boxes and the free-text split come from the detector when it has them (RT-DETR); otherwise the typesetter finds the balloon itself.
  const shapes=(config.detector||'comic-bubble')==='comic-bubble'?getRtDetrLayout():{bubbles:[],freeText:[]},overlap=(p,q)=>Math.max(0,Math.min(p.x2,q.x2)-Math.max(p.x1,q.x1))*Math.max(0,Math.min(p.y2,q.y2)-Math.max(p.y1,q.y1)),area=p=>(p.x2-p.x1)*(p.y2-p.y1);
  const items=valid.filter((_,i)=>!blocked.has(i)).map(v=>{const bubble=shapes.bubbles.filter(q=>overlap(v.box,q)>=.7*area(v.box)&&area(q)<bitmap.width*bitmap.height*.5).sort((p,q)=>area(p)-area(q))[0],free=!bubble&&shapes.freeText.some(q=>overlap(v.box,q)>=.5*Math.min(area(v.box),area(q)));return {index:v.index,text:v.text,original:texts[v.index],box:v.box,bubble,kind:free?'free':undefined,style:translated.styles?.[v.index]};});
  const originalCanvas=document.createElement('canvas');originalCanvas.width=bitmap.width;originalCanvas.height=bitmap.height;const originalCtx=originalCanvas.getContext('2d',{willReadFrequently:true});originalCtx.drawImage(bitmap,0,0);
  await privateFonts();
  const faces=new Set(),set=await typesetPage(ctx,items,{caps:config.caps!==false,original:originalCtx,faceFor:async(role,hint)=>{const face=await loadRoleFace(role,config.font||'comic-relief',hint);faces.add(face.id);return face;}}),layouts=set.layouts;
  originalCanvas.width=originalCanvas.height=0;
  if(layouts.some(l=>!l.fits))warnings.push('Часть реплик не поместилась в свои области и не набрана; полный текст доступен под страницей.');
  timings.typesetMs=Math.round(performance.now()-t);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.94));if(!blob)throw Error('Не удалось собрать страницу.');timings.totalMs=Math.round(performance.now()-started);
  return {detected,debug,detectionReport:{found:boxes.length,translated:valid.length,rejected:boxes.flatMap((b,i)=>texts[i]?[]:['B'+(i+1)]),missed:'unknown'},engine:'Libre Manga Translator',sourceLanguage:config.language,targetLanguage:'ru',machineTranslation:true,detection:{model:detection.model,panelModel:detection.panelModel,panels:detection.panels.length},translationDiagnostics:translated.translationDiagnostics,typesetting:{engine:TYPESETTER,font:config.font||'comic-relief',faces:[...faces],caps:config.caps!==false,baseSize:set.base,layouts},timings,warnings,inpaint:{requested:config.inpaint||'fast',methods:[...new Set(cleaned.regions.map(r=>r.method))],unpainted:blocked.size,segmentationUsed:!!segmentation},inputMode:config.apiInput==='vision'&&config.mode==='api'?'vision':'ocr',renderedImage:await blob.arrayBuffer(),renderedMime:blob.type,regions:valid.map(v=>({x:v.box.x1/bitmap.width,y:v.box.y1/bitmap.height,w:(v.box.x2-v.box.x1)/bitmap.width,h:(v.box.y2-v.box.y1)/bitmap.height,original:texts[v.index],text:v.text,role:layouts.find(l=>l.index===v.index)?.role,placement:'note'}))};
 }finally{globalThis.lmtProgress=null;bitmap?.close();URL.revokeObjectURL(source);}
}
globalThis.mangaTranslate=pipeline;
// Private diagnostics/benchmarks use the exact production detection runner.
globalThis.mangaDetect=async(bytes,config)=>{const source=URL.createObjectURL(new Blob([bytes]));try{const{detectManga}=await import('./detection.js');return await detectManga(source,config);}finally{URL.revokeObjectURL(source);}};
globalThis.mangaPpOcr=async(bytes,boxes)=>{const source=URL.createObjectURL(new Blob([bytes]));try{return await(await import('./ppocrv6.js')).recognizePpManga(source,boxes);}finally{URL.revokeObjectURL(source);}};
// Bubbles Google refuses to translate arrive as already-detected crops. Read
// them with the production OCR selection and script gate of this pipeline;
// the Python worker translates the recognised text (MediaVault integration).
globalThis.mangaFallbackOcr=async(crops,language)=>{
 if(!Array.isArray(crops)||crops.length>40||!['Japanese','Korean','English'].includes(language))throw Error('Некорректный запрос запасного OCR.');
 const engine=resolveMangaOcr(language,'auto'),{textRecognise}=await import('./upstream/lib/ocr/main.ts'),rows=[];
 for(const crop of crops){
  const blob=new Blob([Uint8Array.from(atob(crop.image),c=>c.charCodeAt(0))]),source=URL.createObjectURL(blob),started=performance.now();
  try{
   const bitmap=await createImageBitmap(blob),box={x1:0,y1:0,x2:bitmap.width,y2:bitmap.height};bitmap.close();
   if(box.x2*box.y2>4_000_000)throw Error('Вырезка реплики слишком велика.');
   const ocr=await textRecognise(source,[box],language,.55,4,48,{enabled:true},engine),r=ocr.results[0]||{};
   rows.push({id:crop.id,text:r.gateSkip||r.failed?'':String(r.text||'').trim(),gate:r.gateSkip||null,failed:!!r.failed,confidence:Number.isFinite(r.confidence)?r.confidence:null,ms:Math.round(performance.now()-started)});
  }finally{URL.revokeObjectURL(source);}
 }
 return {engine,rows};
};
const queuedPipeline=serializePipeline(pipeline);
addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='mv-lmt-connect'||event.ports.length!==1)return;
 const port=event.ports[0];port.onmessage=async({data})=>{if(data.type!=='translate')return;
  try{const result=await queuedPipeline(data.bytes,data.config,status=>port.postMessage({id:data.id,status}));port.postMessage({id:data.id,result},result.renderedImage?[result.renderedImage]:[]);}catch(e){port.postMessage({id:data.id,error:e.message||String(e)});}
 };port.start();port.postMessage({ready:true,webgpu:!!navigator.gpu});
});
