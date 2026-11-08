// One Supertonic worker per page, requests served strictly in order.
import {loadTtsModel} from './model.js';

let worker=null,ready=null,chain=Promise.resolve(),sequence=0;
const waiting=new Map();

function post(message,transfer=[]){
 const id=++sequence;
 return new Promise((resolve,reject)=>{waiting.set(id,{resolve,reject});worker.postMessage({...message,id},transfer);});
}
function spawn(){
 worker=new Worker(new URL('./supertonic.worker.js',import.meta.url),{type:'module'});
 worker.onmessage=({data})=>{const job=waiting.get(data.id);if(!job)return;waiting.delete(data.id);data.type==='error'?job.reject(Error(data.message)):job.resolve(data);};
 worker.onerror=event=>{for(const job of waiting.values())job.reject(Error(event.message||'Озвучка остановилась.'));waiting.clear();ready=null;worker=null;};
}

// progress({phase:'download'|'start',loaded,total})
export function startNarrationEngine({prefer='auto',progress=()=>{},signal}={}){
 if(ready)return ready;
 ready=(async()=>{
  const files=await loadTtsModel(value=>progress({phase:'download',...value}),{signal});
  progress({phase:'start'});
  if(!worker)spawn();
  return post({type:'load',files,prefer},Object.values(files));
 })();
 ready.catch(()=>{ready=null;worker?.terminate();worker=null;});
 return ready;
}

export function engineReady(){return ready;}

// {text, lang, voice:{F1:1}, steps, speed, seed} → {audio:Float32Array, sampleRate, ms, provider}
export function synthesize(request){
 const task=chain.then(async()=>{await ready;if(!worker)throw Error('Озвучка не запущена.');return post({type:'synth',...request});});
 chain=task.catch(()=>{});
 return task;
}

export function stopNarrationEngine(){worker?.terminate();worker=null;ready=null;for(const job of waiting.values())job.reject(Error('Озвучка остановлена.'));waiting.clear();}
