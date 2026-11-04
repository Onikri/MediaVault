import {useId,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import './reader-morph.css';
const modes=[['pages','По страницам'],['focus','Вписать целиком'],['spread','Разворот'],['scroll','Вебтун']];
export function ReaderModeIcon({mode,active=false}){
 const clip=useId(),reduced=useReducedMotion(),moving=active&&!reduced;
 const loop={duration:2.8,repeat:Infinity,repeatDelay:.6,ease:'easeInOut'};
 const page=(x,y,w,h,alternate=false)=><g><rect x={x} y={y} width={w} height={h} rx="1.5" fill="currentColor" opacity=".8"/><path d={`M${x+2} ${y+3}h${w-4}v${alternate?4:6}h-${w-4}z`} fill="var(--color-canvas,#141418)" opacity=".55"/><path d={`M${x+2} ${y+h-4}h${w-4}`} stroke="var(--color-canvas,#141418)" strokeWidth="1.5"/></g>;
 return <svg viewBox="0 0 36 30" width="36" height="30" aria-hidden="true" data-motion={moving?'pages':'still'}><defs><clipPath id={clip}><rect x="5" y="4" width="26" height="22" rx="3"/></clipPath></defs><rect x="2" y="2" width="32" height="26" rx="7" fill="currentColor" opacity=".08"/>
  <g clipPath={`url(#${clip})`}>{mode==='scroll'?<motion.g animate={{y:moving?[0,-13]:0}} transition={{duration:2,repeat:Infinity,ease:'linear'}}>{[0,1,2,3].map(i=><g key={i}>{page(11,2+i*13,14,10,i%2===0)}</g>)}</motion.g>:mode==='spread'?<>{page(7,7,10,16)}{page(19,7,10,16,true)}<motion.g style={{transformOrigin:'18px 15px'}} animate={{scaleX:moving?[1,.04,-1,-1]:1,opacity:moving?[1,1,.8,0]:1}} transition={loop}>{page(19,7,10,16)}</motion.g></>:mode==='focus'?<><path d="M6 10V6h5m14 0h5v4M6 20v4h5m14 0h5v-4" stroke="currentColor" fill="none" opacity=".4"/><motion.g style={{transformOrigin:'18px 15px'}} animate={{scale:moving?[1.6,1,1]:1,y:moving?[3,0,0]:0}} transition={loop}>{page(12,6,12,18)}</motion.g></>:<motion.g animate={{x:moving?[0,-22,-22]:0}} transition={loop}>{page(11,6,14,18)}{page(33,6,14,18,true)}</motion.g>}</g>
 </svg>;
}
function ModeButton({id,label,value,onChange,compact}){
 const [hover,setHover]=useState(false);
 return <button aria-label={label} title={label} aria-pressed={value===id} onPointerEnter={()=>setHover(true)} onPointerLeave={()=>setHover(false)} onFocus={()=>setHover(true)} onBlur={()=>setHover(false)} onClick={()=>onChange(id)}><ReaderModeIcon mode={id} active={value===id||hover}/>{!compact&&<span>{label}</span>}</button>;
}
export default function ReaderModePicker({value,onChange,compact=false}){
 return <div className={'reader-mode-picker'+(compact?' is-compact':'')} role="group" aria-label="Режим чтения">{modes.map(([id,label])=><ModeButton key={id} {...{id,label,value,onChange,compact}}/>)}</div>;
}
