import {useEffect,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowLeft,Ban,Check,Copy,Link2,RotateCcw,Trash2,UserPlus} from 'lucide-react';
import UiSelect from '../UiSelect.jsx';
import {inviteLink} from '../guest-session.js';
import GuestAccessEditor,{accessSummary} from '../GuestAccessEditor.jsx';
import {Addresses,Events,Overview as ActivityOverview,Titles,useGuestReport} from '../GuestActivity.jsx';
import {ago,bytes,duration} from '../guest-activity-format.js';
import {useNow} from './use-control-data.js';
import {uiLocale} from '../i18n/index.js';

const TERMS=[['1','1 день'],['7','7 дней'],['30','30 дней'],['90','3 месяца'],['365','Год'],['','Без срока']];
const EXTEND=[['7','На 7 дней'],['30','На 30 дней'],['90','На 3 месяца'],['365','На год'],['unlimited','Без срока']];
const date=value=>new Date(value*1000).toLocaleDateString(uiLocale(),{day:'numeric',month:'long',year:'numeric'});
function status(guest){
 if(guest.disabled)return ['Заблокирован','is-bad'];
 if(guest.expired)return ['Срок истёк','is-bad'];
 if(!guest.enrolled)return ['Ждёт регистрации','is-warn'];
 return ['Активен','is-ok'];
}
const doing=w=>(w.category==='manga'?'Читает':w.category==='music'?'Слушает':'Смотрит')+(w.title?' «'+w.title+'»':'');

function useWide(){
 const query='(min-width:1000px)';
 const [wide,setWide]=useState(()=>matchMedia(query).matches);
 useEffect(()=>{const m=matchMedia(query),u=()=>setWide(m.matches);m.addEventListener('change',u);return()=>m.removeEventListener('change',u);},[]);
 return wide;
}

function CopyLink({url}){
 const [copied,setCopied]=useState(false);
 return <div className="cc-invite"><span>{url}</span><button type="button" className="cc-button" onClick={()=>navigator.clipboard?.writeText(url).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),1600);})}>{copied?<Check size={15}/>:<Copy size={15}/>}{copied?'Скопировано':'Копировать'}</button></div>;
}

const TABS=[['overview','Обзор'],['titles','Тайтлы'],['addresses','IP и устройства'],['events','Журнал'],['access','Доступ']];

function GuestDetail({guest,stats,service,link,busy,onChange,onReinvite,onRemove,onBack}){
 const reduce=useReducedMotion(),now=useNow(5000);
 const [tab,setTab]=useState('overview'),[removing,setRemoving]=useState(false);
 const {report,error,clear}=useGuestReport(service,guest);
 useEffect(()=>{setTab('overview');setRemoving(false);},[guest.id]);
 const [label,tone]=status(guest),w=stats?.watching;
 return <article className="cc-guest-detail" aria-label={'Гость '+guest.name}>
  {onBack&&<button type="button" className="cc-text-button cc-back" onClick={onBack}><ArrowLeft size={15}/>Все гости</button>}
  <header className="cc-guest-head">
   <div>
    <h2>{guest.name}</h2>
    <p><span className={'cc-word '+tone}>{label}</span>{guest.login?<span>@{guest.login}</span>:<span>логин ещё не выбран</span>}<span>{guest.expiresAt?(guest.expired?'истёк ':'до ')+date(guest.expiresAt):'без срока'}</span></p>
    <p className="cc-guest-now" role="status">{w?<><strong className="is-live">{doing(w)}</strong> уже {duration(now/1000-w.since)}</>:stats?.lastActive?'Был в сети '+ago(stats.lastActive):'Ещё не заходил'}</p>
   </div>
   <div className="cc-guest-actions">
    <UiSelect aria-label={'Продлить доступ: '+guest.name} value="" onChange={e=>{const v=e.target.value;if(v==='unlimited')onChange(guest,{unlimited:true});else if(v)onChange(guest,{days:Number(v)});}}><option value="">Продлить…</option>{EXTEND.map(([v,l])=><option key={v} value={v}>{l}</option>)}</UiSelect>
    <button type="button" className="cc-button" disabled={busy} onClick={()=>onReinvite(guest)}><Link2 size={15}/>{guest.enrolled?'Ссылка для нового пароля':'Новая ссылка'}</button>
    <button type="button" className="cc-button" disabled={busy} onClick={()=>onChange(guest,{disabled:!guest.disabled})}>{guest.disabled?<RotateCcw size={15}/>:<Ban size={15}/>}{guest.disabled?'Разблокировать':'Заблокировать'}</button>
    {removing?<span className="cc-confirm"><button type="button" className="cc-button is-danger" disabled={busy} onClick={()=>onRemove(guest)}>Удалить навсегда</button><button type="button" className="cc-button" onClick={()=>setRemoving(false)}>Отмена</button></span>
     :<button type="button" className="cc-button is-quiet-danger" disabled={busy} onClick={()=>setRemoving(true)} aria-label={'Удалить профиль '+guest.name}><Trash2 size={15}/></button>}
   </div>
  </header>
  {link&&<CopyLink url={link}/>}
  <nav className="cc-tabs" role="tablist" aria-label="Сведения о госте">{TABS.map(([id,l])=><button key={id} role="tab" type="button" aria-selected={tab===id} onClick={()=>setTab(id)}>
   {tab===id&&<motion.span className="cc-tab-active" layoutId="cc-guest-tab" transition={reduce?{duration:0}:{type:'spring',stiffness:480,damping:38}}/>}
   <span>{l}{id==='titles'&&report?<small>{report.titles.length}</small>:id==='addresses'&&report?<small>{report.addresses.length}</small>:id==='access'?<small>{guest.access?.scope==='titles'?guest.access.titles.length:'все'}</small>:null}</span>
  </button>)}</nav>
  {error&&<p className="cc-error" role="alert">{error}</p>}
  <AnimatePresence mode="wait" initial={false}><motion.div key={tab} className="cc-tab-body" initial={reduce?false:{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={reduce?undefined:{opacity:0}} transition={{duration:.16}}>
   {tab==='access'?<div className="cc-access"><p className="cc-hint">Сейчас: {accessSummary(guest.access)}.</p><GuestAccessEditor guest={guest} busy={busy} onSave={access=>onChange(guest,{access})}/></div>
   :!report?(!error&&<p className="cc-hint">Загружаем активность…</p>)
   :tab==='overview'?<ActivityOverview report={report}/>:tab==='titles'?<Titles titles={report.titles}/>:tab==='addresses'?<Addresses addresses={report.addresses}/>:<Events events={report.events}/>}
  </motion.div></AnimatePresence>
  {report&&tab!=='access'&&<footer className="cc-guest-foot"><span className="cc-hint">Записываются только действия гостя на твоём сервере.</span><button type="button" className="cc-text-button" onClick={()=>{if(confirm('Очистить журнал и статистику гостя «'+guest.name+'»? Это нельзя отменить.'))clear().then(load);}}>Очистить журнал</button></footer>}
 </article>;
}

export default function GuestsPanel({data,service}){
 const reduce=useReducedMotion(),wide=useWide();
 const [name,setName]=useState(''),[term,setTerm]=useState('30'),[busy,setBusy]=useState(''),[error,setError]=useState(''),[links,setLinks]=useState({}),[selected,setSelected]=useState(null);
 useEffect(()=>{service.request('/admin/rules').then(v=>setTerm(v.rules?.guests?.days?String(v.rules.guests.days):'')).catch(()=>{});},[service.request]);
 const guests=data.guests,activity=data.activity||{};
 if(!guests)return data.errors.guests?<p className="cc-error" role="alert">{data.errors.guests}</p>:<p className="cc-hint">Загружаем гостей…</p>;
 const shown=guests.find(g=>g.id===selected)||(wide?guests[0]:null);
 async function run(key,work){setBusy(key);setError('');try{await work();await data.refresh();}catch(e){setError(e.message);}finally{setBusy('');}}
 const create=event=>{event.preventDefault();if(!name.trim())return;run('create',async()=>{const d=await service.request('/guests',{method:'POST',body:{name:name.trim(),...(term?{days:Number(term)}:{})}});setLinks(v=>({...v,[d.guest.id]:inviteLink(d.invite)}));setName('');setSelected(d.guest.id);});};
 const change=(guest,body)=>run(guest.id,()=>service.request('/guests/'+guest.id,{method:'POST',body}));
 const reinvite=guest=>run(guest.id,async()=>{const d=await service.request('/guests/'+guest.id+'/invite',{method:'POST'});setLinks(v=>({...v,[guest.id]:inviteLink(d.invite)}));});
 const remove=guest=>run(guest.id,async()=>{await service.request('/guests/'+guest.id,{method:'DELETE'});setSelected(null);});
 const ordered=[...guests].sort((a,b)=>Number(!!activity[b.id]?.watching)-Number(!!activity[a.id]?.watching));
 return <div className={'cc-guests'+(shown&&!wide?' is-detail':'')}>
  <div className="cc-guest-index">
   <form className="cc-guest-create" onSubmit={create}>
    <label className="cc-field"><span>Имя гостя</span><input className="field-input" value={name} onChange={e=>setName(e.target.value)} maxLength={40} placeholder="Например, Аня" required/></label>
    <label className="cc-field"><span>Срок</span><UiSelect aria-label="Срок доступа" value={term} onChange={e=>setTerm(e.target.value)}>{TERMS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</UiSelect></label>
    <button className="btn btn-primary" disabled={busy==='create'||!name.trim()}><UserPlus size={17}/>Пригласить</button>
    <p className="cc-hint">Гость получит ссылку и сам задаст логин и пароль. Коллекцию на Google Диске и загрузки гости не видят.</p>
   </form>
   {error&&<p className="cc-error" role="alert">{error}</p>}
   {!guests.length?<p className="cc-hint">Гостей пока нет. Пригласи первого — ссылка появится здесь.</p>:
   <ul className="cc-guest-list" aria-label="Гости">{ordered.map(guest=>{const [label,tone]=status(guest),s=activity[guest.id];return <motion.li key={guest.id} layout={!reduce} transition={{duration:.25}}>
    <button type="button" aria-current={shown?.id===guest.id?'true':undefined} onClick={()=>setSelected(guest.id)}>
     {shown?.id===guest.id&&<motion.span className="cc-row-active" layoutId="cc-guest-row" transition={reduce?{duration:0}:{type:'spring',stiffness:520,damping:42}}/>}
     <span className="cc-guest-line"><strong>{guest.name}</strong>{s?.bytesMonth>0&&<small className="cc-num">{bytes(s.bytesMonth)}</small>}</span>
     <span className="cc-guest-sub">{s?.watching?<span className="is-live">{doing(s.watching)}</span>:<><span className={tone}>{label}</span>{s?.lastActive?<span>{ago(s.lastActive)}</span>:null}</>}</span>
    </button>
   </motion.li>;})}</ul>}
  </div>
  <AnimatePresence mode="wait" initial={false}>{shown&&<motion.div key={shown.id} className="cc-guest-pane" initial={reduce?false:{opacity:0,x:wide?12:24}} animate={{opacity:1,x:0}} exit={reduce?undefined:{opacity:0,x:wide?-8:-16}} transition={{duration:.22,ease:[.22,1,.36,1]}}>
   <GuestDetail guest={shown} stats={activity[shown.id]} service={service} link={links[shown.id]} busy={busy===shown.id} onChange={change} onReinvite={reinvite} onRemove={remove} onBack={wide?null:()=>setSelected(null)}/>
  </motion.div>}</AnimatePresence>
 </div>;
}
