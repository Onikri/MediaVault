// One Google call for narration analysis through the MediaVault gateway.
// A personal key saved on this device is used first (it is sent to the Oracle
// gateway with the request, never stored there); without it the owner's
// server key slots answer. Model output is parsed as data.
import {restoreDirectKeys,rememberDirectKey} from '../manga-direct-key.js';

export const ROLE_MODELS=[
 ['gemma-4-26b-a4b-it','Gemma 4 · 26B A4B'],
 ['gemma-4-31b-it','Gemma 4 · 31B'],
 ['gemini-3.5-flash-lite','Gemini 3.5 Flash Lite'],
];
export const BIBLE_MODELS=[
 ['gemini-3.5-flash','Gemini 3.5 Flash'],
 ['gemini-3.5-flash-lite','Gemini 3.5 Flash Lite'],
 ['gemma-4-31b-it','Gemma 4 · 31B'],
];

export async function personalKey(userId){return (await restoreDirectKeys(String(userId||'anonymous')))[0]||'';}
export async function savePersonalKey(userId,value){await rememberDirectKey(String(userId||'anonymous'),String(value||'').trim());}

export async function generate({service,userId,model,request,signal,timeout=120000}){
 if(!service?.request)throw Error('Для разбора текста подключи сервер MediaVault в профиле.');
 const key=await personalKey(userId);
 let attempt=0;
 for(;;){
  try{
   return await service.request('/reader/google/generate',{method:'POST',signal:AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(timeout)]),
    body:{...(key?{key}:{}),model,request}});
  }catch(error){
   // Free-tier minute limits: wait the advertised time a couple of times.
   const wait=Number(error?.retryAfter)||(/повтор через (\d+)/.exec(error?.message||'')?.[1]|0);
   if(signal?.aborted||attempt++>=2||!(wait>0&&wait<=90))throw error;
   await new Promise((resolve,reject)=>{const timer=setTimeout(resolve,wait*1000);signal?.addEventListener('abort',()=>{clearTimeout(timer);reject(signal.reason);},{once:true});});
  }
 }
}

export function answerJson(answer){
 const text=(answer?.candidates?.[0]?.content?.parts||[]).filter(p=>!p.thought).map(p=>p.text||'').join('');
 try{return JSON.parse(text.replace(/^\s*```(?:json)?\s*|\s*```\s*$/g,''));}catch{throw Error('Модель вернула неполный JSON.');}
}
