import {motion,useReducedMotion} from 'motion/react';
import './reader-morph.css';
const modes=[['pages','По страницам'],['focus','Вписать целиком'],['spread','Разворот'],['scroll','Вебтун']];
export function ReaderModeIcon({mode,active=false}){
 const reduced=useReducedMotion(),moving=active&&!reduced;
 return <svg viewBox="0 0 36 30" width="36" height="30" aria-hidden="true"><rect x="2" y="2" width="32" height="26" rx="7" fill="currentColor" opacity=".08"/>
  {mode==='focus'?<><rect x="6" y="6" width="24" height="18" rx="3" fill="none" stroke="currentColor" opacity=".35"/><motion.rect x="13" y="8" width="10" height="14" rx="2" fill="currentColor" animate={{scale:moving?[1,.88,1]:1}} transition={{duration:2.7,repeat:Infinity}}/></>:mode==='spread'?<><motion.rect x="7" y="7" width="10" height="16" rx="2" fill="currentColor" animate={{rotateY:moving?[0,-25,0]:0}} transition={{duration:2.4,repeat:Infinity,repeatDelay:.6}}/><rect x="19" y="7" width="10" height="16" rx="2" fill="currentColor" opacity=".55"/></>:mode==='scroll'?<g clipPath="inset(4px round 4px)"><motion.g animate={{y:moving?[0,-8,0]:0}} transition={{duration:2.7,repeat:Infinity,ease:'easeInOut'}}>{[0,1,2].map(i=><rect key={i} x="11" y={4+i*11} width="14" height="9" rx="2" fill="currentColor" opacity={i===1?.8:.4}/>)}</motion.g></g>:<motion.rect x="11" y="6" width="14" height="18" rx="2" fill="currentColor" animate={{x:moving?[0,3,0]:0,opacity:moving?[1,.55,1]:.8}} transition={{duration:2.4,repeat:Infinity,ease:'easeInOut'}}/>}
 </svg>;
}
export default function ReaderModePicker({value,onChange,compact=false}){
 return <div className={'reader-mode-picker'+(compact?' is-compact':'')} role="group" aria-label="Режим чтения">{modes.map(([id,label])=><button key={id} aria-label={label} title={label} aria-pressed={value===id} onClick={()=>onChange(id)}><ReaderModeIcon mode={id} active={value===id}/>{!compact&&<span>{label}</span>}</button>)}</div>;
}
