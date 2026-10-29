// SPDX-License-Identifier: AGPL-3.0-or-later
// The pinned LaMa FFC graph runs on WASM. A GPU adapter being present does not
// make its unsupported Fourier operators execute on WebGPU.
import {lamaInputSize,lamaInputTensors,applyLamaOutput} from './manga-cleaning.js';
let loading;
async function initialize(status){
 const started=performance.now();
 status('LaMa Manga · загрузка и запуск CPU / WASM, один раз');
 const ort=await import('onnxruntime-web/all');
 // SharedArrayBuffer requires isolation. GitHub Pages therefore remains 1-thread.
 const threads=globalThis.crossOriginIsolated?Math.min(4,navigator.hardwareConcurrency||1):1;
 ort.env.wasm.numThreads=threads;
 ort.env.wasm.wasmPaths=new URL(/* @vite-ignore */ '../lmt/',import.meta.url).href;
 const [{downloadArtifactHF},{DefaultConfig},{planTiles}]=await Promise.all([import('../lmt/upstream/lib/utils.ts'),import('../lmt/upstream/lib/configs.ts'),import('../lmt/upstream/lib/inpaint/lama.ts')]);
 // Use the upstream integrity-checked cache download, then create the session
 // with this same ORT module/env. Do not route this browser worker through a
 // native bridge or a second module's automatic-provider session.
 await downloadArtifactHF(DefaultConfig.lamaRepo,DefaultConfig.lamaModelPath,true);
 const direct=/^https?:/.test(DefaultConfig.lamaRepo),url=direct?DefaultConfig.lamaRepo+'/'+DefaultConfig.lamaModelPath:'https://huggingface.co/'+DefaultConfig.lamaRepo+'/resolve/main/'+DefaultConfig.lamaModelPath;
 const response=await(await caches.open(direct?'direct-model-cache':DefaultConfig.lamaRepo)).match(url);
 if(!response)throw Error('Модель LaMa отсутствует в проверенном кэше');
 const session=await ort.InferenceSession.create(await response.arrayBuffer(),{executionProviders:['wasm']});
 let gpuAdapter=null;
 try{const adapter=await navigator.gpu?.requestAdapter({powerPreference:'high-performance'});if(adapter)gpuAdapter={vendor:adapter.info?.vendor||'',device:adapter.info?.device||'',description:adapter.info?.description||'',fallback:!!adapter.info?.isFallbackAdapter};}catch{}
 return {ort,session,threads,planTiles,gpuAdapter,startupMs:performance.now()-started};
}
export async function inpaintLamaPatch(image,mask,status=()=>{}){
 const start=performance.now(),cold=!loading;
 if(!loading)loading=initialize(status).catch(error=>{loading=null;throw error;});
 const model=await loading,{ort,session}=model,ready=performance.now();
 if(!(mask instanceof Uint8Array)||mask.length!==image.width*image.height)throw Error('Некорректная маска LaMa');
 const size=lamaInputSize(image.width,image.height);
 let tiles;
 if(size)tiles=[{crop:{x:0,y:0,w:size.width,h:size.height},commit:{x:0,y:0,w:image.width,h:image.height}}];
 else{
  let x1=image.width,y1=image.height,x2=-1,y2=-1;
  for(let y=0;y<image.height;y++)for(let x=0;x<image.width;x++)if(mask[y*image.width+x]){x1=Math.min(x1,x);y1=Math.min(y1,y);x2=Math.max(x2,x);y2=Math.max(y2,y);}
  if(x2<0)throw Error('Пустая маска LaMa');
  tiles=model.planTiles({x:x1,y:y1,w:x2-x1+1,h:y2-y1+1});
 }
 const original=image.data.slice(),done=new Uint8Array(mask.length);let inferenceMs=0,preprocessMs=0,compositeMs=0;
 for(const tile of tiles){
  let t=performance.now();const {rgb,holes}=lamaInputTensors({width:image.width,height:image.height,data:original},mask,tile.crop);
  const imageTensor=new ort.Tensor('float32',rgb,[1,3,tile.crop.h,tile.crop.w]),maskTensor=new ort.Tensor('float32',holes,[1,1,tile.crop.h,tile.crop.w]);
  preprocessMs+=performance.now()-t;let outputs;
  try{
   t=performance.now();outputs=await session.run({[session.inputNames[0]]:imageTensor,[session.inputNames[1]]:maskTensor});
   const output=outputs[session.outputNames[0]],values=await output.getData();inferenceMs+=performance.now()-t;
   t=performance.now();applyLamaOutput(image,mask,values,tile,done);compositeMs+=performance.now()-t;
  }finally{imageTensor.dispose();maskTensor.dispose();if(outputs)for(const value of Object.values(outputs))value.dispose?.();}
 }
 return {provider:'wasm',gpuUsed:false,reason:'Pinned LaMa Fourier graph is not WebGPU compatible',threads:model.threads,gpuAdapter:model.gpuAdapter,coldStart:cold,startupMs:cold?model.startupMs:0,waitForSessionMs:ready-start,inferenceMs,preprocessMs,compositeMs,totalMs:performance.now()-start,inputSizes:tiles.map(t=>[t.crop.w,t.crop.h])};
}
