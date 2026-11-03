'use client';
import {useRef} from 'react';
import {useReducedMotion,useScroll,useTransform} from 'motion/react';
import './title-showcase.css';

// The supplied Skiper29 reference keeps its atmosphere above a single content
// group. Use that scroll composition with our own geometry and existing Motion.
export default function TitleShowcase({background,children}){
 const root=useRef(null),reduce=useReducedMotion();
 const {scrollYProgress}=useScroll({target:root,offset:['start end','end start']});
 const y=useTransform(scrollYProgress,[0,.55,1],[0,0,100]);
 return <section ref={root} className="hero-stage title-hero title-feature title-showcase is-revealed">
  {background(reduce?undefined:{y})}
  <div className="title-showcase-content">{children}</div>
 </section>;
}
