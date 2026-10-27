// SPDX-License-Identifier: AGPL-3.0-or-later
// Cleanup + typesetting run off the UI thread. No OCR or translation network.
import {teleaInpaint} from '../lmt/upstream/lib/inpaint/telea.ts';
import {loadMangaFont} from '../reader-fonts/catalog.js';
import {fitComicText,styleFont} from './manga-typeset.js';

function clean(ctx,region,complex){
 const[x,y,x2,y2]=region.text_bbox.map(Math.round),pad=complex?16:3;
 const left=Math.max(0,x-pad),top=Math.max(0,y-pad),w=Math.min(ctx.canvas.width,x2+pad)-left,h=Math.min(ctx.canvas.height,y2+pad)-top;
 if(w<1||h<1)return {method:'none',background:[255,255,255]};
 const data=ctx.getImageData(left,top,w,h),pixels=data.data,edge=[[],[],[]];
 for(let j=0;j<h;j++)for(let i=0;i<w;i++)if(i<2||i>=w-2||j<2||j>=h-2)for(let c=0;c<3;c++)edge[c].push(pixels[(j*w+i)*4+c]);
 const background=edge.map(a=>a.sort((a,b)=>a-b)[a.length>>1]??255);
 const flat=edge.every((a,c)=>a.reduce((n,v)=>n+Math.abs(v-background[c]),0)/Math.max(1,a.length)<18);
 const seed=new Uint8Array(w*h),mask=new Uint8Array(w*h);
 for(let j=Math.max(0,y-top);j<Math.min(h,y2-top);j++)for(let i=Math.max(0,x-left);i<Math.min(w,x2-left);i++){
  const p=(j*w+i)*4;if(Math.max(...background.map((b,c)=>Math.abs(pixels[p+c]-b)))>28)seed[j*w+i]=1;
 }
 for(let j=1;j<h-1;j++)for(let i=1;i<w-1;i++)if(seed[j*w+i])for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++)mask[(j+dy)*w+i+dx]=1;
 if(flat&&!complex){for(let n=0;n<mask.length;n++)if(mask[n])for(let c=0;c<3;c++)pixels[n*4+c]=background[c];}
 else teleaInpaint(data,mask,3);
 ctx.putImageData(data,left,top);return {method:flat&&!complex?'adaptive-glyph-fill':'telea',background};
}
async function render({data:{id,blob,page,font='auto'}}){
 let bitmap;
 try{
  const start=performance.now();bitmap=await createImageBitmap(blob);
  if(bitmap.width!==page.width||bitmap.height!==page.height||bitmap.width*bitmap.height>24_000_000)throw Error('Размер исходной страницы изменился.');
  const canvas=new OffscreenCanvas(bitmap.width,bitmap.height),ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(bitmap,0,0);
  const layouts=[],warnings=[],methods=new Set();let inpaintMs=0,typesetMs=0;
  for(const region of page.regions){
   if(!region.ru_translation?.trim())continue;
   const box=region.layout_bbox||region.bubble_bbox||region.text_bbox,idFont=font==='auto'?styleFont(region.font_style):font;
   const family=idFont==='serif'?'Georgia, serif':idFont==='mono'?'monospace':await loadMangaFont(idFont);
   const bold=region.font_style==='bold_scream',weight=bold?700:400;
   const fit=fitComicText(region.ru_translation,box,(text,size)=>{ctx.font=`${weight} ${size}px ${family}`;return ctx.measureText(text).width;},{oval:!!region.bubble_bbox});
   if(!fit.fits){warnings.push('Реплика '+region.uid+' не помещается: оригинал сохранён, перевод доступен в тексте.');continue;}
   let t=performance.now();const complex=['sfx','sign','whisper_aside'].includes(region.text_category);const cleaned=clean(ctx,region,complex);methods.add(cleaned.method);const dark=cleaned.background.reduce((a,v)=>a+v,0)<384;inpaintMs+=performance.now()-t;
   t=performance.now();ctx.save();ctx.font=`${weight} ${fit.fontSize}px ${family}`;ctx.textAlign='center';ctx.textBaseline='top';ctx.fillStyle=dark?'#fff':'#151515';ctx.lineJoin='round';
   const cx=(box[0]+box[2])/2,cy=(box[1]+box[3]-fit.blockH)/2;
   for(const[n,line]of fit.lines.entries()){
    if(complex){ctx.strokeStyle=dark?'#151515':'#fff';ctx.lineWidth=Math.max(2,fit.fontSize*.16);ctx.strokeText(line,cx,cy+n*fit.lineH);}
    ctx.fillText(line,cx,cy+n*fit.lineH);
   }
   ctx.restore();typesetMs+=performance.now()-t;layouts.push({uid:region.uid,font:idFont,fontSize:fit.fontSize,lines:fit.lines.length,fits:true});
  }
  const renderedBitmap=canvas.transferToImageBitmap();
  self.postMessage({id,result:{renderedBitmap,warnings,typesetting:{engine:'worker-cyrillic-oval-v1',layouts},inpaint:{methods:[...methods]},timings:{...page.timings,inpaintMs,typesetMs,renderMs:performance.now()-start},regions:page.regions.map(r=>({id:r.uid,text:r.ru_translation,original:r.source_text,x:r.text_bbox[0]/page.width,y:r.text_bbox[1]/page.height,w:(r.text_bbox[2]-r.text_bbox[0])/page.width,h:(r.text_bbox[3]-r.text_bbox[1])/page.height})),usage:page.usage,engine:'Gemma 4 · VM JSON → Canvas Worker',cacheHit:page.cacheHit}},[renderedBitmap]);
 }catch(error){self.postMessage({id,error:error.message});}finally{bitmap?.close();}
};

let queue=Promise.resolve();
self.onmessage=event=>{queue=queue.catch(()=>{}).then(()=>render(event));};
