import {resolveMangaOcr} from './ocr-profiles.js';
export const TRANSLATION_VERSION=6;
export function translationConfig(value={}){
 const backend=!value.engine||['oracle','backend'].includes(value.engine);
 return {...value,version:TRANSLATION_VERSION,engine:value.engine==='gemma'?'gemma':backend?'backend':'lmt',mode:value.mode||'gpu',deviceTranslator:['index','webllm'].includes(value.deviceTranslator)?value.deviceTranslator:'hymt2',hymtQuant:['q4','q6','q8'].includes(value.hymtQuant)?value.hymtQuant:'q8',deviceCompute:['cpu','gpu'].includes(value.deviceCompute)?value.deviceCompute:'auto',language:value.language||'English',ocr:value.ocr||'auto',detector:!backend&&value.detector==='magi'?'comic-bubble':value.detector||'comic-bubble',panelDetector:!backend&&value.panelDetector==='yolov12-panels'?'none':value.panelDetector||'none',inpaint:value.inpaint||'quality',font:value.font||(value.engine==='gemma'?'auto':'comic-relief'),translator:value.translator||'hymt2',model:value.model||'Qwen3.5-4B-q4f16_1-MLC',prefetch:[0,1,2,4].includes(value.prefetch)?value.prefetch:2,cache:value.cache!==false};
}
export function migrateTranslationSettings(value={}){
 // Earlier settings predate the full VM worker: a stored Qwen/default browser
 // mode must not keep selecting the old experiment after the quality rollout.
 return value.version>=4?translationConfig(value):translationConfig({...value,engine:'backend',translator:'hymt2',detector:'comic-bubble',ocr:'auto',inpaint:'quality',mode:'gpu',model:'Qwen3.5-4B-q4f16_1-MLC'});
}
export function resultConfig(value){
 const v=translationConfig(value);
 if(v.engine==='gemma')return {version:TRANSLATION_VERSION,engine:'gemma',mode:'gemma',language:v.language,ocr:'none',detector:'comic-bubble',detectionConfidence:.15,inpaint:v.inpaint,font:v.font,translator:'google-gemma4-pool',promptVersion:v.gemmaPromptVersion||'localization-v1',typesetter:'source-style-cyrillic-v1'};
 return {version:TRANSLATION_VERSION,engine:v.engine,mode:v.engine==='backend'?'backend':v.mode,language:v.language,ocr:resolveMangaOcr(v.language,v.ocr),detector:v.detector,panelDetector:v.panelDetector,inpaint:v.inpaint,font:v.font,translator:v.engine==='backend'?v.translator:v.mode==='api'?v.serverModel:v.deviceTranslator!=='webllm'?(v.deviceTranslator==='index'?'Index-Translate-2B-':'Hy-MT2-1.8B-')+v.hymtQuant:v.model,...(v.mode==='api'&&v.engine!=='backend'?{host:v.host,apiInput:v.apiInput}:{}),...(v.engine!=='backend'&&v.mode!=='api'&&v.deviceTranslator!=='webllm'?{deviceCompute:v.deviceCompute}:{}),typesetter:'fitted-cyrillic-v2'};
}
export function hasRenderedPage(result){return !!result?.renderedImage&&result.renderedImage.byteLength>0;}
export function requireRenderedPage(result){if(!hasRenderedPage(result))throw Error(result?.message||'Готовая страница не получена. Оригинал сохранён; попробуй другой OCR или язык.');return result;}
export function bytesBase64(data){let text='';const a=new Uint8Array(data);for(let i=0;i<a.length;i+=8192)text+=String.fromCharCode(...a.subarray(i,i+8192));return btoa(text);}
export function fromBase64(text){return Uint8Array.from(atob(text),x=>x.charCodeAt(0)).buffer;}
const delay=(ms,signal)=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);reject(signal.reason);};const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();});
export async function translateBackend(blob,config,service,signal,status){
 if(service?.status!=='connected')throw Error('Для перевода на ВМ подключи свой профиль к серверу. На устройстве можно переводить без ВМ.');
 const bytes=await blob.arrayBuffer();signal.throwIfAborted();if(bytes.byteLength>10*1024*1024)throw Error('Страница превышает 10 МБ.');
 const options=resultConfig(config);delete options.version;delete options.engine;delete options.mode;delete options.typesetter;
 const {id}=await service.request('/reader/lmt/jobs',{method:'POST',body:{image:bytesBase64(bytes),options},signal});let completed=false;
 try{const until=Date.now()+15*60*1000;while(Date.now()<until){signal.throwIfAborted();const task=await service.request('/reader/lmt/jobs/'+id,{signal});status?.(task.status||'Обрабатываем страницу на ВМ…');if(task.state==='done'){completed=true;return requireRenderedPage({...task.result,renderedImage:fromBase64(task.result.renderedImage)});}if(['error','cancelled'].includes(task.state))throw Error(task.status||'Перевод остановлен.');await delay(900,signal);}throw Error('Перевод занял больше 15 минут. Проверь состояние ВМ.');}
 finally{if(!completed)service.request('/reader/lmt/jobs/'+id+'/cancel',{method:'POST'}).catch(()=>{});}
}
// One shared worker: visible pages outrank queued prefetch. A page leaving the
// viewport unsubscribes without destroying useful work for the next page.
export class TranslationQueue{
 constructor(run){this.run=run;this.jobs=new Map();this.controller=new AbortController();this.running=false;}
 request(key,input,{background=false,status}={}){
  let job=this.jobs.get(key);
  if(job){if(!background)job.background=false;if(status)job.listeners.add(status);return job.promise;}
  job={key,input,background,listeners:new Set(status?[status]:[])};job.promise=new Promise((resolve,reject)=>Object.assign(job,{resolve,reject}));this.jobs.set(key,job);queueMicrotask(()=>this.drain());return job.promise;
 }
 async drain(){if(this.running)return;this.running=true;try{while(!this.controller.signal.aborted){const job=[...this.jobs.values()].find(j=>!j.started&&!j.background)||[...this.jobs.values()].find(j=>!j.started);if(!job)break;job.started=true;try{const result=await this.run(job.input,this.controller.signal,s=>job.listeners.forEach(fn=>fn(s)));this.controller.signal.throwIfAborted();job.resolve(result);job.done=true;job.input=null;for(const old of [...this.jobs.values()].filter(j=>j.done).slice(0,-6))this.jobs.delete(old.key);}catch(e){this.jobs.delete(job.key);job.reject(e);}finally{job.listeners.clear();}}}finally{this.running=false;}}
 close(){this.controller.abort(new DOMException('Перевод остановлен','AbortError'));for(const job of this.jobs.values())if(!job.started)job.reject(this.controller.signal.reason);this.jobs.clear();}
}
