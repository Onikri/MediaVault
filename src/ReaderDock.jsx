import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ArrowLeft,ChevronDown,ChevronLeft,ChevronRight,ChevronUp,Ellipsis,Grid2X2,ListOrdered,Maximize,Minimize,Settings2} from 'lucide-react';
import './reader-dock.css';

// The reader's control surface. On a title page: one slim glass capsule (no
// «back» — the page around it is where you are). In full screen it parts into
// two small islands that glide from the centre into the corners: «back» on one
// side, the tools on the other; pointing at the tools unrolls every button. A
// webtoon keeps it on the right edge. Page progress is the capsule's top line.
// Everything moves with transform and opacity only, so it stays smooth.
const glide={type:'spring',stiffness:210,damping:24,mass:.9};
const fade={duration:.18,ease:[.22,1,.36,1]};

// Empty glass is the page slider: drag or click to leaf, hover to peek.
function Scrub({progress,onPage,preview,vertical,flip,chapter}){
 const total=Math.max(1,progress?.total||1),current=Math.max(1,Math.min(total,progress?.current||1)),[peek,setPeek]=useState(null),request=useRef(0),box=useRef(null);
 const pageAt=event=>{const r=box.current.getBoundingClientRect(),raw=vertical?(event.clientY-r.top)/r.height:(event.clientX-r.left)/r.width,g=Math.max(0,Math.min(1,flip?1-raw:raw)),f=g<.015?0:g>.985?1:g;return {page:Math.max(1,Math.min(total,Math.round(f*(total-1))+1)),at:vertical?event.clientY-r.top:event.clientX-r.left};};
 const aim=event=>{const p=pageAt(event),id=++request.current;setPeek(old=>old?.page===p.page?{...old,at:p.at}:{...p,url:null});if(preview)Promise.resolve(preview(p.page-1)).then(v=>{if(id===request.current&&v?.url)setPeek(o=>o&&o.page===p.page?{...o,url:v.url}:o);}).catch(()=>{});};
 const leave=()=>{setPeek(null);request.current++;};
 return <span ref={box} className="rd-scrub">
  <input type="range" className="rd-scrub-input" aria-label="Перейти к странице" aria-orientation={vertical?'vertical':'horizontal'} aria-valuetext={'Страница '+current+' из '+total+(chapter?' · '+chapter:'')} min="1" max={total} step="1" value={current}
   onChange={event=>onPage(Number(event.target.value)-1)}
   onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();event.currentTarget.focus({preventScroll:true});event.currentTarget.setPointerCapture(event.pointerId);onPage(pageAt(event).page-1);aim(event);}}
   onPointerMove={event=>{aim(event);if(event.currentTarget.hasPointerCapture(event.pointerId))onPage(pageAt(event).page-1);}}
   onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);if(event.pointerType!=='mouse')leave();}}
   onPointerLeave={event=>{if(!event.currentTarget.hasPointerCapture(event.pointerId))leave();}} onBlur={leave}/>
  {peek&&<span className="rd-peek" style={vertical?{top:peek.at}:{left:peek.at}}>{peek.url&&<img src={peek.url} alt="" draggable={false}/>}<b>{peek.page}</b></span>}
 </span>;
}

// A row of buttons that unrolls smoothly (grid 0fr → 1fr, nothing measured).
const Unroll=({open,vertical,children})=><span className={'rd-unroll'+(open?' is-open':'')+(vertical?' is-vertical':'')} inert={!open||undefined}><span className="rd-unroll-inner">{children}</span></span>;

export default function ReaderDock({title,chapterLabel,full,embedded,vertical,compact,visible,onClose,onExitFullscreen,onFullscreen,progress,onPage,preview,flip,
 onPrevious,onNext,canPrevious,canNext,onChapters,onSettings,onPreviews,translate,actions,activePanel,keepOpen,release}){
 const reduce=useReducedMotion(),split=!!full,host=useRef(null),[open,setOpen]=useState(false),[named,setNamed]=useState(false),[span,setSpan]=useState(0);
 const total=Math.max(1,progress?.total||1),current=Math.max(0,Math.min(total,progress?.current||0));
 const fraction=Number.isFinite(progress?.fraction)?Math.max(0,Math.min(1,progress.fraction)):total>1?Math.max(0,current-1)/(total-1):1;
 // A spread shows both pages («2–3»), as the old page column did.
 const spreadLabel=progress?.start&&progress?.end&&progress.start!==progress.end?progress.start+'–'+progress.end:progress?.label&&!String(progress.label).includes('/')?progress.label:current;
 const touch=typeof matchMedia==='function'&&matchMedia('(pointer: coarse)').matches,showBack=split||!embedded;
 useEffect(()=>{setOpen(false);setNamed(false);},[split]);
 // How far the islands travel from the centre to their corners (one read per change).
 useLayoutEffect(()=>{const r=host.current?.getBoundingClientRect();if(r)setSpan(vertical?r.height:r.width);},[split,vertical]);
 const PrevIcon=vertical?ChevronUp:flip?ChevronRight:ChevronLeft,NextIcon=vertical?ChevronDown:flip?ChevronLeft:ChevronRight;
 const prev=<button key="prev" type="button" className="reader-control" aria-label="Назад" title="Предыдущая страница" disabled={!canPrevious} onClick={onPrevious}><PrevIcon size={17}/></button>;
 const next=<button key="next" type="button" className="reader-control" aria-label="Вперёд" title="Следующая страница" disabled={!canNext} onClick={onNext}><NextIcon size={17}/></button>;
 const screen=<button key="screen" type="button" className="reader-control reader-fullscreen" aria-label={full?'Выйти из полного экрана':'На весь экран'} title={full?'Обычный размер':'На весь экран'} onClick={full?onExitFullscreen:onFullscreen}>{full?<Minimize size={16}/>:<Maximize size={16}/>}</button>;
 const arrows=flip&&!vertical?[next,prev]:[prev,next];
 const extras=<>{split&&arrows}
  {onPreviews&&<button type="button" className="reader-control" aria-label="Превью страниц" title="Страницы главы" aria-expanded={activePanel==='previews'} onClick={onPreviews}><Grid2X2 size={16}/></button>}
  {actions}{split&&screen}</>;
 const primary=<>{!split&&arrows}
  <button type="button" className="reader-control rd-chapters" aria-label="Главы и тома" title="Главы и страницы" aria-expanded={activePanel==='contents'} onClick={onChapters}>
   <ListOrdered size={16}/><span className="reader-page-count" aria-live="polite"><strong>{spreadLabel}</strong>{' '}<small>из {total}</small></span>
  </button>
  {translate}
  <button type="button" className="reader-control" aria-label="Настройки читалки" title="Настройки читалки" aria-expanded={activePanel==='settings'} onClick={onSettings}><Settings2 size={16}/></button>
  {!split&&screen}</>;
 const line=<span className="rd-line" aria-hidden="true"><i style={{transform:`${vertical?'scaleY':'scaleX'}(${Math.max(.002,fraction)})`,transformOrigin:vertical?'50% 0':flip&&!vertical?'100% 50%':'0 50%'}}/></span>;
 const scrub=onPage&&total>1&&<Scrub progress={progress} onPage={onPage} preview={preview} vertical={vertical} flip={flip&&!vertical} chapter={chapterLabel}/>;
 const more=<button type="button" className="reader-control rd-more" aria-label={open?'Скрыть кнопки':'Все кнопки'} aria-expanded={open} onClick={()=>setOpen(v=>!v)}><Ellipsis size={16}/></button>;
 // Where a «more» button exists it alone opens the row; elsewhere pointing at the glass does.
 const hover=compact||touch?{}:{onPointerEnter:event=>{if(event.pointerType==='mouse')setOpen(true);},onPointerLeave:event=>{if(event.pointerType==='mouse')setOpen(false);}};
 const reach=Math.max(0,span/2-80),axis=vertical?'y':'x';
 return <div ref={host} data-chapter={chapterLabel||undefined} className={'reader-dock'+(split?' is-split':' is-joined')+(vertical?' is-vertical':'')+(visible||split?' is-on':'')+(compact?' is-compact':'')}
  onPointerEnter={keepOpen} onPointerLeave={release} onFocusCapture={keepOpen} onBlurCapture={release} inert={!visible&&!split&&!activePanel}>
  <AnimatePresence initial={false}>
   {!split&&<motion.div key="bar" className="rd-glass rd-bar" initial={{opacity:0,scale:.96}} animate={{opacity:1,scale:1}} exit={{opacity:0,scale:.94,transition:fade}} transition={reduce?{duration:0}:fade} {...hover}>
    {line}{scrub}
    {showBack&&<button type="button" className="reader-control rd-back" aria-label="Закрыть просмотр" title="Закрыть" onClick={onClose}><ArrowLeft size={17}/></button>}
    {!vertical&&<span className="rd-title"><strong className="mv-viewer-title">{title}</strong>{chapterLabel&&<small>{chapterLabel}</small>}</span>}
    <span className="rd-group"><Unroll open={open} vertical={vertical}>{extras}</Unroll>{(compact||touch)&&more}{primary}</span>
   </motion.div>}
   {split&&showBack&&<motion.div key="lead" className="rd-glass rd-island rd-lead" initial={reduce?{opacity:0}:{opacity:0,[axis]:reach,scale:.92}} animate={{opacity:1,[axis]:0,scale:1}} exit={{opacity:0,scale:.92,transition:fade}} transition={reduce?{duration:0}:glide}
    onPointerEnter={event=>{if(event.pointerType==='mouse')setNamed(true);}} onPointerLeave={()=>setNamed(false)}>
    <button type="button" className="reader-control rd-back" aria-label={embedded?'Вернуться к главам':'Закрыть просмотр'} title={embedded?'К странице тайтла':'Закрыть'} onClick={embedded?onExitFullscreen:onClose} onFocus={()=>setNamed(true)} onBlur={()=>setNamed(false)}>
     <ArrowLeft size={17}/>{!vertical&&<Unroll open={named}><span className="rd-back-name">{title}</span></Unroll>}
    </button>
   </motion.div>}
   {split&&<motion.div key="tools" className="rd-glass rd-island rd-tools" initial={reduce?{opacity:0}:{opacity:0,[axis]:-reach,scale:.92}} animate={{opacity:1,[axis]:0,scale:1}} exit={{opacity:0,scale:.92,transition:fade}} transition={reduce?{duration:0}:{...glide,delay:.03}} {...hover}>
    {line}{scrub}
    <span className="rd-group"><Unroll open={open} vertical={vertical}>{extras}</Unroll>{(compact||touch)&&more}{primary}</span>
   </motion.div>}
  </AnimatePresence>
 </div>;
}

// Chapters of the title in volumes: number, name and the translating team.
export function ReaderChapterPanel({chapters,current,onChoose}){
 const volumes=[...new Set(chapters.map(c=>Number(c.season)||1))];
 const now=useRef(null);useEffect(()=>{now.current?.scrollIntoView({block:'center'});},[]);
 return <div className="rd-chapters-panel">{volumes.map(v=><section key={v}>
  {volumes.length>1&&<h3>Том {v}</h3>}
  <ol>{chapters.filter(c=>(Number(c.season)||1)===v).map(c=>{const on=c.id===current;return <li key={c.id}><button ref={on?now:undefined} type="button" aria-current={on||undefined} onClick={()=>onChoose(c)}>
   <b>{c.episode??'—'}</b><span><strong>{c.episodeTitle||c.name?.split(' · ').at(-1)||'Глава '+c.episode}</strong>{(c.translator||c.dub)&&<small>{c.translator||c.dub}</small>}</span>
  </button></li>;})}</ol>
 </section>)}</div>;
}
