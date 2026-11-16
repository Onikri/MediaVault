// Where a profile stopped — a ranobe paragraph, an online manga page, an online
// episode and its second, the chosen episode and voice, the viewing history rows
// that name «глава 12» — follows the profile to its other devices through the
// MediaVault server (POST /places). Saving stays local first: each save marks
// its key, a debounced sync sends the marks and brings back what the other
// devices changed. The newest change of a place wins. Offline, the marks wait
// on this device and nothing else changes.
const enc=value=>encodeURIComponent(value||'anonymous');
const HISTORY='mv_viewing_history_v1:',HISTORY_LIMIT=40;
const FAMILIES=[
 ['r',user=>'mediavault_ranobe_progress_v1:'+enc(user)+':'],
 ['m',user=>'mediavault_reading_v1:'+enc(user)+':online:'],
 ['p',user=>'mediavault_progress_v2:'+enc(user)+':online:'],
 ['w',user=>'mv_watch_v1:'+enc(user)+':'],
];
const DIRTY='mv_places_dirty_v1:',CLOCK='mv_places_clock_v1:';
export const PLACES_EVENT='mediavault-places';
const PAGE=800,MAX_VALUE=4000;
const storageOf=storage=>storage||globalThis.localStorage;
function readJSON(storage,key,fallback){try{const value=JSON.parse(storageOf(storage).getItem(key)||'null');return value??fallback;}catch{return fallback;}}
function writeJSON(storage,key,value){try{storageOf(storage).setItem(key,JSON.stringify(value));}catch{}}

export function syncKeyFor(user,storageKey){
 if(!user)return '';
 for(const [family,prefix] of FAMILIES){const head=prefix(user);if(storageKey.startsWith(head)&&storageKey.length>head.length)return family+':'+storageKey.slice(head.length);}
 return '';
}
export function storageKeyFor(user,key){const family=FAMILIES.find(([name])=>key.startsWith(name+':'));return family?family[1](user)+key.slice(2):'';}

function historyRows(user,storage){const rows=readJSON(storage,HISTORY+user,[]);return Array.isArray(rows)?rows:[];}
const validRow=row=>row&&typeof row==='object'&&typeof row.id==='string'&&typeof row.label==='string'&&typeof row.route==='string'&&row.route.startsWith('#')&&Number.isFinite(row.at);

// The local value of one place: {at, v}, or null when this device has none.
export function readPlace(user,key,storage){
 if(key.startsWith('h:')){const row=historyRows(user,storage).find(v=>v?.id===key.slice(2));return row?{at:Number(row.at)||0,v:row}:null;}
 const name=storageKeyFor(user,key);if(!name)return null;
 const value=readJSON(storage,name,null);if(!value||typeof value!=='object')return null;
 return {at:Number(value.updatedAt)||0,v:value};
}
export function writePlace(user,key,value,at,storage){
 if(key.startsWith('h:')){
  const id=key.slice(2),rows=historyRows(user,storage).filter(v=>v?.id!==id);
  if(value!=null){if(!validRow({...value,at}))return false;rows.push({...value,id,at});}
  rows.sort((a,b)=>(b.at||0)-(a.at||0));writeJSON(storage,HISTORY+user,rows.slice(0,HISTORY_LIMIT));return true;
 }
 const name=storageKeyFor(user,key);if(!name)return false;
 try{if(value==null)storageOf(storage).removeItem(name);else{if(typeof value!=='object')return false;storageOf(storage).setItem(name,JSON.stringify(value));}}catch{return false;}
 return true;
}
// Every place this device keeps for the profile (used once, to send what a
// device knew before it started syncing).
export function localPlaceKeys(user,storage){
 const keys=historyRows(user,storage).filter(validRow).map(row=>'h:'+row.id);
 try{const s=storageOf(storage);for(let i=0;i<s.length;i++){const key=syncKeyFor(user,s.key(i)||'');if(key)keys.push(key);}}catch{}
 return keys;
}

const readDirty=(user,storage)=>{const value=readJSON(storage,DIRTY+user,{});return value&&typeof value==='object'&&!Array.isArray(value)?value:{};};
export function markPlace(user,key,at=Date.now(),storage){
 if(!user||!key)return;const dirty=readDirty(user,storage);dirty[key]=Math.max(Number(dirty[key])||0,at);writeJSON(storage,DIRTY+user,dirty);
}
// What a device sends: its marked places with their newest local value, or a
// removal stamped with the time it was removed.
export function outgoingPlaces(user,dirty,storage){
 return Object.entries(dirty).slice(0,PAGE).map(([k,mark])=>{
  const local=readPlace(user,k,storage);
  if(!local)return {k,at:Number(mark)||0,v:null};
  const v=JSON.stringify(local.v).length>MAX_VALUE?null:local.v;
  return v?{k,at:local.at||Number(mark)||0,v}:null;
 }).filter(Boolean);
}
// What a device takes: a place from another device only when it is newer than
// both what this device keeps and any change this device has not sent yet.
export function applyPlaces(user,entries,dirty,storage){
 const applied=[];
 for(const entry of entries||[]){
  if(!entry||typeof entry.k!=='string'||!Number.isFinite(entry.at))continue;
  const local=readPlace(user,entry.k,storage),localAt=Math.max(local?.at||0,Number(dirty?.[entry.k])||0);
  if(entry.at<=localAt)continue;
  if(entry.v==null&&!local)continue;
  if(writePlace(user,entry.k,entry.v,entry.at,storage))applied.push(entry.k);
 }
 return applied;
}

let active=null;
// A writer calls this after it saved a place on this device.
export function notePlace(user,storageKey,storage){const key=syncKeyFor(user,storageKey);if(!key)return;markPlace(user,key,Date.now(),storage);if(active?.user===user)active.schedule();}
export function noteHistory(user,id,storage){if(!user||user==='guest'||!id)return;markPlace(user,'h:'+id,Date.now(),storage);if(active?.user===user)active.schedule();}
// A page that shows a resume place asks for a fresh copy when it opens.
export function requestPlaceSync(){active?.refresh();}

export function createPlaceSync({user,request,storage,delay=3000,maxWait=25000,refreshEvery=15000,emit=keys=>dispatchEvent(new CustomEvent(PLACES_EVENT,{detail:{user,keys}}))}){
 let timer=0,first=0,running=null,again=false,stopped=false,pulled=0;
 const clock=()=>Number(readJSON(storage,CLOCK+user,0))||0;
 async function run({keepalive=false}={}){
  if(stopped&&!keepalive)return;
  if(running){again=true;return running;}
  clearTimeout(timer);timer=0;first=0;
  running=(async()=>{
   for(let round=0;round<8;round++){
    const dirty=readDirty(user,storage),sent=Object.fromEntries(Object.entries(dirty).slice(0,PAGE));
    const result=await request('/places',{method:'POST',body:{since:clock(),entries:outgoingPlaces(user,sent,storage)},keepalive});
    const now=readDirty(user,storage);for(const [k,mark] of Object.entries(sent))if(now[k]===mark)delete now[k];writeJSON(storage,DIRTY+user,now);
    if(stopped&&!keepalive)return;
    const applied=applyPlaces(user,result?.entries,now,storage);
    if(Number.isFinite(result?.clock))writeJSON(storage,CLOCK+user,result.clock);
    pulled=Date.now();
    if(applied.length)emit(applied);
    if(!result?.more&&!Object.keys(now).length)break;
   }
  })().catch(()=>{}).finally(()=>{running=null;if(again&&!stopped){again=false;schedule();}});
  return running;
 }
 function schedule(){
  if(stopped)return;const now=Date.now();if(!first)first=now;
  clearTimeout(timer);timer=setTimeout(run,Math.max(0,Math.min(delay,first+maxWait-now)));
 }
 function refresh(){if(Date.now()-pulled>refreshEvery)run();}
 const flush=()=>{if(Object.keys(readDirty(user,storage)).length)run({keepalive:true});};
 const visible=()=>{if(document.visibilityState==='visible')refresh();else flush();};
 const online=()=>run();
 const sync={user,schedule,refresh,run,
  start(){
   // A device that kept places before syncing existed sends them once.
   if(!readJSON(storage,CLOCK+user,0)){const dirty=readDirty(user,storage);for(const key of localPlaceKeys(user,storage))if(!(key in dirty))dirty[key]=readPlace(user,key,storage)?.at||Date.now();writeJSON(storage,DIRTY+user,dirty);}
   active=sync;globalThis.addEventListener?.('visibilitychange',visible);globalThis.addEventListener?.('online',online);globalThis.addEventListener?.('pagehide',flush);
   return run();
  },
  stop(){stopped=true;clearTimeout(timer);if(active===sync)active=null;globalThis.removeEventListener?.('visibilitychange',visible);globalThis.removeEventListener?.('online',online);globalThis.removeEventListener?.('pagehide',flush);},
 };
 return sync;
}
