import {createContext,useContext,useEffect,useLayoutEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {AppWindow,ArrowUpRight,BookOpen,History,Minimize2,Pause,PictureInPicture2,Play,Video,X} from 'lucide-react';
import {floatingWindowSupported,openFloatingWindow} from './floating-window.js';
import {createRetainedMediaStore} from './retained-media-store.js';
import './retained-media.css';
const POPUP_WIDTH='mediavault_popup_width';
const Workspace=createContext(null),Owner=createContext(null);
export function useRetainedWorkspace(){return useContext(Workspace);}
export function useRetainedMedia(active,descriptor,onStop){
 const owner=useContext(Owner),live=useRef(onStop);live.current=onStop;
 useLayoutEffect(()=>{if(owner)owner.store.owner(owner.id,()=>live.current?.());},[owner?.id]);
 useEffect(()=>{if(!owner)return;if(active)owner.store.activate(owner.id,descriptor);else owner.store.deactivate(owner.id);},[owner?.id,!!active,descriptor?.label,descriptor?.kind]);
 return owner?.mode||'attached';
}
// A retained reader reports its own state to the tray: {playing, toggle}.
export function useRetainedReport(){
 const owner=useContext(Owner);
 return useMemo(()=>owner?change=>owner.store.media(owner.id,change):()=>{},[owner?.id,owner?.store]);
}
export function RetainedMediaProvider({children}){
 const [store]=useState(createRetainedMediaStore),snapshot=useSyncExternalStore(store.subscribe,store.getSnapshot);
 useEffect(()=>{const close=()=>store.clear();addEventListener('mediavault-locked',close);return()=>{removeEventListener('mediavault-locked',close);store.clear();};},[store]);
 return <Workspace.Provider value={store}>{children}{createPortal(snapshot.rows.map(row=><RetainedHost key={row.id} row={row} store={store} popup={snapshot.popup===row.id} active={snapshot.active===row.id}/>),document.body)}</Workspace.Provider>;
}
// overlay: the media covers the screen itself (a full-screen reader), so the
// slot takes no room in the page. data: what a page needs to show it again.
export function RetainedMediaSlot({id,label,kind='video',userId,resumeItemId,restore,overlay=false,data,children}){
 const store=useContext(Workspace),anchor=useRef(null),live=useRef({label,kind,userId,resumeItemId,restore,data});live.current={label,kind,userId,resumeItemId,restore,data};
 useLayoutEffect(()=>{if(!store)return;store.attach(id,{...live.current,route:location.hash||'#home'},anchor.current,children);},[store,id,children]);
 useLayoutEffect(()=>{if(!store)return;const node=anchor.current;return()=>store.detach(id,node);},[store,id]);
 if(!store)return children;
 return <div ref={anchor} className={'retained-media-slot is-'+kind+(overlay?' is-overlay':'')} data-retained-slot={id}/>;
}
function RetainedHost({row,store,popup,active}){
 const root=useRef(null),[box,setBox]=useState({position:'absolute',top:0,left:0,width:900}),attached=!!row.anchor?.isConnected,mode=popup&&active?'popup':attached?'attached':'hidden';
 const owner=useMemo(()=>({id:row.id,store,mode}),[row.id,store,mode]);
 useLayoutEffect(()=>{row.host=root.current;let frame=0,follow=performance.now()+550;
  const update=()=>{frame=0;const node=root.current,anchor=row.anchor;if(!node)return;
   if(mode==='attached'&&anchor?.isConnected){const r=anchor.getBoundingClientRect(),height=Math.ceil(node.getBoundingClientRect().height);if(height>20&&Math.abs(anchor.offsetHeight-height)>1)anchor.style.height=height+'px';const theater=!!node.querySelector('.mv-player.is-theater');const next=theater?{position:'fixed',left:16,top:Math.max(12,document.querySelector('.kt-nav-inner')?.getBoundingClientRect().bottom+12||12),width:innerWidth-32}:{position:'absolute',left:r.left+scrollX,top:r.top+scrollY,width:r.width};setBox(old=>Object.keys(next).every(k=>Math.abs(old[k]-next[k])<.3||old[k]===next[k])?old:next);
    if(row.wantReturn){row.wantReturn=false;requestAnimationFrame(()=>{const media=node.querySelector('.mv-player,.immersive-reader')||node,p=media.getBoundingClientRect(),header=document.querySelector('.kt-nav-inner')?.getBoundingClientRect().bottom||0;scrollTo({top:Math.max(0,scrollY+p.top-Math.max(header+12,(innerHeight-p.height)/2)),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});});}
   }
   if(performance.now()<follow&&mode==='attached')frame=requestAnimationFrame(update);
  };
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(update);};update();const resize=new ResizeObserver(schedule);if(row.anchor)resize.observe(row.anchor);if(root.current)resize.observe(root.current);const mutate=new MutationObserver(schedule);if(root.current)mutate.observe(root.current,{subtree:true,attributes:true,attributeFilter:['class']});addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule);return()=>{cancelAnimationFrame(frame);resize.disconnect();mutate.disconnect();removeEventListener('scroll',schedule);removeEventListener('resize',schedule);};
 },[row.anchor,mode]);
 // The mini window keeps the width you drag it to, on this device.
 const [popupWidth,setPopupWidth]=useState(()=>{try{return Number(localStorage.getItem(POPUP_WIDTH))||0;}catch{return 0;}});
 function resize(event){event.preventDefault();const node=root.current;if(!node)return;const startX=event.clientX,startY=event.clientY,start=node.getBoundingClientRect().width;let width=start;
  const move=e=>{const dx=startX-e.clientX,dy=(startY-e.clientY)*16/9;width=Math.round(Math.max(260,Math.min(innerWidth-24,start+Math.max(dx,dy))));node.style.width=width+'px';};
  const up=()=>{removeEventListener('pointermove',move);removeEventListener('pointerup',up);setPopupWidth(width);try{localStorage.setItem(POPUP_WIDTH,String(width));}catch{}};
  addEventListener('pointermove',move);addEventListener('pointerup',up);}
 function media(event){const v=event.target;if(!v.matches?.('video.mv-player-media'))return;if(event.type==='timeupdate'&&Math.abs((row.time||0)-v.currentTime)<1)return;const change={playing:!v.paused,time:v.currentTime,duration:Number.isFinite(v.duration)?v.duration:0};if(!row.preview&&v.readyState>=2)try{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;canvas.getContext('2d').drawImage(v,0,0,160,90);change.preview=canvas.toDataURL('image/jpeg',.65);}catch{}store.media(row.id,change);}
 return <div ref={root} className="retained-media-host" data-mode={mode} data-session={row.id} style={mode==='attached'?box:mode==='popup'&&popupWidth?{width:Math.min(popupWidth,innerWidth-24)}:undefined} inert={mode==='hidden'} aria-hidden={mode==='hidden'} onPlayCapture={media} onPauseCapture={media} onTimeUpdateCapture={media} onLoadedDataCapture={media}>
 {mode==='popup'&&<span className="retained-popup-resize" aria-hidden="true" title="Потяни, чтобы изменить размер" onPointerDown={resize}/>}
 {mode==='popup'&&<div className="retained-popup-heading"><strong>{row.label}</strong>{row.kind!=='reader'&&floatingWindowSupported()&&<button aria-label="Окно поверх всех окон" title="Окно поверх всех окон" onClick={()=>openFloatingWindow(root.current,{title:row.label}).catch(()=>{})}><AppWindow size={15}/></button>}<button aria-label="Вернуться к просмотру на странице" onClick={()=>store.return(row.id)}><ArrowUpRight size={16}/></button><button aria-label="Свернуть мини-просмотр" title="Свернуть — продолжит в фоне" onClick={()=>store.popup(row.id)}><Minimize2 size={15}/></button><button className="is-close" aria-label={row.kind==='reader'?'Закрыть читалку':'Закрыть просмотр'} title="Закрыть" onClick={()=>store.close(row.id)}><X size={16}/></button></div>}
 <Owner.Provider value={owner}>{row.node}</Owner.Provider></div>;
}
export function VideoDock(){
 const store=useContext(Workspace);if(!store)return null;return <Dock store={store}/>;
}
function Dock({store}){
 const state=useSyncExternalStore(store.subscribe,store.getSnapshot),active=state.rows.find(r=>r.id===state.active),[open,setOpen]=useState(false),trigger=useRef(null),panel=useRef(null),[box,setBox]=useState({right:16,top:70}),reduced=useReducedMotion();
 useEffect(()=>{if(!open)return;const update=()=>{const r=trigger.current?.getBoundingClientRect();if(r)setBox({right:Math.max(12,innerWidth-r.right),top:r.bottom+12});};update();addEventListener('resize',update);addEventListener('scroll',update,true);const outside=e=>{if(!panel.current?.contains(e.target)&&!trigger.current?.contains(e.target))setOpen(false);};const key=e=>{if(e.key==='Escape'){setOpen(false);trigger.current?.focus();}};document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);return()=>{removeEventListener('resize',update);removeEventListener('scroll',update,true);document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key);};},[open]);
 if(!active&&!state.history.length)return null;
 const toggle=()=>{if(active?.toggle){active.toggle();return;}const video=active?.host?.querySelector('video.mv-player-media');if(video){if(video.paused)video.play().catch(()=>{});else video.pause();}};
 const recent=state.history.filter(item=>item.id!==active?.id).slice(0,6);
 // A reader with a voice plays like any other media: pause and resume from the tray.
 const voiced=active?.kind==='reader'&&!!active.toggle,playing=!!active?.playing&&(active?.kind!=='reader'||voiced),progress=active?.duration?Math.min(1,(active.time||0)/active.duration):0;
 const clock=v=>{v=Math.max(0,Math.floor(v||0));const h=Math.floor(v/3600),m=Math.floor(v%3600/60),s=String(v%60).padStart(2,'0');return h?h+':'+String(m).padStart(2,'0')+':'+s:m+':'+s;};
 // The tray of the design: a glass circle in the bar; its panel grows out of it
 // with the frame, a big pause, a thin progress line and the recent places.
 const circle='retained-dock relative w-9 h-9 min-w-0 flex-none bg-transparent grid place-items-center rounded-full bg-gradient-to-b from-white/[0.08] to-white/[0.02] border border-white/[0.07] shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] text-zinc-300 hover:text-white hover:from-white/[0.14] aria-expanded:text-white aria-expanded:from-white/[0.14] transition-colors';
 const eq=<span className="flex items-end gap-[2px] h-3.5" aria-hidden="true">{[0,1,2].map(b=><span key={b} className="w-[3px] h-full rounded-full bg-rose-400" style={{animation:`mvEq .8s ${b*.14}s ease-in-out infinite alternate`}}/>)}</span>;
 const round='grid place-items-center w-10 h-10 shrink-0 rounded-full bg-white/[0.06] border border-white/[0.08] text-zinc-300 hover:text-white hover:bg-white/[0.12] transition-colors';
 return <div className="mv-tw" style={{display:'contents'}}><button ref={trigger} className={circle+(active?' is-live':'')+(playing?' is-playing':'')} title={active?.label||'История просмотра'} aria-label="Плеер в фоне" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>{playing?eq:active?.kind==='reader'?<BookOpen size={17}/>:<Video size={17}/>}{active&&!playing&&<span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 w-3 h-[2px] rounded-full bg-rose-500" aria-hidden="true"/>}</button>{createPortal(<div className="mv-tw" style={{display:'contents'}}><AnimatePresence>{open&&<motion.section ref={panel} role="dialog" aria-label={active?'Сейчас в фоне':'Недавний просмотр'}
  className="retained-dock-panel fixed p-0 max-h-none overflow-hidden w-[min(340px,calc(100vw-24px))] rounded-[26px] border border-white/[0.08] bg-[#12080d]/[0.82] backdrop-blur-2xl backdrop-saturate-150 shadow-[inset_0_1px_0_rgba(255,255,255,0.07),0_30px_70px_-24px_rgba(0,0,0,0.95)] overflow-hidden text-white origin-top-right"
  style={{...box,zIndex:1150}} initial={reduced?{opacity:0}:{opacity:0,y:-10,scale:.94,filter:'blur(6px)'}} animate={{opacity:1,y:0,scale:1,filter:'blur(0px)'}} exit={reduced?{opacity:0}:{opacity:0,y:-8,scale:.96,filter:'blur(4px)'}} transition={reduced?{duration:0}:{type:'spring',stiffness:420,damping:34,mass:.8}}>
  <span aria-hidden="true" className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-rose-400/40 to-transparent"/>
  <div className="p-3.5 flex flex-col gap-3 max-h-[min(640px,calc(100vh-96px))] overflow-y-auto overscroll-contain [scrollbar-width:thin]">
  {active&&<div className="flex flex-col gap-3">
   <div className="group relative aspect-video rounded-2xl overflow-hidden bg-white/[0.04] border border-white/[0.06]">{active.preview?<img src={active.preview} alt="" className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"/>:<span className="absolute inset-0 grid place-items-center text-zinc-600">{active.kind==='reader'?<BookOpen size={28}/>:<Video size={28}/>}</span>}
    <span className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-black/30" aria-hidden="true"/>
    {(active.kind!=='reader'||voiced)&&<button className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 grid place-items-center w-14 h-14 rounded-full bg-white/15 backdrop-blur-md border border-white/25 text-white hover:bg-white/25 hover:scale-105 transition-all" aria-label={playing?'Пауза':'Продолжить'} onClick={toggle}>{playing?<Pause size={20} fill="currentColor"/>:<Play size={20} fill="currentColor" className="ml-0.5"/>}</button>}
    {active.kind!=='reader'&&active.duration>0&&<span className="absolute inset-x-0 bottom-0 h-[3px] bg-white/15" aria-hidden="true"><span className="block h-full bg-rose-500 origin-left" style={{transform:`scaleX(${progress})`}}/></span>}
   </div>
   <div className="px-1">
    <p className="m-0 flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-rose-300">{playing?<>{eq}{voiced?'Читает голос':'Сейчас играет'}</>:voiced?'Озвучка на паузе':active.kind==='reader'?'Открыто чтение':'На паузе'}</p>
    <strong className="block mt-1.5 text-[15px] font-bold leading-snug line-clamp-2" translate="no">{active.label}</strong>
    {active.kind!=='reader'&&active.duration>0&&<div className="mt-1.5 flex justify-between font-mono text-[10px] tabular-nums text-zinc-500" role="progressbar" aria-label="Прогресс просмотра" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress*100)}><span>{clock(active.time)}</span><span>{clock(active.duration)}</span></div>}
   </div>
   <div className="flex items-center gap-1.5">
    <button className="flex-1 min-w-0 h-10 px-4 inline-flex items-center justify-center gap-2 rounded-full bg-rose-600 hover:bg-rose-500 text-white text-[13px] font-semibold shadow-[0_10px_26px_-8px_rgba(225,29,72,0.65)] transition-colors" onClick={()=>{store.return(active.id);setOpen(false);}}><ArrowUpRight size={15}/><span className="truncate">{active.kind==='reader'?'Вернуться к чтению':'Вернуться к просмотру'}</span></button>
    <button className={round} aria-label="Мини-окно на странице" title="Мини-окно на странице" onClick={()=>{store.popup(active.id);setOpen(false);}}><PictureInPicture2 size={16}/></button>
    {active.kind!=='reader'&&floatingWindowSupported()&&<button className={round} aria-label="Окно поверх всех окон" title="Окно поверх всех окон" onClick={()=>{openFloatingWindow(active.host,{title:active.label}).catch(()=>{});setOpen(false);}}><AppWindow size={16}/></button>}
    <button className={round} aria-label={active.kind==='reader'?'Закрыть читалку':'Закрыть просмотр'} title="Закрыть" onClick={()=>{store.close(active.id);setOpen(false);}}><X size={16}/></button>
   </div>
  </div>}
  {recent.length>0&&<div className={active?'pt-1 border-t border-white/[0.06]':''}><p className="m-0 h-8 px-1 flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-zinc-500"><History size={12}/>Недавнее</p>{recent.map((item,i)=><motion.button key={item.id} initial={reduced?false:{opacity:0,x:8}} animate={{opacity:1,x:0}} transition={{duration:.25,delay:.05+i*.035}} onClick={()=>{store.revisit(item);setOpen(false);}} className="group w-full flex items-center gap-3 px-2 py-2 rounded-xl text-left text-[12px] text-zinc-300 hover:bg-white/[0.05] hover:text-white transition-colors"><span className="grid place-items-center w-7 h-7 shrink-0 rounded-lg bg-white/[0.05] text-zinc-400">{item.kind==='reader'?<BookOpen size={13}/>:<Video size={13}/>}</span><span className="flex-1 min-w-0 truncate" translate="no">{item.label}</span><ArrowUpRight size={13} className="text-zinc-600 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-white"/></motion.button>)}</div>}
  </div>
 </motion.section>}</AnimatePresence></div>,document.body)}</div>;
}

