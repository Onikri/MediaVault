import {useCallback,useEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {Download,LoaderCircle,Minimize2,X} from 'lucide-react';
import {SAVE_FORMATS,pagesWord} from './reader-chapter-save.js';
import {chapterSaves} from './chapter-save-jobs.js';
import {PageStrip,ProgressRing,SaveJobPanel,ringFraction,saveSpring,useChapterSaves} from './ChapterSaveView.jsx';
import UiSegmented from './UiSegmented.jsx';
import './reader-save.css';

const contentChoices=[[true,'С переводом'],[false,'Оригинал']],formatChoices=Object.entries(SAVE_FORMATS).map(([id,v])=>[id,v.label]);
function readChoice(key){try{const v=JSON.parse(localStorage.getItem(key)||'{}');return {translate:v.translate!==false,format:SAVE_FORMATS[v.format]?v.format:'cbz'};}catch{return {translate:true,format:'cbz'};}}
function Field({label,...props}){return <div className="reader-save-field"><span>{label}</span><UiSegmented label={label} {...props}/></div>;}

// The save itself lives in chapter-save-jobs: closing this sheet, the reader or
// switching chapters keeps it running, and the navbar shows it meanwhile.
export default function ReaderChapterExport({title,userId,chapterLabel,fileName,total,createSource,readiness,onOpenPage,onEnableTranslation,container,storageKey='mv_reader_save'}){
 const [open,setOpen]=useState(false),[choice,setChoiceState]=useState(()=>readChoice(storageKey)),[ready,setReady]=useState(null),reduce=useReducedMotion();
 const snapshot=useChapterSaves(),job=snapshot.jobs.find(j=>j.id===title),running=job?.state==='running',finished=job?.state==='done';
 const pageOpener=useRef(onOpenPage);pageOpener.current=onOpenPage;
 const setChoice=change=>setChoiceState(old=>{const value={...old,...change};try{localStorage.setItem(storageKey,JSON.stringify(value));}catch{}return value;});
 // While this reader shows the chapter, the navbar sheet can open its pages.
 useEffect(()=>title?chapterSaves.attach(title,{openPage:index=>pageOpener.current?.(index)}):undefined,[title]);
 useEffect(()=>{setReady(null);},[title,total]);
 const refresh=useCallback(()=>{let closed=false;Promise.resolve(readiness?.()).catch(()=>null).then(value=>{if(!closed)setReady(value||{total,translated:0,partial:0,pages:null});});return()=>{closed=true;};},[readiness,total]);
 useEffect(()=>{if(open&&!running&&!finished)return refresh();},[open,running,finished,refresh]);
 // Opening the reader's own sheet takes the job back from the navbar.
 useEffect(()=>{if(open&&snapshot.expanded===title)chapterSaves.collapse();},[open,snapshot.expanded,title]);
 const sourceAvailable=!choice.translate||!!ready?.canTranslate;
 function start(){
  if(running||!total)return;
  chapterSaves.start({id:title,userId,title:fileName,chapterLabel,fileName,total,translate:choice.translate,format:choice.format,pages:choice.translate?ready?.pages:null,createSource});
 }
 const live=running||finished;
 return <Dialog.Root open={open} onOpenChange={setOpen}>
  <Dialog.Trigger className="reader-control reader-save-trigger" aria-label={running?'Сохранение главы · '+(job.progress?.done||0)+' из '+total:finished?'Глава сохранена':'Скачать главу с переводом'} data-running={running||undefined}>
   {running?<ProgressRing fraction={ringFraction(job)}/>:null}
   <Download size={running?14:19}/>
  </Dialog.Trigger>
  <Dialog.Portal container={container||undefined}>
   <Dialog.Overlay className="reader-save-backdrop"/>
   <Dialog.Content className="reader-save-sheet" aria-describedby={undefined} onOpenAutoFocus={e=>{e.preventDefault();e.currentTarget.focus({preventScroll:true});}}>
    <motion.div className="reader-save-body" layout={!reduce} transition={saveSpring}>
     <motion.header layout="position" className="reader-save-head">
      <div><Dialog.Title>{finished?'Глава сохранена':running?'Сохраняем главу':'Сохранить главу'}</Dialog.Title><p>{chapterLabel}</p></div>
      <Dialog.Close className="reader-save-close" aria-label={running?'Свернуть окно сохранения':'Закрыть окно сохранения'} title={running?'Свернуть':'Закрыть'}>{running?<Minimize2 size={15}/>:<X size={17}/>}</Dialog.Close>
     </motion.header>
     <AnimatePresence mode="popLayout" initial={false}>
      {live?<SaveJobPanel key={job.id+job.state} job={job} onMinimize={()=>setOpen(false)} onOpenPage={index=>{setOpen(false);onOpenPage?.(index);}}/>
      :<motion.section key="idle" className="reader-save-state" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} transition={saveSpring}>
       {choice.translate?<><PageStrip states={ready?.pages||null} total={total}/><p className="reader-save-ready">{readinessLine(ready,total)}</p></>:<p className="reader-save-ready">Исходные страницы главы без перевода · {pagesWord(total)}</p>}
       <Field label="Что сохранить" value={choice.translate} options={contentChoices} onChange={translate=>setChoice({translate})}/>
       <Field label="Формат" value={choice.format} options={formatChoices} onChange={format=>setChoice({format})}/>
       {job?.state==='error'?<p className="reader-save-error" role="alert">{job.error}</p>:job?.state==='stopped'?<p className="reader-save-quiet" role="status">Сохранение остановлено. Готовые страницы остались в кэше.</p>:null}
       {choice.translate&&ready&&!ready.canTranslate?<p className="reader-save-quiet">Перевод в ридере выключен.{onEnableTranslation?<> <button type="button" className="reader-save-link" onClick={()=>{onEnableTranslation();setOpen(false);}}>Включить перевод</button></>:null}</p>:null}
       <div className="reader-save-actions"><span className="reader-save-hint">{choice.format==='pdf'?'PDF хранит страницы в JPEG':'Сохранение идёт в фоне — можно читать дальше'}</span><button type="button" className="reader-save-primary" disabled={!total||!ready||!sourceAvailable} onClick={start}>{!ready?<LoaderCircle className="reader-translation-spinner" size={16}/>:<Download size={16}/>}Сохранить главу</button></div>
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
