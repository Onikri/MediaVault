'use client';
import {useId,useState,useRef} from 'react';
import {motion,useMotionValueEvent,useReducedMotion,useScroll,useTransform} from 'motion/react';

// A scroll-driven SVG aperture, inspired by the supplied reference's mask
// approach. The media stays in the same React tree throughout the reveal.
function aperture(progress){
 const x=.075*(1-progress),y=.10*(1-progress),r=.12*(1-progress);
 return `M ${x+r} ${y} H ${1-x-r} Q ${1-x} ${y} ${1-x} ${y+r} V ${1-y-r} Q ${1-x} ${1-y} ${1-x-r} ${1-y} H ${x+r} Q ${x} ${1-y} ${x} ${1-y-r} V ${y+r} Q ${x} ${y} ${x+r} ${y} Z`;
}
export default function PlaybackReveal({children,active=false}){
 const root=useRef(null),id='playback-aperture-'+useId().replace(/[^\w-]/g,''),reduce=useReducedMotion(),[interacting,setInteracting]=useState(false);
 const {scrollYProgress}=useScroll({target:root,offset:['start end','start 25%']});
 const path=useTransform(scrollYProgress,aperture),scale=useTransform(scrollYProgress,[0,1],[.97,1]);
 useMotionValueEvent(scrollYProgress,'change',value=>{if(value<.95)setInteracting(false);});
 const open=reduce||interacting;
 return <motion.div ref={root} className={'title-playback-reveal'+(open?' is-revealed':'')} style={{clipPath:open?'none':`url(#${id})`,scale:open?1:scale}}
  onPointerDownCapture={()=>setInteracting(true)} onPointerLeave={()=>setInteracting(false)} onFocusCapture={()=>setInteracting(true)} onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget))setInteracting(false);}}>
  <svg width="0" height="0" className="title-playback-mask" aria-hidden="true"><defs><clipPath id={id} clipPathUnits="objectBoundingBox"><motion.path d={path}/></clipPath></defs></svg>
  {children}
 </motion.div>;
}
