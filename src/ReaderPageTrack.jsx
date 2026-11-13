import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {pageAtPosition,pageTrackPoints,pageTrackPosition} from './reader-page-track.js';
import './reader-page-track.css';

// One page, one position: the marker shows the page being read (or, in a
// continuous webtoon, how far down the chapter the reader is). Ticks mark page
// boundaries; a preview of the page under the pointer follows it.
const spring={type:'spring',stiffness:520,damping:42,mass:.7};
function PagePreview({page,total,vertical,length,preview,reduce}){
 const [shown,setShown]=useState(null),direction=useRef(1),last=useRef(page),request=useRef(0);
 useEffect(()=>{
  if(!preview||!page)return;const id=++request.current;
  const timer=setTimeout(()=>{Promise.resolve(preview(page-1)).then(value=>{if(id!==request.current||!value?.url)return;direction.current=page>=last.current?1:-1;last.current=page;setShown({page,...value});}).catch(()=>{});},shown?35:0);
  return()=>clearTimeout(timer);
 },[page,preview]);
 const width=vertical?96:92,ratio=Math.min(1.75,Math.max(.6,shown?.ratio||1.42)),height=Math.round(width*ratio),offset=pageTrackPosition(page,total)*length;
 const shift=vertical?Math.max(-30,Math.min(length-height+30,offset-height/2)):Math.max(-6,Math.min(length-width+6,offset-width/2)),axis=vertical?'y':'x';
 return <motion.div className="reader-page-preview" initial={{opacity:0,scale:.9,[axis]:shift}} animate={{opacity:1,scale:1,[axis]:shift}} exit={{opacity:0,scale:.92,transition:{duration:.14}}} transition={reduce?{duration:0}:spring}>
  {preview&&<motion.div className="reader-page-preview-frame" animate={{width,height}} transition={reduce?{duration:0}:spring}>
   <AnimatePresence initial={false} custom={direction.current}>
    {shown&&<motion.img key={shown.page} src={shown.url} alt="" draggable={false} initial={reduce?{opacity:0}:{opacity:0,[axis]:direction.current*14,scale:1.04}} animate={{opacity:1,x:0,y:0,scale:1}} exit={reduce?{opacity:0}:{opacity:0,[axis]:-direction.current*10,scale:.98}} transition={reduce?{duration:.1}:{type:'spring',stiffness:420,damping:34}}/>}
   </AnimatePresence>
  </motion.div>}
  <span className="reader-page-hint">Страница {page}</span>
 </motion.div>;
}
export default function ReaderPageTrack({progress,onPage,orientation='vertical',chapter='',preview}){
 const line=useRef(null),[length,setLength]=useState(200),[hover,setHover]=useState(null),[dragging,setDragging]=useState(false),reduce=useReducedMotion(),vertical=orientation==='vertical';
 const total=Math.max(1,progress.total||1),current=Math.max(1,Math.min(total,progress.current||1));
 const start=Math.max(1,Math.min(total,progress.start||current)),end=Math.max(start,Math.min(total,progress.end||current));
 // A continuous webtoon reports its scroll fraction; pages report their index.
 const position=Number.isFinite(progress.fraction)?Math.max(0,Math.min(1,progress.fraction)):pageTrackPosition(current,total);
 useLayoutEffect(()=>{const update=()=>{const r=line.current?.getBoundingClientRect();if(r)setLength(vertical?r.height:r.width);};update();const observer=new ResizeObserver(update);if(line.current)observer.observe(line.current);return()=>observer.disconnect();},[vertical]);
 function point(event,seek=false){
  const r=line.current?.getBoundingClientRect();if(!r)return;
  const fraction=vertical?(event.clientY-r.top)/r.height:(event.clientX-r.left)/r.width,page=pageAtPosition(fraction,total);
  setHover(page);if(seek)onPage(page-1);
 }
 const leave=()=>setHover(null),axis=vertical?'top':'left',extent=vertical?'scaleY':'scaleX';
 const label=start!==end?start+'–'+end:String(current);
 const ticks=total<=90?pageTrackPoints(total,length*3):[];
 return <div className={'reader-page-track'+(vertical?' is-vertical':'')+(hover!==null?' is-hovered':'')+(dragging?' is-dragging':'')}>
  <span className="reader-page-count" aria-live="polite"><strong>{label}</strong>{' '}<small>из {total}</small></span>
  <div className="reader-page-rail" ref={line}>
   <i className="reader-page-groove" aria-hidden="true"/>
   <motion.i className="reader-page-fill" aria-hidden="true" initial={false} animate={{[extent]:position}} transition={reduce?{duration:0}:spring}/>
   {ticks.length>1&&<span className="reader-page-ticks" aria-hidden="true">{ticks.map(page=><i key={page} className={page>=start&&page<=end?'is-current':page<start?'is-read':undefined} style={{[axis]:pageTrackPosition(page,total)*100+'%'}}/>)}</span>}
   <motion.i className="reader-page-thumb" aria-hidden="true" initial={false} animate={{[axis]:position*100+'%'}} transition={reduce||dragging?{duration:0}:spring}/>
   <AnimatePresence>{hover!==null&&<PagePreview key="preview" page={hover} total={total} vertical={vertical} length={length} preview={preview} reduce={reduce}/>}</AnimatePresence>
   <input type="range" className="reader-progress-slider" aria-label="Перейти к странице" aria-orientation={orientation} aria-valuetext={'Страница '+current+' из '+total+(chapter?' · '+chapter:'')} min="1" max={total} step="1" value={current} onChange={event=>onPage(Number(event.target.value)-1)} onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();event.currentTarget.focus({preventScroll:true});event.currentTarget.setPointerCapture(event.pointerId);setDragging(true);point(event,true);}} onPointerMove={event=>{if(event.pointerType==='touch'&&!event.currentTarget.hasPointerCapture(event.pointerId))return;point(event,event.currentTarget.hasPointerCapture(event.pointerId));}} onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId)){point(event,true);event.currentTarget.releasePointerCapture(event.pointerId);}setDragging(false);if(event.pointerType==='touch')leave();}} onPointerLeave={event=>{if(!event.currentTarget.hasPointerCapture(event.pointerId))leave();}} onLostPointerCapture={event=>{setDragging(false);if(event.pointerType!=='mouse')leave();}} onBlur={leave}/>
  </div>
 </div>;
}
