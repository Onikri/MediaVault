import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Download,LoaderCircle,X} from 'lucide-react';
import {SAVE_FORMATS,downloadBlob,formatDuration,pagesWord,plural,saveReaderChapter} from './reader-chapter-save.js';
import UiSegmented from './UiSegmented.jsx';
import './reader-save.css';

const spring={type:'spring',stiffness:420,damping:36};
const contentChoices=[[true,'С переводом'],[false,'Оригинал']],formatChoices=Object.entries(SAVE_FORMATS).map(([id,v])=>[id,v.label]);
const PENDING=0,TRANSLATED=1,SAVED=2,PROBLEM=3;
function readChoice(key){try{const v=JSON.parse(localStorage.getItem(key)||'{}');return {translate:v.translate!==false,format:SAVE_FORMATS[v.format]?v.format:'cbz'};}catch{return {translate:true,format:'cbz'};}}
const megabytes=bytes=>bytes>=1024*1024?(bytes/1024/1024).toFixed(bytes>=100*1024*1024?0:1).replace('.',',')+' МБ':Math.max(1,Math.round(bytes/1024))+' КБ';

function Field({label,...props}){return <div className="reader-save-field"><span>{label}</span><UiSegmented label={label} {...props}/></div>;}
// One bar per page; drawn on canvas so a 1500-page chapter costs one paint.
function PageStrip({states,total,version=0}){
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

export default function ReaderChapterExport({title,chapterLabel,fileName,total,createSource,readiness,onOpenPage,onEnableTranslation,container,storageKey='mv_reader_save'}){
 const [open,setOpen]=useState(false),[choice,setChoiceState]=useState(()=>readChoice(storageKey)),[ready,setReady]=useState(null),[run,setRun]=useState(null),reduce=useReducedMotion();
 const abort=useRef(null),source=useRef(null),states=useRef(null),[tick,setTick]=useState(0),progressFrame=useRef(0),latest=useRef(null),lastPaint=useRef(0);
 const running=run?.state==='running';
 const setChoice=change=>setChoiceState(old=>{const value={...old,...change};try{localStorage.setItem(storageKey,JSON.stringify(value));}catch{}return value;});
 useEffect(()=>()=>{abort.current?.abort(new DOMException('Читалка закрыта','AbortError'));source.current?.close?.();},[]);
 useEffect(()=>{if(!running){setRun(null);setReady(null);}},[title,total]);
 const refresh=useCallback(()=>{let closed=false;Promise.resolve(readiness?.()).catch(()=>null).then(value=>{if(!closed)setReady(value||{total,translated:0,partial:0,pages:null});});return()=>{closed=true;};},[readiness,total]);
 useEffect(()=>{if(open&&!running)return refresh();},[open,running,refresh]);
 const sourceAvailable=!choice.translate||!!ready?.canTranslate;
 async function start(){
  if(running||!total)return;
  const controller=new AbortController();abort.current=controller;
  const base=new Uint8Array(total);if(ready?.pages)base.set(ready.pages.subarray(0,total));states.current=base;
  setRun({state:'running',progress:{phase:'pages',done:0,total,problems:[]},startedAt:Date.now()});
  let chapter;
  try{
   chapter=await createSource(choice.translate);if(!chapter)throw Error('Перевод в ридере выключен. Включи перевод страницы и сохрани главу снова.');source.current=chapter;
   const result=await saveReaderChapter({total,translate:choice.translate,format:choice.format,name:fileName+(choice.translate?' · RU':''),source:chapter,signal:controller.signal,onProgress:value=>{
    // At most ~8 renders a second; timers (not animation frames) so a hidden tab still catches up.
    const apply=()=>{progressFrame.current=0;lastPaint.current=Date.now();setTick(n=>n+1);setRun(old=>old?.state==='running'?{...old,progress:latest.current}:old);};
    latest.current=value;if(!progressFrame.current)progressFrame.current=setTimeout(apply,Math.max(0,120-(Date.now()-lastPaint.current)));
   },onPage:(index,kind)=>{const grid=states.current;if(grid)grid[index]=kind==='problem'?PROBLEM:SAVED;}});
   downloadBlob(result.blob,result.filename);
   setTick(n=>n+1);setRun({state:'done',result});
  }catch(error){
   const stopped=controller.signal.aborted;
   setRun({state:stopped?'stopped':'error',error:stopped?'':error.message||'Не удалось сохранить главу.'});
  }finally{
   clearTimeout(progressFrame.current);progressFrame.current=0;
   if(abort.current===controller)abort.current=null;
   if(chapter&&!chapter.live)chapter.close?.();if(source.current===chapter)source.current=null;
  }
 }
 const stop=()=>abort.current?.abort(new DOMException('Сохранение остановлено','AbortError'));
 const progress=run?.progress,done=progress?.done||0,fraction=running&&total?done/total:0;
 const stripStates=running||run?.state==='done'?states.current:ready?.pages||null;
 const problems=run?.state==='done'?run.result.problems:progress?.problems||[];
 return <Dialog.Root open={open} onOpenChange={setOpen}>
  <Dialog.Trigger className="reader-control reader-save-trigger" aria-label={running?'Сохранение главы · '+done+' из '+total:'Скачать главу с переводом'} data-running={running||undefined}>
   {running?<svg className="reader-save-ring" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="10" pathLength="100" strokeDasharray={Math.max(2,fraction*100)+' 100'}/></svg>:null}
   <Download size={running?14:19}/>
  </Dialog.Trigger>
  <Dialog.Portal container={container||undefined}>
   <Dialog.Overlay className="reader-save-backdrop"/>
   <Dialog.Content className="reader-save-sheet" aria-describedby={undefined} onOpenAutoFocus={e=>{e.preventDefault();e.currentTarget.focus({preventScroll:true});}}>
    <motion.div className="reader-save-body" layout={!reduce} transition={spring}>
     <motion.header layout="position" className="reader-save-head">
      <div><Dialog.Title>{run?.state==='done'?'Глава сохранена':'Сохранить главу'}</Dialog.Title><p>{chapterLabel}</p></div>
      <Dialog.Close className="reader-save-close" aria-label="Закрыть окно сохранения"><X size={17}/></Dialog.Close>
     </motion.header>
     <AnimatePresence mode="popLayout" initial={false}>
      {running?<motion.section key="running" className="reader-save-state" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} transition={spring}>
       <div className="reader-save-count" aria-live="polite"><strong>{done}</strong><span>из {total}</span>{progress?.etaMs?<em>{formatDuration(progress.etaMs)}</em>:null}</div>
       <PageStrip states={stripStates} total={total} version={tick}/>
       <p className="reader-save-now" role="status">{progressLine(progress,choice)}</p>
       {choice.translate&&progress?.untranslated>0&&progress.phase==='pages'?<p className="reader-save-quiet">Осталось перевести {pagesWord(progress.untranslated)}</p>:null}
       {problems.length?<p className="reader-save-quiet reader-save-warn">С пропусками: {problems.slice(0,6).map(p=>'стр. '+p.page).join(', ')}{problems.length>6?' и ещё '+(problems.length-6):''}</p>:null}
       <div className="reader-save-actions"><span className="reader-save-hint">Окно можно закрыть — сохранение продолжится</span><button type="button" className="reader-save-secondary" onClick={stop}>Остановить</button></div>
      </motion.section>
      :run?.state==='done'?<motion.section key="done" className="reader-save-state" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} transition={spring}>
       <PageStrip states={stripStates} total={total} version={tick}/>
       <p className="reader-save-summary">{pagesWord(run.result.total)} · {SAVE_FORMATS[choice.format].label} · {megabytes(run.result.size)} · {formatDuration(run.result.elapsedMs).replace('около ','за ')}</p>
       {run.result.problems.length?<div className="reader-save-problems"><p>{run.result.problems.length} {plural(run.result.problems.length,['страница сохранена','страницы сохранены','страниц сохранено'])} с пропусками перевода</p><ul>{run.result.problems.map(p=><li key={p.page}><span><b>Стр. {p.page}</b> {p.message}</span>{onOpenPage&&<button type="button" onClick={()=>{setOpen(false);onOpenPage(p.page-1);}}>Открыть</button>}</li>)}</ul></div>:<p className="reader-save-quiet">Все страницы переведены полностью.</p>}
       <div className="reader-save-actions"><button type="button" className="reader-save-secondary" onClick={()=>downloadBlob(run.result.blob,run.result.filename)}>Скачать ещё раз</button><button type="button" className="reader-save-primary" onClick={()=>{setOpen(false);setRun(null);}}>Готово</button></div>
      </motion.section>
      :<motion.section key="idle" className="reader-save-state" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} transition={spring}>
       {choice.translate?<><PageStrip states={stripStates} total={total} version={tick}/><p className="reader-save-ready">{readinessLine(ready,total)}</p></>:<p className="reader-save-ready">Исходные страницы главы без перевода · {pagesWord(total)}</p>}
       <Field label="Что сохранить" value={choice.translate} options={contentChoices} onChange={translate=>setChoice({translate})}/>
       <Field label="Формат" value={choice.format} options={formatChoices} onChange={format=>setChoice({format})}/>
       {run?.state==='error'?<p className="reader-save-error" role="alert">{run.error}</p>:run?.state==='stopped'?<p className="reader-save-quiet" role="status">Сохранение остановлено. Готовые страницы остались в кэше.</p>:null}
       {choice.translate&&ready&&!ready.canTranslate?<p className="reader-save-quiet">Перевод в ридере выключен.{onEnableTranslation?<> <button type="button" className="reader-save-link" onClick={()=>{onEnableTranslation();setOpen(false);}}>Включить перевод</button></>:null}</p>:null}
       <div className="reader-save-actions"><span className="reader-save-hint">{choice.format==='pdf'?'PDF хранит страницы в JPEG':'Файл сохранится на это устройство'}</span><button type="button" className="reader-save-primary" disabled={!total||!ready||!sourceAvailable} onClick={start}>{!ready?<LoaderCircle className="reader-translation-spinner" size={16}/>:<Download size={16}/>}Сохранить главу</button></div>
      </motion.section>}
     </AnimatePresence>
    </motion.div>
   </Dialog.Content>
  </Dialog.Portal>
 </Dialog.Root>;
}
function readinessLine(ready,total){
 if(!ready)return 'Проверяем готовые страницы…';
 const translated=ready.translated||0,partial=ready.partial||0,left=Math.max(0,total-translated-partial);
 if(!translated&&!partial)return 'Перевод ещё не начат · страницы переведутся при сохранении';
 return (translated+partial)+' из '+total+' переведены'+(partial?' · '+partial+' с пропусками':'')+(left?' · '+pagesWord(left)+' переведём при сохранении':'');
}
function progressLine(progress,choice){
 if(!progress)return 'Готовим сохранение…';
 if(progress.phase==='pack')return 'Собираем файл '+SAVE_FORMATS[choice.format].label+'…';
 if(progress.phase==='recover')return progress.current?.label||'Проверяем пропущенные реплики';
 if(progress.phase==='retry')return (progress.current?'Стр. '+progress.current.page+' · ':'')+'Повторяем страницы с ошибкой';
 if(!progress.current)return choice.translate?'Готовим перевод главы…':'Собираем исходные страницы…';
 return 'Стр. '+progress.current.page+' · '+progress.current.label;
}
