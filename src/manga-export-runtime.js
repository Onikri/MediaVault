// The VM uses the reader's actual Google, cleanup and Cyrillic layout pipeline.
import {DirectChapter} from './manga-direct.js';
import {translationConfig,bytesBase64,fromBase64} from './manga-translation.js';
import {stopLmt} from './lmt-client.js';
import {preloadPrivateFonts} from './private-fonts.js';

// The owner's lettering faces, as the reader receives them; an older VM without
// the font bridge letters with the open fonts.
const fontService={request:async(path,options={})=>{
 if(path==='/reader/lmt/fonts')return window.exportFontList?await window.exportFontList():{fonts:[]};
 const index=Number(path.split('/').pop());
 if(options.raw)return {arrayBuffer:async()=>fromBase64(await window.exportFont(index))};
 throw Error('Неподдерживаемый запрос шрифтов.');
}};

window.translateExportChapter=async({count,options,slots,skip=[]})=>{
 await preloadPrivateFonts(fontService);
 const controller=new AbortController(),ignored=new Set(skip);
 const entries=Array.from({length:count},(_,index)=>({async:async()=>new Blob([fromBase64(await window.exportSourcePage(index))])}));
 const config=translationConfig({...options,firstPagePriority:true,directTimeoutMs:120000,engine:'vm',directViaOracle:true,chapterPipeline:false,cache:false,modelBudgetMs:120000,allowDownloads:true,skipPages:ignored});
 const service={session:{googleGatewayVersion:5},request:(path,request)=>window.exportGoogleRequest(path,request.body||{})};
 const chapter=new DirectChapter({entries,scope:'vm-export',keyScope:'vm-export',config,direction:options.direction,serverSlots:slots,service:()=>service});
 try{
  const pending=entries.map((_,index)=>index).filter(index=>!ignored.has(index)),failures=new Map();
  // A region the renderer left in the original (its translation does not fit,
  // the cleanup was declined) is retried once; after that the page is saved as
  // the reader shows it. Untranslated lines still stop the page for review.
  const save=async (index,blob,acceptPartial=false)=>{
    const result=await chapter.render(blob,index,config.font,value=>window.exportPageProgress(index,value),config,controller.signal);
    if(result.unresolvedRegions?.length||result.inpaint?.unpainted&&!acceptPartial){
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
  const run=async (indices,acceptPartial=false)=>{
   for(let offset=0;offset<indices.length;offset+=9){
    const packet=indices.slice(offset,offset+9),loaded=await Promise.allSettled(packet.map(index=>entries[index].async()));
    await Promise.all(packet.map((index,i)=>loaded[i].status==='fulfilled'?save(index,loaded[i].value,acceptPartial).catch(error=>failures.set(index,error)):failures.set(index,loaded[i].reason)));
   }
  };
  // Source reads, detection and rendering of later pages cannot hold up page 1.
  await run(pending.slice(0,1));
  await run(pending.slice(1));
  // Keep already verified pages and retry only missing work.
  if(failures.size){
   await run([...failures].filter(([,error])=>!error?.needsReview).map(([index])=>index).sort((a,b)=>a-b),true);
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
