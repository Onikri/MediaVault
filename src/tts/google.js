// One Google call for narration analysis through the MediaVault gateway.
// A personal key saved on this device is used first (it is sent to the Oracle
// gateway with the request, never stored there); without it the owner's
// server key slots answer. Model output is parsed as data.
import {restoreDirectKeys,rememberDirectKey} from '../manga-direct-key.js';

export const ROLE_MODELS=[
 ['gemini-3.5-flash-lite','Gemini 3.5 Flash Lite · быстро'],
 ['gemma-4-26b-a4b-it','Gemma 4 · 26B A4B'],
 ['gemma-4-31b-it','Gemma 4 · 31B'],
];
export const BIBLE_MODELS=[
 ['gemini-3.5-flash-lite','Gemini 3.5 Flash Lite'],
 ['gemma-4-31b-it','Gemma 4 · 31B'],
];

export async function personalKey(userId){return (await restoreDirectKeys(String(userId||'anonymous')))[0]||'';}
export async function savePersonalKey(userId,value){await rememberDirectKey(String(userId||'anonymous'),String(value||'').trim());}

// pool: narration lets a personal key work next to the server keys
// (the gateway spreads the parts of a chapter over all of them).
// Thinking settings differ by model: Gemma refuses a thinking level (HTTP 400,
// checked 2026-11-09) and 2.5 Lite takes a budget instead.
export function forModel(request,model){
 const config=request?.generationConfig;if(!config?.thinkingConfig)return request;
 if(model.startsWith('gemma-')){const {thinkingConfig,...rest}=config;return {...request,generationConfig:rest};}
 if(model.startsWith('gemini-2.5'))return {...request,generationConfig:{...config,thinkingConfig:{thinkingBudget:0}}};
 return request;
}

export async function generate({service,userId,model,request,signal,timeout=120000,pool=false}){
 if(!service?.request)throw Error('Для разбора текста подключи сервер MediaVault в профиле.');
 request=forModel(request,model);
 const key=await personalKey(userId);
 let attempt=0;
 for(;;){
  try{
   return await service.request('/reader/google/generate',{method:'POST',signal:AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(timeout)]),
    body:{...(key?{key}:{}),...(pool&&key&&Number(service?.session?.serverVersion)>=60?{pool:true}:{}),model,request}});
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
