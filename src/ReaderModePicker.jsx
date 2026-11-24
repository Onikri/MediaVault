import {useId,useState} from 'react';
import {LayoutGroup,motion,useReducedMotion} from 'motion/react';
import './reader-morph.css';
const modes=[['pages','По страницам','Страницы'],['focus','Вписать целиком','Целиком'],['spread','Разворот','Разворот'],['scroll','Вебтун','Вебтун']];
const turn={duration:.55,ease:[.22,1,.36,1]};

// Each mode draws what it does, and acts it out once when pointed at or
// chosen (a page turns, the frame fits, the book opens, the strip scrolls).
// Nothing moves while the panel just sits there.
function Glyph({mode,beat}){
 const clip=useId(),play=beat%2?'a':'b',same=v=>({a:v,b:v});
 const common={fill:'none',stroke:'currentColor',strokeWidth:1.5,strokeLinecap:'round',strokeLinejoin:'round'};
 const svg=children=><svg className="reader-mode-glyph" viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" {...common}>{children}</svg>;
 if(mode==='pages')return svg(<>
  <rect x="8.5" y="3" width="11.5" height="16" rx="2" opacity=".45"/>
  <motion.rect x="4" y="5" width="11.5" height="16" rx="2" fill="var(--glyph-fill)" style={{originX:0,originY:.5}} initial={false} animate={play} variants={same({scaleX:beat?[1,.08,1]:1,x:beat?[0,5,0]:0})} transition={turn}/>
 </>);
 if(mode==='focus'){
  const corner=(d,x,y)=><motion.path d={d} initial={false} animate={play} variants={same({x:beat?[0,x,0]:0,y:beat?[0,y,0]:0})} transition={turn}/>;
  return svg(<>
   {corner('M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9',2,2)}{corner('M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9',-2,2)}
   {corner('M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15',-2,-2)}{corner('M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15',2,-2)}
   <motion.rect x="8.5" y="7.5" width="7" height="9" rx="1.2" fill="var(--glyph-fill)" style={{originX:.5,originY:.5}} initial={false} animate={play} variants={same({scale:beat?[1,1.3,1]:1})} transition={turn}/>
  </>);
 }
 if(mode==='spread')return svg(<>
  <motion.path d="M12 6.5C10 5 7 4.5 4 5v13c3-.5 6 0 8 1.5" fill="var(--glyph-fill)" style={{originX:1,originY:.5}} initial={false} animate={play} variants={same({scaleX:beat?[1,.1,1]:1})} transition={turn}/>
  <motion.path d="M12 6.5c2-1.5 5-2 8-1.5v13c-3-.5-6 0-8 1.5" style={{originX:0,originY:.5}} initial={false} animate={play} variants={same({scaleX:beat?[1,.1,1]:1})} transition={{...turn,delay:.08}}/>
  <path d="M12 6.5v13"/>
 </>);
 return svg(<>
  <defs><clipPath id={clip}><rect x="6" y="2.5" width="12" height="19" rx="2.5"/></clipPath></defs>
  <rect x="6" y="2.5" width="12" height="19" rx="2.5"/>
  <motion.g clipPath={`url(#${clip})`} initial={false} animate={play} variants={same({y:beat?[0,-7,0]:0})} transition={{duration:.7,ease:[.65,0,.35,1]}}>
   <rect x="8.5" y="5" width="7" height="5.5" rx="1" fill="var(--glyph-fill)"/><rect x="8.5" y="12.5" width="7" height="5.5" rx="1"/><rect x="8.5" y="20" width="7" height="5.5" rx="1"/>
  </motion.g>
 </>);
}
export function ReaderModeIcon({mode,beat=0}){return <Glyph mode={mode} beat={beat}/>;}

function ModeButton({id,label,short,value,onChange,unavailable,compact,group}){
 const reduce=useReducedMotion(),[beat,setBeat]=useState(0),on=value===id,act=()=>{if(!reduce)setBeat(b=>b+1);};
 return <button aria-label={label} title={unavailable[id]||label} disabled={!!unavailable[id]} aria-pressed={on} onPointerEnter={event=>{if(event.pointerType==='mouse')act();}} onFocus={act} onClick={()=>{if(!on)act();onChange(id);}}>
  {on&&<motion.span layoutId={group+'-lit'} className="reader-mode-lit" transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:34}}/>}
  <ReaderModeIcon mode={id} beat={beat}/>{!compact&&<span className="reader-mode-label" aria-hidden="true">{short}</span>}
 </button>;
}
// unavailable: {mode: reason} — a mode this chapter cannot show, with why.
export default function ReaderModePicker({value,onChange,compact=false,unavailable={}}){
 const group=useId();
 return <LayoutGroup id={group}><div className={'reader-mode-picker'+(compact?' is-compact':'')} role="group" aria-label="Режим чтения">{modes.map(([id,label,short])=><ModeButton key={id} id={id} label={label} short={short} value={value} onChange={onChange} unavailable={unavailable} compact={compact} group={group}/>)}</div></LayoutGroup>;
}
