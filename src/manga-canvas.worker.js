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
  const allowed=()=>{if(event.data.allowDownloads===false)throw Error('Разреши загрузку выбранной модели или используй быструю очистку.');};
  const lama=mode==='migan'?async(image,mask,progress)=>{allowed();const {inpaintMiganPatch}=await import('./manga-migan.js');return inpaintMiganPatch(image,mask,progress);}:mode==='moebius'?async(image,mask,progress)=>{allowed();const {inpaintMoebiusPage}=await import('./manga-moebius.js');return inpaintMoebiusPage(image,mask,progress);}:mode==='fast'?undefined:async(image,mask,progress)=>{allowed();const {inpaintLamaPatch}=await import('./manga-lama.js');return inpaintLamaPatch(image,mask,progress);};
  const result=await renderComicPage({blob,page,font,mode,cache,lama,status,captureDebug:event.data.captureDebug===true,cleanOnly:event.data.operation==='clean-prepare',preparedClean:event.data.preparedClean});
  self.postMessage({id,result},[...(result.renderedBitmap?[result.renderedBitmap]:[]),...(result.cleanedImage?[result.cleanedImage]:[]),...(result.cacheImage?[result.cacheImage]:[]),...(result.debug?.cleanedImage?[result.debug.cleanedImage]:[]),...(result.debug?.maskImage?[result.debug.maskImage]:[])]);
 }catch(error){self.postMessage({id,error:error.message});}
});};
