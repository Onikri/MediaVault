import {useId} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import './ui-segmented.css';

// Radio group whose selection pill morphs between options (shared layout id).
export default function UiSegmented({label,value,options,onChange,disabled=false,className='',size}){
 const id=useId(),reduce=useReducedMotion();
 return <div className={'mv-segmented'+(size?' is-'+size:'')+(className?' '+className:'')} role="radiogroup" aria-label={label}>
  {options.map(([key,text,hint])=>{const active=String(key)===String(value);return <button key={String(key)} type="button" role="radio" aria-checked={active} title={hint} disabled={disabled} onClick={()=>!active&&onChange(key)}>
   {active&&<motion.span layoutId={id+'-pill'} className="mv-segmented-pill" transition={reduce?{duration:0}:{type:'spring',stiffness:460,damping:38}}/>}
   <span className="mv-segmented-text">{text}</span>
  </button>;})}
 </div>;
}
