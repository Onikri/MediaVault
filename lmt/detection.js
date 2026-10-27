// SPDX-License-Identifier: AGPL-3.0-or-later
import * as ort from 'onnxruntime-web/all';
import {downloadArtifactFromUrl} from './upstream/lib/utils.ts';
import {refineDetections} from './upstream/lib/detections/boxes.ts';
import {clearSegmentation} from './upstream/lib/detections/segmentation.ts';
import {planDetectionTiles,shouldTile,mergeTiledBoxes} from './upstream/lib/detections/tiling.ts';
import {decodeYolo26,decodeDb,ppSize,orderByPanels} from './detection-geometry.js';
const urls={
 'yolo26n-manga':'https://huggingface.co/mednasserallah/manga-panel-detector-yolo26n-onnx/resolve/f6b7f3cb2bada1ec7d8b16501f9c984890811445/manga_panel_detector_fp32_1024.onnx',
 'ppocrv6-det':'https://huggingface.co/Kellenok/PP-OCRv6_manga/resolve/62375557b5b0a4b2bc8e05484a97c7ea1df7229e/det/manga_det_v0.2.onnx',
};
let current=null,session=null;
async function load(model){if(current!==model){await session?.release();session=await downloadArtifactFromUrl(urls[model],model,{gpu:false});current=model;}return session;}
async function single(bitmap,model){
 const s=await load(model),yolo=model==='yolo26n-manga',[w,h]=yolo?[1024,1024]:ppSize(bitmap.width,bitmap.height),canvas=new OffscreenCanvas(w,h),ctx=canvas.getContext('2d');
 if(yolo){ctx.fillStyle='#727272';ctx.fillRect(0,0,w,h);const r=Math.min(w/bitmap.width,h/bitmap.height),rw=Math.round(bitmap.width*r),rh=Math.round(bitmap.height*r);ctx.drawImage(bitmap,Math.floor((w-rw)/2),Math.floor((h-rh)/2),rw,rh);}else ctx.drawImage(bitmap,0,0,w,h);
 const pixels=ctx.getImageData(0,0,w,h).data,n=w*h,buffer=new Float32Array(n*3),mean=[.485,.456,.406],std=[.229,.224,.225];
 for(let i=0;i<n;i++)for(let c=0;c<3;c++){const v=pixels[i*4+c]/255;buffer[c*n+i]=yolo?v:(v-mean[c])/std[c];}
 const input=new ort.Tensor('float32',buffer,[1,3,h,w]);let result;
 try{result=await s.run({[s.inputNames[0]]:input});const output=result[s.outputNames[0]],data=await output.getData();return yolo?decodeYolo26(data,bitmap.width,bitmap.height):{text:decodeDb(data,output.dims.at(-1),output.dims.at(-2),bitmap.width,bitmap.height),panels:[]};}
 finally{input.dispose();if(result)Object.values(result).forEach(v=>v.dispose());}
}
export const detectPpLines=async bitmap=>(await single(bitmap,'ppocrv6-det')).text;
export async function detectManga(source,config){
 const model=config.detector||'comic-bubble',panelModel=config.panelDetector||'none';let text,panels=[];
 if(['magi'].includes(model)||panelModel==='yolov12-panels'){
  if(typeof globalThis.mvMangaDetect!=='function')throw Error('MAGI и YOLOv12 доступны на ВМ. Выбери обработку на ВМ.');
  const bytes=new Uint8Array(await(await fetch(source)).arrayBuffer());let raw='';for(let i=0;i<bytes.length;i+=8192)raw+=String.fromCharCode(...bytes.subarray(i,i+8192));
  const result=await globalThis.mvMangaDetect({image:btoa(raw),textModel:model==='magi'?'magi':'none',panelModel:panelModel==='yolov12-panels'?'yolov12-panels':'none'});if(model==='magi')text=result.text;panels=result.panels||[];
 }
 const bitmap=await createImageBitmap(await(await fetch(source)).blob());
 try{
  if(urls[model]||(panelModel==='yolo26n-manga')){
   const chosen=urls[model]?model:'yolo26n-manga',all=[],allPanels=[];
   const tiles=shouldTile(bitmap.width,bitmap.height)?planDetectionTiles(bitmap.width,bitmap.height):[{x:0,y:0,w:bitmap.width,h:bitmap.height}];
   for(const tile of tiles){const crop=await createImageBitmap(bitmap,tile.x,tile.y,tile.w,tile.h);try{const r=await single(crop,chosen);for(const [from,to]of [[r.text,all],[r.panels,allPanels]])for(const b of from)to.push({...b,x1:b.x1+tile.x,x2:b.x2+tile.x,y1:b.y1+tile.y,y2:b.y2+tile.y});}finally{crop.close();}}
   if(urls[model]){clearSegmentation();text=refineDetections(mergeTiledBoxes(all),bitmap.width,bitmap.height).boxes;}
   if(chosen==='yolo26n-manga'&&panelModel==='yolo26n-manga')panels=mergeTiledBoxes(allPanels);
   if(panelModel==='yolo26n-manga'&&chosen!=='yolo26n-manga')panels=(await single(bitmap,'yolo26n-manga')).panels;
  }
  if(!text){const{detectTextBubble}=await import('./upstream/lib/detections/main.ts');text=await detectTextBubble(source,config.detectionConfidence??.5,model);}
  return {boxes:orderByPanels(text,panels,config.language==='Japanese'),panels,model,panelModel};
 }finally{bitmap.close();}
}
