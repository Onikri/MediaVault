// SPDX-License-Identifier: AGPL-3.0-or-later
// Developer-only harness. Built separately; never loaded by the reader.
import '../../lmt/shim.js';
import * as ort from 'onnxruntime-web/all';
import {detectTextBubble,releaseDetection} from '../../lmt/upstream/lib/detections/main.ts';
import {getOcrEngine,releaseOcrEngines,textRecognise} from '../../lmt/upstream/lib/ocr/main.ts';
import {inpaintImageAuto,inpaintImageQuality} from '../../lmt/upstream/lib/inpaint/ladder.ts';
import {loadMangaFont,mangaFontStack,MANGA_FONTS} from '../../reader-fonts/catalog.js';
import {calculateFittedTextLayout} from '../../lmt/upstream/lib/canvas/text-fit.ts';
ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=new URL('./ort/',location.href).href;
window.browser.runtime.getURL=p=>new URL('dicts/'+String(p).split('/').pop(),location.href).href;
const images=new Map();
async function source(bytes){const url=URL.createObjectURL(new Blob([new Uint8Array(bytes)]));images.set(url,true);return url;}
window.bench={
 async detect(bytes,model){const url=await source(bytes);try{const t=performance.now();const boxes=await detectTextBubble(url,.35,model);return {ms:performance.now()-t,boxes};}finally{URL.revokeObjectURL(url);images.delete(url);}},
 async ocr(bytes,boxes,language,model){const url=await source(bytes);try{const t=performance.now();const r=await textRecognise(url,boxes,language,.3,1,48,{enabled:false},model);return {ms:performance.now()-t,results:r.results};}finally{URL.revokeObjectURL(url);images.delete(url);}},
 async inpaint(bytes,boxes,method){const url=await source(bytes);try{const t=performance.now(),r=await(method==='quality'?inpaintImageQuality:inpaintImageAuto)(url,boxes),blob=await(await fetch(r.url)).blob();return {ms:performance.now()-t,regions:r.regions,image:Array.from(new Uint8Array(await blob.arrayBuffer()))};}finally{URL.revokeObjectURL(url);images.delete(url);}},
 async fonts(){const result=[];for(const f of MANGA_FONTS){await loadMangaFont(f.id);const layouts=[];for(const[w,h]of[[140,100],[220,170],[100,60]]){const text='Момо, ты в порядке? Не открывай эту дверь! Ёжик ждёт у подъезда.';const l=calculateFittedTextLayout(text,w,h,mangaFontStack(f.id),undefined,false);layouts.push({w,h,...l});}result.push({id:f.id,family:f.family,available:f.id==='system'||document.fonts.check(`20px "${f.family}"`),layouts});}return result;},
 async release(){await releaseDetection();await releaseOcrEngines();}
};
