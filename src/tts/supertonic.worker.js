// Supertonic 3 inference in a worker (port of the MIT web/helper.js of
// supertone-oss-archive/supertonic). Four ONNX graphs: duration predictor,
// text encoder, flow-matching vector estimator (N steps) and vocoder.
// Voices are preset style vectors; characters may get a blend of two presets.
import {modelText} from './text.js';

let ort,sessions,config,indexer,styles={},provider='';

async function runtime(prefer){
 ort=await import('onnxruntime-web/webgpu');
 // Production: build-lmt.mjs copies the ORT wasm next to dist/lmt. Dev: serve them from node_modules.
 ort.env.wasm.wasmPaths=import.meta.env?.PROD?new URL(/* @vite-ignore */ '../lmt/',import.meta.url).href:new URL('/node_modules/onnxruntime-web/dist/',self.location.origin).href;
 ort.env.wasm.numThreads=globalThis.crossOriginIsolated?Math.min(4,navigator.hardwareConcurrency||2):1;
 const tryProviders=prefer==='wasm'||!('gpu' in navigator)?[['wasm']]:[['webgpu'],['wasm']];
 return tryProviders;
}

async function create(bytes,providers){
 return ort.InferenceSession.create(new Uint8Array(bytes),{executionProviders:providers,graphOptimizationLevel:'all'});
}

async function load({files,prefer}){
 const options=await runtime(prefer);
 config=JSON.parse(new TextDecoder().decode(files['onnx/tts.json']));
 indexer=JSON.parse(new TextDecoder().decode(files['onnx/unicode_indexer.json']));
 for(const [path,bytes] of Object.entries(files)){
  const match=path.match(/^voice_styles\/(\w+)\.json$/);
  if(!match)continue;
  const raw=JSON.parse(new TextDecoder().decode(bytes));
  styles[match[1]]={ttl:Float32Array.from(raw.style_ttl.data.flat(Infinity)),ttlDims:raw.style_ttl.dims,dp:Float32Array.from(raw.style_dp.data.flat(Infinity)),dpDims:raw.style_dp.dims};
 }
 let lastError;
 for(const providers of options){
  try{
   sessions={
    dp:await create(files['onnx/duration_predictor.onnx'],providers),
    enc:await create(files['onnx/text_encoder.onnx'],providers),
    vec:await create(files['onnx/vector_estimator.onnx'],providers),
    voc:await create(files['onnx/vocoder.onnx'],providers),
   };
   provider=providers[0];
   // One short warm-up proves the provider can actually run every graph.
   await synthesize({text:'Готово.',lang:'ru',voice:{F1:1},steps:2,speed:1,seed:1});
   return {provider,voices:Object.keys(styles)};
  }catch(error){lastError=error;sessions=null;}
 }
 throw lastError||Error('Не удалось запустить модель озвучки.');
}

function blend(voice){
 // voice: {"F1":1} or {"F2":0.6,"M3":0.4}
 const entries=Object.entries(voice||{F1:1}).filter(([name,w])=>styles[name]&&w>0);
 if(!entries.length)entries.push(['F1',1]);
 const sum=entries.reduce((a,[,w])=>a+w,0),first=styles[entries[0][0]];
 const ttl=new Float32Array(first.ttl.length),dp=new Float32Array(first.dp.length);
 for(const [name,w] of entries){const s=styles[name],k=w/sum;for(let i=0;i<ttl.length;i++)ttl[i]+=s.ttl[i]*k;for(let i=0;i<dp.length;i++)dp[i]+=s.dp[i]*k;}
 return {ttl:new ort.Tensor('float32',ttl,first.ttlDims),dp:new ort.Tensor('float32',dp,first.dpDims)};
}

function random(seed){let a=seed>>>0;return()=>{a=a+0x6D2B79F5>>>0;let t=a;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};}

async function synthesize({text,lang,voice,steps=5,speed=1,seed=7,tags=[]}){
 if(!sessions)throw Error('Модель озвучки ещё не загружена.');
 const input=modelText(text,lang,tags),ids=new BigInt64Array(input.length);
 for(let i=0;i<input.length;i++){const code=input.codePointAt(i);ids[i]=BigInt(code<indexer.length?indexer[code]:-1);}
 const length=ids.length,style=blend(voice);
 const textIds=new ort.Tensor('int64',ids,[1,length]),textMask=new ort.Tensor('float32',new Float32Array(length).fill(1),[1,1,length]);
 const {duration}=await sessions.dp.run({text_ids:textIds,style_dp:style.dp,text_mask:textMask});
 const seconds=Math.max(.15,Math.min(60,duration.data[0]/Math.max(.5,Math.min(2,speed))));
 const {text_emb}=await sessions.enc.run({text_ids:textIds,style_ttl:style.ttl,text_mask:textMask});
 const rate=config.ae.sample_rate,chunk=config.ae.base_chunk_size*config.ttl.chunk_compress_factor;
 const latentLength=Math.max(1,Math.ceil(seconds*rate/chunk)),dim=config.ttl.latent_dim*config.ttl.chunk_compress_factor;
 const next=random(seed),noise=new Float32Array(dim*latentLength);
 for(let i=0;i<noise.length;i+=2){const u1=Math.max(1e-4,next()),u2=next(),r=Math.sqrt(-2*Math.log(u1));noise[i]=r*Math.cos(2*Math.PI*u2);if(i+1<noise.length)noise[i+1]=r*Math.sin(2*Math.PI*u2);}
 let latent=new ort.Tensor('float32',noise,[1,dim,latentLength]);
 const latentMask=new ort.Tensor('float32',new Float32Array(latentLength).fill(1),[1,1,latentLength]);
 const total=new ort.Tensor('float32',new Float32Array([steps]),[1]);
 for(let step=0;step<steps;step++){
  const output=await sessions.vec.run({noisy_latent:latent,text_emb,style_ttl:style.ttl,latent_mask:latentMask,text_mask:textMask,current_step:new ort.Tensor('float32',new Float32Array([step]),[1]),total_step:total});
  latent=new ort.Tensor('float32',Float32Array.from(output.denoised_latent.data),[1,dim,latentLength]);
 }
 const {wav_tts}=await sessions.voc.run({latent});
 const samples=Math.min(wav_tts.data.length,Math.floor(seconds*rate));
 return {audio:Float32Array.from(wav_tts.data.subarray(0,samples)),sampleRate:rate};
}

self.onmessage=async({data})=>{
 const {id,type}=data;
 try{
  if(type==='load'){self.postMessage({id,type:'loaded',...await load(data)});return;}
  if(type==='synth'){const started=performance.now(),result=await synthesize(data);self.postMessage({id,type:'audio',...result,provider,ms:Math.round(performance.now()-started)},[result.audio.buffer]);return;}
  throw Error('Неизвестная команда озвучки.');
 }catch(error){self.postMessage({id,type:'error',message:error?.message||String(error)});}
};
