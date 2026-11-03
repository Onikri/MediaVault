import {useContext,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {motion,useReducedMotion,useIsPresent} from 'motion/react';
import {PlayerContext} from './player-session.js';
export default function PlayerPopover({anchor,label,children,className='',onClose}){
 const player=useContext(PlayerContext),close=useRef(onClose);close.current=onClose;
 const root=useRef(null),restoreFocus=useRef(true),reduced=useReducedMotion(),present=useIsPresent();
 const [box,setBox]=useState({position:'absolute',left:8,top:8,width:320,maxHeight:300,transformOrigin:'bottom right'});
 useEffect(()=>{
  const previous=document.activeElement;if(!root.current?.contains(previous))root.current?.focus({preventScroll:true});
  const key=e=>{
   if(e.key==='Escape'){e.preventDefault();close.current();}
   if(e.key!=='Tab')return;
   const nodes=[...root.current?.querySelectorAll('button:not(:disabled),select:not(:disabled),input:not(:disabled),a[href]')||[]].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);
   if(!first){e.preventDefault();return;}
   if(e.shiftKey&&(document.activeElement===first||document.activeElement===root.current)){e.preventDefault();last.focus();}
   else if(!e.shiftKey&&(document.activeElement===last||document.activeElement===root.current)){e.preventDefault();first.focus();}
  };
  const outside=e=>{const host=player?.root||root.current?.closest('.mv-player');if(host&&!host.contains(e.target)){restoreFocus.current=false;close.current();}};
  const node=root.current;node?.addEventListener('keydown',key);document.addEventListener('pointerdown',outside,true);
  return()=>{node?.removeEventListener('keydown',key);document.removeEventListener('pointerdown',outside,true);const target=anchor?.current||previous;if(restoreFocus.current&&target?.isConnected)target.focus?.({preventScroll:true});};
 },[anchor,player]);
 useLayoutEffect(()=>{
  let frame=0;
  const host=player?.root||root.current?.closest('.mv-player');
  const update=()=>{
   frame=0;
   const r=host?.getBoundingClientRect()||{left:0,top:0,width:innerWidth,height:innerHeight},a=anchor?.current?.getBoundingClientRect();
   const visibleTop=Math.max(8,8-r.top),visibleBottom=Math.min(r.height-8,innerHeight-r.top-8);
   const maxHeight=Math.max(80,visibleBottom-visibleTop);
   const width=Math.max(100,Math.min(className.includes('music')?370:380,r.width-16));
   const h=Math.min(root.current?.scrollHeight||280,maxHeight);
   const left=Math.max(8,Math.min(r.width-width-8,(a?.right??r.left+r.width-8)-r.left-width));
   const top=Math.max(visibleTop,Math.min((a?.top??r.top+r.height)-r.top-h-8,visibleBottom-h));
   const next={position:host?'absolute':'fixed',left,top,width,maxHeight,transformOrigin:Math.max(0,Math.min(width,(a?.left??r.left+left)-r.left-left))+'px '+h+'px'};
   setBox(old=>Object.keys(next).every(k=>next[k]===old[k])?old:next);
  };
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(update);};
  update();const observer=new ResizeObserver(schedule);if(host)observer.observe(host);if(root.current)observer.observe(root.current);
  addEventListener('resize',schedule);if(!host)addEventListener('scroll',schedule,true);
  return()=>{cancelAnimationFrame(frame);observer.disconnect();removeEventListener('resize',schedule);if(!host)removeEventListener('scroll',schedule,true);};
 },[anchor,className,player]);
 return <><div className="player-popover-scrim" style={{position:player?'absolute':'fixed',inset:0,pointerEvents:present?'auto':'none'}} onPointerDown={onClose}/><motion.section ref={root} className={'player-popover '+className+(box.maxHeight<300?' is-player-constrained':'')} role="dialog" aria-modal="true" aria-label={label} style={{...box,'--player-menu-height':box.maxHeight+'px',pointerEvents:present?'auto':'none'}} tabIndex={-1} initial={{opacity:0,scale:reduced?1:.965,y:reduced?0:10}} animate={{opacity:1,scale:1,y:0}} exit={{opacity:0,scale:reduced?1:.98,y:reduced?0:4}} transition={reduced?{duration:0}:{type:'spring',stiffness:420,damping:34,mass:.7}}>{children}</motion.section></>;
}
