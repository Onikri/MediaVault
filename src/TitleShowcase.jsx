'use client';
import {Children,useRef,useLayoutEffect,useId,useState,useEffect} from 'react';
import {createPortal} from 'react-dom';
import {ArrowLeft} from 'lucide-react';
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

// Phone cover mask: a leaf with two wide opposite corners. Scrolling widens
// them, so the cover sinks into the shape while it shrinks and zooms.
const PHONE='(max-width:640px)';
export function leafPath(t){
 const R=.14+.3*t,Ry=R*.75,r=.05,ry=r*.75,k=.45,f=n=>n.toFixed(4);
 return `M${f(R)},0H${f(1-r)}Q1,0 1,${f(ry)}V${f(1-Ry)}C1,${f(1-Ry*k)} ${f(1-R*k)},1 ${f(1-R)},1H${f(r)}Q0,1 0,${f(1-ry)}V${f(Ry)}C0,${f(Ry*k)} ${f(R*k)},0 ${f(R)},0Z`;
}
export function usePhone(){
 const [phone,setPhone]=useState(()=>typeof matchMedia==='function'&&matchMedia(PHONE).matches);
 useEffect(()=>{const query=matchMedia(PHONE),sync=()=>setPhone(query.matches);sync();query.addEventListener('change',sync);return()=>query.removeEventListener('change',sync);},[]);
 return phone;
}
function PhoneCover({reduce,clip}){
 const {scrollY}=useScroll(),span=[0,380];
 const t=useTransform(scrollY,span,[0,1],{clamp:true}),d=useTransform(t,leafPath);
 const scale=useTransform(t,[0,1],[1,.8]),y=useTransform(t,[0,1],[0,64]),zoom=useTransform(t,[0,1],[1,1.16]);
 const backX=useTransform(t,[0,1],[16,34]),backY=useTransform(t,[0,1],[14,40]),farX=useTransform(t,[0,1],[-14,-30]),farY=useTransform(t,[0,1],[24,58]);
 const still=reduce?{}:undefined;
 return <>
  <svg className="title-phone-mask" width="0" height="0" aria-hidden="true" focusable="false"><clipPath id={clip} clipPathUnits="objectBoundingBox"><motion.path d={reduce?leafPath(0):d}/></clipPath></svg>
  <motion.i className="title-phone-layer is-far" aria-hidden="true" style={still||{x:farX,y:farY,scale}}/>
  <motion.i className="title-phone-layer is-near" aria-hidden="true" style={still||{x:backX,y:backY,scale}}/>
  <PhoneCoverMotion y={y} scale={scale} zoom={zoom} reduce={reduce}/>
 </>;
}
// Drives the real cover through CSS variables, so the poster markup stays one.
function PhoneCoverMotion({y,scale,zoom,reduce}){
 const ref=useRef(null);
 useEffect(()=>{if(reduce)return;const layer=ref.current?.parentElement;if(!layer)return;const set=()=>{layer.style.setProperty('--cover-y',y.get()+'px');layer.style.setProperty('--cover-scale',scale.get());layer.style.setProperty('--cover-zoom',zoom.get());};set();const stops=[y.on('change',set),scale.on('change',set),zoom.on('change',set)];return()=>{stops.forEach(stop=>stop());['--cover-y','--cover-scale','--cover-zoom'].forEach(name=>layer.style.removeProperty(name));};},[y,scale,zoom,reduce]);
 return <span ref={ref} hidden/>;
}
// On a phone the way back lives in the top-left corner, outside every
// transformed layer so it stays fixed while the page scrolls.
function PhoneBack({label,onBack,id}){
 return createPortal(<button type="button" id={id} className="title-phone-back" aria-label={label} title={label} onClick={onBack}><ArrowLeft size={19} aria-hidden="true"/></button>,document.body);
}

export default function TitleShowcase({background,children,backLabel,onBack,backId}){
 const root=useRef(null),content=useRef(null),reduce=useReducedMotion();
 useLayoutEffect(()=>{const update=()=>root.current?.style.setProperty('--showcase-content-height',(content.current?.offsetHeight||0)+'px');update();const observer=new ResizeObserver(update);if(content.current)observer.observe(content.current);return()=>observer.disconnect();},[]);
 const {scrollYProgress}=useScroll({target:root,offset:['start start','end start']});
 const pointer=useMotionValue(0),x=useSpring(pointer,{stiffness:100,damping:25});
 const y=useTransform(scrollYProgress,[0,1],[0,390]),scale=useTransform(scrollYProgress,[0,1],[1.04,1.36]);
 const contentY=useTransform(scrollYProgress,[0,.75],[0,-70]),contentOpacity=useTransform(scrollYProgress,[0,.35,.8],[1,1,0]);
 const contentBlur=useTransform(scrollYProgress,[.3,.8],[0,6]),filter=useMotionTemplate`blur(${contentBlur}px)`;
 const parts=Children.toArray(children),phone=usePhone(),clip='title-cover-'+useId().replace(/[^a-z0-9]/gi,'');
 const enter=(delay,from={y:22})=>reduce?{}:{initial:{opacity:0,...from},animate:{opacity:1,x:0,y:0,scale:1,filter:'blur(0px)'},transition:{duration:.8,ease:EASE,delay}};
 return <section ref={root} className={'hero-stage title-hero title-feature title-showcase is-revealed'+(reduce?'':' is-animated')+(!parts[2]?' without-info':'')} onPointerMove={event=>{if(!reduce&&event.pointerType==='mouse'){const r=event.currentTarget.getBoundingClientRect();pointer.set((event.clientX-r.left-r.width/2)/r.width*28);}}} onPointerLeave={()=>pointer.set(0)}>
  {background(reduce?undefined:{y,x,scale})}
  <motion.div ref={content} className="title-showcase-content" style={reduce||phone?undefined:{y:contentY,opacity:contentOpacity,filter}}>
   <motion.div className="title-showcase-poster-layer" style={phone?{'--cover-clip':`url(#${clip})`}:undefined} {...enter(.05,{filter:'blur(14px)'})}>{phone&&<PhoneCover reduce={reduce} clip={clip}/>}<TiltPoster reduce={reduce}>{parts[0]}</TiltPoster></motion.div>
   <div className="title-showcase-copy-layer">{parts[1]}</div>
   {parts[2]&&<motion.div className="title-showcase-info-layer" {...enter(.45,{x:18,y:0})}>{parts[2]}</motion.div>}
  </motion.div>
  {phone&&onBack&&<PhoneBack id={backId} label={backLabel} onBack={onBack}/>}
 </section>;
}
