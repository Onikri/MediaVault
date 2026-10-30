import {BLOCK_LIMITS,linkPageBlocks,packBlockSheets,unpackBlockTranslations} from './manga-blocks.js';
import {directKey,restoreDirectKeys} from './manga-direct-key.js';

// Measured budgets determine how many source pages share a sheet.
export async function drainBlockChapter(c){
 if(c.active||c.controller.signal.aborted)return;c.active++;
 try{while(!c.controller.signal.aborted){
  const waiting=[...c.jobs.values()].filter(j=>j.state==='queued'),first=waiting.find(j=>!j.background)||waiting[0];if(!first)break;
  const group=[],prepared=[];let key,diagnostics,sourcePixels=0,sourceBytes=0;const started=performance.now();
  try{
   // First-page cache hits need no neighbour work. If it is missing, rebuild
   // any linked neighbours together so cached halves cannot split a sentence.
   const firstHit=await c.cached(first);if(firstHit){c.finish(first,firstHit);continue;}
   const previous=c.config.webtoon&&first.index>0&&!c.jobs.has(first.index-1)?first.index-1:first.index;
   for(let n=previous;n<c.entries.length;n++){
    let job=c.jobs.get(n);if(job&&job.state!=='queued'){if(n>=first.index)break;continue;}
    job=job||c.request(n,null,true);job.state='running';job.queueMs=Math.round(performance.now()-job.started);group.push(job);
    try{
     if(n>first.index&&!c.config.webtoon)job.sourceTimeoutMs=Math.ceil(Math.max(100,1800-(performance.now()-started)));
     await c.cached(job);
     c.notify(n,{phase:'detecting',message:'Блоки · быстрый алгоритмический поиск без весов'});
     const page=job.prepared||await c.prepare(job.blob,n,message=>c.notify(n,{phase:'detecting',message}));job.prepared=page;
     c.notify(n,{phase:'detecting',message:'Блоки · '+page.regions.length+' областей',detected:{width:page.width,height:page.height,regions:page.regions.map(r=>({id:r.id,bbox:r.bbox}))}});
     const nextPixels=sourcePixels+page.width*page.height,nextBytes=sourceBytes+job.blob.size;
     const tail=prepared.at(-1),needsNeighbour=c.config.webtoon&&tail?.regions.some(r=>tail.height-r.bbox[3]<=Math.max(16,tail.width*.025));
     if(needsNeighbour&&(nextPixels>2*BLOCK_LIMITS.pixels||nextBytes>2*BLOCK_LIMITS.sourceBytes))throw Error('Связанные фрагменты превышают лимит памяти. Раздели главу на меньшие страницы.');
     if(prepared.length&&!needsNeighbour&&(nextPixels>BLOCK_LIMITS.pixels||nextBytes>BLOCK_LIMITS.sourceBytes||prepared.reduce((sum,p)=>sum+p.regions.length,0)+page.regions.length>BLOCK_LIMITS.regions)){
      job.state='queued';group.pop();break;
     }
     prepared.push({...page,blob:job.blob});sourcePixels=nextPixels;sourceBytes=nextBytes;
     const sheets=packBlockSheets(linkPageBlocks(prepared,{direction:c.direction,webtoon:c.config.webtoon}));
     const nextEdge=c.config.webtoon&&n<c.entries.length-1&&page.regions.some(r=>page.height-r.bbox[3]<=Math.max(16,page.width*.025));
     if(n>=first.index&&!nextEdge&&(sheets.length>=2||performance.now()-started>1800||c.config.saveData))break;
    }catch(error){c.fail(job,error);job.state='failed';break;}
   }
   let active=group.filter(j=>j.state==='running');if(!active.length)continue;
   const groups=linkPageBlocks(prepared,{direction:c.direction,webtoon:c.config.webtoon}),sheets=packBlockSheets(groups);
   let pages=prepared.map(p=>({page:p.page,width:p.width,height:p.height,regions:[],detected:{width:p.width,height:p.height,regions:[]},timings:{detectionMs:p.detectionMs,ocrMs:0}})),usage=[];
   if(sheets.length){
    const available=c.serverSlots.length?c.serverSlots.map(slot=>'oracle-slot:'+slot):c.getKey===directKey?await restoreDirectKeys(c.keyScope):[c.getKey(c.keyScope)];key=available.find(k=>!c.keyBusy.has(k));if(!key)throw Error('Добавь ключ Google в настройках перевода.');c.keyBusy.add(key);
    const packed=await c.canvasTask({operation:'blocks-pack',sheets,pages:prepared});c.controller.signal.throwIfAborted();
    const answers=[];let pack=[],count=0,bytes=0;
    const send=async()=>{if(!pack.length)return;const current=pack;pack=[];count=0;bytes=0;
     for(const job of active){job.keySlot=c.serverSlots.length?c.serverSlots[available.indexOf(key)]+1:available.indexOf(key)+1;job.serverKey=!!c.serverSlots.length;c.notify(job.index,{phase:'translating',message:'Блоки · '+current.length+' лист(а), '+prepared.length+' исходных страниц',model:c.config.directModel,totalRegions:job.prepared.regions.length,completedRegions:0});}
     const result=await c.callGoogle(current,{key,model:c.config.directModel,language:c.config.language,direction:c.direction,gemmaProfile:'compat',context:[...c.context].filter(([i])=>i<first.index).map(([,s])=>s).join('\n').slice(-1200),signal:c.controller.signal,timeoutMs:c.config.directTimeoutMs,onDiagnostic:value=>{
      diagnostics={...value,blocks:{sourcePages:prepared.map(p=>p.page),sheets:current.map(s=>({id:s.id,width:s.width,height:s.height,placements:s.placements.map(p=>({id:p.group.id,box:p.box,parts:p.group.parts.map(part=>({page:part.page,bbox:part.bbox}))}))})),joined:groups.filter(g=>g.parts.length>1).map(g=>g.id)},transport:{viaOracle:!!c.config.directViaOracle,keySlot:active[0]?.keySlot,serverKey:!!c.serverSlots.length}};
      for(const job of active)c.notify(job.index,{phase:'translating',message:'Лист блоков · '+value.stage,diagnostics});
     }});answers.push(...result.pages);usage.push(result.usage);
    };
    for(const sheet of packed){if(sheet.image.length>16*1024*1024)throw Error('Лист превышает лимит запроса. Раздели слишком большой текстовый блок.');if(pack.length&&(pack.length>=3||count+sheet.regions.length>100||bytes+sheet.image.length>16*1024*1024))await send();pack.push(sheet);count+=sheet.regions.length;bytes+=sheet.image.length;}
    await send();pages=unpackBlockTranslations(answers,sheets,prepared);
   }
   c.controller.signal.throwIfAborted();
   for(const job of active){const page=pages.find(p=>p.page===job.index+1);if(!page)throw Error('Не получена страница пакета блоков.');page.usage=usage;page.engine='Блоки → Google → очистка на устройстве';page.diagnostics=diagnostics;
    page.detectionReport={found:page.detected.regions.length,translated:page.regions.filter(r=>r.ru_translation?.trim()).length,rejected:page.regions.filter(r=>!r.ru_translation?.trim()).map(r=>r.uid),missed:'unknown'};
    if(c.config.cache){const{diagnostics,...safe}=page;await c.writeCache(job.cacheId,c.scope,{kind:'manga-json',page:safe});}c.finish(job,page);
   }
  }catch(error){if(!group.length&&first.state==='queued')c.fail(first,error);for(const job of group)if(job.state==='running')c.fail(job,error);}
  finally{if(key)c.keyBusy.delete(key);}
 }}finally{c.active--;if([...c.jobs.values()].some(j=>j.state==='queued')&&!c.controller.signal.aborted)queueMicrotask(()=>c.drain());}
}
