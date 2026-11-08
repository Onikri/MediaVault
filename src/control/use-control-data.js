import {useCallback,useEffect,useRef,useState} from 'react';

// One poll for the whole owner console: every section and the rail counters
// read the same snapshot, so numbers never disagree between screens.
const EMPTY={health:null,latency:null,rooms:null,roomRules:null,guests:null,activity:{},drive:null};

export function useControlData(service,enabled){
 const [data,setData]=useState(EMPTY),[errors,setErrors]=useState({}),[updatedAt,setUpdatedAt]=useState(0),[loading,setLoading]=useState(false);
 const alive=useRef(true),request=service?.request;
 const connected=enabled&&service?.status==='connected'&&service.session?.role!=='guest';
 const refresh=useCallback(async()=>{
  if(!connected)return;
  setLoading(true);
  const started=performance.now();
  const calls={
   health:request('/health',{auth:false}).then(value=>({health:value,latency:Math.round(performance.now()-started)})),
   rooms:request('/rooms').then(value=>({rooms:value.rooms||[],roomRules:value.rules||null})),
   guests:request('/guests').then(value=>({guests:value.guests||[]})),
   activity:request('/guests/activity').then(value=>({activity:value.guests||{}})),
   drive:request('/google/connection').then(value=>({drive:value})),
  };
  const names=Object.keys(calls),results=await Promise.allSettled(Object.values(calls));
  if(!alive.current)return;
  const next={},failed={};
  results.forEach((result,index)=>{if(result.status==='fulfilled')Object.assign(next,result.value);else failed[names[index]]=result.reason?.status===404?'Сервер ещё не умеет это показывать. Обнови MediaVault на ВМ.':result.reason?.message||'Нет ответа';});
  setData(old=>({...old,...next}));setErrors(failed);setUpdatedAt(Date.now());setLoading(false);
 },[connected,request]);
 useEffect(()=>{
  alive.current=true;if(!connected)return()=>{alive.current=false;};
  refresh();
  const timer=setInterval(()=>{if(document.visibilityState==='visible')refresh();},15000);
  const wake=()=>{if(document.visibilityState==='visible')refresh();};
  document.addEventListener('visibilitychange',wake);
  return()=>{alive.current=false;clearInterval(timer);document.removeEventListener('visibilitychange',wake);};
 },[connected,refresh]);
 const patch=useCallback(change=>setData(old=>({...old,...(typeof change==='function'?change(old):change)})),[]);
 return {...data,errors,updatedAt,loading,refresh,patch,connected};
}

// A clock that ticks once per interval; live timelines and "N seconds ago" read it.
export function useNow(interval=1000){
 const [now,setNow]=useState(()=>Date.now());
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),interval);return()=>clearInterval(timer);},[interval]);
 return now;
}

export function since(ms,now=Date.now()){
 const s=Math.max(0,Math.round((now-ms)/1000));
 if(s<5)return 'только что';
 if(s<60)return s+' с назад';
 if(s<3600)return Math.floor(s/60)+' мин назад';
 return Math.floor(s/3600)+' ч назад';
}

export function timecode(seconds){
 const s=Math.max(0,Math.floor(seconds||0)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=String(s%60).padStart(2,'0');
 return h?h+':'+String(m).padStart(2,'0')+':'+r:m+':'+r;
}

export function left(epochSeconds,now=Date.now()){
 const s=Math.max(0,Math.round(epochSeconds-now/1000));
 if(s<60)return 'меньше минуты';
 if(s<3600)return Math.floor(s/60)+' мин';
 const h=Math.floor(s/3600),m=Math.floor(s%3600/60);
 return m?h+' ч '+m+' мин':h+' ч';
}

export function plural(n,one,few,many){
 const a=Math.abs(n)%100,b=a%10;
 return a>10&&a<20?many:b>1&&b<5?few:b===1?one:many;
}

export const JOB_ACTIVE=new Set(['running','queued','cancelling']);
export function jobCounts(jobs=[]){
 const c={running:0,queued:0,waiting:0,failed:0,done:0};
 for(const j of jobs){if(j.status==='running'||j.status==='cancelling')c.running++;else if(j.status==='queued')c.queued++;else if(j.status==='waiting_auth')c.waiting++;else if(j.status==='failed')c.failed++;else if(j.status==='completed')c.done++;}
 return c;
}
