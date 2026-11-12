import {useEffect,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Check,Download,Minimize2,TriangleAlert} from 'lucide-react';
import {SAVE_FORMATS,downloadBlob,formatDuration,pagesWord,plural} from './reader-chapter-save.js';
import {PENDING,PROBLEM,chapterSaves} from './chapter-save-jobs.js';
import './reader-save.css';

export const saveSpring={type:'spring',stiffness:420,damping:36};
const enter={initial:{opacity:0,y:8},animate:{opacity:1,y:0},exit:{opacity:0,y:-6},transition:saveSpring};
export const megabytes=bytes=>bytes>=1024*1024?(bytes/1024/1024).toFixed(bytes>=100*1024*1024?0:1).replace('.',',')+' МБ':Math.max(1,Math.round(bytes/1024))+' КБ';
export function useChapterSaves(){return useSyncExternalStore(chapterSaves.subscribe,chapterSaves.getSnapshot);}

// One bar per page; drawn on canvas so a 1500-page chapter costs one paint.
export function PageStrip({states,total,version=0}){
 const canvas=useRef(null),[width,setWidth]=useState(0);
 useLayoutEffect(()=>{const node=canvas.current;if(!node)return;const update=()=>setWidth(node.clientWidth);update();const o=new ResizeObserver(update);o.observe(node);return()=>o.disconnect();},[]);
 useEffect(()=>{
  const node=canvas.current;if(!node||!width)return;const frame=requestAnimationFrame(()=>{
   const ratio=Math.min(2,devicePixelRatio||1),height=node.clientHeight||10,context=node.getContext('2d');node.width=Math.round(width*ratio);node.height=Math.round(height*ratio);context.scale(ratio,ratio);
   const style=getComputedStyle(node),colors=[style.getPropertyValue('--strip-pending'),style.getPropertyValue('--strip-translated'),style.getPropertyValue('--strip-saved'),style.getPropertyValue('--strip-problem')];
   context.clearRect(0,0,width,height);context.save();context.beginPath();context.roundRect?.(0,0,width,height,height/2);context.clip();
   const step=width/Math.max(1,total),gap=step>=4?1:0;
   for(let i=0;i<total;i++){const state=states?.[i]||PENDING,x=i*step,w=state===PROBLEM?Math.max(2,step-gap):Math.max(.6,step-gap);context.fillStyle=colors[state]||colors[0];context.fillRect(state===PROBLEM&&step<2?x-(2-step)/2:x,0,w+(gap?0:.4),height);}
   context.restore();
  });return()=>cancelAnimationFrame(frame);
 },[states,total,width,version]);
 return <canvas ref={canvas} className="reader-save-strip" aria-hidden="true"/>;
}

export function progressLine(progress,choice){
 if(!progress)return 'Готовим сохранение…';
 if(progress.phase==='wait'&&progress.wait){const w=progress.wait;return (w.reason==='busy'?'Google перегружен':'Перевод завис')+' · повторим '+pagesWord(w.pages)+' через '+w.seconds+' с';}
 if(progress.phase==='pack')return 'Собираем файл '+SAVE_FORMATS[choice.format].label+'…';
 if(progress.phase==='recover')return progress.current?.label||'Переводим пропущенные реплики запасной моделью';
 if(progress.phase==='retry')return (progress.current?'Стр. '+progress.current.page+' · ':'')+'Повторяем страницы, которые не успели';
 if(!progress.current)return choice.translate?'Готовим перевод главы…':'Собираем исходные страницы…';
 return 'Стр. '+progress.current.page+' · '+progress.current.label;
}
export const ringFraction=job=>job?.state==='running'&&job.total?(job.progress?.done||0)/job.total:job?.state==='done'?1:0;
export function ProgressRing({fraction}){return <svg className="reader-save-ring" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="10" pathLength="100" strokeDasharray={Math.max(2,fraction*100)+' 100'}/></svg>;}

// Running and finished states of a job, shared by the reader sheet and the navbar sheet.
export function SaveJobPanel({job,onMinimize,onOpenPage}){
 const progress=job.progress,done=progress?.done||0,problems=job.state==='done'?job.result.problems:progress?.problems||[];
 if(job.state==='running')return <motion.section key="running" className="reader-save-state" {...enter}>
  <div className="reader-save-count" aria-live="polite"><strong>{done}</strong><span>из {job.total}</span>{progress?.etaMs?<em>{formatDuration(progress.etaMs)}</em>:null}</div>
  <PageStrip states={job.states} total={job.total} version={job.version}/>
  <p className="reader-save-now" role="status">{progressLine(progress,job.choice)}</p>
  {job.choice.translate&&progress?.untranslated>0&&progress.phase==='pages'?<p className="reader-save-quiet">Осталось перевести {pagesWord(progress.untranslated)}</p>:null}
  {problems.length?<p className="reader-save-quiet reader-save-warn">Ещё не готовы: {problems.slice(0,6).map(p=>'стр. '+p.page).join(', ')}{problems.length>6?' и ещё '+(problems.length-6):''}</p>:null}
  <div className="reader-save-actions"><span className="reader-save-hint">Можно читать дальше — сохранение идёт в фоне</span><button type="button" className="reader-save-secondary" onClick={()=>chapterSaves.stop(job.id)}>Остановить</button>{onMinimize&&<button type="button" className="reader-save-primary" onClick={onMinimize}><Minimize2 size={15}/>Свернуть</button>}</div>
 </motion.section>;
 if(job.state==='done'){const r=job.result;return <motion.section key="done" className="reader-save-state" {...enter}>
  <PageStrip states={job.states} total={job.total} version={job.version}/>
  <p className="reader-save-summary">{pagesWord(r.total)} · {SAVE_FORMATS[job.choice.format].label} · {megabytes(r.size)} · {formatDuration(r.elapsedMs).replace('около ','за ')}</p>
  {r.problems.length?<div className="reader-save-problems"><p>{r.problems.length} {plural(r.problems.length,['страница сохранена','страницы сохранены','страниц сохранено'])} не полностью</p><ul>{r.problems.map(p=><li key={p.page}><span><b>Стр. {p.page}</b> {p.message}</span>{onOpenPage&&<button type="button" onClick={()=>onOpenPage(p.page-1)}>Открыть</button>}</li>)}</ul></div>:<p className="reader-save-quiet">{job.choice.translate?'Все страницы переведены полностью.':'Все страницы сохранены.'}</p>}
  <div className="reader-save-actions"><button type="button" className="reader-save-secondary" onClick={()=>downloadBlob(r.blob,r.filename)}>Скачать ещё раз</button><button type="button" className="reader-save-primary" onClick={()=>{chapterSaves.dismiss(job.id);onMinimize?.();}}>Готово</button></div>
 </motion.section>;}
 return <motion.section key="failed" className="reader-save-state" {...enter}>
  {job.state==='error'?<p className="reader-save-error" role="alert">{job.error}</p>:<p className="reader-save-quiet" role="status">Сохранение остановлено. Готовые страницы остались в кэше.</p>}
  <div className="reader-save-actions"><button type="button" className="reader-save-primary" onClick={()=>{chapterSaves.dismiss(job.id);onMinimize?.();}}>Понятно</button></div>
 </motion.section>;
}

// The navbar button for saves running in the background, next to the
// retained player/readers and the music island. It expands into the sheet.
export function ChapterSaveDock({userId}){
 const snapshot=useChapterSaves(),reduce=useReducedMotion(),trigger=useRef(null),[anchor,setAnchor]=useState(null);
 useEffect(()=>chapterSaves.scope(userId),[userId]);
 const visible=snapshot.jobs.filter(job=>job.state!=='stopped'),job=snapshot.jobs.find(j=>j.id===snapshot.expanded)||visible[0],open=!!snapshot.expanded&&!!job;
 const running=visible.filter(j=>j.state==='running');
 useLayoutEffect(()=>{if(!open)return;const update=()=>{const r=trigger.current?.getBoundingClientRect();if(r)setAnchor({top:r.bottom+10,right:Math.max(12,innerWidth-r.right)});};update();addEventListener('resize',update);return()=>removeEventListener('resize',update);},[open]);
 const openPage=job&&snapshot.readers.has(job.id)?index=>{chapterSaves.reader(job.id)?.openPage?.(index);chapterSaves.collapse();}:null;
 const label=!job?'':job.state==='running'?'Сохранение главы · '+(job.progress?.done||0)+' из '+job.total:job.state==='done'?'Глава сохранена':'Сохранение не удалось';
 return <>
  <AnimatePresence>{job&&<motion.button key="dock" ref={trigger} type="button" className={'retained-dock chapter-save-dock is-'+job.state} aria-label={label} title={job.title} aria-expanded={open} onClick={()=>open?chapterSaves.collapse():chapterSaves.expand(job.id)} initial={reduce?false:{scale:.4,opacity:0}} animate={{scale:1,opacity:1}} exit={reduce?{opacity:0}:{scale:.4,opacity:0}} transition={saveSpring}>
   {job.state==='running'&&<ProgressRing fraction={ringFraction(job)}/>}
   {job.state==='done'?<Check size={17}/>:job.state==='error'?<TriangleAlert size={16}/>:<Download size={14}/>}
   {running.length>1&&<b className="chapter-save-count">{running.length}</b>}
  </motion.button>}</AnimatePresence>
  <Dialog.Root open={open} onOpenChange={value=>{if(!value)chapterSaves.collapse();}} modal={false}>
   <Dialog.Portal>
    <Dialog.Content onInteractOutside={e=>{if(trigger.current?.contains(e.target))e.preventDefault();}} className="reader-save-sheet is-docked" style={anchor?{'--dock-top':anchor.top+'px','--dock-right':anchor.right+'px'}:undefined} aria-describedby={undefined} onOpenAutoFocus={e=>{e.preventDefault();e.currentTarget.focus({preventScroll:true});}} onCloseAutoFocus={e=>{e.preventDefault();trigger.current?.focus({preventScroll:true});}}>
     {job&&<motion.div className="reader-save-body" layout={!reduce} transition={saveSpring}>
      <motion.header layout="position" className="reader-save-head">
       <div><Dialog.Title>{job.state==='done'?'Глава сохранена':job.state==='running'?'Сохраняем главу':'Сохранение главы'}</Dialog.Title><p>{job.title} · {pagesWord(job.total)}</p></div>
       <Dialog.Close className="reader-save-close" aria-label="Свернуть окно сохранения" title="Свернуть"><Minimize2 size={15}/></Dialog.Close>
      </motion.header>
      <AnimatePresence mode="popLayout" initial={false}><SaveJobPanel key={job.id+job.state} job={job} onMinimize={()=>chapterSaves.collapse()} onOpenPage={openPage}/></AnimatePresence>
      {visible.length>1&&<div className="chapter-save-others"><p>Другие главы</p>{visible.filter(other=>other.id!==job.id).map(other=><button key={other.id} type="button" onClick={()=>chapterSaves.expand(other.id)}><span>{other.title}</span><em>{other.state==='running'?(other.progress?.done||0)+' из '+other.total:other.state==='done'?'готово':'ошибка'}</em></button>)}</div>}
     </motion.div>}
    </Dialog.Content>
   </Dialog.Portal>
  </Dialog.Root>
 </>;
}
