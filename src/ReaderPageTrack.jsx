import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {pageAtPosition,pageTrackPoints,pageTrackPosition} from './reader-page-track.js';
import './reader-page-track.css';

// Points only, no rule between them. Points near the pointer swell like a
// magnifier (imperative, one rAF per move, no React render per frame); a page
// preview follows the pointer and morphs between pages.
const spring={type:'spring',stiffness:520,damping:40,mass:.7};
function PagePreview({page,total,vertical,length,preview,reduce}){
 const [shown,setShown]=useState(null),direction=useRef(1),last=useRef(page),request=useRef(0);
 useEffect(()=>{
  if(!preview||!page)return;const id=++request.current;
  const timer=setTimeout(()=>{Promise.resolve(preview(page-1)).then(value=>{if(id!==request.current||!value?.url)return;direction.current=page>=last.current?1:-1;last.current=page;setShown({page,...value});}).catch(()=>{});},shown?35:0);
  return()=>clearTimeout(timer);
 },[page,preview]);
 const width=vertical?84:92,ratio=Math.min(1.75,Math.max(.6,shown?.ratio||1.42)),height=Math.round(width*ratio),offset=pageTrackPosition(page,total)*length;
 // Centre on the hovered point, kept inside the rail so it never leaves the bar.
 const shift=vertical?Math.max(-20,Math.min(length-height,offset-height/2)):Math.max(-6,Math.min(length-width+6,offset-width/2)),axis=vertical?'y':'x';
 return <motion.div className="reader-page-preview" initial={{opacity:0,scale:.86,[axis]:shift}} animate={{opacity:1,scale:1,[axis]:shift}} exit={{opacity:0,scale:.9,transition:{duration:.14}}} transition={reduce?{duration:0}:spring}>
  {preview&&<motion.div className="reader-page-preview-frame" animate={{width,height}} transition={reduce?{duration:0}:spring}>
   <AnimatePresence initial={false} custom={direction.current}>
    {shown&&<motion.img key={shown.page} src={shown.url} alt="" draggable={false} custom={direction.current} initial={reduce?{opacity:0}:{opacity:0,[vertical?'y':'x']:direction.current*14,scale:1.04}} animate={{opacity:1,x:0,y:0,scale:1}} exit={reduce?{opacity:0}:{opacity:0,[vertical?'y':'x']:-direction.current*10,scale:.98}} transition={reduce?{duration:.1}:{type:'spring',stiffness:420,damping:34}}/>}
   </AnimatePresence>
  </motion.div>}
  <span className="reader-page-hint">Страница {page}</span>
 </motion.div>;
}
export default function ReaderPageTrack({progress,onPage,orientation='horizontal',chapter='',preview}){
 const line=useRef(null),points=useRef(null),frame=useRef(0),pointer=useRef(null),[length,setLength]=useState(200),[hover,setHover]=useState(null),reduce=useReducedMotion(),vertical=orientation==='vertical',total=progress.total,current=Math.min(total,progress.current||1);
 useLayoutEffect(()=>{const update=()=>{const r=line.current?.getBoundingClientRect();if(r)setLength(vertical?r.height:r.width);};update();const observer=new ResizeObserver(update);if(line.current)observer.observe(line.current);return()=>observer.disconnect();},[vertical]);
 useEffect(()=>()=>cancelAnimationFrame(frame.current),[]);
 const start=pageTrackPosition(progress.start||current,total)*100,end=pageTrackPosition(progress.end||current,total)*100,position=vertical?'top':'left',extent=vertical?'height':'width';
 const magnify=()=>{frame.current=0;const nodes=points.current?.children;if(!nodes)return;const at=pointer.current;
  for(const node of nodes){const offset=Number(node.dataset.offset)*length,d=at===null?Infinity:Math.abs(offset-at),k=Math.max(0,1-d/38);node.style.setProperty('--swell',(1+k*k*1.9).toFixed(3));}
 };
 const schedule=()=>{if(!frame.current)frame.current=requestAnimationFrame(magnify);};
 function point(event,seek=false){
  const r=line.current?.getBoundingClientRect();if(!r)return;
  const fraction=vertical?(event.clientY-r.top)/r.height:(event.clientX-r.left)/r.width,page=pageAtPosition(fraction,total);
  pointer.current=Math.max(0,Math.min(1,fraction))*length;schedule();setHover(page);if(seek)onPage(page-1);
 }
 const leave=()=>{pointer.current=null;schedule();setHover(null);};
 return <div className={'reader-page-track'+(vertical?' is-vertical':'')+(hover!==null?' is-hovered':'')}>
 <span className="reader-page-count" aria-live="polite">{vertical?<>{progress.start&&progress.end&&progress.start!==progress.end?progress.start+'–'+progress.end:current}<br/>/ {total}</>:progress.label||current+' / '+total}</span>
 <div className="reader-page-rail" ref={line}>
  <motion.i className="reader-page-halo" initial={false} animate={{[position]:`calc(${start}% - 7px)`,[extent]:`calc(${Math.max(0,end-start)}% + 14px)`}} transition={reduce?{duration:0}:{type:'spring',stiffness:380,damping:32}}/>
  <span className="reader-page-points" ref={points}>{pageTrackPoints(total,length).map(page=>{const at=pageTrackPosition(page,total);return <i key={page} data-offset={at} className={'reader-page-point'+(page>=(progress.start||current)&&page<=(progress.end||current)?' is-current':'')} style={{[position]:at*100+'%'}}/>;})}</span>
  <AnimatePresence>{hover!==null&&<PagePreview key="preview" page={hover} total={total} vertical={vertical} length={length} preview={preview} reduce={reduce}/>}</AnimatePresence>
 </div>
 <input type="range" className="reader-progress-slider" aria-label="Перейти к странице" aria-orientation={orientation} aria-valuetext={'Страница '+current+' из '+total+(chapter?' · '+chapter:'')} min="1" max={total} step="1" value={current} onChange={event=>onPage(Number(event.target.value)-1)} onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();event.currentTarget.focus({preventScroll:true});event.currentTarget.setPointerCapture(event.pointerId);point(event,true);}} onPointerMove={event=>{if(event.pointerType==='touch'&&!event.currentTarget.hasPointerCapture(event.pointerId))return;point(event,event.currentTarget.hasPointerCapture(event.pointerId));}} onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId)){point(event,true);event.currentTarget.releasePointerCapture(event.pointerId);if(event.pointerType==='touch')leave();}}} onPointerLeave={event=>{if(!event.currentTarget.hasPointerCapture(event.pointerId))leave();}} onLostPointerCapture={event=>{if(event.pointerType!=='mouse')leave();}} onBlur={leave}/>
 </div>;
}
