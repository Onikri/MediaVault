// SPDX-License-Identifier: AGPL-3.0-or-later
import {prepareEnglishPage} from './manga-fast-detect.js';
import {renderComicPage} from './manga-renderer.js';
import {prepareBlocksPage} from './manga-block-detect.js';
import {paintBlockSheets} from './manga-blocks.js';
let queue=Promise.resolve();
self.onmessage=event=>{queue=queue.catch(()=>{}).then(async()=>{
 const {id,blob,page,font='auto',mode='fast',cache=false}=event.data;
 try{
  if(event.data.operation==='blocks-prepare'){self.postMessage({id,result:await prepareBlocksPage(blob,event.data.index,event.data.direction,event.data.language)});return;}
  if(event.data.operation==='blocks-pack'){self.postMessage({id,result:await paintBlockSheets(event.data.sheets,event.data.pages)});return;}
  if(event.data.operation==='direct-prepare'){self.postMessage({id,result:await prepareEnglishPage(blob,event.data.index,event.data.direction,event.data.inputMode)});return;}
  const status=value=>self.postMessage({id,status:value});
  const lama=mode==='moebius'?async(image,mask,progress)=>{const {inpaintMoebiusPage}=await import('./manga-moebius.js');return inpaintMoebiusPage(image,mask,progress);}:mode==='fast'?undefined:async(image,mask,progress)=>{const {inpaintLamaPatch}=await import('./manga-lama.js');return inpaintLamaPatch(image,mask,progress);};
  const result=await renderComicPage({blob,page,font,mode,cache,lama,status,captureDebug:event.data.captureDebug===true});
  self.postMessage({id,result},[result.renderedBitmap,...(result.cacheImage?[result.cacheImage]:[]),...(result.debug?.cleanedImage?[result.debug.cleanedImage]:[])]);
 }catch(error){self.postMessage({id,error:error.message});}
});};
