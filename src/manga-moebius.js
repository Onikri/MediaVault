// Moebius neural inpainting, adapted Apache-2.0 pipeline in lmt/moebius/.
// Fixed 512 input. Only the original glyph mask is composited back to the page.
import {moebiusRuntimeUrl,moebiusLayout,moebiusPageMask} from './moebius-layout.js';
let loading;
const BASE='https://huggingface.co/simonw/Moebius-ONNX/resolve/5bf1ef5d2861ec01a727183a3f95dc64f352120e';
async function initialize(status){
 if(!navigator.gpu||!await navigator.gpu.requestAdapter({powerPreference:'high-performance'}))throw Error('Moebius требует доступный WebGPU. Выбери LaMa или быструю очистку.');
 const {MoebiusPipeline}=await import('../lmt/moebius/pipeline.ts');
 // BASE_URL can be './'. Resolving that against location.origin drops the
 // /MediaVault/ prefix on Pages. Resolve from this module's actual asset URL.
 const moduleUrl=import.meta.url;MoebiusPipeline.configureRuntime(moebiusRuntimeUrl(moduleUrl));
 const pipeline=new MoebiusPipeline();try{await pipeline.load(BASE,(stage,n,total)=>status('Moebius · '+stage+(total?' '+Math.round(n/total*100)+'%':'')));return pipeline;}catch(error){await pipeline.dispose();throw error;}
}
export async function inpaintMoebiusPatch(image,mask,status=()=>{},{wholePage=false}={}){
 const start=performance.now(),cold=!loading;if(!loading){loading=initialize(status);loading.catch(()=>loading=null);}const pipeline=await loading,ready=performance.now();
 const canvas=new OffscreenCanvas(512,512),context=canvas.getContext('2d'),source=new OffscreenCanvas(image.width,image.height);source.getContext('2d').putImageData(image,0,0);
 const layout=moebiusLayout(image.width,image.height),{w,h,x,y}=layout;
 context.fillStyle='#fff';context.fillRect(0,0,512,512);context.drawImage(source,x,y,w,h);
 const holes=new OffscreenCanvas(image.width,image.height),pixels=new ImageData(image.width,image.height);for(let n=0;n<mask.length;n++)if(mask[n])pixels.data.set([255,255,255,255],n*4);holes.getContext('2d').putImageData(pixels,0,0);
 const maskCanvas=new OffscreenCanvas(512,512),mc=maskCanvas.getContext('2d');
 if(wholePage){const pooled=moebiusPageMask(mask,image.width,image.height,layout),pixels=new ImageData(512,512);for(let n=0;n<pooled.length;n++)if(pooled[n])pixels.data.set([255,255,255,255],n*4);mc.putImageData(pixels,0,0);}else mc.drawImage(holes,x,y,w,h);
 let result;
 try{result=await pipeline.run(canvas,maskCanvas,{steps:10,guidance:3,seed:42,paste:false,wholePage,onProgress:(stage,n,total)=>status('Moebius · '+stage+(total?' '+n+'/'+total:''))});}catch(error){loading=null;await pipeline.dispose();throw error;}
 const restored=new OffscreenCanvas(image.width,image.height),ctx=restored.getContext('2d');ctx.drawImage(result,x,y,w,h,0,0,image.width,image.height);const output=ctx.getImageData(0,0,image.width,image.height).data;
 for(let n=0;n<mask.length;n++)if(mask[n])image.data.set(output.subarray(n*4,n*4+4),n*4);
 return {provider:'webgpu',strategy:wholePage?'whole-page':'region',calls:1,sourceSize:[image.width,image.height],startupMs:cold?Math.round(ready-start):0,inferenceMs:Math.round(performance.now()-ready),totalMs:Math.round(performance.now()-start),steps:10,inputSizes:[[512,512]],threads:1,model:'Moebius-0.22B'};
}
export function inpaintMoebiusPage(image,mask,status){return inpaintMoebiusPatch(image,mask,status,{wholePage:true});}
