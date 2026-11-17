import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import './shortcut-sheet.css';

// One keyboard sheet for the whole site. The video player and every reader
// call showShortcuts(title, groups) on «?»; the host draws the sheet inside
// the fullscreen element when there is one, so it shows over a fullscreen
// player too. groups: [[heading, [[keys, label], …]], …], keys like 'Shift+N'
// or 'J / ←'.
export function showShortcuts(title,groups){dispatchEvent(new CustomEvent('mediavault-shortcuts',{detail:{title,groups}}));}
import {isHelpKey} from './reader-keys.js';
export {isHelpKey};

export default function ShortcutHost(){
 const reduce=useReducedMotion(),[sheet,setSheet]=useState(null),[target,setTarget]=useState(null),panel=useRef(null),back=useRef(null);
 useEffect(()=>{
  const open=event=>{back.current=document.activeElement;setTarget(document.fullscreenElement||document.body);setSheet(old=>old&&old.title===event.detail.title?null:event.detail);};
  addEventListener('mediavault-shortcuts',open);return()=>removeEventListener('mediavault-shortcuts',open);
 },[]);
 useEffect(()=>{
  if(!sheet)return;
  const key=event=>{if(event.key==='Escape'||isHelpKey(event)){event.preventDefault();event.stopImmediatePropagation();close();}};
  const leave=()=>{if(!document.fullscreenElement||!document.fullscreenElement.contains(panel.current))close();};
  addEventListener('keydown',key,true);document.addEventListener('fullscreenchange',leave);
  requestAnimationFrame(()=>panel.current?.focus({preventScroll:true}));
  return()=>{removeEventListener('keydown',key,true);document.removeEventListener('fullscreenchange',leave);};
 },[sheet]);
 function close(){setSheet(null);back.current?.focus?.({preventScroll:true});}
 if(!target)return null;
 const spring=reduce?{duration:.12}:{type:'spring',stiffness:380,damping:32};
 return createPortal(<AnimatePresence>{sheet&&<motion.div key="shortcuts" className="shortcut-scrim" onPointerDown={event=>{if(event.target===event.currentTarget)close();}} initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduce?.1:.22}}>
  <motion.section ref={panel} tabIndex={-1} className="shortcut-sheet" role="dialog" aria-modal="true" aria-label={'Клавиши: '+sheet.title}
   initial={reduce?{opacity:0}:{opacity:0,y:18,scale:.96,rotateX:8,filter:'blur(8px)'}} animate={{opacity:1,y:0,scale:1,rotateX:0,filter:'blur(0px)'}} exit={reduce?{opacity:0}:{opacity:0,y:10,scale:.98,filter:'blur(6px)'}} transition={spring}>
   <header><span>Клавиши</span><h2>{sheet.title}</h2></header>
   <div className="shortcut-groups">{sheet.groups.filter(([,rows])=>rows.length).map(([heading,rows],g)=><div key={heading} className="shortcut-group">
    <h3>{heading}</h3>
    <dl>{rows.map(([keys,label],i)=><motion.div key={keys} initial={reduce?false:{opacity:0,x:-8}} animate={{opacity:1,x:0}} transition={reduce?{duration:0}:{delay:.05+g*.06+i*.025,duration:.28,ease:[.22,1,.36,1]}}>
     <dt>{String(keys).split(' / ').map((alt,a)=><span key={alt} className="shortcut-alt">{a>0&&<i>или</i>}{alt.split('+').map(cap=><kbd key={cap}>{cap}</kbd>)}</span>)}</dt><dd>{label}</dd>
    </motion.div>)}</dl>
   </div>)}</div>
   <p className="shortcut-foot"><kbd>?</kbd> или <kbd>Esc</kbd> — закрыть</p>
  </motion.section>
 </motion.div>}</AnimatePresence>,target);
}
