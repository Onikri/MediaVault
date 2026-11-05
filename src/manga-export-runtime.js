// The VM uses the reader's actual Google, cleanup and Cyrillic layout pipeline.
import {DirectChapter} from './manga-direct.js';
import {translationConfig,bytesBase64,fromBase64} from './manga-translation.js';
import {stopLmt} from './lmt-client.js';

window.translateExportChapter=async({count,options,slots,skip=[]})=>{
 const controller=new AbortController(),ignored=new Set(skip);
 const entries=Array.from({length:count},(_,index)=>({async:async()=>new Blob([fromBase64(await window.exportSourcePage(index))])}));
 const config=translationConfig({...options,directTimeoutMs:120000,engine:'vm',directViaOracle:true,chapterPipeline:false,cache:false,allowDownloads:true});
 const service={request:(path,request)=>window.exportGoogleRequest(path,request.body||{})};
 const chapter=new DirectChapter({entries,scope:'vm-export',keyScope:'vm-export',config,direction:options.direction,serverSlots:slots,service:()=>service});
 try{
  const pending=entries.map((_,index)=>index).filter(index=>!ignored.has(index));
  for(let offset=0;offset<pending.length;offset+=9){
   const indices=pending.slice(offset,offset+9),blobs=await Promise.all(indices.map(index=>entries[index].async()));
   await Promise.all(indices.map(async (index,position)=>{
    const blob=blobs[position],result=await chapter.render(blob,index,config.font,value=>window.exportPageProgress(index,value),config,controller.signal);
    let image=result.renderedImage;
    if(!image&&result.renderedBitmap){
     const bitmap=result.renderedBitmap,canvas=new OffscreenCanvas(bitmap.width,bitmap.height);
     try{canvas.getContext('2d').drawImage(bitmap,0,0);image=await(await canvas.convertToBlob({type:'image/png'})).arrayBuffer();}
     finally{bitmap.close();}
    }
    if(!image)throw Error('Переводчик не вернул готовую страницу.');
    await window.exportRenderedPage(index,bytesBase64(image));
   }));
  }
 }finally{controller.abort();chapter.close();stopLmt();}
 return {pages:count};
};
