import {useCallback,useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useMotionValue,useReducedMotion,useSpring} from 'motion/react';
import {ArrowUpRight,ImageUp,Play,RotateCcw,ScanSearch,X} from 'lucide-react';
import {CONFIDENT,clock,requestSceneJump,russianTitles,searchScene} from './scene-search.js';
import {onlineTitleLocation} from './title-route.js';
import './scene-search.css';

const EASE=[.22,1,.36,1],SPRING={type:'spring',stiffness:300,damping:30,mass:.9};
const hasImage=dt=>!!dt&&([...(dt.items||[])].some(i=>i.kind==='file'&&/^image\//.test(i.type))||[...(dt.types||[])].includes('Files')||[...(dt.types||[])].includes('text/uri-list'));
function searchOrigin(){const r=document.querySelector('.blossom-navbar .header-center-search .header-search')?.getBoundingClientRect();return r?{x:r.left+r.width/2,y:r.top+r.height/2}:{x:innerWidth/2,y:40};}
function anchorTop(){const r=document.querySelector('.blossom-navbar')?.getBoundingClientRect();return Math.max(72,(r?.bottom||70)+22);}

// Drop a frame anywhere (or paste it, or pick it from the search panel): the
// search button grows into a lens, swallows the picture, finds the scene and
// opens the episode at that second.
export default function SceneSearch(){
 const reduce=useReducedMotion();
 const [phase,setPhase]=useState('idle'),[preview,setPreview]=useState(''),[drop,setDrop]=useState(null),[matches,setMatches]=useState([]),[error,setError]=useState(''),[quota,setQuota]=useState(null),[countdown,setCountdown]=useState(0),[hold,setHold]=useState(false),[showAll,setShowAll]=useState(false);
 const depth=useRef(0),abort=useRef(null),picker=useRef(null),origin=useRef(searchOrigin()),[top,setTop]=useState(anchorTop);
 const tiltX=useSpring(useMotionValue(0),{stiffness:150,damping:18}),tiltY=useSpring(useMotionValue(0),{stiffness:150,damping:18});
 const active=phase!=='idle';
 const reset=useCallback(()=>{abort.current?.abort();setPhase('idle');setMatches([]);setError('');setDrop(null);setCountdown(0);setShowAll(false);setPreview(old=>{if(old.startsWith('blob:'))URL.revokeObjectURL(old);return '';});},[]);
 const loadQuota=useCallback(()=>{fetch('https://api.trace.moe/me',{signal:AbortSignal.timeout(8000)}).then(r=>r.ok?r.json():null).then(d=>{if(d&&Number.isFinite(d.quota))setQuota(Math.max(0,d.quota-d.quotaUsed));}).catch(()=>{});},[]);
 const run=useCallback(async(source,point)=>{
  abort.current?.abort();const controller=new AbortController();abort.current=controller;
  origin.current=searchOrigin();setTop(anchorTop());setError('');setMatches([]);setShowAll(false);setDrop(point||null);
  setPreview(old=>{if(old.startsWith('blob:'))URL.revokeObjectURL(old);return typeof source==='string'?source:URL.createObjectURL(source);});
  setPhase('scan');
  try{
   const started=performance.now();
   const {matches:found,remaining}=await searchScene(source,{signal:controller.signal});
   if(Number.isFinite(remaining))setQuota(remaining);
   const names=await russianTitles(found.map(m=>m.mal),controller.signal);
   const rows=found.map(m=>({...m,title:names[m.mal]?.title||m.title,cover:names[m.mal]?.cover||''}));
   // Let the absorb + scan read as one gesture even on a fast answer.
   const rest=900-(performance.now()-started);if(rest>0&&!reduce)await new Promise(r=>setTimeout(r,rest));
   if(controller.signal.aborted)return;
   if(!rows.length){setError('Эту сцену не узнали. Попробуй чистый кадр без рамок, надписей и обрезки.');setPhase('error');return;}
   setMatches(rows);setPhase('result');
   setCountdown(rows[0].similarity>=CONFIDENT&&rows[0].mal?3:0);
  }catch(e){if(!controller.signal.aborted){setError(e.message||'Поиск не удался.');setPhase('error');}}
 },[reduce]);
 const open=useCallback(match=>{
  if(!match?.mal)return;
  requestSceneJump(match);
  onlineTitleLocation({kind:'anime',provider:'shikimori',providerId:match.mal,id:'shikimori:'+match.mal,ids:{mal:match.mal},title:match.title,cover:match.cover,aliases:[match.title,match.original].filter(Boolean)});
  reset();window.scrollTo({top:0,behavior:'instant'});
 },[reset]);

 // Global drag-and-drop, paste and the search panel's "by frame" button.
 useEffect(()=>{
  const enter=e=>{if(!hasImage(e.dataTransfer))return;depth.current++;if(depth.current===1){origin.current=searchOrigin();setTop(anchorTop());setPhase(p=>p==='idle'||p==='error'||p==='result'?'drag':p);if(quota==null)loadQuota();}};
  const over=e=>{if(!hasImage(e.dataTransfer))return;e.preventDefault();e.dataTransfer.dropEffect='copy';const w=innerWidth/2;tiltX.set((e.clientX-w)/w*10);tiltY.set((e.clientY-top-150)/innerHeight*8);};
  const leave=e=>{if(!hasImage(e.dataTransfer))return;depth.current=Math.max(0,depth.current-1);if(!depth.current)setPhase(p=>p==='drag'?'idle':p);};
  const dropped=e=>{if(!hasImage(e.dataTransfer))return;e.preventDefault();depth.current=0;tiltX.set(0);tiltY.set(0);
   const file=[...(e.dataTransfer.files||[])].find(f=>/^image\//.test(f.type));const point={x:e.clientX,y:e.clientY};
   if(file){run(file,point);return;}
   const url=(e.dataTransfer.getData('text/uri-list')||e.dataTransfer.getData('text/plain')||'').split('\n').find(v=>/^https:\/\//.test(v.trim()))?.trim();
   if(url)run(url,point);else{setError('Перетащи сам файл картинки или изображение со страницы.');setPhase('error');}};
  const paste=e=>{const target=e.target;if(target?.closest?.('input,textarea,[contenteditable=true]')&&!target.closest('.morph-search-dialog'))return;const file=[...(e.clipboardData?.files||[])].find(f=>/^image\//.test(f.type));if(!file)return;e.preventDefault();run(file,null);};
  const pick=()=>picker.current?.click();
  addEventListener('dragenter',enter);addEventListener('dragover',over);addEventListener('dragleave',leave);addEventListener('drop',dropped);document.addEventListener('paste',paste);addEventListener('mediavault:scene-pick',pick);
  return()=>{removeEventListener('dragenter',enter);removeEventListener('dragover',over);removeEventListener('dragleave',leave);removeEventListener('drop',dropped);document.removeEventListener('paste',paste);removeEventListener('mediavault:scene-pick',pick);};
 },[run,quota,loadQuota,top]);
 // Some browsers drop the final dragleave; any real pointer move means the drag is over.
 useEffect(()=>{if(phase!=='drag')return;const done=()=>{depth.current=0;setPhase(p=>p==='drag'?'idle':p);};addEventListener('pointermove',done);addEventListener('dragend',done);return()=>{removeEventListener('pointermove',done);removeEventListener('dragend',done);};},[phase]);
 useEffect(()=>{if(!active)return;const key=e=>{if(e.key==='Escape'){e.preventDefault();reset();}};addEventListener('keydown',key);return()=>removeEventListener('keydown',key);},[active,reset]);
 useEffect(()=>{if(phase!=='result'||!countdown||hold)return;const t=setTimeout(()=>{if(countdown<=1)open(matches[0]);else setCountdown(c=>c-1);},1000);return()=>clearTimeout(t);},[phase,countdown,hold,open,matches]);

 const best=matches[0],confident=best&&best.similarity>=CONFIDENT&&best.mal;
 const others=matches.slice(1).filter(m=>m.similarity>.6);
 const shape=phase==='drag'?{width:'min(460px, calc(100vw - 32px))',borderRadius:34}:phase==='scan'?{width:136,borderRadius:68}:{width:'min(540px, calc(100vw - 32px))',borderRadius:30};
 const center={x:innerWidth/2,y:top+(phase==='scan'?68:140)};
 return <>
  <input ref={picker} type="file" accept="image/*" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)run(file,null);}}/>
  {createPortal(<AnimatePresence>{active&&<motion.div key="scene" className={'scene-search is-'+phase} initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduce?0:.22}}>
   <motion.div className="scene-backdrop" onClick={()=>phase!=='scan'&&reset()} initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}/>
   <div className="scene-stage" style={{paddingTop:top}}>
    <motion.section role="dialog" aria-modal="true" aria-label="Поиск аниме по кадру" className="scene-lens" layout={!reduce} style={{width:shape.width,rotateY:phase==='drag'&&!reduce?tiltX:0,rotateX:phase==='drag'&&!reduce?tiltY:0,transformPerspective:900}}
     initial={reduce?false:{opacity:0,scale:.12,x:origin.current.x-innerWidth/2,y:origin.current.y-center.y,borderRadius:999}} animate={{opacity:1,scale:1,x:0,y:0,borderRadius:shape.borderRadius}} exit={reduce?{opacity:0}:{opacity:0,scale:.2,borderRadius:999,x:origin.current.x-innerWidth/2,y:origin.current.y-center.y}} transition={SPRING}
     onPointerEnter={()=>setHold(true)} onPointerLeave={()=>setHold(false)}>
     <AnimatePresence mode="popLayout" initial={false}>
      {phase==='drag'&&<motion.div key="drag" className="scene-drop" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:.18}}>
       <span className="scene-drop-glow" aria-hidden="true"/>
       <span className="scene-drop-icon"><ScanSearch size={30}/></span>
       <strong>Отпусти кадр</strong>
       <p>Найду аниме, серию и точную секунду — и сразу включу этот момент.</p>
       <small>Кадр уйдёт в trace.moe{quota!=null?' · осталось поисков в этом месяце: '+quota:''}</small>
      </motion.div>}
      {phase==='scan'&&<motion.div key="scan" className="scene-scan" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:.2}}>
       {preview&&<motion.img src={preview} alt="" initial={reduce?false:{scale:1.6,filter:'blur(0px)'}} animate={{scale:1,filter:'blur(1.5px)'}} transition={{duration:.6,ease:EASE}}/>}
       <span className="scene-ring" aria-hidden="true"/>
       <span className="sr-only" role="status">Ищем сцену</span>
      </motion.div>}
      {phase==='result'&&best&&<motion.div key="result" className="scene-result" initial={reduce?false:{opacity:0,y:10}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.28,ease:EASE,delay:reduce?0:.08}}>
       <div className="scene-clip">{best.video?<video src={best.video} poster={best.image||undefined} autoPlay muted loop playsInline/>:best.image?<img src={best.image} alt=""/>:null}
        <span className="scene-match" title="Насколько кадр совпал со сценой">{Math.round(best.similarity*100)}%</span></div>
       <div className="scene-copy">
        <p className="scene-eyebrow">{confident?'Нашёл сцену':'Похоже, это'}</p>
        <h2>{best.title}</h2>
        <p className="scene-meta"><span>Серия {best.episode}</span><span>{clock(best.time)}</span>{best.original&&best.original!==best.title&&<span className="scene-original">{best.original}</span>}</p>
        {!best.mal&&<p className="scene-note">Этого тайтла нет в каталоге MyAnimeList, поэтому открыть его здесь не получится.</p>}
        <div className="scene-actions">
         {best.mal&&<button type="button" className="scene-open" onClick={()=>open(best)}>{countdown>0&&!reduce&&<motion.span key={'c'+countdown} className="scene-open-progress" initial={{scaleX:(3-countdown)/3}} animate={{scaleX:(4-countdown)/3}} transition={{duration:1,ease:'linear'}}/>}<Play size={16}/><span>{countdown>0?(hold?'Открою, когда уберёшь курсор':'Открываю через '+countdown):'Открыть с '+clock(best.time)}</span></button>}
         <button type="button" className="scene-secondary" aria-label="Отмена" title="Отмена" onClick={reset}><X size={17}/></button>
        </div>
       </div>
       {others.length>0&&<div className="scene-others"><button type="button" className="scene-others-toggle" aria-expanded={showAll||!confident} onClick={()=>{setShowAll(v=>!v);setCountdown(0);}}>{confident?'Другие варианты · '+others.length:'Ещё варианты'}</button>
        <AnimatePresence initial={false}>{(showAll||!confident)&&<motion.ul key="others" initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}} transition={{duration:.22}}>{others.map(m=><li key={m.key}><button type="button" disabled={!m.mal} onClick={()=>open(m)}><span className="scene-other-frame">{m.image&&<img src={m.image} alt=""/>}</span><span className="scene-other-text"><strong>{m.title}</strong><small>Серия {m.episode} · {clock(m.time)} · {Math.round(m.similarity*100)}%</small></span><ArrowUpRight size={15}/></button></li>)}</motion.ul>}</AnimatePresence>
       </div>}
      </motion.div>}
      {phase==='error'&&<motion.div key="error" className="scene-error" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}>
       <span className="scene-drop-icon"><ImageUp size={26}/></span>
       <p>{error}</p>
       <div className="scene-actions"><button type="button" className="scene-open" onClick={()=>picker.current?.click()}><RotateCcw size={16}/><span>Другой кадр</span></button><button type="button" className="scene-secondary" aria-label="Закрыть" onClick={reset}><X size={17}/></button></div>
      </motion.div>}
     </AnimatePresence>
    </motion.section>
    {phase==='scan'&&<motion.p className="scene-status" initial={{opacity:0,y:6}} animate={{opacity:1,y:0}} transition={{delay:reduce?0:.25}}>Ищем сцену по кадру…</motion.p>}
   </div>
   {phase==='scan'&&drop&&preview&&!reduce&&<motion.img className="scene-swallow" src={preview} alt="" aria-hidden="true" style={{left:0,top:0}}
    initial={{x:drop.x-90,y:drop.y-55,width:180,opacity:1,rotate:-5,borderRadius:16,filter:'blur(0px)'}} animate={{x:innerWidth/2-20,y:top+48,width:40,opacity:0,rotate:8,borderRadius:40,filter:'blur(6px)'}} transition={{duration:.6,ease:[.55,0,.25,1]}}/>}
  </motion.div>}</AnimatePresence>,document.body)}
 </>;
}
