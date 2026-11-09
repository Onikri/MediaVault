// The narration director. It owns the book (the title bible: cast, voices,
// point of view) and splits each chapter between workers:
// 1. the heuristic roles are instant, so the voice can start at once;
// 2. the chapter is cut into parts at paragraph borders — a small part at the
//    reading position first, then larger ones — and every part goes to a
//    worker at the same time. The MediaVault gateway hands each request to the
//    least busy Google key within that key's per-minute request and token and
//    per-day budgets, so three keys work in parallel;
// 3. each answer is applied as soon as it arrives (onUpdate);
// 4. speakers the workers met for the first time go to the director, who
//    merges them into known characters or writes their cards (voice included)
//    into the bible, so the next chapters name them consistently;
// 5. the result is stored on the device and the next chapter is prepared in
//    the background, so turning the page needs no waiting and no tokens.
import {heuristicRoles,rolesRequest,parseRoles,applyRoles,ROLE_MODEL,ROLES_VERSION} from './roles.js';
import {generate} from './google.js';
import {buildBible,saveBible,aliasMap,reconcileRequest,mergeCast} from './bible.js';
import {readRoles,writeRoles,textHash} from './role-store.js';
import {P} from './role-prompts.js';

const plain=n=>String(n||'').normalize('NFC').replace(/ё/g,'е').replace(/Ё/g,'Е').toLowerCase().trim();
const memory=new Map(),running=new Map(),studies=new Map(),latest=new Map(),directing=new Map();
const remember=(key,value)=>{memory.set(key,value);while(memory.size>30)memory.delete(memory.keys().next().value);};

// Parts as [from, to) segment indexes. Sizes are in characters as sent
// (author text is cut to ~330): a first part of ~2600 answers in about two
// seconds; ~7500 (about 2000 input tokens) keeps every answer short.
export function planChunks(segments,{start=0,first=2600,size=7500,limit=90}={}){
 const weight=s=>Math.min(s.kind==='narration'?330:430,s.text.length)+8;
 const take=(from,budget,stop)=>{
  let to=from,sum=0;
  while(to<stop&&(to===from||(sum+weight(segments[to])<=budget&&to-from<limit))){sum+=weight(segments[to]);to++;}
  while(to<stop&&segments[to].p===segments[to-1].p)to++;
  return to;
 };
 const found=segments.findIndex(s=>s.p>=start),at=found<0?0:found,chunks=[];
 let i=at,budget=first;
 while(i<segments.length){const to=take(i,budget,segments.length);chunks.push([i,to]);i=to;budget=size;}
 i=0;while(i<at){const to=take(i,size,at);chunks.push([i,to]);i=to;}
 return chunks;
}

function narratorLine(bible){
 if(bible?.pov==='first'&&bible.narratorName){const n=bible.characters.findIndex(c=>c.name===bible.narratorName);return P.firstPerson+(n>=0?(n+1)+' ':'')+bible.narratorName;}
 return bible?.pov==='third'?P.thirdPerson:'';
}

// One worker request; on an overload, a spent quota or a broken answer the
// next Lite model tries once (2.5 Flash Lite answered 404 on 2026-11-09). A part
// Google refuses to read (promptFeedback.blockReason, the same on every model)
// is not retried: the caller splits it so only the refused paragraph is left.
export class Refused extends Error{}
async function work(request,{model,service,userId,signal}){
 let last;
 for(const candidate of [...new Set([model,ROLE_MODEL,'gemini-3.1-flash-lite'])]){
  try{
   const answer=await generate({service,userId,model:candidate,request,signal,timeout:60000,pool:true});
   if(answer?.promptFeedback?.blockReason&&!answer.candidates?.length)throw new Refused(answer.promptFeedback.blockReason);
   return {parsed:parseRoles(answer),model:candidate,usage:answer?.usageMetadata||{}};
  }catch(error){last=error;if(signal?.aborted||error instanceof Refused)throw error;}
 }
 throw last;
}
// A refused part is halved (twice at most); the halves that pass are tagged.
async function workParts(segments,from,to,options,depth=0){
 const {cast,context,stats}=options,part=segments.slice(from,to);
 try{
  const result=await work(rolesRequest(part,cast,{...context,before:segments.slice(Math.max(0,from-6),from)}),options);
  return [{...result,ids:new Set(part.map(s=>s.id))}];
 }catch(error){
  if(!(error instanceof Refused)||depth>=2||to-from<4)throw error;
  stats.refused++;
  let middle=from+Math.floor((to-from)/2);
  while(middle<to-1&&segments[middle].p===segments[middle-1].p)middle++;
  const halves=await Promise.allSettled([workParts(segments,from,middle,options,depth+1),workParts(segments,middle,to,options,depth+1)]);
  const done=halves.filter(h=>h.status==='fulfilled').flatMap(h=>h.value);
  if(!done.length)throw error;
  if(done.length<halves.length)stats.partial++;
  return done;
 }
}

// The bible is written once per book; concurrent readers share the request.
export function studyBook({bookKey,meta,sample,service,userId,model}){
 if(!studies.has(bookKey)){
  const job=buildBible({book:meta,sample,service,userId,model}).then(value=>{saveBible(bookKey,value);latest.set(bookKey,value);return value;});
  studies.set(bookKey,job);job.catch(()=>studies.delete(bookKey));
 }
 return studies.get(bookKey);
}
export const bookStudy=bookKey=>studies.get(bookKey)||null;
export function forgetStudy(bookKey){studies.delete(bookKey);latest.delete(bookKey);}
// The newest bible of a book in this session (cast merges included).
export function adoptBible(bookKey,bible){if(bible&&!latest.has(bookKey))latest.set(bookKey,bible);}
export const latestBible=bookKey=>latest.get(bookKey)||null;

// Director step for one chapter; steps of one book run one after another so
// two chapters never overwrite each other's new characters.
function direct(bookKey,fallback,candidates,{service,userId,meta,onBible,stats}){
 const step=(directing.get(bookKey)||Promise.resolve()).then(async()=>{
  const current=latest.get(bookKey)||await (bookStudy(bookKey)||Promise.resolve(fallback)).catch(()=>fallback);
  if(!current?.characters)return null;
  const names=aliasMap(current),wanted=candidates.filter(c=>!names.has(plain(c.name)));
  if(!wanted.length)return {bible:current,rename:new Map()};
  const answer=await generate({service,userId,model:current.model?.startsWith('gemma')?ROLE_MODEL:(current.model||ROLE_MODEL),request:reconcileRequest(current,wanted,{title:meta.title,language:meta.language}),timeout:90000,pool:true});
  stats.input+=answer?.usageMetadata?.promptTokenCount||0;stats.output+=answer?.usageMetadata?.candidatesTokenCount||0;stats.requests++;
  const merged=mergeCast(current,answer,wanted);
  latest.set(bookKey,merged.bible);saveBible(bookKey,merged.bible);onBible(merged.bible);
  return merged;
 });
 directing.set(bookKey,step.catch(()=>{}));
 return step;
}

// → {segments, characters, stats}. The work is not cancelled when the reader
// leaves the chapter: requests already sent are paid for, so their answer is
// stored for the next visit. onUpdate stops being called after `detached()`.
export function analyseChapter(options){
 const {paragraphs,bookKey,chapterKey,model=ROLE_MODEL}=options;
 const key=[bookKey,chapterKey,textHash(paragraphs),ROLES_VERSION,model].join('|');
 if(running.has(key)){
  const job=running.get(key);job.listeners.add(options.onUpdate);
  if(job.last)options.onUpdate?.(job.last);
  return job.promise;
 }
 const job={listeners:new Set([options.onUpdate]),last:null};
 const emit=value=>{job.last=value;for(const listener of job.listeners)try{listener?.(value);}catch{}};
 job.promise=run(key,options,emit).finally(()=>running.delete(key));
 running.set(key,job);
 return job.promise;
}
export function detach(chapterKey,listener){for(const [key,job] of running)if(key.includes('|'+chapterKey+'|'))job.listeners.delete(listener);}

async function run(key,{paragraphs,bible,meta={},service,userId,model=ROLE_MODEL,start=0,onBible=()=>{},bookKey},emit){
 const cached=memory.get(key)||await readRoles(key);
 if(cached?.segments?.length===heuristicRoles(paragraphs).length){remember(key,cached);const value={...cached,done:true,cached:true};emit(value);return value;}
 let segments=heuristicRoles(paragraphs);
 const book=latest.get(bookKey)||bible,began=performance.now(),cast=book?.characters||[],canonical=aliasMap(book);
 const context={title:meta.title||'',tone:book?.tone||'',language:meta.language||'ru',pov:narratorLine(book)};
 // failed: no answer (network, quota) — the chapter is not stored and is tried
 // again next time; refused: Google will not read that text — stored as it is.
 const chunks=planChunks(segments,{start}),fresh=new Map(),stats={parts:chunks.length,done:0,failed:0,refused:0,partial:0,input:0,output:0,requests:0,models:{},firstMs:0,ms:0};
 const characters=()=>[...fresh.values()].map(({lines,...c})=>c);
 emit({segments,characters:[],done:false,stats:{...stats}});
 const options={model,service,userId,cast,context,stats};
 await Promise.all(chunks.map(async([from,to])=>{
  try{
   for(const {parsed,usage,model:used,ids} of await workParts(segments,from,to,options)){
    segments=applyRoles(segments,parsed,{cast,canonical,ids});
    for(const c of parsed.cast){
     if(canonical.get(plain(c.name)))continue;
     const entry=fresh.get(plain(c.name))||{...c,lines:[]};fresh.set(plain(c.name),entry);
    }
    for(const s of segments)if(ids.has(s.id)&&s.speaker){const entry=fresh.get(plain(s.speaker));if(entry&&entry.lines.length<3)entry.lines.push(s.text);}
    stats.input+=usage.promptTokenCount||0;stats.output+=usage.candidatesTokenCount||0;stats.requests++;stats.models[used]=(stats.models[used]||0)+1;
   }
  }catch(error){if(error instanceof Refused)stats.partial++;else stats.failed++;}
  stats.done++;if(!stats.firstMs)stats.firstMs=Math.round(performance.now()-began);
  emit({segments,characters:characters(),done:false,stats:{...stats}});
 }));
 // The director: new speakers join the bible (it may still be being written for a new book).
 if(fresh.size)try{
  const merged=await direct(bookKey,bible,[...fresh.values()],{service,userId,meta,onBible,stats});
  if(merged){
   const names=aliasMap(merged.bible),info=new Map(merged.bible.characters.map(c=>[c.name,c]));
   segments=segments.map(s=>{
    if(!s.speaker)return s;
    const name=merged.rename.get(s.speaker)||names.get(plain(s.speaker))||s.speaker,c=info.get(name);
    return {...s,speaker:name,gender:c&&c.gender!=='u'?c.gender:s.gender};
   });
   for(const name of [...fresh.keys()])if(names.has(name))fresh.delete(name);
  }
 }catch{}
 stats.ms=Math.round(performance.now()-began);
 const value={segments,characters:characters(),done:true,stats};
 if(!stats.failed){remember(key,value);writeRoles(key,{segments,characters:value.characters,stats});}
 emit(value);
 return value;
}

// Background preparation of the next chapter, one at a time.
let prefetching=null;
export function prefetchChapter(options){
 if(prefetching)return prefetching;
 prefetching=Promise.resolve().then(()=>options.load()).then(paragraphs=>paragraphs?.length?analyseChapter({...options,paragraphs,start:0,onUpdate:null}):null)
  .catch(()=>null).finally(()=>{prefetching=null;});
 return prefetching;
}
