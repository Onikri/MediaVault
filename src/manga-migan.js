import {MIGAN_MODEL,miganInputs,applyMiganOutput} from './migan-model.js';
let loading;
export async function loadMiganBytes(status=()=>{}){
 const {downloadArtifactHF}=await import('../lmt/upstream/lib/utils.ts');
 await downloadArtifactHF('',MIGAN_MODEL.url,true,{onProgress:(n,total)=>status('MI-GAN · загрузка '+Math.round(n/(total||MIGAN_MODEL.bytes)*100)+'%')});
 const hit=await(await caches.open('direct-model-cache')).match(MIGAN_MODEL.url);
 if(!hit)throw Error('MI-GAN отсутствует в проверенном кэше');return hit.arrayBuffer();
}
async function initialize(status){
 const start=performance.now();status('MI-GAN · загрузка и запуск CPU / WASM');
 const ort=await import('onnxruntime-web/all');ort.env.wasm.numThreads=1;
 ort.env.wasm.wasmPaths=new URL(/* @vite-ignore */ '../lmt/',import.meta.url).href;
 const session=await ort.InferenceSession.create(await loadMiganBytes(status),{executionProviders:['wasm']});
 return {ort,session,startupMs:performance.now()-start};
}
export async function inpaintMiganPatch(image,mask,status=()=>{}){
 const start=performance.now(),cold=!loading;
 if(!loading)loading=initialize(status).catch(error=>{loading=null;throw error;});
 const {ort,session,startupMs}=await loading,ready=performance.now(),{rgb,known}=miganInputs(image,mask),dims=[1,3,image.height,image.width];
 const input=new ort.Tensor('uint8',rgb,dims),holes=new ort.Tensor('uint8',known,[1,1,image.height,image.width]);let outputs;
 try{
  status('MI-GAN · восстановление фона');const t=performance.now();outputs=await session.run({image:input,mask:holes});
  const output=outputs[session.outputNames[0]],values=await output.getData(),inferenceMs=performance.now()-t;
  if(output.type!=='uint8'||output.dims.some((v,i)=>v!==dims[i]))throw Error('MI-GAN вернула неверный размер страницы');
  applyMiganOutput(image,mask,values);
  return {model:'MI-GAN-512-Places2',provider:'wasm',threads:1,calls:1,startupMs:cold?startupMs:0,waitForSessionMs:ready-start,inferenceMs,totalMs:performance.now()-start,inputSizes:[[image.width,image.height]]};
 }finally{input.dispose();holes.dispose();if(outputs)for(const value of Object.values(outputs))value.dispose?.();}
}
