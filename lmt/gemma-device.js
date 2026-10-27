// SPDX-License-Identifier: AGPL-3.0-or-later
// Detection and cleanup only. No OCR graph or translation model is loaded.
import {validateConfig} from './config.js';
import {drawStyledRegion} from './typography.js';

async function setup(config){
 validateConfig({...config,mode:'gemma'});
 const ort=await import('onnxruntime-web/all');ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=new URL('./',location.href).href;
}
export async function prepareGemmaPage(bytes,config,progress){
 await setup(config);if(bytes.byteLength>10*1024*1024)throw Error('Страница превышает 10 МБ.');
 const bitmap=await createImageBitmap(new Blob([bytes])),url=URL.createObjectURL(new Blob([bytes]));
 try{
  if(bitmap.width*bitmap.height>24_000_000)throw Error('Страница превышает 24 Мп.');
  progress('RT-DETR Comic v4 · ищем текст и координаты без OCR');const started=performance.now();
  const{detectTextBubble}=await import('./upstream/lib/detections/main.ts');
  const boxes=await detectTextBubble(url,.15,'comic-bubble');
  if(boxes.length>100)throw Error('Слишком много областей на странице. Раздели длинный вебтун.');
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
  const id='P'+((Number.isInteger(config.pageIndex)?config.pageIndex:0)+1)+'_'+digest.slice(0,12);
  const regions=boxes.map((b,i)=>({id:id+'_B'+(i+1),bbox:[b.x1,b.y1,b.x2,b.y2].map(v=>Math.round(v*100)/100),class:'text'}));
  for(const r of regions)if(!r.bbox.every(Number.isFinite)||r.bbox[0]<0||r.bbox[1]<0||r.bbox[2]>bitmap.width||r.bbox[3]>bitmap.height||r.bbox[2]<=r.bbox[0]||r.bbox[3]<=r.bbox[1])throw Error('Детектор вернул некорректные координаты.');
  const scale=Math.min(1,1280/Math.max(bitmap.width,bitmap.height)),canvas=document.createElement('canvas');canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);
  const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
  for(const [i,r]of regions.entries()){
   const[x,y,z,w]=r.bbox.map(v=>v*scale);ctx.strokeStyle='#e11d48';ctx.lineWidth=2;ctx.strokeRect(x,y,z-x,w-y);
   const label='B'+(i+1);ctx.font='bold 12px sans-serif';const top=Math.max(0,y-16),lw=ctx.measureText(label).width+6;
   ctx.fillStyle='white';ctx.fillRect(x,top,lw,15);ctx.fillStyle='#b10024';ctx.textBaseline='top';ctx.fillText(label,x+3,top+1);
  }
  const encoded=canvas.toDataURL('image/webp',.8),match=/^data:(image\/\w+);base64,(.+)$/.exec(encoded);
  return {id,width:bitmap.width,height:bitmap.height,image:match[2],mime:match[1],regions,detectionMs:Math.round(performance.now()-started),sourceSha256:digest};
 }finally{bitmap.close();URL.revokeObjectURL(url);}
}

export async function renderGemmaPage(bytes,config,progress){
 await setup(config);const prepared=config.prepared,result=config.translation;
 if(!prepared||!result||prepared.id!==result.id)throw Error('Ответ относится к другой странице. Оригинал сохранён.');
 const expected=new Map(prepared.regions.map(r=>[r.id,r])),seen=new Set();
 for(const r of result.regions||[]){
  if(!expected.has(r.id)||seen.has(r.id)||JSON.stringify(r.bbox)!==JSON.stringify(expected.get(r.id).bbox))throw Error('Перевод нарушил координаты или ID. Оригинал сохранён.');seen.add(r.id);
 }
 if(seen.size!==expected.size)throw Error('В переводе не хватает областей. Оригинал сохранён.');
 const url=URL.createObjectURL(new Blob([bytes]));let bitmap,cleanedUrl;
 try{
  bitmap=await createImageBitmap(new Blob([bytes]));if(bitmap.width!==prepared.width||bitmap.height!==prepared.height)throw Error('Размер страницы изменился после детекции.');
  const valid=result.regions.filter(r=>r.status==='translated'&&r.translation?.trim()),warnings=[];
  const unreadable=result.regions.filter(r=>r.status==='unreadable').length;if(unreadable)warnings.push('Не прочитано областей: '+unreadable+'. Они оставлены в оригинале.');
  const boxes=valid.map(r=>({x1:r.bbox[0],y1:r.bbox[1],x2:r.bbox[2],y2:r.bbox[3]}));
  progress('LaMa · восстанавливаем фон на устройстве');let t=performance.now();
  const{inpaintImageQuality,inpaintImageAuto}=await import('./upstream/lib/inpaint/ladder.ts');
  const cleaned=boxes.length?await(config.inpaint==='fast'?inpaintImageAuto:inpaintImageQuality)(url,boxes):{url,regions:[]};
  cleanedUrl=cleaned.url;
  const inpaintMs=Math.round(performance.now()-t),blocked=new Set(cleaned.regions.filter(r=>['declined','skipped'].includes(r.method)).map(r=>r.index));
  if(blocked.size)warnings.push('Часть областей оставлена в оригинале: фон не удалось безопасно очистить.');
  if(cleaned.regions.some(r=>r.lamaStage==='failed'))warnings.push('Часть очистки выполнена резервным быстрым методом после ошибки LaMa.');
  const cleanBlob=await(await fetch(cleaned.url)).blob(),cleanBitmap=await createImageBitmap(cleanBlob),canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
  const ctx=canvas.getContext('2d');ctx.drawImage(cleanBitmap,0,0);cleanBitmap.close();
  progress('Набираем перевод · шрифт, цвет, обводка, наклон и переносы');t=performance.now();const layouts=[];
  for(const [i,r]of valid.entries())if(!blocked.has(i))layouts.push(await drawStyledRegion(ctx,r,config.font||'auto'));
  const typesetMs=Math.round(performance.now()-t),blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.94));if(!blob)throw Error('Не удалось собрать страницу.');
  const renderedImage=await blob.arrayBuffer();
  return {engine:'RT-DETR → own backend → Google Gemma → LaMa',inputMode:'vision',sourceLanguage:config.language,targetLanguage:'ru',machineTranslation:true,renderedImage,renderedMime:blob.type,...(config.returnCleaned?{cleanedImage:await cleanBlob.arrayBuffer()}:{}),
   timings:{detectionMs:prepared.detectionMs,ocrMs:0,translationMs:config.cloudMs||0,inpaintMs,typesetMs},usage:config.usage||[],warnings,
   typesetting:{engine:'source-style-cyrillic-v1',font:config.font||'auto',layouts},inpaint:{requested:config.inpaint||'quality',methods:[...new Set(cleaned.regions.map(r=>r.method))],unpainted:blocked.size},
   regions:result.regions.map(r=>({id:r.id,x:r.bbox[0]/bitmap.width,y:r.bbox[1]/bitmap.height,w:(r.bbox[2]-r.bbox[0])/bitmap.width,h:(r.bbox[3]-r.bbox[1])/bitmap.height,text:r.translation,original:r.source_text||'',placement:'note',fontStyle:r.font_style,speechStyle:r.speech_style,status:r.status,appearance:r.appearance}))};
 }finally{bitmap?.close();URL.revokeObjectURL(url);if(cleanedUrl&&cleanedUrl!==url)URL.revokeObjectURL(cleanedUrl);}
}
