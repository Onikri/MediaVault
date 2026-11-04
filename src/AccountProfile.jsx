import {useEffect,useState} from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import {UserRound,Palette,Plug,ShieldCheck,LogOut,Check,ChevronRight} from 'lucide-react';
import './account-profile.css';

// shadcn/ui's open Card + Radix Tabs composition, adapted to AniView tokens.
const sections=[['account','Аккаунт',UserRound],['appearance','Оформление',Palette],['connections','Подключения',Plug],['privacy','Устройство и доступ',ShieldCheck]];
export default function AccountProfile({state,panels,onLogout}){
 const [horizontal,setHorizontal]=useState(()=>matchMedia('(max-width:760px)').matches);
 useEffect(()=>{const query=matchMedia('(max-width:760px)'),update=()=>setHorizontal(query.matches);query.addEventListener('change',update);return()=>query.removeEventListener('change',update);},[]);
 const name=state.user?.given_name||'Мой профиль',initial=(state.user?.given_name||state.user?.email||'М').slice(0,1).toUpperCase();
 return <section className="account-page"><header className="account-heading"><div><p className="eyebrow">Настройки</p><h1>Профиль</h1></div><span className={'account-presence'+(state.user?' is-connected':'')}><i/>{state.user?'Вход выполнен':'Гостевой режим'}</span></header>
  <Tabs.Root defaultValue="account" className="account-layout" orientation={horizontal?'horizontal':'vertical'} activationMode="automatic">
   <aside className="account-sidebar"><div className="account-identity"><div className="account-avatar">{initial}</div><strong>{name}</strong><small>{state.user?.email||'Подключи Google для своей коллекции'}</small></div>
    <Tabs.List className="account-navigation" aria-label="Разделы профиля">{sections.map(([id,label,Icon])=><Tabs.Trigger key={id} value={id}><Icon size={17}/><span>{label}</span><ChevronRight size={13}/></Tabs.Trigger>)}</Tabs.List>
    <div className="account-services"><span><Check size={13}/>Настройки сохраняются на устройстве</span>{state.user&&<button onClick={onLogout}><LogOut size={15}/>Выйти из аккаунта</button>}</div>
   </aside>
   <div className="account-content">{sections.map(([id,label])=><Tabs.Content key={id} value={id} className="account-section" aria-label={label}>{panels[id]}</Tabs.Content>)}</div>
  </Tabs.Root>
 </section>;
}
