'use client';
import {Children,useRef,useLayoutEffect} from 'react';
import {motion,useMotionTemplate,useMotionValue,useSpring,useReducedMotion,useScroll,useTransform} from 'motion/react';
import './title-showcase.css';

const EASE=[.22,1,.36,1];
// The background keeps its scroll/pointer parallax. The foreground is one plane:
// it arrives with a staggered reveal, leaves together on scroll, and the poster
// answers the pointer with a small physical tilt and a moving highlight.
function TiltPoster({children,reduce}){
 const rx=useMotionValue(0),ry=useMotionValue(0),gx=useMotionValue(50),gy=useMotionValue(30);
 const rotateX=useSpring(rx,{stiffness:170,damping:18}),rotateY=useSpring(ry,{stiffness:170,damping:18});
 const tiltX=useMotionTemplate`${rotateX}deg`,tiltY=useMotionTemplate`${rotateY}deg`,glareX=useMotionTemplate`${gx}%`,glareY=useMotionTemplate`${gy}%`;
 const reset=()=>{rx.set(0);ry.set(0);gx.set(50);gy.set(30);};
 const move=event=>{
  if(reduce||event.pointerType!=='mouse')return;
  const card=event.currentTarget.querySelector('.title-poster');if(!card||!card.contains(event.target))return reset();
  const r=card.getBoundingClientRect(),px=(event.clientX-r.left)/r.width,py=(event.clientY-r.top)/r.height;
  ry.set((px-.5)*12);rx.set((.5-py)*10);gx.set(px*100);gy.set(py*100);
 };
 // Only the poster card tilts (CSS reads these variables); its buttons stay put.
 return <motion.div className="title-showcase-tilt" onPointerMove={move} onPointerLeave={reset} style={reduce?undefined:{'--tilt-x':tiltX,'--tilt-y':tiltY,'--glare-x':glareX,'--glare-y':glareY}}>{children}</motion.div>;
}

export default function TitleShowcase({background,children}){
 const root=useRef(null),content=useRef(null),reduce=useReducedMotion();
 useLayoutEffect(()=>{const update=()=>root.current?.style.setProperty('--showcase-content-height',(content.current?.offsetHeight||0)+'px');update();const observer=new ResizeObserver(update);if(content.current)observer.observe(content.current);return()=>observer.disconnect();},[]);
 const {scrollYProgress}=useScroll({target:root,offset:['start start','end start']});
 const pointer=useMotionValue(0),x=useSpring(pointer,{stiffness:100,damping:25});
 const y=useTransform(scrollYProgress,[0,1],[0,390]),scale=useTransform(scrollYProgress,[0,1],[1.04,1.36]);
 const contentY=useTransform(scrollYProgress,[0,.75],[0,-70]),contentOpacity=useTransform(scrollYProgress,[0,.35,.8],[1,1,0]);
 const contentBlur=useTransform(scrollYProgress,[.3,.8],[0,6]),filter=useMotionTemplate`blur(${contentBlur}px)`;
 const parts=Children.toArray(children);
 const enter=(delay,from={y:22})=>reduce?{}:{initial:{opacity:0,...from},animate:{opacity:1,x:0,y:0,scale:1,filter:'blur(0px)'},transition:{duration:.8,ease:EASE,delay}};
 return <section ref={root} className={'hero-stage title-hero title-feature title-showcase is-revealed'+(reduce?'':' is-animated')+(!parts[2]?' without-info':'')} onPointerMove={event=>{if(!reduce&&event.pointerType==='mouse'){const r=event.currentTarget.getBoundingClientRect();pointer.set((event.clientX-r.left-r.width/2)/r.width*28);}}} onPointerLeave={()=>pointer.set(0)}>
  {background(reduce?undefined:{y,x,scale})}
  <motion.div ref={content} className="title-showcase-content" style={reduce?undefined:{y:contentY,opacity:contentOpacity,filter}}>
   <motion.div className="title-showcase-poster-layer" {...enter(.05,{filter:'blur(14px)'})}><TiltPoster reduce={reduce}>{parts[0]}</TiltPoster></motion.div>
   <div className="title-showcase-copy-layer">{parts[1]}</div>
   {parts[2]&&<motion.div className="title-showcase-info-layer" {...enter(.45,{x:18,y:0})}>{parts[2]}</motion.div>}
  </motion.div>
 </section>;
}
