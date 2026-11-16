import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import {ChevronDown} from 'lucide-react';
import './fold.css';

// A long block of a page (all episode dates, the whole staff list) shows its
// first screenful, fading out at the edge; «Показать всё» unrolls the rest in
// place with a spring, and folding it back keeps the reader where they were.
// Nothing is hidden for good and nothing is removed: short content renders as is.
const PHONE='(max-width:640px)';
export default function Fold({limit=640,phoneLimit=limit,label='Показать всё',className='',children}){
 const reduce=useReducedMotion(),root=useRef(null),inner=useRef(null);
 const [full,setFull]=useState(0),[open,setOpen]=useState(false);
 const [phone,setPhone]=useState(()=>typeof matchMedia==='function'&&matchMedia(PHONE).matches);
 useEffect(()=>{if(typeof matchMedia!=='function')return;const query=matchMedia(PHONE),change=()=>setPhone(query.matches);query.addEventListener('change',change);return()=>query.removeEventListener('change',change);},[]);
 useLayoutEffect(()=>{
  const node=inner.current;if(!node)return;
  const measure=()=>setFull(node.scrollHeight);measure();
  const observer=new ResizeObserver(measure);observer.observe(node);return()=>observer.disconnect();
 },[]);
 const cap=phone?phoneLimit:limit,folds=full>cap*1.2,closed=folds&&!open;
 function toggle(){
  if(open){const top=root.current?.getBoundingClientRect().top??0;if(top<0)root.current.scrollIntoView({behavior:reduce?'instant':'smooth',block:'start'});}
  setOpen(!open);
 }
 return <div ref={root} className={'fold '+className} data-folded={closed||undefined}>
  <motion.div className="fold-body" initial={false} animate={{height:closed?cap:full||'auto'}} transition={reduce?{duration:0}:{type:'spring',stiffness:150,damping:24,mass:.9}}>
   <div ref={inner}>{children}</div>
  </motion.div>
  {folds&&<button type="button" className="fold-toggle" aria-expanded={open} onClick={toggle}><span>{open?'Свернуть':label}</span><ChevronDown size={16} aria-hidden="true"/></button>}
 </div>;
}
