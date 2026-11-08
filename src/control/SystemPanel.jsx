import {useEffect,useRef,useState} from 'react';
import {bytes,duration} from '../guest-activity-format.js';

// Live VM metrics for the storage section: space, load, containers and processes.
// /admin/system is polled every 5 s while the tab is visible; the last 5 minutes
// of CPU and memory are kept in memory for the sparklines.
const POLL=5000,KEEP=60,QUOTA_POLL=300000;
const reason=error=>error?.status===404?'Сервер ещё не умеет это показывать. Обнови MediaVault на ВМ.':error?.message||'Нет ответа';
const share=(used,total)=>total?Math.min(1,Math.max(0,used/total)):0;
const tone=value=>value>=.9?'is-bad':value>=.75?'is-warn':'';
const percent=value=>Math.round(value*100)+'%';
const uptime=seconds=>seconds>=86400?Math.floor(seconds/86400)+' дн '+Math.floor(seconds%86400/3600)+' ч':duration(seconds);

function useSystem(service){
 const [system,setSystem]=useState(null),[history,setHistory]=useState([]),[error,setError]=useState('');
 const [quota,setQuota]=useState(null),[quotaError,setQuotaError]=useState('');
 const request=service?.request;
 useEffect(()=>{
  if(!request)return;let alive=true;
  const load=async()=>{if(document.visibilityState!=='visible')return;
   try{const value=await request('/admin/system');if(!alive)return;setSystem(value);setError('');
    const h=value.host||{},m=h.memory;
    setHistory(old=>[...old,{cpu:h.cpu,memory:m?m.used/m.total:null}].slice(-KEEP));}
   catch(cause){if(alive)setError(reason(cause));}};
  const drive=async()=>{try{const value=await request('/admin/drive-quota');if(alive){setQuota(value);setQuotaError('');}}catch(cause){if(alive)setQuotaError(reason(cause));}};
  load();drive();const timer=setInterval(load,POLL),slow=setInterval(drive,QUOTA_POLL);
  document.addEventListener('visibilitychange',load);
  return()=>{alive=false;clearInterval(timer);clearInterval(slow);document.removeEventListener('visibilitychange',load);};
 },[request]);
 return {system,history,error,quota,quotaError};
}

function Spark({values,label}){
 // The line spans the whole width from the first sample and gains detail as history fills.
 const points=values.map((v,i)=>v==null?null:[values.length>1?i/(values.length-1)*100:0,30-v*28]).filter(Boolean);
 if(points.length<2)return <svg className="cc-spark" viewBox="0 0 100 30" aria-hidden="true"/>;
 const line=points.map(([x,y])=>x.toFixed(2)+','+y.toFixed(2)).join(' ');
 return <svg className="cc-spark" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={label}>
  <polygon points={points[0][0].toFixed(2)+',30 '+line+' '+points[points.length-1][0].toFixed(2)+',30'}/><polyline points={line}/>
 </svg>;
}

function Space({label,used,total,detail,error}){
 const value=share(used,total);
 return <div className="cc-space">
  <span className="cc-health-label">{label}</span>
  {error?<p className="cc-hint">{error}</p>:total?<>
   <strong className={'cc-num '+tone(value)}>{bytes(total-used)} <small>свободно</small></strong>
   <i className="cc-meter" style={{'--share':value}} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value*100)} aria-label={label+': занято '+percent(value)}/>
   <span className="cc-health-detail">Занято {bytes(used)} из {bytes(total)}, {percent(value)}{detail?'. '+detail:''}</span>
  </>:<p className="cc-hint">Загружаем…</p>}
 </div>;
}

export default function SystemPanel({service}){
 const {system,history,error,quota,quotaError}=useSystem(service);
 const host=system?.host||{},memory=host.memory,disk=host.disk,root=system?.hostDisk;
 const cpu=host.cpu,load=host.load,cores=host.cores||1;
 const unlimited=quota&&!quota.limit;
 return <div className="cc-system">
  <section aria-labelledby="cc-space-title">
   <div className="cc-section-head"><h2 id="cc-space-title">Место</h2></div>
   <div className="cc-space-grid">
    <Space label="Google Диск" used={quota?.usage} total={unlimited?0:quota?.limit} error={quotaError||(unlimited?'У аккаунта безлимитное хранилище.':'')}
     detail={quota&&quota.trash?'В корзине '+bytes(quota.trash):''}/>
    <Space label="Диск данных на ВМ" used={disk?.used} total={disk?.total} error={error&&!disk?error:''} detail="Здесь каталог, кэш и задания"/>
    {root&&root.total!==disk?.total&&<Space label="Системный диск ВМ" used={root.used} total={root.total} detail="Образы Docker и релизы"/>}
   </div>
  </section>
  <section aria-labelledby="cc-load-title">
   <div className="cc-section-head"><h2 id="cc-load-title">Нагрузка</h2>{system&&<span className="cc-hint">Обновляется каждые 5 секунд{host.uptime?', ВМ работает '+uptime(host.uptime):''}</span>}</div>
   {error&&!system?<p className="cc-error">{error}</p>:<div className="cc-load">
    <div className="cc-load-item"><span className="cc-health-label">Процессор, {cores} {cores===1?'ядро':cores<5?'ядра':'ядер'}</span>
     <strong className={'cc-num '+tone((cpu||0)/100)}>{cpu==null?'…':Math.round(cpu)+'%'}</strong>
     <Spark values={history.map(h=>h.cpu==null?null:h.cpu/100)} label="Загрузка процессора за 5 минут"/></div>
    <div className="cc-load-item"><span className="cc-health-label">Память</span>
     <strong className={'cc-num '+tone(memory?memory.used/memory.total:0)}>{memory?bytes(memory.used):'…'}{memory&&<small> из {bytes(memory.total)}</small>}</strong>
     <Spark values={history.map(h=>h.memory)} label="Занятая память за 5 минут"/></div>
    <div className="cc-load-item"><span className="cc-health-label">Средняя нагрузка, 1, 5 и 15 минут</span>
     <strong className={'cc-num '+tone((load?.[0]||0)/cores)}>{load?load.map(v=>v.toFixed(2)).join(' / '):'…'}</strong>
     <span className="cc-health-detail">{load?(load[0]<=cores?'Ядрам хватает работы без очереди':'Задач больше, чем ядер: часть ждёт'):''}{memory?.swapTotal?'. Подкачка '+bytes(memory.swapUsed)+' из '+bytes(memory.swapTotal):''}</span></div>
   </div>}
  </section>
  {system&&!system.available?<p className="cc-hint">Контейнеры и процессы ВМ появятся, когда на ВМ запущен сборщик <code>mediavault-host-status</code>.</p>:system&&<>
   {system.stale&&<p className="cc-error">Сборщик на ВМ не обновлял данные больше полутора минут.</p>}
   <section aria-labelledby="cc-containers-title">
    <div className="cc-section-head"><h2 id="cc-containers-title">Контейнеры</h2><span className="cc-hint">{system.containers.filter(c=>c.state==='running').length} из {system.containers.length} запущено</span></div>
    <div className="cc-table" role="table" aria-label="Контейнеры">
     <div role="row" className="cc-table-head"><span role="columnheader">Контейнер</span><span role="columnheader">Состояние</span><span role="columnheader">Процессор</span><span role="columnheader">Память</span></div>
     {system.containers.map(c=><div role="row" key={c.name}>
      <span role="cell"><strong>{c.name}</strong><small>{c.image}</small></span>
      <span role="cell" className={c.state==='running'?'':'is-warn'}>{c.status}</span>
      <span role="cell" className="cc-num">{c.cpu||'—'}</span>
      <span role="cell" className="cc-num">{c.memory?c.memory.split('/')[0].trim():'—'}{c.memoryPercent&&<small>{c.memoryPercent}</small>}</span>
     </div>)}
    </div>
   </section>
   <section aria-labelledby="cc-proc-title">
    <div className="cc-section-head"><h2 id="cc-proc-title">Самые нагруженные процессы</h2></div>
    <div className="cc-table is-proc" role="table" aria-label="Процессы">
     <div role="row" className="cc-table-head"><span role="columnheader">Процесс</span><span role="columnheader">Работает</span><span role="columnheader">Процессор</span><span role="columnheader">Память</span></div>
     {system.processes.map(p=><div role="row" key={p.pid}>
      <span role="cell"><strong>{p.command}</strong><small>PID {p.pid}, {p.user}</small></span>
      <span role="cell">{duration(p.elapsed)}</span>
      <span role="cell" className="cc-num">{p.cpu.toFixed(1)}%</span>
      <span role="cell" className="cc-num">{bytes(p.rss)}<small>{p.memory.toFixed(1)}%</small></span>
     </div>)}
    </div>
   </section>
  </>}
 </div>;
}
