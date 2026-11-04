import {TITLE_UPSCALE} from './title-upscale-model.js';
let runtime;
const hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(v=>v.toString(16).padStart(2,'0')).join('');
async function initialize(url,paths){
 let cache;try{cache=await caches.open('mv-public-models-v1');}catch{}
 let bytes=await (await cache?.match(url))?.arrayBuffer();
 if(!bytes||bytes.byteLength!==TITLE_UPSCALE.bytes||await hash(bytes)!==TITLE_UPSCALE.sha256){
  const response=await fetch(url,{credentials:'omit'});if(!response.ok)throw Error('Модель фона пока недоступна.');bytes=await response.arrayBuffer();
  if(bytes.byteLength!==TITLE_UPSCALE.bytes||await hash(bytes)!==TITLE_UPSCALE.sha256)throw Error('Проверка модели фона не прошла.');
  try{await cache?.put(url,new Response(bytes,{headers:{'Content-Type':'application/octet-stream'}}));}catch{}
 }
 const ort=await import('onnxruntime-web/wasm');ort.env.wasm.numThreads=1;ort.env.wasm.wasmPaths=paths||new URL(/* @vite-ignore */ '../lmt/',import.meta.url).href;
 const session=await ort.InferenceSession.create(bytes,{executionProviders:['wasm'],graphOptimizationLevel:'all'});return {ort,session};
}
let chain=Promise.resolve();
self.onmessage=({data})=>{chain=chain.then(async()=>{
 let input,output;
 try{
  const {bitmap}=data,max=384,scale=Math.min(1,max/Math.max(bitmap.width,bitmap.height));
  if(Math.max(bitmap.width,bitmap.height)>=768){bitmap.close();postMessage({id:data.id,type:'skip'});return;}
  if(!runtime)runtime=initialize(data.modelUrl,data.runtimePaths).catch(e=>{runtime=null;throw e;});
  const {ort,session}=await runtime;
  const w=Math.max(16,Math.round(bitmap.width*scale)),h=Math.max(16,Math.round(bitmap.height*scale)),canvas=new OffscreenCanvas(w,h),ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(bitmap,0,0,w,h);bitmap.close();
  const rgba=ctx.getImageData(0,0,w,h).data,n=w*h,values=new Float32Array(n*3);
  for(let i=0;i<n;i++){values[i]=rgba[i*4]/255;values[n+i]=rgba[i*4+1]/255;values[n*2+i]=rgba[i*4+2]/255;}
  input=new ort.Tensor('float32',values,[1,3,h,w]);const started=performance.now();output=await session.run({[session.inputNames[0]]:input});const y=output[session.outputNames[0]],pixels=await y.getData(),elapsed=performance.now()-started;
  const ow=y.dims.at(-1),oh=y.dims.at(-2);if(ow!==w*2||oh!==h*2||pixels.length!==ow*oh*3)throw Error('Модель вернула неправильный размер.');
  const target=new OffscreenCanvas(ow,oh),draw=target.getContext('2d'),image=draw.createImageData(ow,oh),total=ow*oh;
  for(let i=0;i<total;i++){image.data[i*4]=Math.max(0,Math.min(255,pixels[i]*255));image.data[i*4+1]=Math.max(0,Math.min(255,pixels[total+i]*255));image.data[i*4+2]=Math.max(0,Math.min(255,pixels[total*2+i]*255));image.data[i*4+3]=255;}
  draw.putImageData(image,0,0);const blob=await target.convertToBlob({type:'image/webp',quality:.94});postMessage({id:data.id,type:'result',blob,width:ow,height:oh,inferenceMs:elapsed,provider:'wasm'});
 }catch(e){postMessage({id:data.id,type:'error',message:e.message});}
 finally{input?.dispose();if(output)for(const tensor of Object.values(output))tensor.dispose?.();}
}).catch(()=>{});};
