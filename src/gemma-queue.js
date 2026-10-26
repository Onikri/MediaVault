import {TranslationQueue} from './manga-translation.js';
// Visible work keeps priority. Only already-queued pages form a batch: the
// current page never waits for three future pages to become available.
export class GemmaQueue extends TranslationQueue{
 constructor(runBatch){super(null);this.runBatch=runBatch;}
 async drain(){
  if(this.running)return;this.running=true;
  try{
   while(!this.controller.signal.aborted){
    const jobs=[...this.jobs.values()].filter(j=>!j.started).sort((a,b)=>Number(a.background)-Number(b.background)).slice(0,4);
    if(!jobs.length)break;for(const j of jobs)j.started=true;
    try{
     const results=await this.runBatch(jobs.map(j=>j.input),this.controller.signal,(index,text)=>jobs[index]?.listeners.forEach(fn=>fn(text)));
     this.controller.signal.throwIfAborted();if(!Array.isArray(results)||results.length!==jobs.length)throw Error('Пакет вернул не все страницы.');
     for(const [i,j]of jobs.entries()){
      if(results[i] instanceof Error){this.jobs.delete(j.key);j.reject(results[i]);}
      else{j.resolve(results[i]);j.done=true;j.input=null;}
     }
     for(const old of [...this.jobs.values()].filter(j=>j.done).slice(0,-6))this.jobs.delete(old.key);
    }catch(error){for(const j of jobs){this.jobs.delete(j.key);j.reject(error);}}
    finally{for(const j of jobs)j.listeners.clear();}
   }
  }finally{this.running=false;}
 }
}
