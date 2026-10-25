// SPDX-License-Identifier: AGPL-3.0-or-later
import './shim.js';
import {validateConfig} from './config.js';
const contexts=new Map();
let running=false;
async function pipeline(bytes,config,progress){
 validateConfig(config);
 if(bytes.byteLength>10*1024*1024)throw Error('Страница превышает 10 МБ.');
 if(config.mode!=='api'&&!navigator.gpu)throw Error('Для локального LMT нужен WebGPU. Используй совместимый браузер или режим своего LLM-сервера.');
 globalThis.lmtProgress=progress;
 const ort=await import('onnxruntime-web/all');ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=new URL('./',location.href).href;
 const [{detectTextBubble},{textRecognise},{translateLocal},{translateWithServer},{inpaintImageAuto,inpaintImageQuality},{drawFittedText}]=await Promise.all([import('./upstream/lib/detections/main.ts'),import('./upstream/lib/ocr/main.ts'),import('./upstream/lib/webllm.ts'),import('./upstream/lib/server/main.ts'),import('./upstream/lib/inpaint/ladder.ts'),import('./upstream/lib/canvas/text-fit.ts')]);
 const source=URL.createObjectURL(new Blob([bytes]));let bitmap;
 try{
  bitmap=await createImageBitmap(new Blob([bytes]));if(bitmap.width*bitmap.height>24000000)throw Error('Страница превышает 24 Мп.');
  progress('Определяем речевые области · при первом запуске загружаются модели');const boxes=await detectTextBubble(source,.5,config.detector||'comic-bubble');
  if(boxes.length>100)throw Error('Найдено слишком много областей. Раздели длинный вебтун на страницы.');
  if(!boxes.length)return {regions:[],engine:'Libre Manga Translator',message:'Речевые области не найдены.'};
  progress('Распознаём текст · '+boxes.length+' областей');const ocr=await textRecognise(source,boxes,config.language||'English',.55,4,48,{enabled:true},config.ocr||'paddle');
  const texts=ocr.results.map(r=>r.gateSkip||r.failed?'':r.text);
  if(!texts.some(Boolean))return {regions:[],engine:'Libre Manga Translator',message:'OCR не распознал реплики. Проверь исходный язык и движок.'};
  progress('Переводим полные реплики на русский');let translated;const contextKey=config.contextKey||'default',context=contexts.get(contextKey);
  if(config.mode==='api'){
   const endpoint=new URL(config.host);if(endpoint.username||endpoint.password||!['https:','http:'].includes(endpoint.protocol))throw Error('Некорректный адрес своего сервера.');
   if(endpoint.protocol==='http:'&&!['localhost','127.0.0.1','[::1]'].includes(endpoint.hostname))throw Error('Для удалённого сервера нужен HTTPS.');
   translated=await translateWithServer(texts,'Russian',config.language||'English',context,{serverHost:endpoint.href,serverSchema:'openai',serverModel:config.serverModel,useServerApiKey:false,temperature:.2});
  }else translated=await translateLocal(texts,'Russian',config.language||'English',context,config.model||'Qwen3.5-0.8B-q4f16_1-MLC',.2);
  if(translated.context){contexts.set(contextKey,translated.context);while(contexts.size>8)contexts.delete(contexts.keys().next().value);}
  const valid=boxes.map((b,i)=>({box:b,index:i,text:String(translated.translations?.[i]||'')})).filter(v=>texts[v.index]&&v.text);
  if(!valid.length)throw Error('Модель не вернула переведённые реплики. Попробуй другую модель.');
  progress('Восстанавливаем фон и набираем русский текст');const cleaned=await(config.inpaint==='quality'?inpaintImageQuality:inpaintImageAuto)(source,valid.map(v=>v.box));
  const cleanBitmap=await createImageBitmap(await(await fetch(cleaned.url)).blob()),canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;const ctx=canvas.getContext('2d');ctx.drawImage(cleanBitmap,0,0);cleanBitmap.close();
  for(const value of valid)await drawFittedText(ctx,value.text,value.box,'system-ui, sans-serif',40);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.94));if(!blob)throw Error('Не удалось собрать страницу.');
  return {engine:'Libre Manga Translator',sourceLanguage:config.language,targetLanguage:'ru',machineTranslation:true,renderedImage:await blob.arrayBuffer(),renderedMime:blob.type,regions:valid.map(v=>({x:v.box.x1/bitmap.width,y:v.box.y1/bitmap.height,w:(v.box.x2-v.box.x1)/bitmap.width,h:(v.box.y2-v.box.y1)/bitmap.height,original:texts[v.index],text:v.text,placement:'note'}))};
 }finally{globalThis.lmtProgress=null;bitmap?.close();URL.revokeObjectURL(source);}
}
addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='mv-lmt-connect'||event.ports.length!==1)return;
 const port=event.ports[0];port.onmessage=async({data})=>{if(data.type!=='translate')return;if(running){port.postMessage({id:data.id,error:'Предыдущая страница ещё обрабатывается.'});return;}running=true;
  try{const result=await pipeline(data.bytes,data.config,status=>port.postMessage({id:data.id,status}));port.postMessage({id:data.id,result},result.renderedImage?[result.renderedImage]:[]);}catch(e){port.postMessage({id:data.id,error:e.message||String(e)});}finally{running=false;}
 };port.start();port.postMessage({ready:true,webgpu:!!navigator.gpu});
});
