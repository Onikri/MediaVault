import {useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {motion,useReducedMotion} from 'motion/react';
import './merged-catalog-toolbar.css';

// Keep a single set of controls. Typing holds the current parent so scrolling
// never destroys the focused search input or its composition/selection.
export default function MergedCatalogToolbar({stuck,children}){
 const local=useRef(null),lastHeight=useRef(100),[host,setHost]=useState(null),reduced=useReducedMotion(),desired=useRef(stuck),synchronize=useRef(()=>{});desired.current=stuck;
 useLayoutEffect(()=>{
  const slot=document.createElement('div');slot.className='catalog-nav-slot';
  const dock=document.querySelector('.mobile-dock'),header=document.querySelector('.blossom-navbar');
  let frame;
  const sync=()=>{
   const focused=document.activeElement;
   if(focused?.matches('input,textarea')&&focused.closest('.catalog-toolbar,.fdock-panel'))return;
   const mobile=matchMedia('(max-width:1000px)').matches;
   const target=desired.current?(mobile?dock:header?.querySelector('.header-center-search')):null;
   if(target){const changed=slot.parentNode!==target;if(changed)target.append(slot);document.documentElement.dataset.catalogMerged='true';setHost(slot);if(changed)dispatchEvent(new CustomEvent('mediavault:catalog-merged',{detail:{mobile}}));}
   else{slot.remove();delete document.documentElement.dataset.catalogMerged;setHost(null);}
  };
  const later=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(sync);};
  if(local.current?.offsetHeight)lastHeight.current=local.current.offsetHeight;
  synchronize.current=sync;
  const focus=()=>slot.querySelector('input')?.focus({preventScroll:true});
  sync();addEventListener('mediavault:catalog-focus',focus);addEventListener('resize',later);document.addEventListener('focusout',later);
  return()=>{cancelAnimationFrame(frame);removeEventListener('mediavault:catalog-focus',focus);removeEventListener('resize',later);document.removeEventListener('focusout',later);slot.remove();delete document.documentElement.dataset.catalogMerged;};
 },[]);
 useLayoutEffect(()=>synchronize.current(),[stuck]);
 const toolbar=<motion.div layout={!reduced} layoutId="catalog-unified-toolbar" transition={reduced?{duration:0}:{type:'spring',stiffness:420,damping:38}} className="unified-catalog-content">{children}</motion.div>;
 return <><div ref={local} className="unified-catalog-placeholder" style={host?{height:lastHeight.current}:undefined}>{!host&&toolbar}</div>{host&&createPortal(toolbar,host)}</>;
}
