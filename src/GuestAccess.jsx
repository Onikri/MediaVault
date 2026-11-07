import {useEffect,useMemo,useState} from 'react';
import {motion,useMotionValue,useReducedMotion,useSpring,useTransform} from 'motion/react';
import {ArrowRight,Eye,EyeOff,LoaderCircle,X} from 'lucide-react';
import {enrollGuest,invitePreview,loginGuest} from './guest-session.js';
import './guest-access.css';

// Posters of the running season, used as the scene. Public metadata only.
function usePosters(){
 const [posters,setPosters]=useState([]);
 useEffect(()=>{const server=String(window.MEDIA_VAULT_CONFIG?.importServerUrl||'');if(!server)return;const abort=new AbortController();
  fetch(server+'/metadata/anime-home',{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(15000)])}).then(r=>r.ok?r.json():null).then(data=>{
   const rows=[...(data?.current||[]),...(data?.popular||[]),...(data?.top||[])].map(v=>v?.images?.webp?.large_image_url||v?.images?.jpg?.large_image_url).filter(url=>/^https:\/\/cdn\.myanimelist\.net\//.test(url||''));
   if(!abort.signal.aborted)setPosters([...new Set(rows)].slice(0,24));
  }).catch(()=>{});return()=>abort.abort();},[]);
 return posters;
}
function Wall({posters}){
 const reduce=useReducedMotion(),px=useMotionValue(0),py=useMotionValue(0),x=useSpring(px,{stiffness:60,damping:20}),y=useSpring(py,{stiffness:60,damping:20});
 const depth=[useTransform(x,v=>v*-18),useTransform(x,v=>v*-34),useTransform(x,v=>v*-52)],lift=[useTransform(y,v=>v*-12),useTransform(y,v=>v*-24),useTransform(y,v=>v*-38)];
 useEffect(()=>{if(reduce)return;const move=e=>{px.set(e.clientX/innerWidth-.5);py.set(e.clientY/innerHeight-.5);};addEventListener('pointermove',move);return()=>removeEventListener('pointermove',move);},[reduce]);
 const columns=useMemo(()=>{const list=posters.length?posters:Array(18).fill('');return [0,1,2,3,4,5].map(c=>list.filter((_,i)=>i%6===c));},[posters]);
 return <div className="guest-wall" aria-hidden="true">{columns.map((column,c)=>{const layer=c%3;return <motion.div key={c} className={'guest-wall-column depth-'+layer} style={reduce?undefined:{x:depth[layer],y:lift[layer]}}>
  {column.map((url,i)=>url?<img key={url} src={url} alt="" loading="lazy" referrerPolicy="no-referrer" style={{animationDelay:(c*.08+i*.12)+'s'}}/>:<span key={i}/>)}
 </motion.div>;})}</div>;
}
function Field({label,hint,type='text',value,onChange,autoComplete,autoFocus,minLength,maxLength,pattern}){
 const [shown,setShown]=useState(false),secret=type==='password';
 return <label className="guest-field"><span>{label}</span><span className="guest-input"><input type={secret&&!shown?'password':secret?'text':type} value={value} onChange={e=>onChange(e.target.value)} autoComplete={autoComplete} autoFocus={autoFocus} minLength={minLength} maxLength={maxLength} pattern={pattern} required spellCheck={false}/>{secret&&<button type="button" aria-label={shown?'Скрыть пароль':'Показать пароль'} onClick={()=>setShown(v=>!v)}>{shown?<EyeOff size={16}/>:<Eye size={16}/>}</button>}</span>{hint&&<small>{hint}</small>}</label>;
}
const date=value=>new Date(value*1000).toLocaleDateString('ru',{day:'numeric',month:'long',year:'numeric'});
export default function GuestAccess({mode,invite,onDone,onClose,onGoogle}){
 const posters=usePosters(),reduce=useReducedMotion();
 const [preview,setPreview]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [name,setName]=useState(''),[login,setLogin]=useState(''),[password,setPassword]=useState(''),[again,setAgain]=useState('');
 useEffect(()=>{if(mode!=='invite')return;setError('');invitePreview(invite).then(data=>{setPreview(data);setName(data.name||'');setLogin(data.login||'');}).catch(e=>setError(e.message));},[mode,invite]);
 async function submit(event){
  event.preventDefault();setError('');
  if(mode==='invite'&&password!==again){setError('Пароли не совпадают.');return;}
  setBusy(true);
  try{const session=mode==='invite'?await enrollGuest({invite,login:login.trim(),password,name:name.trim()||undefined}):await loginGuest({login:login.trim(),password});onDone?.(session);}
  catch(e){setError(e.message);}finally{setBusy(false);}
 }
 const invited=mode==='invite',ready=!invited||preview;
 return <div className="guest-access" role="dialog" aria-modal="true" aria-labelledby="guestAccessTitle">
  <Wall posters={posters}/>
  <div className="guest-shade"/>
  {onClose&&<button type="button" className="guest-close" aria-label="Закрыть" onClick={onClose}><X size={18}/></button>}
  <motion.form className="guest-card" onSubmit={submit} initial={reduce?false:{opacity:0,y:24,scale:.97}} animate={{opacity:1,y:0,scale:1}} transition={{duration:.7,ease:[.22,1,.36,1],delay:.15}}>
   <p className="guest-brand">Media<span>Vault</span></p>
   <h1 id="guestAccessTitle">{invited?(preview?.reset?'Новый пароль':preview?'Привет, '+preview.name+'!':'Приглашение'):'Вход для гостей'}</h1>
   <p className="guest-lead">{invited?(preview?.reset?'Владелец сбросил вход. Задай пароль заново — коллекция и история останутся на этом устройстве.':preview?'Тебя пригласили смотреть аниме, читать мангу и слушать музыку в MediaVault. Придумай логин и пароль — с ними ты сможешь входить снова.':error?'':'Проверяем приглашение…'):'Войди логином и паролем, которые ты задал по приглашению.'}</p>
   {invited&&preview&&<p className="guest-term">{preview.expiresAt?'Доступ открыт до '+date(preview.expiresAt):'Доступ без ограничения срока'}</p>}
   {ready&&<div className="guest-fields">
    {invited&&!preview?.reset&&<Field label="Как тебя называть" value={name} onChange={setName} autoComplete="nickname" maxLength={40}/>}
    <Field label="Логин" hint={invited?'Латиница, цифры, точка, дефис — от 3 символов':undefined} value={login} onChange={v=>setLogin(v.toLowerCase())} autoComplete="username" autoFocus={!invited} minLength={3} maxLength={32}/>
    <Field label="Пароль" type="password" hint={invited?'Не короче 8 символов':undefined} value={password} onChange={setPassword} autoComplete={invited?'new-password':'current-password'} minLength={invited?8:1} maxLength={128}/>
    {invited&&<Field label="Повтори пароль" type="password" value={again} onChange={setAgain} autoComplete="new-password" minLength={8} maxLength={128}/>}
   </div>}
   {error&&<p className="guest-error" role="alert">{error}</p>}
   {ready&&<button className="guest-submit" disabled={busy}>{busy?<LoaderCircle className="guest-spin" size={18}/>:<ArrowRight size={18}/>}{invited?(preview?.reset?'Сохранить пароль':'Создать профиль'):'Войти'}</button>}
   {!invited&&onGoogle&&<button type="button" className="guest-alt" onClick={onGoogle}>Я владелец — войти через Google</button>}
  </motion.form>
 </div>;
}
