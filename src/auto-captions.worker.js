// Whisper fallback for automatic captions, entirely in the viewer's browser.
// Model: OpenAI Whisper base (MIT) as ONNX by onnx-community; runtime files are
// self-hosted under /lmt/transformers-ort/ (copied by scripts/build-lmt.mjs).
import {pipeline,env} from '@huggingface/transformers';

export const WHISPER_MODEL='onnx-community/whisper-base';
env.allowLocalModels=false;
env.useBrowserCache=true;
env.backends.onnx.wasm.wasmPaths=new URL(/* @vite-ignore */ '../lmt/transformers-ort/',import.meta.url).href;
env.backends.onnx.wasm.numThreads=1;

let loading=null,device='wasm';
async function load(){
 if(loading)return loading;
 loading=(async()=>{
  const adapter=self.navigator?.gpu?await self.navigator.gpu.requestAdapter().catch(()=>null):null;
  device=adapter?'webgpu':'wasm';
  const files=new Map();
  // Report overall progress across all model files (sizes arrive per file).
  const progress=p=>{if(p.status!=='progress'||!p.file)return;files.set(p.file,{loaded:p.loaded||0,total:p.total||0});let loaded=0,total=0;for(const f of files.values()){loaded+=f.loaded;total+=f.total;}postMessage({type:'status',phase:'download',loaded,total,device});};
  return pipeline('automatic-speech-recognition',WHISPER_MODEL,{device,dtype:device==='webgpu'?{encoder_model:'fp32',decoder_model_merged:'q4'}:'q8',progress_callback:progress});
 })().catch(error=>{loading=null;throw error;});
 return loading;
}

self.onmessage=async({data})=>{
 try{
  if(data.type==='load'){await load();postMessage({type:'ready',device});return;}
  if(data.type==='chunk'){
   const asr=await load(),audio=new Float32Array(data.audio);
   const result=await asr(audio,{language:data.language,task:data.task||'transcribe',return_timestamps:false});
   postMessage({type:'text',id:data.id,text:String(result?.text||'').trim()});
  }
 }catch(error){postMessage({type:'error',id:data.id,message:String(error?.message||error).slice(0,200)});}
};
