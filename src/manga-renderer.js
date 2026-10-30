import {teleaInpaint} from '../lmt/upstream/lib/inpaint/telea.ts';
import {loadMangaFont} from '../reader-fonts/catalog.js';
import {fitComicText,styleFont,comicInkColor} from './manga-typeset.js';
import {prepareInkPatch,preparePageInk,compositeInkPatch,dilateInk} from './manga-cleaning.js';
export const READER_RENDER_VERSION=7;
function overlap(a,b){const area=(a[2]-a[0])*(a[3]-a[1]),other=(b[2]-b[0])*(b[3]-b[1]),shared=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));return shared/Math.max(1,area+other-shared);}
function maskRuns(patch,pageWidth,mask=patch.mask){const runs=[];for(let y=0;y<patch.height;y++){let x=0;while(x<patch.width){while(x<patch.width&&!mask[y*patch.width+x])x++;const start=x;while(x<patch.width&&mask[y*patch.width+x])x++;if(x>start)runs.push((patch.top+y)*pageWidth+patch.left+start,(patch.top+y)*pageWidth+patch.left+x);}}return runs;}
export async function renderComicPage({blob,page,font='auto',mode='hybrid',lama,cache=false,status=()=>{},moebiusStrategy='page',captureDebug=false,cleanOnly=false,preparedClean}){
 const start=performance.now(),bitmap=await createImageBitmap(blob);
 try{
  if(bitmap.width!==page.width||bitmap.height!==page.height||bitmap.width*bitmap.height>24_000_000)throw Error('Размер исходной страницы изменился.');
  const canvas=new OffscreenCanvas(bitmap.width,bitmap.height),ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(bitmap,0,0);
  const original=ctx.getImageData(0,0,canvas.width,canvas.height),working=new ImageData(original.data.slice(),original.width,original.height),plans=[],records=[],warnings=[],methods=new Set();let inpaintMs=0,typesetMs=0;
  const normalize=text=>String(text).normalize('NFC').replace(/[\u200b\u00ad]/g,'').replace(/\s+/g,' ').trim();
  // Plan and measure every caption before changing any pixel.
  for(const region of page.regions){
   const text=normalize(region.ru_translation||'');if(!cleanOnly&&!text)continue;
   const box=region.layout_bbox||region.bubble_bbox||region.text_bbox;
   const valid=b=>Array.isArray(b)&&b.length===4&&b.every(Number.isFinite)&&b[0]>=0&&b[1]>=0&&b[2]<=page.width&&b[3]<=page.height&&b[2]>b[0]&&b[3]>b[1];
   if(!valid(box)||!valid(region.text_bbox)){records.push({uid:region.uid,method:'declined',reason:'Некорректная область вёрстки'});continue;}
   if(cleanOnly){plans.push({region,box});continue;}
   const idFont=font==='auto'?styleFont(region.font_style):font,weight=region.font_style==='bold_scream'?700:400;let family;
   try{family=idFont==='serif'?'Georgia, serif':idFont==='mono'?'monospace':await loadMangaFont(idFont);}catch{family='system-ui';warnings.push('Шрифт не загрузился: использован системный шрифт.');}
   const flow=region.flow;
   if(flow&&(![flow.width,flow.height,flow.offsetY].every(Number.isFinite)||flow.width<=0||flow.height<=0||flow.offsetY<0||flow.offsetY+box[3]-box[1]>flow.height+1)){records.push({uid:region.uid,method:'declined',reason:'Некорректная связанная область'});continue;}
   const fit=fitComicText(text,flow?[0,0,flow.width,flow.height]:box,(value,size)=>{ctx.font=`${weight} ${size}px ${family}`;return ctx.measureText(value).width;},{oval:!flow&&!!region.bubble_bbox});
   if(!fit.fits){records.push({uid:region.uid,method:'declined',reason:'Перевод не помещается; исходные буквы сохранены'});continue;}
   plans.push({region,text,box,idFont,family,weight,fit});
  }
  // Conflicting duplicate boxes must not be painted over one another.
  const conflicts=new Set();for(let i=0;i<plans.length;i++)for(let j=i+1;j<plans.length;j++)if(overlap(plans[i].region.text_bbox,plans[j].region.text_bbox)>.85){conflicts.add(i);conflicts.add(j);}
  let lamaUnavailable=null,modelCalls=0,pageExecution,cleanupMask=captureDebug?new Uint8Array(original.width*original.height):null;
  if(mode==='moebius'&&moebiusStrategy==='page'&&!preparedClean){
   const t=performance.now(),eligible=[];
   for(const[i,plan]of plans.entries())if(conflicts.has(i))records.push({uid:plan.region.uid,method:'declined',reason:'Пересекающиеся текстовые области'});else eligible.push(plan);
   const merged=preparePageInk(original,eligible.map(p=>p.region),{model:'moebius'}),safe=[];
   if(cleanupMask)cleanupMask.set(merged.mask);
   for(const{region,patch}of merged.patches){const plan=eligible.find(p=>p.region===region);if(patch.declined)records.push({uid:region.uid,method:'declined',reason:patch.declined});else{plan.background=patch.background;safe.push(plan);}}
   if(safe.length&&merged.maskedPixels){
    status({phase:'cleaning',message:'Moebius · вся страница, общая маска · один проход',cleanedRegions:0,completedRegions:0,totalRegions:safe.length});
    try{
     if(!lama)throw Error('Moebius недоступен в этом обработчике');
     modelCalls++;pageExecution=await lama(working,merged.mask,message=>status({phase:'cleaning',message}));
     // Enforce the native mask at this boundary, regardless of provider output.
     for(let n=0;n<merged.mask.length;n++)if(!merged.mask[n])working.data.set(original.data.subarray(n*4,n*4+4),n*4);
     methods.add('moebius');for(const plan of safe){plan.painted=true;const patch=merged.patches.find(p=>p.region===plan.region).patch;if(cleanOnly)plan.runs=maskRuns(patch,original.width);records.push({uid:plan.region.uid,method:'moebius',execution:pageExecution,painted:true,sharedPagePass:true,maskKind:patch.maskKind,margin:patch.margin});}
    }catch(error){lamaUnavailable=error.message;working.data.set(original.data);for(const plan of safe)records.push({uid:plan.region.uid,method:'declined',reason:'Moebius: '+error.message});}
   }
   inpaintMs+=performance.now()-t;
  }
  let preparedPixels;
  if(preparedClean?.cleanedImage){const decoded=await createImageBitmap(new Blob([preparedClean.cleanedImage],{type:'image/png'}));try{if(decoded.width!==original.width||decoded.height!==original.height)throw Error('Размер фона изменился');const c=new OffscreenCanvas(original.width,original.height),cx=c.getContext('2d');cx.drawImage(decoded,0,0);preparedPixels=cx.getImageData(0,0,c.width,c.height).data;}finally{decoded.close();}}
  for(const[i,plan]of (mode==='moebius'&&moebiusStrategy==='page'&&!preparedClean?[]:plans).entries()){
   const region=plan.region;if(conflicts.has(i)){records.push({uid:region.uid,method:'declined',reason:'Пересекающиеся текстовые области'});continue;}
   const ready=preparedPixels&&preparedClean.regions.find(r=>r.uid===region.uid&&JSON.stringify(r.box)===JSON.stringify(region.text_bbox));
   if(ready){
    if(ready.painted){for(let n=0;n<ready.runs.length;n+=2){const a=ready.runs[n],b=ready.runs[n+1];working.data.set(preparedPixels.subarray(a*4,b*4),a*4);if(cleanupMask)cleanupMask.fill(1,a,b);}plan.painted=true;methods.add(ready.method);}
    records.push({...ready,prepared:true});continue;
   }
   status({phase:'cleaning',message:'Очистка областей · '+(i+1)+' / '+plans.length,cleanedRegions:records.filter(r=>r.painted).length,completedRegions:records.filter(r=>r.painted).length,totalRegions:plans.length});
   const t=performance.now(),patch=prepareInkPatch(original,region.text_bbox,{category:region.text_category,neural:mode!=='fast',model:mode});
   if(patch.declined){records.push({uid:region.uid,method:'declined',reason:patch.declined});continue;}
   if(cleanupMask)for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++)if(patch.mask[y*patch.width+x])cleanupMask[(patch.top+y)*original.width+patch.left+x]=1;
   const image=new ImageData(patch.data.slice(),patch.width,patch.height);let method,execution,write=patch.mask;
   try{
    if(mode==='quality'||mode==='moebius'||mode==='migan'||mode==='hybrid'&&!patch.flat){
     if(lamaUnavailable)throw Error(lamaUnavailable);if(!lama)throw Error('LaMa недоступна в этом обработчике');
     try{modelCalls++;execution=await lama(image,patch.mask,message=>status({phase:'cleaning',message}));}catch(error){lamaUnavailable=error.message;throw error;}
     method=mode==='moebius'?'moebius':mode==='migan'?'migan':'lama';write=dilateInk(patch.mask,patch.width,patch.height,2);
    }else if(patch.flat){
     for(let n=0;n<patch.mask.length;n++)if(patch.mask[n])for(let c=0;c<3;c++)image.data[n*4+c]=patch.background[c];method='adaptive-glyph-fill';
    }else{
     // Telea only receives a bounded mask with plenty of known context.
     if(patch.coverage>.6)throw Error('Недостаточно фона для Telea');teleaInpaint(image,patch.mask,3);method='telea';
    }
    compositeInkPatch(working,patch,image.data,write);plan.painted=true;if(cleanOnly)plan.runs=maskRuns(patch,original.width,write);plan.background=patch.background;methods.add(method);records.push({uid:region.uid,method,execution,painted:true,maskKind:patch.maskKind||'glyphs',coverage:patch.coverage,ms:performance.now()-t});
   }catch(error){records.push({uid:region.uid,method:'declined',reason:'Не удалось очистить область: '+error.message,ms:performance.now()-t});}
   inpaintMs+=performance.now()-t;
  }
  ctx.putImageData(working,0,0);
  if(cleanOnly)return {cleanedImage:await(await canvas.convertToBlob({type:'image/png'})).arrayBuffer(),width:page.width,height:page.height,mode,version:READER_RENDER_VERSION,inpaint:{modelCalls,execution:pageExecution,methods:[...methods]},regions:plans.map(p=>({...records.find(r=>r.uid===p.region.uid),uid:p.region.uid,box:p.region.text_bbox,painted:!!p.painted,runs:p.runs||[]})),timings:{inpaintMs}};
  let debug;
  if(captureDebug){
   const mc=new OffscreenCanvas(original.width,original.height),pixels=new ImageData(original.width,original.height);
   for(let n=0;n<cleanupMask.length;n++)if(cleanupMask[n])pixels.data.set([255,70,35,180],n*4);
   mc.getContext('2d').putImageData(pixels,0,0);
   debug={cleanedImage:await(await canvas.convertToBlob({type:'image/webp',quality:.95})).arrayBuffer(),maskImage:await(await mc.convertToBlob({type:'image/png'})).arrayBuffer(),detected:{width:page.width,height:page.height,regions:page.regions.map(r=>({id:r.uid,bbox:r.text_bbox}))},coordinatesKind:'translation'};
  }
  // Typography is the last phase. Cleanup never reads these newly drawn glyphs.
  // Explicit readable fallback: never claim a failed cleanup succeeded. Paint
  // Russian black with a white, rounded ~3px backing around the actual glyphs.
  for(const[i,p]of plans.entries())if(!p.painted&&!conflicts.has(i)){p.fallback=true;const record=records.find(r=>r.uid===p.region.uid);if(record)record.fallback='white-lettering';}
  const layouts=[];for(const p of plans)if(p.painted||p.fallback){
   const t=performance.now(),{box,fit}=p,ink=comicInkColor(working,box),dark=!p.fallback&&ink.dark,complex=p.fallback||ink.outline||['sfx','sign','whisper_aside'].includes(p.region.text_category);
   ctx.save();ctx.beginPath();ctx.rect(box[0]-(p.fallback?3:0),box[1]-(p.fallback?3:0),box[2]-box[0]+(p.fallback?6:0),box[3]-box[1]+(p.fallback?6:0));ctx.clip();ctx.font=`${p.weight} ${fit.fontSize}px ${p.family}`;ctx.textAlign='center';ctx.textBaseline='top';ctx.fillStyle=dark?'#fff':'#151515';ctx.lineJoin='round';
   const cx=(box[0]+box[2])/2,cy=p.region.flow?box[1]-p.region.flow.offsetY+(p.region.flow.height-fit.blockH)/2:(box[1]+box[3]-fit.blockH)/2;
   for(const[n,line]of fit.lines.entries()){if(complex){ctx.strokeStyle=dark?'#151515':'#fff';ctx.lineWidth=p.fallback?Math.max(6,fit.fontSize*.18):Math.max(2,fit.fontSize*.16);ctx.strokeText(line,cx,cy+n*fit.lineH);}ctx.fillText(line,cx,cy+n*fit.lineH);}
   ctx.restore();typesetMs+=performance.now()-t;layouts.push({uid:p.region.uid,font:p.idFont,fontSize:fit.fontSize,lines:fit.lines.length,color:dark?'#fff':'#151515',backgroundLuma:ink.luma,fallback:!!p.fallback,fits:true});
  }
  const unpainted=records.filter(r=>!r.painted).length;
  if(unpainted)warnings.push('Фон восстановлен для '+records.filter(r=>r.painted).length+' из '+records.length+' областей. При неудачной очистке перевод показан с белой подложкой.');
  if(lamaUnavailable)warnings.push((mode==='moebius'?'Moebius':mode==='migan'?'MI-GAN':'LaMa')+': '+lamaUnavailable);
  let cacheImage;if(cache&&!unpainted)cacheImage=await(await canvas.convertToBlob({type:'image/webp',quality:.94})).arrayBuffer();
  const renderedBitmap=canvas.transferToImageBitmap();
  return {renderedBitmap,cacheImage,debug,warnings,typesetting:{engine:'staged-cyrillic-ru-v3',layouts},inpaint:{requested:mode,strategy:mode==='moebius'?moebiusStrategy:'regions',modelCalls,execution:pageExecution,prepared:preparedClean?{cacheHit:!!preparedClean.cacheHit,inpaint:preparedClean.inpaint,timings:preparedClean.timings}:undefined,methods:[...methods],unpainted,regions:records},timings:{...page.timings,inpaintMs,typesetMs,renderMs:performance.now()-start},regions:page.regions.map(r=>({id:r.uid,text:r.ru_translation,original:r.source_text,x:r.text_bbox[0]/page.width,y:r.text_bbox[1]/page.height,w:(r.text_bbox[2]-r.text_bbox[0])/page.width,h:(r.text_bbox[3]-r.text_bbox[1])/page.height})),usage:page.usage,engine:page.engine||'Перевод → очистка → русский набор',cacheHit:page.cacheHit};
 }finally{bitmap.close();}
}
