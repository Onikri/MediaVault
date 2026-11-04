'use client';
import {Children,useRef,useLayoutEffect} from 'react';
import {motion,useMotionValue,useSpring,useReducedMotion,useScroll,useTransform} from 'motion/react';
import './title-showcase.css';

// The supplied Skiper29 reference keeps its atmosphere above a single content
// group. Use that scroll composition with our own geometry and existing Motion.
export default function TitleShowcase({background,children}){
 const root=useRef(null),content=useRef(null),reduce=useReducedMotion();
 useLayoutEffect(()=>{const update=()=>root.current?.style.setProperty('--showcase-content-height',(content.current?.offsetHeight||0)+'px');update();const observer=new ResizeObserver(update);if(content.current)observer.observe(content.current);return()=>observer.disconnect();},[]);
 const {scrollYProgress}=useScroll({target:root,offset:['start start','end start']});
 const pointer=useMotionValue(0),x=useSpring(pointer,{stiffness:100,damping:25});
 const y=useTransform(scrollYProgress,[0,1],[0,270]),scale=useTransform(scrollYProgress,[0,1],[1.06,1.18]);
 const posterY=useTransform(scrollYProgress,[0,1],[0,-165]),copyY=useTransform(scrollYProgress,[0,1],[0,-75]),infoY=useTransform(scrollYProgress,[0,1],[0,-35]);
 const posterX=useTransform(x,value=>-value*.35);
 const opacity=useTransform(scrollYProgress,[0,.6,1],[1,1,.3]),parts=Children.toArray(children);
 return <section ref={root} className={'hero-stage title-hero title-feature title-showcase is-revealed'+(!parts[2]?' without-info':'')} onPointerMove={event=>{if(!reduce&&event.pointerType==='mouse'){const r=event.currentTarget.getBoundingClientRect();pointer.set((event.clientX-r.left-r.width/2)/r.width*28);}}} onPointerLeave={()=>pointer.set(0)}>
  {background(reduce?undefined:{y,x,scale})}
  <div ref={content} className="title-showcase-content">
   <motion.div className="title-showcase-poster-layer" style={reduce?undefined:{y:posterY,x:posterX,opacity}}>{parts[0]}</motion.div>
   <motion.div className="title-showcase-copy-layer" style={reduce?undefined:{y:copyY,opacity}}>{parts[1]}</motion.div>
   {parts[2]&&<motion.div className="title-showcase-info-layer" style={reduce?undefined:{y:infoY,opacity}}>{parts[2]}</motion.div>}
  </div>
 </section>;
}
