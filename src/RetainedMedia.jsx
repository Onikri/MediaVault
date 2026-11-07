import {createContext,useContext,useEffect,useLayoutEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowUpRight,BookOpen,History,Pause,PictureInPicture2,Play,Square,Video,X} from 'lucide-react';
import {createRetainedMediaStore} from './retained-media-store.js';
import './retained-media.css';
const Workspace=createContext(null),Owner=createContext(null);
export function useRetainedWorkspace(){return useContext(Workspace);}
export function useRetainedMedia(active,descriptor,onStop){
 const owner=useContext(Owner),live=useRef(onStop);live.current=onStop;
 useLayoutEffect(()=>{if(owner)owner.store.owner(owner.id,()=>live.current?.());},[owner?.id]);
 useEffect(()=>{if(!owner)return;if(active)owner.store.activate(owner.id,descriptor);else owner.store.deactivate(owner.id);},[owner?.id,!!active,descriptor?.label,descriptor?.kind]);
 return owner?.mode||'attached';
}
export function RetainedMediaProvider({children}){
 const [store]=useState(createRetainedMediaStore),snapshot=useSyncExternalStore(store.subscribe,store.getSnapshot);
 useEffect(()=>{const close=()=>store.clear();addEventListener('mediavault-locked',close);return()=>{removeEventListener('mediavault-locked',close);store.clear();};},[store]);
 return <Workspace.Provider value={store}>{children}{createPortal(snapshot.rows.map(row=><RetainedHost key={row.id} row={row} store={store} popup={snapshot.popup===row.id} active={snapshot.active===row.id}/>),document.body)}</Workspace.Provider>;
}
export function RetainedMediaSlot({id,label,kind='video',userId,resumeItemId,restore,children}){
 const store=useContext(Workspace),anchor=useRef(null),live=useRef({label,kind,userId,resumeItemId,restore});live.current={label,kind,userId,resumeItemId,restore};
 useLayoutEffect(()=>{if(!store)return;store.attach(id,{...live.current,route:location.hash||'#home'},anchor.current,children);},[store,id,children]);
 useLayoutEffect(()=>{if(!store)return;const node=anchor.current;return()=>store.detach(id,node);},[store,id]);
 if(!store)return children;
 return <div ref={anchor} className={'retained-media-slot is-'+kind} data-retained-slot={id}/>;
}
function RetainedHost({row,store,popup,active}){
 const root=useRef(null),[box,setBox]=useState({position:'absolute',top:0,left:0,width:900}),attached=!!row.anchor?.isConnected,mode=popup&&active?'popup':attached?'attached':'hidden';
 const owner=useMemo(()=>({id:row.id,store,mode}),[row.id,store,mode]);
 useLayoutEffect(()=>{row.host=root.current;let frame=0,follow=performance.now()+550;
  const update=()=>{frame=0;const node=root.current,anchor=row.anchor;if(!node)return;
   if(mode==='attached'&&anchor?.isConnected){const r=anchor.getBoundingClientRect(),height=Math.ceil(node.getBoundingClientRect().height);if(height>20&&Math.abs(anchor.offsetHeight-height)>1)anchor.style.height=height+'px';const theater=!!node.querySelector('.mv-player.is-theater');const next=theater?{position:'fixed',left:16,top:Math.max(12,document.querySelector('.site-header')?.getBoundingClientRect().bottom+12||12),width:innerWidth-32}:{position:'absolute',left:r.left+scrollX,top:r.top+scrollY,width:r.width};setBox(old=>Object.keys(next).every(k=>Math.abs(old[k]-next[k])<.3||old[k]===next[k])?old:next);
    if(row.wantReturn){row.wantReturn=false;requestAnimationFrame(()=>{const media=node.querySelector('.mv-player,.immersive-reader')||node,p=media.getBoundingClientRect(),header=document.querySelector('.site-header')?.getBoundingClientRect().bottom||0;scrollTo({top:Math.max(0,scrollY+p.top-Math.max(header+12,(innerHeight-p.height)/2)),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});});}
   }
   if(performance.now()<follow&&mode==='attached')frame=requestAnimationFrame(update);
  };
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(update);};update();const resize=new ResizeObserver(schedule);if(row.anchor)resize.observe(row.anchor);if(root.current)resize.observe(root.current);const mutate=new MutationObserver(schedule);if(root.current)mutate.observe(root.current,{subtree:true,attributes:true,attributeFilter:['class']});addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule);return()=>{cancelAnimationFrame(frame);resize.disconnect();mutate.disconnect();removeEventListener('scroll',schedule);removeEventListener('resize',schedule);};
 },[row.anchor,mode]);
 function media(event){const v=event.target;if(!v.matches?.('video.mv-player-media'))return;if(event.type==='timeupdate'&&Math.abs((row.time||0)-v.currentTime)<1)return;const change={playing:!v.paused,time:v.currentTime,duration:Number.isFinite(v.duration)?v.duration:0};if(!row.preview&&v.readyState>=2)try{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;canvas.getContext('2d').drawImage(v,0,0,160,90);change.preview=canvas.toDataURL('image/jpeg',.65);}catch{}store.media(row.id,change);}
 return <div ref={root} className="retained-media-host" data-mode={mode} data-session={row.id} style={mode==='attached'?box:undefined} inert={mode==='hidden'} aria-hidden={mode==='hidden'} onPlayCapture={media} onPauseCapture={media} onTimeUpdateCapture={media} onLoadedDataCapture={media}>
 {mode==='popup'&&<div className="retained-popup-heading"><strong>{row.label}</strong><button aria-label="Вернуться к просмотру на странице" onClick={()=>store.return(row.id)}><ArrowUpRight size={16}/></button><button aria-label="Скрыть мини-просмотр" onClick={()=>store.popup(row.id)}><X size={16}/></button></div>}
 <Owner.Provider value={owner}>{row.node}</Owner.Provider></div>;
}
export function VideoDock(){
 const store=useContext(Workspace);if(!store)return null;return <Dock store={store}/>;
}
function Dock({store}){
 const state=useSyncExternalStore(store.subscribe,store.getSnapshot),active=state.rows.find(r=>r.id===state.active),[open,setOpen]=useState(false),trigger=useRef(null),panel=useRef(null),[box,setBox]=useState({right:16,top:70}),reduced=useReducedMotion();
 useEffect(()=>{if(!open)return;const update=()=>{const r=trigger.current?.getBoundingClientRect();if(r)setBox({right:Math.max(12,innerWidth-r.right),top:r.bottom+10});};update();addEventListener('resize',update);addEventListener('scroll',update,true);const outside=e=>{if(!panel.current?.contains(e.target)&&!trigger.current?.contains(e.target))setOpen(false);};const key=e=>{if(e.key==='Escape'){setOpen(false);trigger.current?.focus();}};document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);return()=>{removeEventListener('resize',update);removeEventListener('scroll',update,true);document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key);};},[open]);
 if(!active&&!state.history.length)return null;
 const toggle=()=>{const video=active?.host?.querySelector('video.mv-player-media');if(video){if(video.paused)video.play().catch(()=>{});else video.pause();}};
 const recent=state.history.filter(item=>item.id!==active?.id).slice(0,6);
 const playing=!!active?.playing&&active?.kind!=='reader',progress=active?.duration?Math.min(1,(active.time||0)/active.duration):0;
 const clock=v=>{v=Math.max(0,Math.floor(v||0));const h=Math.floor(v/3600),m=Math.floor(v%3600/60),s=String(v%60).padStart(2,'0');return h?h+':'+String(m).padStart(2,'0')+':'+s:m+':'+s;};
 return <><button ref={trigger} className={'retained-dock'+(active?' is-live':'')+(playing?' is-playing':'')} title={active?.label||'История просмотра'} aria-label="Плеер в фоне" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>{playing?<span className="retained-eq" aria-hidden="true"><i/><i/><i/></span>:active?.kind==='reader'?<BookOpen size={18}/>:<Video size={18}/>}</button>{createPortal(<AnimatePresence>{open&&<motion.section ref={panel} role="dialog" aria-label={active?'Сейчас в фоне':'Недавний просмотр'} className="retained-dock-panel" style={box} initial={{opacity:0,scale:reduced?1:.94,y:reduced?0:-4}} animate={{opacity:1,scale:1,y:0}} exit={{opacity:0,scale:reduced?1:.96}} transition={{type:'spring',stiffness:420,damping:34}}>
  {active&&<div className="retained-player">
   <div className="retained-cover">{active.preview?<img src={active.preview} alt=""/>:<span className="retained-cover-empty">{active.kind==='reader'?<BookOpen size={28}/>:<Video size={28}/>}</span>}
    {active.kind!=='reader'&&<button className="retained-cover-play" aria-label={playing?'Пауза':'Продолжить'} onClick={toggle}>{playing?<Pause size={20}/>:<Play size={20}/>}</button>}
   </div>
   <p className="retained-eyebrow">{playing?<><span className="retained-eq" aria-hidden="true"><i/><i/><i/></span>Сейчас играет</>:active.kind==='reader'?'Открыто чтение':'На паузе'}</p>
   <strong className="retained-title">{active.label}</strong>
   {active.kind!=='reader'&&active.duration>0&&<div className="retained-progress" role="progressbar" aria-label="Прогресс просмотра" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress*100)}><span style={{transform:`scaleX(${progress})`}}/><small>{clock(active.time)}</small><small>{clock(active.duration)}</small></div>}
   <div className="retained-dock-actions">
    <button className="is-primary" onClick={()=>{store.return(active.id);setOpen(false);}}><ArrowUpRight size={16}/>Вернуться к просмотру</button>
    <button aria-label="Картинка в картинке" title="Картинка в картинке" onClick={()=>{store.popup(active.id);setOpen(false);}}><PictureInPicture2 size={17}/></button>
    <button aria-label="Остановить просмотр" title="Остановить" onClick={()=>{store.close(active.id);setOpen(false);}}><Square size={14}/></button>
   </div>
  </div>}
  {recent.length>0&&<div className="retained-history"><h3><History size={13}/>Недавнее</h3>{recent.map(item=><button key={item.id} onClick={()=>{store.revisit(item);setOpen(false);}}>{item.kind==='reader'?<BookOpen size={14}/>:<Video size={14}/>}<span>{item.label}</span><ArrowUpRight size={13}/></button>)}</div>}
 </motion.section>}</AnimatePresence>,document.body)}</>;
}
