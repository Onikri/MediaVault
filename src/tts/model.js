// Supertonic 3 (Supertone, OpenRAIL-M). The two large graphs are the 4-bit
// browser build by danyalmalik; the duration predictor and text encoder are the
// original fp32 graphs, because ONNX Runtime's WASM backend has no
// GatherBlockQuantized kernel (measured in Chromium, 2026-11-08). One set then
// runs on WebGPU and on CPU/WASM. Both repositories are pinned to a revision;
// see docs/benchmarks/tts-shootout-2026-11-08.md for the measured quality.
// Every file is size- and SHA-256-checked before use; nothing loads without
// the reader's explicit consent.
import {readModelFile,writeModelFile,removeModelFile,readModelResponse} from '../model-folder.js';

export const TTS_MODEL={
 id:'supertonic-3-q4',
 name:'Supertonic 3 · 4-bit',
 license:'OpenRAIL-M',
 base:'https://huggingface.co/danyalmalik/Supertonic-3-ONNX-WebGPU/resolve/aed039b76a7472220e9d89f3ef537f7e2ff077a7/',
 original:'https://huggingface.co/Supertone/supertonic-3/resolve/3cadd1ee6394adea1bd021217a0e650ede09a323/',
 files:[
  ['onnx/duration_predictor.onnx',3700147,'c3eb91414d5ff8a7a239b7fe9e34e7e2bf8a8140d8375ffb14718b1c639325db','original'],
  ['onnx/text_encoder.onnx',36416150,'c7befd5ea8c3119769e8a6c1486c4edc6a3bc8365c67621c881bbb774b9902ff','original'],
  ['onnx/vector_estimator.onnx',70634099,'26d0e5d82073f2cd2d3db6a335f238a4f7b8cf07c46d351e47398acc23208b50'],
  ['onnx/vocoder.onnx',28762717,'0f744ea78edd6e0b3fea4ba387f6a5e293ff89efeff63a0881291fe4a7f079a3'],
  ['onnx/tts.json',8253,'42078d3aef1cd43ab43021f3c54f47d2d75ceb4e75f627f118890128b06a0d09'],
  ['onnx/unicode_indexer.json',277676,'9bf7346e43883a81f8645c81224f786d43c5b57f3641f6e7671a7d6c493cb24f'],
  ['voice_styles/F1.json',292046,'bbdec6ee00231c2c742ad05483df5334cab3b52fda3ba38e6a07059c4563dbc2'],
  ['voice_styles/F2.json',292423,'7c722c6a72707b1a77f035d67f0d1351ba187738e06f7683e8c72b1df3477fc6'],
  ['voice_styles/F3.json',290794,'12f6ef2573baa2defa1128069cb59f203e3ab67c92af77b42df8a0e3a2f7c6ab'],
  ['voice_styles/F4.json',291808,'c2fa764c1225a76dfc3e2c73e8aa4f70d9ee48793860eb34c295fff01c2e032b'],
  ['voice_styles/F5.json',291479,'45966e73316415626cf41a7d1c6f3b4c70dbc1ba2bee5c1978ef0ce33244fc8d'],
  ['voice_styles/M1.json',291748,'e35604687f5d23694b8e91593a93eec0e4eca6c0b02bb8ed69139ab2ea6b0a5b'],
  ['voice_styles/M2.json',292055,'b76cbf62bac707c710cf0ae5aba5e31eea1a6339a9734bfae33ab98499534a50'],
  ['voice_styles/M3.json',290198,'ea1ac35ccb91b0d7ecad533a2fbd0eec10c91513d8951e3b25fbba99954e159b'],
  ['voice_styles/M4.json',291522,'ca8eefad4fcd989c9379032ff3e50738adc547eeb5e221b82593a6d7b3bac303'],
  ['voice_styles/M5.json',291469,'dd22b92740314321f8ae11c5e87f8dd60d060f15dd3a632b5adf77f471f77af2'],
 ],
};
export const TTS_BYTES=TTS_MODEL.files.reduce((sum,[,bytes])=>sum+bytes,0);
export const ttsFileUrl=([path,,,origin])=>(origin==='original'?TTS_MODEL.original:TTS_MODEL.base)+path;
export const PRESET_VOICES=['F1','F2','F3','F4','F5','M1','M2','M3','M4','M5'];
const CACHE='mediavault-tts-supertonic3-v1';
const CONSENT='mediavault_tts_consent_v1';

const hex=buffer=>Array.from(new Uint8Array(buffer)).map(n=>n.toString(16).padStart(2,'0')).join('');
async function valid(bytes,size,sha){return bytes.byteLength===size&&hex(await crypto.subtle.digest('SHA-256',bytes))===sha;}

export function ttsConsent(){try{return localStorage.getItem(CONSENT)==='yes';}catch{return false;}}
export function setTtsConsent(value){try{value?localStorage.setItem(CONSENT,'yes'):localStorage.removeItem(CONSENT);}catch{}}

export async function ttsCached(){
 try{const cache=await caches.open(CACHE);const hits=await Promise.all(TTS_MODEL.files.map(file=>cache.match(ttsFileUrl(file))));return hits.every(Boolean);}catch{return false;}
}
export async function forgetTtsModel(){try{await caches.delete(CACHE);}catch{}for(const file of TTS_MODEL.files)try{await removeModelFile(ttsFileUrl(file));}catch{}}

// Returns {path: ArrayBuffer}. progress({loaded,total,file,cached}).
export async function loadTtsModel(progress=()=>{},{signal}={}){
 let cache;try{cache=await caches.open(CACHE);}catch{}
 const result={};let done=0;
 for(const file of TTS_MODEL.files){
  const [path,size,sha]=file;
  signal?.throwIfAborted();
  const url=ttsFileUrl(file);let bytes=null;
  const folder=await readModelFile(url).catch(()=>null);
  if(folder){const value=await folder.arrayBuffer();if(await valid(value,size,sha))bytes=value;else await removeModelFile(url).catch(()=>{});}
  if(!bytes&&cache){const hit=await cache.match(url);if(hit){const value=await hit.arrayBuffer();if(await valid(value,size,sha))bytes=value;else await cache.delete(url);}}
  if(bytes){done+=size;progress({loaded:done,total:TTS_BYTES,file:path,cached:true});}
  else{
   const response=await fetch(url,{credentials:'omit',referrerPolicy:'no-referrer',signal:signal?AbortSignal.any([signal,AbortSignal.timeout(600000)]):AbortSignal.timeout(600000)});
   if(!response.ok)throw Error('Не удалось загрузить модель озвучки ('+path+', HTTP '+response.status+').');
   const start=done;
   bytes=await readModelResponse(response,loaded=>progress({loaded:start+loaded,total:TTS_BYTES,file:path,cached:false}));
   if(!await valid(bytes,size,sha))throw Error('Файл модели озвучки не прошёл проверку SHA-256: '+path+'.');
   done+=size;
   let stored=false;try{stored=await writeModelFile(url,bytes);}catch{}
   if(!stored)try{await cache?.put(url,new Response(bytes,{headers:{'Content-Type':'application/octet-stream'}}));}catch{}
  }
  result[path]=bytes;
 }
 return result;
}
