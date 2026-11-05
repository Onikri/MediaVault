import {useLayoutEffect,useRef,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {pageAtPosition,pageTrackPoints,pageTrackPosition} from './reader-page-track.js';
import './reader-page-track.css';
export default function ReaderPageTrack({progress,onPage,orientation='horizontal',chapter=''}){
 const line=useRef(null),[length,setLength]=useState(200),[hover,setHover]=useState(null),reduced=useReducedMotion(),vertical=orientation==='vertical',total=progress.total,current=Math.min(total,progress.current||1);
 useLayoutEffect(()=>{const update=()=>{const r=line.current?.getBoundingClientRect();if(r)setLength(vertical?r.height:r.width);};update();const observer=new ResizeObserver(update);if(line.current)observer.observe(line.current);return()=>observer.disconnect();},[vertical]);
 const start=pageTrackPosition(progress.start||current,total)*100,end=pageTrackPosition(progress.end||current,total)*100,position=vertical?'top':'left',extent=vertical?'height':'width';
 function point(event,seek=false){const r=line.current?.getBoundingClientRect();if(!r)return;const fraction=vertical?(event.clientY-r.top)/r.height:(event.clientX-r.left)/r.width,page=pageAtPosition(fraction,total);setHover(page);if(seek)onPage(page-1);}
 return <div className={'reader-page-track'+(vertical?' is-vertical':'')}>
 <span className="reader-page-count" aria-live="polite">{vertical?<>{progress.start&&progress.end&&progress.start!==progress.end?progress.start+'–'+progress.end:current}<br/>/ {total}</>:progress.label||current+' / '+total}</span>
 <div className="reader-page-rail" ref={line}><i className="reader-page-rule"/>{pageTrackPoints(total,length).map(page=><i key={page} className={'reader-page-point'+(page>=(progress.start||current)&&page<=(progress.end||current)?' is-current':'')+(hover&&Math.abs(pageTrackPosition(hover,total)-pageTrackPosition(page,total))*length<12?' is-near':'')} style={{[position]:pageTrackPosition(page,total)*100+'%'}}/>)}
 <motion.i className="reader-page-halo" initial={false} animate={{[position]:`calc(${start}% - 7px)`,[extent]:`calc(${Math.max(0,end-start)}% + 14px)`}} transition={reduced?{duration:0}:{type:'spring',stiffness:380,damping:32}}/>
 <AnimatePresence>{hover!==null&&<motion.span key="hint" className="reader-page-hint" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} style={{[position]:pageTrackPosition(hover,total)*100+'%'}}>Страница {hover}</motion.span>}</AnimatePresence>
 </div>
 <input type="range" className="reader-progress-slider" aria-label="Перейти к странице" aria-orientation={orientation} aria-valuetext={'Страница '+current+' из '+total+(chapter?' · '+chapter:'')} min="1" max={total} step="1" value={current} onChange={event=>onPage(Number(event.target.value)-1)} onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();event.currentTarget.focus({preventScroll:true});event.currentTarget.setPointerCapture(event.pointerId);point(event,true);}} onPointerMove={event=>point(event,event.currentTarget.hasPointerCapture(event.pointerId))} onPointerUp={event=>{if(event.currentTarget.hasPointerCapture(event.pointerId)){point(event,true);event.currentTarget.releasePointerCapture(event.pointerId);}}} onPointerLeave={event=>{if(!event.currentTarget.hasPointerCapture(event.pointerId))setHover(null);}} onLostPointerCapture={()=>setHover(null)} onBlur={()=>setHover(null)}/>
 </div>;
}
