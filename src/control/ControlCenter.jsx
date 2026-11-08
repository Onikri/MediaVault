import {useEffect,useMemo,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Clapperboard,Gauge,HardDrive,ListChecks,LogOut,Palette,Plug,RefreshCw,ShieldCheck,SlidersHorizontal,UserRound,UsersRound} from 'lucide-react';
import {useControlData,useNow,since,jobCounts} from './use-control-data.js';
import Overview from './Overview.jsx';
import RoomsPanel from './RoomsPanel.jsx';
import GuestsPanel from './GuestsPanel.jsx';
import TasksPanel from './TasksPanel.jsx';
import RulesPanel from './RulesPanel.jsx';
import SystemPanel from './SystemPanel.jsx';
import './control-center.css';

// The owner's control center and everyone's settings share one shell:
// a rail of sections grouped by what they manage, one header, one rhythm.
const GROUPS=[
 ['server','Сервер',[
  ['overview','Обзор',Gauge,'Что происходит на сервере прямо сейчас'],
  ['rooms','Комнаты',Clapperboard,'Совместный просмотр: кто в комнатах и что идёт'],
  ['guests','Гости',UsersRound,'Профили по приглашению, их доступ и активность'],
  ['tasks','Задачи',ListChecks,'Импорт и оформление библиотеки на ВМ'],
  ['rules','Правила',SlidersHorizontal,'Ограничения комнат и права новых гостей'],
 ]],
 ['data','Данные',[
  ['storage','Хранилище',HardDrive,'Место, нагрузка сервера, коллекция и Google Диск'],
  ['sources','Источники',Plug,'Каталоги, музыка и читалки, из которых берётся контент'],
 ]],
 ['personal','Личное',[
  ['account','Профиль',UserRound,'Вход, аватар и твоя коллекция'],
  ['appearance','Оформление',Palette,'Язык интерфейса, палитра и фон сайта'],
  ['privacy','Устройство',ShieldCheck,'Что этот браузер помнит и кому доверяет'],
 ]],
];
const ADMIN=new Set(['overview','rooms','guests','tasks','rules']),LIVE=new Set(['overview','rooms','guests']);

function Counter({value,tone}){
 const reduce=useReducedMotion();
 if(value==null||value===0)return null;
 return <AnimatePresence mode="popLayout" initial={false}><motion.b key={value} className={'cc-count'+(tone?' '+tone:'')} initial={reduce?false:{y:6,opacity:0}} animate={{y:0,opacity:1}} exit={reduce?undefined:{y:-6,opacity:0}} transition={{duration:.2}}>{value}</motion.b></AnimatePresence>;
}

export default function ControlCenter({state,guest,service,initialTab,onLogout,panels,onOpenRoom}){
 const reduce=useReducedMotion(),admin=!!(state.admin&&state.user);
 const data=useControlData(service,admin);
 const groups=useMemo(()=>GROUPS.map(([id,label,items])=>[id,label,items.filter(([key])=>ADMIN.has(key)?admin:panels[key])]).filter(([,,items])=>items.length),[admin,panels]);
 const order=groups.flatMap(([,,items])=>items.map(([key])=>key));
 const first=order.includes(initialTab)?initialTab:order[0];
 const [tab,setTab]=useState(first),direction=useRef(1),content=useRef(null);
 useEffect(()=>{if(order.includes(initialTab))setTab(initialTab);},[initialTab]);
 useEffect(()=>{try{sessionStorage.setItem('mediavault_control_tab',tab);}catch{}},[tab]);
 const current=order.includes(tab)?tab:order[0];
 const meta=groups.flatMap(([,,items])=>items).find(([key])=>key===current);
 const now=useNow(5000);
 const jobs=jobCounts(service?.jobs);
 const live=Object.values(data.activity||{}).filter(s=>s.watching).length;
 const counts={rooms:data.rooms?.length,guests:live,tasks:jobs.running+jobs.queued+jobs.waiting};
 const tones={guests:'is-live',rooms:data.rooms?.some(r=>r.playing)?'is-live':'',tasks:jobs.waiting||jobs.failed?'is-warn':''};
 function choose(key,event){
  event?.currentTarget?.scrollIntoView?.({inline:'nearest',block:'nearest',behavior:reduce?'auto':'smooth'});
  if(key===current)return;
  direction.current=order.indexOf(key)>order.indexOf(current)?1:-1;setTab(key);
  if(content.current&&content.current.getBoundingClientRect().top<0)content.current.scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});
 }
 const name=state.user?.given_name||state.user?.name||guest?.guest?.name||'Гость';
 const role=admin?'Владелец':guest?'Гостевой профиль':state.user?'Зритель':'Вход не выполнен';
 const section=ADMIN.has(current)?{
  overview:<Overview data={data} service={service} onOpen={choose} onOpenRoom={onOpenRoom}/>,
  rooms:<RoomsPanel data={data} service={service} onOpenRoom={onOpenRoom} onRules={()=>choose('rules')}/>,
  guests:<GuestsPanel data={data} service={service}/>,
  tasks:<TasksPanel service={service}/>,
  rules:<RulesPanel service={service} onSaved={data.refresh}/>,
 }[current]:current==='storage'&&admin?<><SystemPanel service={service}/>{panels.storage}</>:panels[current];
 return <section className="cc" aria-label="Пульт и настройки">
  <aside className="cc-rail">
   <div className="cc-who"><strong>{name}</strong><span>{role}{state.user?.email?<small>{state.user.email}</small>:guest?<small>@{guest.guest.login}</small>:null}</span></div>
   <nav className="cc-nav" aria-label="Разделы">{groups.map(([id,label,items])=><div className="cc-group" key={id} role="group" aria-label={label}><span className="cc-group-label">{label}</span>
    {items.map(([key,text,Icon])=><button key={key} type="button" className="cc-link" aria-current={current===key?'page':undefined} onClick={event=>choose(key,event)}>
     {current===key&&<motion.span className="cc-link-active" layoutId="cc-link-active" transition={reduce?{duration:0}:{type:'spring',stiffness:520,damping:42}}/>}
     <Icon size={17} aria-hidden="true"/><span>{text}</span><Counter value={counts[key]} tone={tones[key]}/>
    </button>)}
   </div>)}</nav>
   {(state.user||guest)&&<button type="button" className="cc-exit" onClick={onLogout}><LogOut size={16}/>Выйти</button>}
  </aside>
  <div className="cc-main" ref={content}>
   <header className="cc-head">
    <AnimatePresence mode="wait" initial={false}><motion.div key={current} className="cc-title" initial={reduce?false:{opacity:0,y:direction.current*8}} animate={{opacity:1,y:0}} exit={reduce?undefined:{opacity:0,y:direction.current*-6}} transition={{duration:.18,ease:[.22,1,.36,1]}}>
     <h1>{meta?.[1]}</h1><p>{meta?.[3]}</p>
    </motion.div></AnimatePresence>
    {LIVE.has(current)&&data.connected&&<button type="button" className="cc-sync" onClick={data.refresh} disabled={data.loading} title="Данные обновляются каждые 15 секунд">
     <RefreshCw size={15}/><span>{data.updatedAt?'Обновлено '+since(data.updatedAt,now):'Загружаем…'}</span>
    </button>}
   </header>
   {ADMIN.has(current)&&!data.connected&&<p className="cc-offline" role="status">{service?.error||'Подключаемся к серверу MediaVault. Пульт оживёт, как только сервер ответит.'}</p>}
   <AnimatePresence mode="wait" initial={false}>
    <motion.div key={current} className="cc-body" initial={reduce?false:{opacity:0,y:direction.current*14}} animate={{opacity:1,y:0}} exit={reduce?undefined:{opacity:0,y:direction.current*-8,transition:{duration:.12}}} transition={{duration:.26,ease:[.22,1,.36,1]}}>
     {section}
    </motion.div>
   </AnimatePresence>
  </div>
 </section>;
}
