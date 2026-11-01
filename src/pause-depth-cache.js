import {DEPTH_MODEL} from './pause-depth-model.js';
import {readModelFile,writeModelFile,removeModelFile,readModelResponse} from './model-folder.js';
const CACHE='mediavault-pause-depth-v1';
async function valid(bytes){return bytes.byteLength===DEPTH_MODEL.bytes&&Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(n=>n.toString(16).padStart(2,'0')).join('')===DEPTH_MODEL.sha256;}
export async function depthWeights(progress=()=>{}){
 const folder=await readModelFile(DEPTH_MODEL.url);
 if(folder){const bytes=await folder.arrayBuffer();if(await valid(bytes)){progress({phase:'cached'});return bytes;}await removeModelFile(DEPTH_MODEL.url);}
 let cache;try{cache=await caches.open(CACHE);}catch{}
 const hit=await cache?.match(DEPTH_MODEL.url);
 if(hit){const bytes=await hit.arrayBuffer();if(await valid(bytes)){progress({phase:'cached'});return bytes;}await cache.delete(DEPTH_MODEL.url);}
 progress({phase:'download',loaded:0,total:DEPTH_MODEL.bytes});
 const response=await fetch(DEPTH_MODEL.url,{credentials:'omit',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(180000)});
 if(!response.ok)throw Error('Не удалось загрузить модель глубины. Повтори позже.');
 const bytes=await readModelResponse(response,(loaded)=>progress({phase:'download',loaded,total:DEPTH_MODEL.bytes}));
 if(!await valid(bytes))throw Error('Проверка файла модели глубины не прошла.');
 let stored=false;try{stored=await writeModelFile(DEPTH_MODEL.url,bytes);}catch{}
 if(!stored)try{await cache?.put(DEPTH_MODEL.url,new Response(bytes,{headers:{'Content-Type':'application/octet-stream'}}));}catch{}
 return bytes;
}
