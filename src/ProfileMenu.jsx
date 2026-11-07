import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ChevronRight,Cloud,Download,History,LogIn,LogOut,Settings,UserPlus,UsersRound} from 'lucide-react';
import ProfileAvatar from './ProfileAvatar.jsx';
import './profile-menu.css';

// Compact account island under the avatar. The full profile page is only for settings.
export default function ProfileMenu({state,guest,importActive,onNavigate,onDownloads,onGuests,onLogin,onGuestLogin,onLogout}){
 const [open,setOpen]=useState(false),[box,setBox]=useState({right:16,top:72}),trigger=useRef(null),panel=useRef(null),reduce=useReducedMotion();
 useLayoutEffect(()=>{if(!open)return;const update=()=>{const r=trigger.current?.getBoundingClientRect();if(r)setBox({right:Math.max(12,innerWidth-r.right),top:r.bottom+10});};update();addEventListener('resize',update);addEventListener('scroll',update,true);return()=>{removeEventListener('resize',update);removeEventListener('scroll',update,true);};},[open]);
 useEffect(()=>{if(!open)return;const outside=e=>{if(!panel.current?.contains(e.target)&&!trigger.current?.contains(e.target))setOpen(false);};const key=e=>{if(e.key==='Escape'){setOpen(false);trigger.current?.focus();}};document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key);};},[open]);
 const go=fn=>()=>{setOpen(false);fn?.();};
 const user=state.user||(guest?{sub:'guest:'+guest.id,given_name:guest.name,name:guest.name,email:''}:null);
 const name=user?.given_name||user?.name||'Гость';
 const role=state.admin?'Владелец':guest?'Гостевой профиль':state.user?'Зритель':'Не выполнен вход';
 const until=guest?.expiresAt?'до '+new Date(guest.expiresAt*1000).toLocaleDateString('ru',{day:'numeric',month:'long'}):guest?'без срока':'';
 const items=[
  state.catalog&&{id:'collection',label:'Моя коллекция',icon:Cloud,run:()=>onNavigate('collection')},
  {id:'history',label:'История',icon:History,run:()=>onNavigate('history')},
  state.admin&&{id:'downloads',label:'Загрузки',icon:Download,run:onDownloads,live:importActive},
  state.admin&&{id:'guests',label:'Гостевые профили',icon:UsersRound,run:onGuests},
  {id:'settings',label:'Настройки',icon:Settings,run:()=>onNavigate('profile'),chevron:true},
 ].filter(Boolean);
 return <><button ref={trigger} id="profileBtn" className={'avatar-button'+(open?' nav-active':'')} onClick={()=>setOpen(v=>!v)} aria-haspopup="dialog" aria-expanded={open} aria-label="Профиль">{user?<ProfileAvatar user={user}/>:<UserIconFallback/>}</button>
 {createPortal(<AnimatePresence>{open&&<motion.section ref={panel} role="dialog" aria-label="Профиль" className="profile-menu" style={box} initial={reduce?false:{opacity:0,scale:.94,y:-4}} animate={{opacity:1,scale:1,y:0}} exit={reduce?{opacity:0}:{opacity:0,scale:.96}} transition={{type:'spring',stiffness:420,damping:34}}>
  <header className="profile-menu-identity">
   {user&&<ProfileAvatar user={user} className="profile-menu-avatar"/>}
   <div><strong>{user?name:'Ты не вошёл'}</strong><small>{user?(user.email||role):'Войди, чтобы смотреть онлайн и открыть коллекцию'}</small></div>
  </header>
  {(state.user||guest)&&<p className="profile-menu-role"><span>{role}</span>{until&&<span>{until}</span>}</p>}
  {!state.user&&!guest&&<div className="profile-menu-login">
   <button type="button" className="profile-menu-primary" onClick={go(onLogin)}><LogIn size={16}/>Войти через Google</button>
   <button type="button" className="profile-menu-secondary" onClick={go(onGuestLogin)}><UserPlus size={16}/>Вход по приглашению</button>
  </div>}
  <nav className="profile-menu-list" aria-label="Профиль">{items.map(item=><button type="button" key={item.id} onClick={go(item.run)}><item.icon size={17}/><span>{item.label}</span>{item.live&&<i className="profile-menu-live" aria-label="Идут загрузки"/>}{item.chevron&&<ChevronRight size={15}/>}</button>)}</nav>
  {(state.user||guest)&&<button type="button" className="profile-menu-exit" onClick={go(onLogout)}><LogOut size={16}/>Выйти</button>}
 </motion.section>}</AnimatePresence>,document.body)}</>;
}
function UserIconFallback(){return <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>;}
