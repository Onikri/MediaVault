// SPDX-License-Identifier: AGPL-3.0-or-later
import './entry.js';
import {mount,unmount} from 'svelte';
import Overlay from './upstream/lib/components/Overlay.svelte';
import {drawFittedText,resolveFontStack} from './upstream/lib/canvas/text-fit.ts';
import './upstream/assets/app.css';
import './editor.css';

let port,config,bytes,bitmap,component,originalSrc,cleanedSrc,lastResult,sequence=0;
const pending=new Map(),urls=new Set();
const status=text=>{document.getElementById('editor-status').textContent=text;};
function imageUrl(data,mime='image/webp'){const url=URL.createObjectURL(new Blob([data],{type:mime}));urls.add(url);return url;}
async function stage(operation,boxes,extra={},sourceBytes=bytes){
 if(config.engine!=='backend')return globalThis.mangaTranslate(sourceBytes.slice(0),{...config,operation,boxes,...extra},status);
 const id=++sequence;
 return new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{pending.delete(id);reject(Error('Backend не завершил обработку.'));},16*60*1000);
  pending.set(id,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});
  const image=sourceBytes.slice(0);port.postMessage({type:'stage',id,operation,boxes,...extra,bytes:image},[image]);
 });
}
let cleanedKey='';
async function clean(boxes){
 const active=boxes.filter(box=>!box.gateSkip),key=JSON.stringify(active.map(({x1,y1,x2,y2})=>({x1,y1,x2,y2})));
 if(cleanedSrc&&key===cleanedKey)return cleanedSrc;
 const result=await stage('inpaint',active);cleanedSrc=imageUrl(result.cleanedImage);cleanedKey=key;return cleanedSrc;
}
async function render(translations,boxes){
 const valid=boxes.filter((_,i)=>translations[i]&&!boxes[i].gateSkip);
 const background=await clean(valid),image=await createImageBitmap(await(await fetch(background)).blob());
 const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
 const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,canvas.width,canvas.height);image.close();
 const font=await resolveFontStack();
 for(let i=0;i<boxes.length;i++)if(translations[i]&&!boxes[i].gateSkip)await drawFittedText(ctx,translations[i],boxes[i],font,40);
 const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.95));
 if(!blob)throw Error('Не удалось собрать страницу.');
 lastResult={renderedImage:await blob.arrayBuffer(),renderedMime:'image/webp',regions:boxes.map((b,i)=>({x:b.x1/bitmap.width,y:b.y1/bitmap.height,w:(b.x2-b.x1)/bitmap.width,h:(b.y2-b.y1)/bitmap.height,text:translations[i]||'',original:b.original||'',style:b.style,placement:'note'}))};
 status('Страница готова. Примени изменения, чтобы вернуться в читалку.');
 return imageUrl(lastResult.renderedImage);
}
async function applyPatches(base,added,removed){
 const baseBytes=await(await fetch(base)).arrayBuffer();
 const result=added.length?await stage('inpaint',added,{},baseBytes):{cleanedImage:baseBytes};
 const image=await createImageBitmap(new Blob([result.cleanedImage]));
 const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
 const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);image.close();
 for(const b of removed)ctx.drawImage(bitmap,b.x1,b.y1,b.x2-b.x1,b.y2-b.y1,b.x1,b.y1,b.x2-b.x1,b.y2-b.y1);
 const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
 cleanedSrc=imageUrl(await blob.arrayBuffer(),'image/png');return cleanedSrc;
}
function exportJpeg(canvas,quality=.95,filename='MediaVault-translated.jpg'){
 canvas.toBlob(blob=>{if(!blob)return;const link=document.createElement('a'),url=URL.createObjectURL(blob);link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},'image/jpeg',quality);
}
async function initialize(data){
 config=data.config;bytes=data.bytes;lastResult=data.result||null;
 await storage.setItem('sync:source-lang',config.language||'English');
 await storage.setItem('sync:ocr-engine',config.ocr||'paddle');
 await storage.setItem('sync:current-mode',config.mode||'api');
 originalSrc=imageUrl(bytes);bitmap=await createImageBitmap(new Blob([bytes]));
 const image=document.getElementById('original');image.src=originalSrc;await image.decode();
 const wrapper=document.getElementById('page-wrapper'),rect=image.getBoundingClientRect();
 const cached=data.result?.regions?.length?{
  bboxes:data.result.regions.map(r=>({x1:r.x*bitmap.width,y1:r.y*bitmap.height,x2:(r.x+r.w)*bitmap.width,y2:(r.y+r.h)*bitmap.height,confidence:1,style:r.style,original:r.original})),
  translatedSrc:data.result.renderedImage?imageUrl(data.result.renderedImage):originalSrc,
  translations:data.result.regions.map(r=>r.text||''),sourceTexts:data.result.regions.map(r=>r.original||'')
 }:undefined;
 component=mount(Overlay,{target:document.getElementById('editor-mount'),props:{
  targetImageRect:rect,scaleX:rect.width/bitmap.width,scaleY:rect.height/bitmap.height,originalSrc,wrapper,
  getTranslationCache:async()=>cached,
  requestBubbleDetection:async()=>{try{return (await stage('detect')).boxes||[];}catch(e){return {error:e.message};}},
  requestTextTranslation:async(boxes,_,options)=>{try{const result=await stage('translate',boxes,{gateForce:!!options?.gateForce});for(let i=0;i<boxes.length;i++)boxes[i].original=result.sourceTexts?.[i]||'';return result;}catch(e){return {error:e.message};}},
  renderTranslations:render,getCleanedSrc:clean,applyInpaintPatches:applyPatches,exportCanvasToJpeg:exportJpeg,
  onClose:()=>port.postMessage({type:'close'})
 }});
 const observer=new ResizeObserver(()=>{const r=image.getBoundingClientRect();wrapper.dispatchEvent(new CustomEvent('lmt:geometry-change',{detail:{width:r.width,height:r.height,scaleX:r.width/bitmap.width,scaleY:r.height/bitmap.height}}));});observer.observe(image);
 status('Уточни области, затем переведи страницу. Изменения хранятся в памяти.');
}
addEventListener('message',event=>{
 if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='mv-lmt-editor-connect'||event.ports.length!==1||port)return;
 port=event.ports[0];port.onmessage=async({data})=>{
  if(data.type==='init'){try{await initialize(data);}catch(e){status(e.message);}}
  else if(data.type==='stage-result'){
   const task=pending.get(data.id);if(!task)return;pending.delete(data.id);data.error?task.reject(Error(data.error)):task.resolve(data.result);
  }else if(data.type==='progress')status(data.status);
 };port.start();port.postMessage({type:'ready'});
});
document.getElementById('close').onclick=()=>port?.postMessage({type:'close'});
document.getElementById('save').onclick=()=>{if(lastResult?.renderedImage)port?.postMessage({type:'apply',result:lastResult});else status('Сначала переведи страницу или примени изменения редактора.');};
document.getElementById('font').onchange=event=>storage.setItem('sync:text-font',event.target.value);
document.getElementById('custom-font').onchange=async event=>{
 const file=event.target.files[0];if(!file)return;if(file.size>10*1024*1024){status('Шрифт превышает 10 МБ.');return;}
 const reader=new FileReader();reader.onload=async()=>{
  const name='MediaVaultCustom',fonts=[{name,dataUrl:reader.result}];
  await storage.setItem('local:custom-fonts',fonts);await storage.setItem('sync:text-font',name);
  status('Шрифт загружен. Открой правку текста, чтобы применить его.');
 };reader.readAsDataURL(file);
};
addEventListener('pagehide',()=>{if(component)void unmount(component);bitmap?.close();for(const url of urls)URL.revokeObjectURL(url);for(const task of pending.values())task.reject(Error('Редактор закрыт.'));pending.clear();});
