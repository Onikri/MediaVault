import {useEffect,useRef,useState} from 'react';
import {Radio,Pause,LogIn,Eye,EyeOff,Camera,X,Crown,ChevronLeft} from 'lucide-react';
import {clock} from './player-runtime.js';
import Artwork from './Artwork.jsx';
import TypingField from './TypingField.jsx';
import './room-lobby.css';

const reduced=()=>typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp=(v,a=-1,b=1)=>Math.min(b,Math.max(a,v));

// Depth scene: pointer (or device tilt on phones) and scroll drive the art
// layers at different speeds. Values are written as CSS variables so React
// never re-renders on movement.
function useDepth(ref){
 useEffect(()=>{
  const node=ref.current;if(!node||reduced())return;
  let tx=0,ty=0,x=0,y=0,frame=0;
  const step=()=>{x+=(tx-x)*.075;y+=(ty-y)*.075;node.style.setProperty('--px',x.toFixed(4));node.style.setProperty('--py',y.toFixed(4));frame=Math.abs(tx-x)+Math.abs(ty-y)>.0008?requestAnimationFrame(step):0;};
  const aim=(a,b)=>{tx=clamp(a);ty=clamp(b);if(!frame)frame=requestAnimationFrame(step);};
  const move=e=>{if(e.pointerType==='mouse'||e.pointerType==='pen')aim(e.clientX/innerWidth*2-1,e.clientY/innerHeight*2-1);};
  const leave=()=>aim(0,0);
  const tilt=e=>{if(e.gamma!=null&&e.beta!=null)aim(e.gamma/28,(e.beta-40)/28);};
  const scroll=()=>node.style.setProperty('--scroll',String(Math.round(scrollY)));
  const touchOnly=!matchMedia('(pointer: fine)').matches,orientation=touchOnly&&typeof DeviceOrientationEvent!=='undefined'&&typeof DeviceOrientationEvent.requestPermission!=='function';
  addEventListener('pointermove',move,{passive:true});document.documentElement.addEventListener('pointerleave',leave);addEventListener('scroll',scroll,{passive:true});if(orientation)addEventListener('deviceorientation',tilt);
  return()=>{cancelAnimationFrame(frame);removeEventListener('pointermove',move);document.documentElement.removeEventListener('pointerleave',leave);removeEventListener('scroll',scroll);removeEventListener('deviceorientation',tilt);};
 },[]);
}

// The room preview is polled every few seconds; between polls the position
// advances locally so the timeline shows where the group actually is.
function useLivePosition(preview){
 const [now,setNow]=useState(()=>performance.now()),received=useRef({at:performance.now(),preview});
 if(received.current.preview!==preview)received.current={at:performance.now(),preview};
 useEffect(()=>{if(!preview?.playing)return;const timer=setInterval(()=>setNow(performance.now()),1000);return()=>clearInterval(timer);},[preview?.playing]);
 if(!preview?.duration)return 0;
 const elapsed=preview.playing?Math.max(0,(now-received.current.at)/1000):0;
 return Math.min(preview.duration,(preview.position||0)+elapsed);
}

function plural(n,one,few,many){const a=n%10,b=n%100;return a===1&&b!==11?one:a>=2&&a<=4&&(b<10||b>=20)?few:many;}

// The photo is cropped to a square and re-encoded in the browser, so the
// server only ever receives a small WebP/JPEG, never the original file.
export async function guestPhoto(file){
 if(!file||!/^image\//.test(file.type))throw Error('Выбери фото или картинку.');
 if(file.size>20*1024*1024)throw Error('Файл больше 20 МБ.');
 const bitmap=await createImageBitmap(file),size=160,canvas=document.createElement('canvas'),side=Math.min(bitmap.width,bitmap.height);
 canvas.width=canvas.height=size;canvas.getContext('2d').drawImage(bitmap,(bitmap.width-side)/2,(bitmap.height-side)/2,side,side,0,0,size,size);bitmap.close?.();
 for(const quality of [.86,.74,.6,.46])for(const type of ['image/webp','image/jpeg']){
  const url=canvas.toDataURL(type,quality);if(!url.startsWith('data:'+type+';'))continue;
  if(url.length*.75<30*1024)return url;break;
 }
 throw Error('Не получилось сжать фото.');
}

function PhotoPicker({avatar,setAvatar,name}){
 const input=useRef(null),[error,setError]=useState('');
 async function choose(e){const file=e.target.files?.[0];e.target.value='';if(!file)return;setError('');try{setAvatar(await guestPhoto(file));}catch(x){setError(x.message);}}
 return <div className="room-lobby-photo">
  <button type="button" className={'room-lobby-photo-face'+(avatar?' has-photo':'')} onClick={()=>input.current?.click()} aria-label={avatar?'Сменить фото':'Добавить фото'}>
   {avatar?<img key={avatar.length} src={avatar} alt=""/>:<Camera size={22}/>}
  </button>
  <div className="room-lobby-photo-copy">
   <strong>{name.trim()?name.trim()+', тебя ждут':'Как тебя представить?'}</strong>
   <span>{avatar?<><button type="button" className="text-link" onClick={()=>input.current?.click()}>Сменить фото</button><button type="button" className="text-link" onClick={()=>setAvatar('')}><X size={13}/>Убрать</button></>:<button type="button" className="text-link" onClick={()=>input.current?.click()}>Добавить фото</button>}</span>
   {error&&<small role="alert">{error}</small>}
  </div>
  <input ref={input} type="file" accept="image/*" hidden onChange={choose}/>
 </div>;
}

function People({preview,server,name,avatar}){
 const people=preview?.people||(preview?.names||[]).map(n=>({name:n})),me=name.trim()||avatar;
 if(!people.length&&!me)return null;
 const src=v=>v?(v.startsWith('/')?server.replace(/\/$/,'')+v:v):'';
 return <ul className="room-lobby-people" aria-label="Кто в комнате">
  {people.map((p,i)=><li key={i} style={{'--i':i}}>{p.avatar&&<img src={src(p.avatar)} alt=""/>}<span>{p.name}</span>{p.host&&<Crown size={13} aria-label="создатель"/>}</li>)}
  {me&&<li className="is-me">{avatar&&<img src={avatar} alt=""/>}<span>{name.trim()||'Ты'}</span><small>ты</small></li>}
 </ul>;
}

export default function RoomLobby({preview,profile,server,name,setName,password,setPassword,avatar,setAvatar,busy,error,leaving,onJoin}){
 const root=useRef(null),form=useRef(null),keyImage=useRef(null);
 const [lit,setLit]=useState(false),[posterReady,setPosterReady]=useState(false),[reveal,setReveal]=useState(false),[frame,setFrame]=useState(-1),[seen,setSeen]=useState(()=>new Set());
 useDepth(root);
 const g=profile||{},title=g.title||preview?.title||'Комната просмотра',duration=preview?.duration||0,position=useLivePosition(preview);
 const key=(g.backgrounds||[])[0]||(g.screenshots||[])[0]||g.background||g.cover||'',far=g.cover||key;
 const frames=(g.screenshots||[]).filter(v=>v!==key).slice(0,6);
 const facts=[g.year,g.format,g.episodes>1?g.episodes+' '+plural(g.episodes,'серия','серии','серий'):'',g.studios?.[0],...(g.genres||[]).slice(0,2)].filter(Boolean);
 // The entrance plays once, when the key art is decoded. Metadata or art that
 // is slow (or missing) must not keep the invitation hidden for long.
 useEffect(()=>{if(lit)return;if(key&&keyImage.current?.complete&&keyImage.current.naturalWidth)return setLit(true);const t=setTimeout(()=>setLit(true),key?2200:1200);return()=>clearTimeout(t);},[key,lit]);
 useEffect(()=>{if(!error||!form.current||reduced())return;form.current.animate([{transform:'translateX(0)'},{transform:'translateX(-9px)'},{transform:'translateX(7px)'},{transform:'translateX(-4px)'},{transform:'translateX(0)'}],{duration:380,easing:'cubic-bezier(.36,.07,.19,.97)'});},[error]);
 const shown=e=>{e.currentTarget.dataset.ready='';};
 // Frames under the title become the backdrop while hovered or focused.
 const pick=i=>{setFrame(i);if(i>=0&&!seen.has(i))setSeen(s=>new Set(s).add(i));};
 return <main ref={root} lang="ru" className={'room-lobby'+(lit?' is-lit':'')+(leaving?' is-leaving':'')+(frame>=0?' is-framed':'')} aria-busy={busy||undefined}>
  <div className="room-lobby-scene" aria-hidden="true">
   {far&&<img className="room-lobby-far" src={far} alt="" decoding="async" onLoad={shown}/>}
   {key&&<img ref={keyImage} className="room-lobby-key" src={key} alt="" decoding="async" onLoad={e=>{shown(e);setLit(true);}} onError={()=>setLit(true)}/>}
   {frames.map((src,i)=>seen.has(i)&&<img key={src} className={'room-lobby-key room-lobby-frame'+(frame===i?' is-active':'')} src={src} alt="" decoding="async" onLoad={shown}/>)}
   <div className="room-lobby-shade"/>
  </div>
  <div className="room-lobby-stage">
   <header className="room-lobby-bar">
    <a className="room-lobby-home" href={location.pathname+location.search}><ChevronLeft size={18}/>MediaVault</a>
    {preview&&<p className={'room-lobby-state'+(preview.playing?' is-playing':'')}>{preview.playing?<><Radio size={15}/>Сейчас смотрят</>:<><Pause size={15}/>На паузе</>}</p>}
   </header>

   <section className="room-lobby-show">
    <div className="room-lobby-poster-rise">
     <div className={'room-lobby-poster'+(posterReady||!g.cover?' is-ready':'')}>
      {g.cover?<img src={g.cover} alt={'Постер: '+title} onLoad={()=>setPosterReady(true)}/>:<Artwork kind="anime"/>}
     </div>
    </div>
    <div className="room-lobby-copy">
     <h1 className="room-lobby-title"><span>{title}</span></h1>
     {facts.length>0&&<ul className="room-lobby-facts">{facts.map(v=><li key={v}>{v}</li>)}</ul>}
     {g.description&&<p className="room-lobby-description">{g.description}</p>}
    </div>
   </section>

   <form ref={form} className="room-lobby-form" onSubmit={onJoin}>
    <PhotoPicker avatar={avatar} setAvatar={setAvatar} name={name}/>
    <label>Имя<TypingField aria-label="Имя в комнате" maxLength={40} value={name} onChange={e=>setName(e.target.value)} autoComplete="nickname" placeholder="Как тебя называть"/></label>
    <label>Пароль комнаты
     <span className="room-lobby-secret">
      <TypingField secret reveal={reveal} aria-label="Пароль комнаты" maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required/>
      <button type="button" className="room-lobby-eye" onClick={()=>setReveal(v=>!v)} aria-pressed={reveal} aria-label={reveal?'Скрыть пароль':'Показать пароль'} title={reveal?'Скрыть пароль':'Показать пароль'}>{reveal?<EyeOff size={18}/>:<Eye size={18}/>}</button>
     </span>
    </label>
    <p className="room-lobby-hint">Пароль знает тот, кто прислал ссылку.</p>
    <button className="btn btn-primary" disabled={busy||leaving||!password||!server}><LogIn size={17}/>{busy?'Подключаемся…':'Войти в комнату'}</button>
    {!server&&<p className="inline-error">Сервер не подключён. Открой ссылку в браузере, где подключён сервер MediaVault.</p>}
    {error&&<p className="inline-error" role="alert">{error}</p>}
   </form>

   <footer className="room-lobby-band">
    {duration>0&&<div className="room-lobby-timeline">
     <p><strong>{clock(position)}</strong><span>{clock(duration)}</span></p>
     <div className="room-lobby-track" role="progressbar" aria-label="Где сейчас комната" aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(position)} aria-valuetext={clock(position)+' из '+clock(duration)}><span style={{transform:`scaleX(${Math.min(1,position/duration)})`}}/><i style={{left:Math.min(100,position/duration*100)+'%'}}/></div>
    </div>}
    <People preview={preview} server={server} name={name} avatar={avatar}/>
    {frames.length>0&&<ul className="room-lobby-frames" onPointerLeave={()=>pick(-1)}>
     {frames.map((src,i)=><li key={src} style={{'--i':i}}><button type="button" aria-label={'Кадр '+(i+1)+' фоном'} aria-pressed={frame===i} onPointerEnter={()=>pick(i)} onFocus={()=>pick(i)} onBlur={()=>pick(-1)} onClick={()=>pick(frame===i?-1:i)}><img src={src} alt="" loading="lazy"/></button></li>)}
    </ul>}
   </footer>
  </div>
 </main>;
}
