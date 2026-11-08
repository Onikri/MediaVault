import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Copy,Search} from 'lucide-react';
import {CATEGORY_LABELS,EVENT_GROUPS,ago,bytes,clock,dayLabel,device,duration,eventTone,stamp} from './guest-activity-format.js';
import './guest-activity.css';
import {uiLocale} from './i18n/index.js';


function TrafficChart({days}){
 const [hover,setHover]=useState(null);
 const max=Math.max(1,...days.map(d=>d.bytes));
 const width=600,height=150,gap=2,bar=(width-gap*(days.length-1))/days.length;
 const tick=v=>{const t=new Date(v+'T00:00:00Z');return t.toLocaleDateString(uiLocale(),{day:'numeric',month:'short',timeZone:'UTC'});};
 const shown=hover==null?null:days[hover];
 return <figure className="guest-chart">
  <figcaption><span>Трафик по дням, 30 дней</span><strong>{shown?tick(shown.day)+': '+bytes(shown.bytes)+' · '+shown.requests+' запр.':'Наведи на столбец'}</strong></figcaption>
  <svg viewBox={`0 0 ${width} ${height+18}`} role="img" aria-label="Трафик гостя по дням за 30 дней" onPointerLeave={()=>setHover(null)}>
   <line x1="0" x2={width} y1={height} y2={height} className="guest-chart-base"/>
   {days.map((d,i)=>{const h=d.bytes?Math.max(3,d.bytes/max*(height-8)):0,x=i*(bar+gap);return <g key={d.day} onPointerEnter={()=>setHover(i)}>
    <rect x={x} y="0" width={bar+gap} height={height} fill="transparent"/>
    {h>0&&<path className={'guest-chart-bar'+(hover===i?' is-hover':'')} d={`M${x},${height}V${height-h+Math.min(4,h)}Q${x},${height-h} ${x+Math.min(4,bar/2)},${height-h}H${x+bar-Math.min(4,bar/2)}Q${x+bar},${height-h} ${x+bar},${height-h+Math.min(4,h)}V${height}Z`}/>}
   </g>;})}
   {[0,Math.floor(days.length/2),days.length-1].map(i=><text key={i} x={i*(bar+gap)+(i===days.length-1?bar:0)} y={height+14} textAnchor={i===0?'start':i===days.length-1?'end':'middle'} className="guest-chart-tick">{tick(days[i].day)}</text>)}
  </svg>
  <table className="sr-only"><caption>Трафик по дням</caption><tbody>{days.map(d=><tr key={d.day}><th>{d.day}</th><td>{bytes(d.bytes)}</td><td>{d.requests}</td></tr>)}</tbody></table>
 </figure>;
}

export function Overview({report}){
 const s=report.summary,cats=Object.entries(report.categories||{}).filter(([,v])=>v>0).sort((a,b)=>b[1]-a[1]),top=Math.max(1,...cats.map(([,v])=>v));
 const topTitles=[...report.titles].sort((a,b)=>b.bytes-a.bytes||b.opens-a.opens).slice(0,5);
 return <div className="guest-overview">
  <dl className="guest-stats">
   <div><dt>Сегодня</dt><dd>{bytes(s.bytesToday)}</dd></div>
   <div><dt>7 дней</dt><dd>{bytes(s.bytesWeek)}</dd></div>
   <div><dt>30 дней</dt><dd>{bytes(s.bytesMonth)}</dd></div>
   <div><dt>Всего</dt><dd>{bytes(s.bytes)}</dd></div>
   <div><dt>Запросов</dt><dd>{s.requests.toLocaleString(uiLocale())}</dd></div>
   <div><dt>Тайтлов</dt><dd>{s.titles}</dd></div>
   <div><dt>IP-адресов</dt><dd>{s.addresses}</dd></div>
  </dl>
  <TrafficChart days={report.days}/>
  <div className="guest-overview-columns">
   <section><h3>На что ушёл трафик</h3>{cats.length?<ul className="guest-bars">{cats.map(([k,v])=><li key={k}><span>{CATEGORY_LABELS[k]||k}</span><strong>{bytes(v)}</strong><i style={{'--share':v/top}}/></li>)}</ul>:<p className="fine">Трафика пока не было.</p>}</section>
   <section><h3>Больше всего смотрит</h3>{topTitles.length?<ol className="guest-top">{topTitles.map(t=><li key={t.key}><span>{t.title||'Без названия'}</span><small>{bytes(t.bytes)} · {t.opens} откр.</small></li>)}</ol>:<p className="fine">Ещё ничего не открывал.</p>}</section>
  </div>
  {s.lastAddress&&<p className="guest-last">Последний вход: <strong>{s.lastAddress}</strong> · {device(s.lastAgent)}</p>}
 </div>;
}

export function Titles({titles}){
 const [query,setQuery]=useState(''),[sort,setSort]=useState('last');
 const rows=useMemo(()=>titles.filter(t=>!query||t.title.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>sort==='bytes'?b.bytes-a.bytes:sort==='opens'?b.opens-a.opens:b.last-a.last),[titles,query,sort]);
 if(!titles.length)return <p className="fine guest-empty">Гость ещё не открывал тайтлы.</p>;
 return <div className="guest-tab-body">
  <div className="guest-tools"><label className="guest-search"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Найти тайтл" aria-label="Найти тайтл в активности"/></label>
   <div className="guest-segment" role="group" aria-label="Сортировка">{[['last','Недавние'],['bytes','По трафику'],['opens','По открытиям']].map(([id,l])=><button key={id} type="button" aria-pressed={sort===id} onClick={()=>setSort(id)}>{l}</button>)}</div></div>
  <div className="guest-table-wrap"><table className="guest-table">
   <thead><tr><th>Тайтл</th><th>Открыл</th><th>Запусков</th><th>Трафик</th><th>Последний раз</th></tr></thead>
   <tbody>{rows.map(t=><tr key={t.key}><td><div className="guest-title-cell">{t.cover&&<img src={t.cover} alt="" referrerPolicy="no-referrer"/>}<span><strong>{t.title||'Без названия'}</strong><small>{t.kind==='manga'?'Чтение':'Просмотр'}{t.mal?' · MAL '+t.mal:''} · впервые {stamp(t.first,false)}</small></span></div></td><td>{t.opens}</td><td>{t.plays}</td><td>{bytes(t.bytes)}</td><td title={stamp(t.last)}>{ago(t.last)}</td></tr>)}</tbody>
  </table></div>
  <p className="fine">Трафик видео и манги засчитывается тайтлу, который гость открыл последним.</p>
 </div>;
}

export function Addresses({addresses}){
 const [copied,setCopied]=useState('');
 if(!addresses.length)return <p className="fine guest-empty">Адресов пока нет.</p>;
 return <div className="guest-tab-body"><div className="guest-table-wrap"><table className="guest-table">
  <thead><tr><th>IP-адрес</th><th>Устройство</th><th>Впервые</th><th>Последний раз</th><th>Запросов</th><th>Трафик</th></tr></thead>
  <tbody>{addresses.map(a=><tr key={a.ip}><td><button type="button" className="guest-ip" onClick={()=>navigator.clipboard?.writeText(a.ip).then(()=>{setCopied(a.ip);setTimeout(()=>setCopied(''),1400);})} aria-label={'Скопировать '+a.ip}><code>{a.ip}</code><Copy size={12}/>{copied===a.ip&&<em>скопирован</em>}</button></td><td title={a.agent}>{device(a.agent)}</td><td>{stamp(a.first)}</td><td title={stamp(a.last)}>{ago(a.last)}</td><td>{a.requests.toLocaleString(uiLocale())}</td><td>{bytes(a.bytes)}</td></tr>)}</tbody>
 </table></div></div>;
}

export function Events({events}){
 const reduce=useReducedMotion(),[group,setGroup]=useState('all'),[query,setQuery]=useState(''),[limit,setLimit]=useState(80);
 const test=EVENT_GROUPS.find(g=>g[0]===group)?.[2];
 const rows=events.filter(e=>(!test||test(e.action))&&(!query||[e.action,e.title,e.ip,e.detail].join(' ').toLowerCase().includes(query.toLowerCase())));
 const days=[];for(const e of rows.slice(0,limit)){const label=dayLabel(e.t);if(days.at(-1)?.label!==label)days.push({label,items:[]});days.at(-1).items.push(e);}
 if(!events.length)return <p className="fine guest-empty">Журнал пуст.</p>;
 return <div className="guest-tab-body">
  <div className="guest-tools"><label className="guest-search"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Действие, тайтл или IP" aria-label="Поиск по журналу"/></label>
   <div className="guest-segment" role="group" aria-label="Тип событий">{EVENT_GROUPS.map(([id,l])=><button key={id} type="button" aria-pressed={group===id} onClick={()=>{setGroup(id);setLimit(80);}}>{l}</button>)}</div></div>
  {!rows.length&&<p className="fine guest-empty">Под фильтр ничего не попало.</p>}
  {days.map(d=><section key={d.label} className="guest-day"><h3>{d.label}</h3><ul className="guest-events">{d.items.map((e,i)=><motion.li key={e.t+':'+i} initial={reduce?false:{opacity:0,y:4}} animate={{opacity:1,y:0}}>
   <time dateTime={new Date(e.t*1000).toISOString()}>{clock(e.t)}</time>
   <div><strong className={eventTone(e.action)}>{e.action}</strong>{e.title&&<span className="guest-event-title">{e.title}</span>}{(e.ip||e.detail)&&<small>{[e.ip,e.detail&&(/Mozilla/.test(e.detail)?device(e.detail):e.detail)].filter(Boolean).join(' · ')}</small>}</div>
  </motion.li>)}</ul></section>)}
  {rows.length>limit&&<button type="button" className="btn btn-secondary btn-small guest-more" onClick={()=>setLimit(n=>n+120)}>Показать ещё ({rows.length-limit})</button>}
 </div>;
}

// Report for one guest, refreshed every 15 seconds while it is on screen.
export function useGuestReport(service,guest){
 const [report,setReport]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const alive=useRef(true);
 const load=useCallback(()=>{if(!guest)return Promise.resolve();setLoading(true);return service.request('/guests/'+guest.id+'/activity').then(d=>{if(alive.current){setReport(d);setError('');}}).catch(e=>{if(alive.current)setError(e.message);}).finally(()=>{if(alive.current)setLoading(false);});},[guest?.id,service.request]);
 useEffect(()=>{alive.current=true;setReport(null);setError('');if(!guest)return()=>{alive.current=false;};load();const timer=setInterval(()=>{if(document.visibilityState==='visible')load();},15000);return()=>{alive.current=false;clearInterval(timer);};},[guest?.id,load]);
 const clear=()=>service.request('/guests/'+guest.id+'/activity',{method:'DELETE'}).then(load).catch(e=>setError(e.message));
 return {report,error,loading,load,clear};
}
