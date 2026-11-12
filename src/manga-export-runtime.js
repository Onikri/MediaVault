// The VM uses the reader's actual Google, cleanup and Cyrillic layout pipeline.
import {DirectChapter} from './manga-direct.js';
import {translationConfig,bytesBase64,fromBase64} from './manga-translation.js';
import {stopLmt} from './lmt-client.js';

window.translateExportChapter=async({count,options,slots,skip=[]})=>{
 const controller=new AbortController(),ignored=new Set(skip);
 const entries=Array.from({length:count},(_,index)=>({async:async()=>new Blob([fromBase64(await window.exportSourcePage(index))])}));
 const config=translationConfig({...options,firstPagePriority:true,directTimeoutMs:120000,engine:'vm',directViaOracle:true,chapterPipeline:false,cache:false,allowDownloads:true,skipPages:ignored});
 const service={session:{googleGatewayVersion:5},request:(path,request)=>window.exportGoogleRequest(path,request.body||{})};
 const chapter=new DirectChapter({entries,scope:'vm-export',keyScope:'vm-export',config,direction:options.direction,serverSlots:slots,service:()=>service});
 try{
  const pending=entries.map((_,index)=>index).filter(index=>!ignored.has(index)),failures=new Map();
  const save=async (index,blob)=>{
    const result=await chapter.render(blob,index,config.font,value=>window.exportPageProgress(index,value),config,controller.signal);
    if(result.unresolvedRegions?.length||result.inpaint?.unpainted){
     result.renderedBitmap?.close();
     const error=Error(result.unresolvedRegions?.length?'Осталось реплик без перевода: '+result.unresolvedRegions.length:result.warnings?.[0]||'Фон восстановлен частично.');
     error.needsReview=!!result.unresolvedRegions?.length;
     throw error;
    }
    let image=result.renderedImage;
    if(!image&&result.renderedBitmap){
     const bitmap=result.renderedBitmap,canvas=new OffscreenCanvas(bitmap.width,bitmap.height);
     try{canvas.getContext('2d').drawImage(bitmap,0,0);image=await(await canvas.convertToBlob({type:'image/png'})).arrayBuffer();}
     finally{bitmap.close();}
    }
    if(!image)throw Error('Переводчик не вернул готовую страницу.');
    await window.exportRenderedPage(index,bytesBase64(image));
    failures.delete(index);
  };
  const run=async indices=>{
   for(let offset=0;offset<indices.length;offset+=9){
    const packet=indices.slice(offset,offset+9),loaded=await Promise.allSettled(packet.map(index=>entries[index].async()));
    await Promise.all(packet.map((index,i)=>loaded[i].status==='fulfilled'?save(index,loaded[i].value).catch(error=>failures.set(index,error)):failures.set(index,loaded[i].reason)));
   }
  };
  // Source reads, detection and rendering of later pages cannot hold up page 1.
  await run(pending.slice(0,1));
  await run(pending.slice(1));
  // Keep already verified pages and retry only missing work.
  if(failures.size){
   await run([...failures].filter(([,error])=>!error?.needsReview).map(([index])=>index).sort((a,b)=>a-b));
   await chapter.recoverChapter();
   await run([...failures].filter(([,error])=>error?.needsReview).map(([index])=>index).sort((a,b)=>a-b));
   if(failures.size){
    const [index,error]=failures.entries().next().value;
    throw Error('Не удалось завершить перевод · стр. '+[...failures.keys()].map(i=>i+1).sort((a,b)=>a-b).slice(0,12).join(', ')+'. Стр. '+(index+1)+': '+error.message);
   }
  }
 }finally{controller.abort();chapter.close();stopLmt();}
 return {pages:count};
};
