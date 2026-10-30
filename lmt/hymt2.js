// SPDX-License-Identifier: AGPL-3.0-or-later
// Actual local llama.cpp runtime. No page, dialogue or credential is uploaded.
import {Wllama} from '@wllama/wllama/esm/index.js';
import wasmUrl from '@wllama/wllama/esm/wasm/wllama.wasm?url';
import {cachedGguf} from '../src/model-gguf.js';
import {readModelFile} from '../src/model-folder.js';
import {hymtModel,hymtUrl,hymtPrompt} from '../src/hymt-models.js';
import {indexModel,indexUrl,indexPrompt} from '../src/index-models.js';
const quiet={debug(){},log(){},warn(){},error(){}};
export function createHymtTranslator({createEngine=()=>new Wllama({default:wasmUrl},{suppressNativeLog:true,logger:quiet,allowOffline:true,parallelDownloads:1}),resolveUrl=null}={}){
 let engine=null,identity='',busy=false;
 async function close(){const old=engine;engine=null;identity='';if(old)await old.exit().catch(()=>{});}
 async function load(config,progress){
  const indexed=config.deviceTranslator==='index',name=indexed?'Index Translate':'Hy-MT2',model=indexed?indexModel(config.hymtQuant):hymtModel(config.hymtQuant),compute=config.deviceCompute||'auto',key=model.sha+':'+compute;
  if(compute==='gpu'&&!navigator.gpu)throw Error('WebGPU недоступен. Выбери «Авто» или «CPU / WASM».');
  if(engine&&identity===key)return engine;
  await close();engine=createEngine();
  // No implicit latest-version compatibility scripts from a third-party CDN.
  engine.setCompat(null);
  try{
   const url=resolveUrl?resolveUrl(model):(indexed?indexUrl:hymtUrl)(model),disk=await readModelFile(url),cached=disk?.size===model.bytes||(await engine.modelManager.getModels()).some(v=>v.url===url&&v.size===model.bytes);
   if(!cached&&navigator.storage?.estimate){const space=await navigator.storage.estimate();if(space.quota&&space.quota-(space.usage||0)<model.bytes+64*1024*1024)throw Error('Недостаточно места в кэше браузера для выбранных весов. Освободи место или выбери Q4');}
   progress(name+' · загрузка весов '+(model.bytes/1e9).toFixed(2)+' ГБ, затем кэш устройства');
   const source=await cachedGguf(url,model,engine.modelManager,progress);
   const params={n_ctx:2048,n_batch:128,n_ubatch:64,n_parallel:1,n_threads:globalThis.crossOriginIsolated?Math.max(1,Math.min(4,navigator.hardwareConcurrency||1)):1,n_gpu_layers:compute==='cpu'?0:99999,seed:42,reasoning:false,warmup:false,default_template_kwargs:{enable_thinking:false}};
   progress(name+' · запускаем '+(compute==='cpu'?'CPU / WASM':'WebGPU или CPU / WASM'));
   try{await engine.loadModel(await source.open(),params);}
   catch(e){if(compute!=='auto')throw e;await close();engine=createEngine();engine.setCompat(null);progress(name+' · GPU недоступен, запускаем CPU / WASM');await engine.loadModel(await source.open(),{...params,n_gpu_layers:0});}
   identity=key;return engine;
  }catch(e){await close();throw Error(name+' на устройстве: '+(e.message||e)+'. Если не хватает памяти, выбери Q4 или перевод на ВМ.');}
 }
 async function translate(texts,config={},context,progress=()=>{}){
  if(!config.allowDownloads)throw Error('Разреши загрузку моделей на устройство.');
  if(busy)throw Error('Предыдущий локальный перевод ещё выполняется.');busy=true;
  try{
   const indexed=config.deviceTranslator==='index',name=indexed?'Index Translate':'Hy-MT2',runtime=await load(config,progress),translations=Array(texts.length).fill(''),active=texts.filter(t=>t.trim()).length;let completed=0;
   for(let i=0;i<texts.length;i++)if(texts[i].trim()){
    progress(name+' · переводим реплику '+(++completed)+' / '+active);
    const response=await runtime.createChatCompletion({messages:[{role:'user',content:(indexed?indexPrompt:hymtPrompt)(texts[i])}],max_tokens:Math.min(768,Math.max(128,texts[i].length*4)),temperature:indexed?0:.7,...(indexed?{}:{top_p:.6,top_k:20,penalty_repeat:1.05}),seed:42,stream:false,chat_template_kwargs:{enable_thinking:false}});
    const choice=response.choices?.[0],text=choice?.message?.content?.trim();
    if(choice?.finish_reason==='length'||!text||/<think>/i.test(text))throw Error(name+' не вернул полный перевод реплики. Страница сохранена в оригинале.');
    translations[i]=text;
   }
   return {translations,context,translationDiagnostics:{profile:indexed?'index-device':'hymt2-device',model:(indexed?indexModel:hymtModel)(config.hymtQuant).file,runtime:'wllama-3.8.1',libllama:Wllama.getLibllamaVersion()}};
  }finally{busy=false;}
 }
 return {translate,close};
}
const local=createHymtTranslator();
export const translateHymt2=(texts,config,context,progress)=>local.translate(texts,config,context,progress);
