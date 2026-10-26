// SPDX-License-Identifier: AGPL-3.0-or-later
import './shim.js';
import {loadMangaFont} from '../reader-fonts/catalog.js';
import {resolveMangaOcr} from '../src/ocr-profiles.js';
import {validateConfig} from './config.js';
import {getCachedSegmentation} from './upstream/lib/detections/segmentation.ts';
const contexts=new Map();let running=false;
async function pipeline(bytes,config,progress){
 validateConfig(config);
 if(bytes.byteLength>10*1024*1024)throw Error('Страница превышает 10 МБ.');
 if(config.mode!=='api'&&!navigator.gpu)throw Error('Для локального LMT нужен WebGPU. Используй совместимый браузер или режим своего LLM-сервера.');
 globalThis.lmtProgress=progress;
 const ort=await import('onnxruntime-web/all');ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=new URL('./',location.href).href;
 const [{detectTextBubble},{inpaintImageAuto,inpaintImageQuality},{drawFittedText}]=await Promise.all([import('./upstream/lib/detections/main.ts'),import('./upstream/lib/inpaint/ladder.ts'),import('./upstream/lib/canvas/text-fit.ts')]);
 const source=URL.createObjectURL(new Blob([bytes]));let bitmap;const timings={},started=performance.now();
 try{
  bitmap=await createImageBitmap(new Blob([bytes]));if(bitmap.width*bitmap.height>24000000)throw Error('Страница превышает 24 Мп.');
  progress('Определяем речевые области · при первом запуске загружаются модели');let t=performance.now();const boxes=await detectTextBubble(source,.5,config.detector||'comic-bubble');timings.detectionMs=Math.round(performance.now()-t);
  if(boxes.length>100)throw Error('Найдено слишком много областей. Раздели длинный вебтун на страницы.');
  if(!boxes.length)return {regions:[],engine:'Libre Manga Translator',message:'Речевые области не найдены.'};
  const contextKey=config.contextKey||'default',context=contexts.get(contextKey);let translated,texts;
  if(config.mode==='api'&&config.apiInput==='vision'){
   progress('VLM читает страницу и переводит реплики с визуальным контекстом');const{translateVision}=await import('./vision.js');t=performance.now();translated=await translateVision(bitmap,boxes,config,context);timings.translationMs=Math.round(performance.now()-t);timings.ocrMs=0;texts=translated.sourceTexts;
  }else{
   progress('Распознаём текст · '+boxes.length+' областей');const{textRecognise}=await import('./upstream/lib/ocr/main.ts');t=performance.now();const ocr=await textRecognise(source,boxes,config.language||'English',.55,4,48,{enabled:true},resolveMangaOcr(config.language,config.ocr));timings.ocrMs=Math.round(performance.now()-t);
   texts=ocr.results.map(r=>r.gateSkip||r.failed?'':r.text);if(!texts.some(Boolean))return {regions:[],engine:'Libre Manga Translator',message:'OCR не распознал реплики. Проверь исходный язык и движок.'};
   progress('Переводим полные реплики на русский');t=performance.now();
   if(config.mode==='api'){const{translateWithServer}=await import('./upstream/lib/server/main.ts');translated=await translateWithServer(texts,'Russian',config.language||'English',context,{serverHost:new URL(config.host).href,serverSchema:'openai',serverModel:config.serverModel,useServerApiKey:!!config.apiKey,serverApiKey:config.apiKey,temperature:.1});}
   else{const{translateLocal}=await import('./upstream/lib/webllm.ts');translated=await translateLocal(texts,'Russian',config.language||'English',context,config.model||'Qwen3.5-4B-q4f16_1-MLC',.1);}
   timings.translationMs=Math.round(performance.now()-t);
  }
  if(translated.context){contexts.set(contextKey,translated.context);while(contexts.size>8)contexts.delete(contexts.keys().next().value);}
  const valid=boxes.map((b,i)=>({box:b,index:i,text:String(translated.translations?.[i]||'')})).filter(v=>texts[v.index]&&v.text);
  if(!valid.length)throw Error('Модель не вернула переведённые реплики. Попробуй другую модель.');
  progress('Восстанавливаем фон и набираем русский текст');t=performance.now();const segmentation=getCachedSegmentation(source);const cleaned=await(config.inpaint==='quality'?inpaintImageQuality:inpaintImageAuto)(source,valid.map(v=>v.box),{segmentation});timings.inpaintMs=Math.round(performance.now()-t);
  const cleanBitmap=await createImageBitmap(await(await fetch(cleaned.url)).blob()),canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;const ctx=canvas.getContext('2d');ctx.drawImage(cleanBitmap,0,0);cleanBitmap.close();t=performance.now();
  const blocked=new Set(cleaned.regions.filter(r=>['declined','skipped'].includes(r.method)).map(r=>r.index));const warnings=[];if(blocked.size)warnings.push('Часть реплик оставлена в оригинале: полный перевод доступен по маркерам.');if(config.inpaint==='quality'&&cleaned.regions.some(r=>r.lamaStage==='failed'))warnings.push('LaMa не выполнила часть редро: использован быстрый клининг.');
  const fontStack=await loadMangaFont(config.font||'comic-relief');for(const [i,value]of valid.entries())if(!blocked.has(i))await drawFittedText(ctx,value.text,{...value.box,style:{bold:false,...value.box.style}},fontStack,40);timings.typesetMs=Math.round(performance.now()-t);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.94));if(!blob)throw Error('Не удалось собрать страницу.');timings.totalMs=Math.round(performance.now()-started);
  return {engine:'Libre Manga Translator',sourceLanguage:config.language,targetLanguage:'ru',machineTranslation:true,timings,warnings,inpaint:{requested:config.inpaint||'fast',methods:[...new Set(cleaned.regions.map(r=>r.method))],unpainted:blocked.size,segmentationUsed:!!segmentation},inputMode:config.apiInput==='vision'&&config.mode==='api'?'vision':'ocr',renderedImage:await blob.arrayBuffer(),renderedMime:blob.type,regions:valid.map(v=>({x:v.box.x1/bitmap.width,y:v.box.y1/bitmap.height,w:(v.box.x2-v.box.x1)/bitmap.width,h:(v.box.y2-v.box.y1)/bitmap.height,original:texts[v.index],text:v.text,placement:'note'}))};
 }finally{globalThis.lmtProgress=null;bitmap?.close();URL.revokeObjectURL(source);}
}
addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='mv-lmt-connect'||event.ports.length!==1)return;
 const port=event.ports[0];port.onmessage=async({data})=>{if(data.type!=='translate')return;if(running){port.postMessage({id:data.id,error:'Предыдущая страница ещё обрабатывается.'});return;}running=true;
  try{const result=await pipeline(data.bytes,data.config,status=>port.postMessage({id:data.id,status}));port.postMessage({id:data.id,result},result.renderedImage?[result.renderedImage]:[]);}catch(e){port.postMessage({id:data.id,error:e.message||String(e)});}finally{running=false;}
 };port.start();port.postMessage({ready:true,webgpu:!!navigator.gpu});
});
