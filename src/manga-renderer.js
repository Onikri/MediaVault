import {teleaInpaint} from '../lmt/upstream/lib/inpaint/telea.ts';
import {loadMangaFont} from '../reader-fonts/catalog.js';
import {fitComicText,styleFont} from './manga-typeset.js';
import {prepareInkPatch,preparePageInk,compositeInkPatch,dilateInk} from './manga-cleaning.js';
export const READER_RENDER_VERSION=5;
function overlap(a,b){const area=(a[2]-a[0])*(a[3]-a[1]),other=(b[2]-b[0])*(b[3]-b[1]),shared=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));return shared/Math.max(1,area+other-shared);}
export async function renderComicPage({blob,page,font='auto',mode='hybrid',lama,cache=false,status=()=>{},moebiusStrategy='page'}){
 const start=performance.now(),bitmap=await createImageBitmap(blob);
 try{
  if(bitmap.width!==page.width||bitmap.height!==page.height||bitmap.width*bitmap.height>24_000_000)throw Error('Размер исходной страницы изменился.');
  const canvas=new OffscreenCanvas(bitmap.width,bitmap.height),ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(bitmap,0,0);
  const original=ctx.getImageData(0,0,canvas.width,canvas.height),working=new ImageData(original.data.slice(),original.width,original.height),plans=[],records=[],warnings=[],methods=new Set();let inpaintMs=0,typesetMs=0;
  const normalize=text=>String(text).normalize('NFC').replace(/[\u200b\u00ad]/g,'').replace(/\s+/g,' ').trim();
  // Plan and measure every caption before changing any pixel.
  for(const region of page.regions){
   const text=normalize(region.ru_translation||'');if(!text)continue;
   const box=region.layout_bbox||region.bubble_bbox||region.text_bbox;
   const valid=b=>Array.isArray(b)&&b.length===4&&b.every(Number.isFinite)&&b[0]>=0&&b[1]>=0&&b[2]<=page.width&&b[3]<=page.height&&b[2]>b[0]&&b[3]>b[1];
   if(!valid(box)||!valid(region.text_bbox)){records.push({uid:region.uid,method:'declined',reason:'Некорректная область вёрстки'});continue;}
   const idFont=font==='auto'?styleFont(region.font_style):font,weight=region.font_style==='bold_scream'?700:400;let family;
   try{family=idFont==='serif'?'Georgia, serif':idFont==='mono'?'monospace':await loadMangaFont(idFont);}catch{family='system-ui';warnings.push('Шрифт не загрузился: использован системный шрифт.');}
   const fit=fitComicText(text,box,(value,size)=>{ctx.font=`${weight} ${size}px ${family}`;return ctx.measureText(value).width;},{oval:!!region.bubble_bbox});
   if(!fit.fits){records.push({uid:region.uid,method:'declined',reason:'Перевод не помещается; исходные буквы сохранены'});continue;}
   plans.push({region,text,box,idFont,family,weight,fit});
  }
  // Conflicting duplicate boxes must not be painted over one another.
  const conflicts=new Set();for(let i=0;i<plans.length;i++)for(let j=i+1;j<plans.length;j++)if(overlap(plans[i].region.text_bbox,plans[j].region.text_bbox)>.85){conflicts.add(i);conflicts.add(j);}
  let lamaUnavailable=null,modelCalls=0,pageExecution;
  if(mode==='moebius'&&moebiusStrategy==='page'){
   const t=performance.now(),eligible=[];
   for(const[i,plan]of plans.entries())if(conflicts.has(i))records.push({uid:plan.region.uid,method:'declined',reason:'Пересекающиеся текстовые области'});else eligible.push(plan);
   const merged=preparePageInk(original,eligible.map(p=>p.region)),safe=[];
   for(const{region,patch}of merged.patches){const plan=eligible.find(p=>p.region===region);if(patch.declined)records.push({uid:region.uid,method:'declined',reason:patch.declined});else{plan.background=patch.background;safe.push(plan);}}
   if(safe.length&&merged.maskedPixels){
    status({phase:'cleaning',message:'Moebius · вся страница, общая маска · один проход',cleanedRegions:0,completedRegions:0,totalRegions:safe.length});
    try{
     if(!lama)throw Error('Moebius недоступен в этом обработчике');
     modelCalls++;pageExecution=await lama(working,merged.mask,message=>status({phase:'cleaning',message}));
     // Enforce the native mask at this boundary, regardless of provider output.
     for(let n=0;n<merged.mask.length;n++)if(!merged.mask[n])working.data.set(original.data.subarray(n*4,n*4+4),n*4);
     methods.add('moebius');for(const plan of safe){plan.painted=true;records.push({uid:plan.region.uid,method:'moebius',execution:pageExecution,painted:true,sharedPagePass:true});}
    }catch(error){lamaUnavailable=error.message;working.data.set(original.data);for(const plan of safe)records.push({uid:plan.region.uid,method:'declined',reason:'Moebius: '+error.message});}
   }
   inpaintMs+=performance.now()-t;
  }
  for(const[i,plan]of (mode==='moebius'&&moebiusStrategy==='page'?[]:plans).entries()){
   const region=plan.region;if(conflicts.has(i)){records.push({uid:region.uid,method:'declined',reason:'Пересекающиеся текстовые области'});continue;}
   status({phase:'cleaning',message:'Очистка областей · '+(i+1)+' / '+plans.length,cleanedRegions:records.filter(r=>r.painted).length,completedRegions:records.filter(r=>r.painted).length,totalRegions:plans.length});
   const t=performance.now(),patch=prepareInkPatch(original,region.text_bbox,{category:region.text_category,neural:mode!=='fast'});
   if(patch.declined){records.push({uid:region.uid,method:'declined',reason:patch.declined});continue;}
   const image=new ImageData(patch.data.slice(),patch.width,patch.height);let method,execution,write=patch.mask;
   try{
    if(mode==='quality'||mode==='moebius'||mode==='hybrid'&&!patch.flat){
     if(lamaUnavailable)throw Error(lamaUnavailable);if(!lama)throw Error('LaMa недоступна в этом обработчике');
     try{modelCalls++;execution=await lama(image,patch.mask,message=>status({phase:'cleaning',message}));}catch(error){lamaUnavailable=error.message;throw error;}
     method=mode==='moebius'?'moebius':'lama';write=dilateInk(patch.mask,patch.width,patch.height,2);
    }else if(patch.flat){
     for(let n=0;n<patch.mask.length;n++)if(patch.mask[n])for(let c=0;c<3;c++)image.data[n*4+c]=patch.background[c];method='adaptive-glyph-fill';
    }else{
     // Telea only receives a bounded mask with plenty of known context.
     if(patch.coverage>.6)throw Error('Недостаточно фона для Telea');teleaInpaint(image,patch.mask,3);method='telea';
    }
    compositeInkPatch(working,patch,image.data,write);plan.painted=true;plan.background=patch.background;methods.add(method);records.push({uid:region.uid,method,execution,painted:true,coverage:patch.coverage,ms:performance.now()-t});
   }catch(error){records.push({uid:region.uid,method:'declined',reason:'Не удалось очистить область: '+error.message,ms:performance.now()-t});}
   inpaintMs+=performance.now()-t;
  }
  ctx.putImageData(working,0,0);
  // Typography is the last phase. Cleanup never reads these newly drawn glyphs.
  const layouts=[];for(const p of plans)if(p.painted){
   const t=performance.now(),dark=p.background.reduce((a,v)=>a+v,0)<384,complex=['sfx','sign','whisper_aside'].includes(p.region.text_category),{box,fit}=p;
   ctx.save();ctx.beginPath();ctx.rect(box[0],box[1],box[2]-box[0],box[3]-box[1]);ctx.clip();ctx.font=`${p.weight} ${fit.fontSize}px ${p.family}`;ctx.textAlign='center';ctx.textBaseline='top';ctx.fillStyle=dark?'#fff':'#151515';ctx.lineJoin='round';
   const cx=(box[0]+box[2])/2,cy=(box[1]+box[3]-fit.blockH)/2;
   for(const[n,line]of fit.lines.entries()){if(complex){ctx.strokeStyle=dark?'#151515':'#fff';ctx.lineWidth=Math.max(2,fit.fontSize*.16);ctx.strokeText(line,cx,cy+n*fit.lineH);}ctx.fillText(line,cx,cy+n*fit.lineH);}
   ctx.restore();typesetMs+=performance.now()-t;layouts.push({uid:p.region.uid,font:p.idFont,fontSize:fit.fontSize,lines:fit.lines.length,fits:true});
  }
  const unpainted=records.filter(r=>!r.painted).length;
  if(unpainted)warnings.push('Очищено '+layouts.length+' из '+records.length+' областей. Остальные сохранены в оригинале; перевод доступен под страницей.');
  if(lamaUnavailable)warnings.push((mode==='moebius'?'Moebius':'LaMa')+': '+lamaUnavailable);
  let cacheImage;if(cache&&!unpainted)cacheImage=await(await canvas.convertToBlob({type:'image/webp',quality:.94})).arrayBuffer();
  const renderedBitmap=canvas.transferToImageBitmap();
  return {renderedBitmap,cacheImage,warnings,typesetting:{engine:'staged-cyrillic-v2',layouts},inpaint:{requested:mode,strategy:mode==='moebius'?moebiusStrategy:'regions',modelCalls,execution:pageExecution,methods:[...methods],unpainted,regions:records},timings:{...page.timings,inpaintMs,typesetMs,renderMs:performance.now()-start},regions:page.regions.map(r=>({id:r.uid,text:r.ru_translation,original:r.source_text,x:r.text_bbox[0]/page.width,y:r.text_bbox[1]/page.height,w:(r.text_bbox[2]-r.text_bbox[0])/page.width,h:(r.text_bbox[3]-r.text_bbox[1])/page.height})),usage:page.usage,engine:page.engine||'Перевод → очистка → русский набор',cacheHit:page.cacheHit};
 }finally{bitmap.close();}
}
