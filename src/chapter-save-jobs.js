// Chapter saves outlive the reader that started them: the job, its source and
// its abort controller live here, the reader and the navbar only render it.
// Nothing is persisted; a vault lock or a user switch stops every save.
import {downloadBlob,saveReaderChapter} from './reader-chapter-save.js';

export const PENDING=0,TRANSLATED=1,SAVED=2,PROBLEM=3;

export function createChapterSaves({save=saveReaderChapter,download=downloadBlob,throttle=120}={}){
 const jobs=new Map(),listeners=new Set(),controllers=new Map(),readers=new Map();
 let expanded='',scope=null,snapshot;
 function emit(){snapshot={jobs:[...jobs.values()].sort((a,b)=>b.startedAt-a.startedAt),expanded,readers:new Set(readers.keys())};for(const fn of listeners)fn();}
 function patch(id,change){const job=jobs.get(id);if(!job)return;jobs.set(id,{...job,...change});emit();}
 function stop(id,reason='Сохранение остановлено'){controllers.get(id)?.abort(new DOMException(reason,'AbortError'));}
 function drop(id,reason){stop(id,reason);jobs.delete(id);if(expanded===id)expanded='';}
 const store={
  subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn);},
  getSnapshot:()=>snapshot,
  get:id=>jobs.get(id),
  running:id=>jobs.get(id)?.state==='running',
  async start({id,userId,title,chapterLabel,fileName,total,translate,format,pages,createSource}){
   if(!id||!total||jobs.get(id)?.state==='running')return jobs.get(id);
   const controller=new AbortController(),states=new Uint8Array(total);controllers.set(id,controller);
   if(pages)states.set(pages.subarray(0,total));
   const startedAt=Date.now();let source,timer=0,latest=null,lastPaint=0,version=0;
   jobs.set(id,{id,userId:userId||'',title:title||'Глава',chapterLabel:chapterLabel||'',total,choice:{translate,format},state:'running',progress:{phase:'pages',done:0,total,problems:[]},states,version,startedAt});emit();
   // At most ~8 renders a second; timers (not animation frames) so a hidden tab still catches up.
   const flush=()=>{timer=0;lastPaint=Date.now();if(jobs.get(id)?.startedAt===startedAt&&jobs.get(id).state==='running')patch(id,{progress:latest,version:++version});};
   try{
    source=await createSource(translate);
    if(!source)throw Error('Перевод в ридере выключен. Включи перевод страницы и сохрани главу снова.');
    // Six server keys work in parallel; small phones keep three pages in flight.
    const concurrency=translate?(globalThis.navigator?.deviceMemory&&navigator.deviceMemory<=4?3:6):3;
    const result=await save({total,translate,format,name:fileName+(translate?' · RU':''),source,signal:controller.signal,concurrency,
     onProgress:value=>{latest=value;if(!timer)timer=setTimeout(flush,Math.max(0,throttle-(Date.now()-lastPaint)));},
     onPage:(index,kind)=>{states[index]=kind==='problem'?PROBLEM:SAVED;}});
    if(jobs.get(id)?.startedAt!==startedAt)return;
    download(result.blob,result.filename);
    patch(id,{state:'done',result,progress:latest,version:++version,finishedAt:Date.now()});
   }catch(error){
    const stopped=controller.signal.aborted;
    if(jobs.get(id)?.startedAt===startedAt)patch(id,{state:stopped?'stopped':'error',error:stopped?'':error?.message||'Не удалось сохранить главу.',version:++version});
   }finally{
    clearTimeout(timer);if(controllers.get(id)===controller)controllers.delete(id);
    try{source?.close?.();}catch{}
   }
   return jobs.get(id);
  },
  stop,
  // Done/failed jobs stay until the user dismisses them; stopping is final.
  dismiss(id){drop(id);emit();},
  expand(id){if(!jobs.has(id))return;expanded=id;emit();},
  collapse(){if(!expanded)return;expanded='';emit();},
  // The reader that can show a job's page registers itself while it is mounted.
  attach(id,handlers){readers.set(id,handlers);emit();return()=>{if(readers.get(id)===handlers){readers.delete(id);emit();}};},
  reader:id=>readers.get(id),
  scope(userId){userId=userId||'';if(scope===userId)return;scope=userId;let changed=false;for(const job of [...jobs.values()])if(job.userId!==userId){drop(job.id,'Сменился пользователь');changed=true;}if(changed)emit();},
  clear(){if(!jobs.size)return;for(const id of [...jobs.keys()])drop(id,'Хранилище заблокировано');emit();},
 };
 emit();return store;
}

export const chapterSaves=createChapterSaves();
if(typeof addEventListener==='function')addEventListener('mediavault-locked',()=>chapterSaves.clear());
