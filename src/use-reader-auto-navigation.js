import {useEffect,useRef,useState} from 'react';

export const scrollSpeeds={slow:42,normal:76,fast:128};
const atBottom=node=>node.scrollHeight-node.clientHeight-node.scrollTop<=3;
const isLoaded=(node,index)=>node.querySelector('[data-page="'+index+'"] .reader-image-stack img')?.naturalWidth>0;

export default function useReaderAutoNavigation({surface,chapter,page,lastShown,total,scroll,ready,blocked,canAdvance,autoNext,autoScroll,speed,nextChapter,turnPage}){
 const [paused,setPaused]=useState(false);
 const actions=useRef({});actions.current={nextChapter,turnPage};
 const last=lastShown>=total-1;
 const playing=autoScroll&&!paused;

 useEffect(()=>{
  const node=surface.current;
  if(!node||!ready||blocked||!total||(!autoNext&&!playing))return;
  let frame=0,previous=0,carry=0,rest=0,advanced=false,manualUntil=0;
  let pressure=0,wheelAt=0,touch=null;
  const canGo=()=>!advanced&&autoNext&&canAdvance&&(scroll||last)&&atBottom(node)
   &&!node.closest('[data-panel]')&&isLoaded(node,total-1);
  const advance=()=>{
   if(!canGo())return;
   advanced=true;
   actions.current.nextChapter();
  };

  function wheel(event){
   if(event.ctrlKey||Math.abs(event.deltaX)>Math.abs(event.deltaY))return;
   const now=performance.now();
   manualUntil=now+1150;
   if(event.deltaY<=0||!canGo()){pressure=0;return;}
   if(now-wheelAt>360)pressure=0;
   wheelAt=now;
   const multiplier=event.deltaMode===1?16:event.deltaMode===2?node.clientHeight:1;
   pressure+=event.deltaY*multiplier;
   if(pressure>=180)advance();
  }
  function touchStart(event){
   manualUntil=performance.now()+1150;
   const point=event.touches[0];
   touch=event.touches.length===1&&canGo()?{x:point.clientX,y:point.clientY}:null;
  }
  function touchEnd(event){
   manualUntil=performance.now()+1150;
   const point=event.changedTouches[0];
   if(touch&&point&&touch.y-point.clientY>=76&&Math.abs(point.clientX-touch.x)<48)advance();
   touch=null;
  }
  function touchCancel(){touch=null;}

  function tick(now){
   if(advanced)return;
   const elapsed=previous?Math.min(48,now-previous):0;
   previous=now;
   if(document.hidden||now<manualUntil||node.closest('[data-panel]')||!isLoaded(node,page)){
    rest=0;
   }else if(!atBottom(node)){
    rest=0;
    const pixels=carry+elapsed*velocity/1000;
    const step=Math.floor(pixels);
    carry=pixels-step;
    if(step)node.scrollBy({top:step,behavior:'instant'});
   }else if(!scroll||isLoaded(node,total-1)){
    rest+=elapsed;
    const delay=scroll?850:Math.max(3500,node.clientHeight/velocity*1000);
    if(rest>=delay){
     if(!scroll&&!last){actions.current.turnPage();return;}
     if(canGo())advance();
     else setPaused(true);
     return;
    }
   }
   frame=requestAnimationFrame(tick);
  }

  const velocity=scrollSpeeds[speed]||scrollSpeeds.normal;
  node.addEventListener('wheel',wheel,{passive:true});
  node.addEventListener('touchstart',touchStart,{passive:true});
  node.addEventListener('touchend',touchEnd,{passive:true});
  node.addEventListener('touchcancel',touchCancel,{passive:true});
  if(playing)frame=requestAnimationFrame(tick);
  return()=>{
   cancelAnimationFrame(frame);
   node.removeEventListener('wheel',wheel);
   node.removeEventListener('touchstart',touchStart);
   node.removeEventListener('touchend',touchEnd);
   node.removeEventListener('touchcancel',touchCancel);
  };
 },[surface,chapter,page,last,total,scroll,ready,blocked,canAdvance,autoNext,playing,speed]);

 return {playing,toggle:()=>setPaused(value=>!value),reset:()=>setPaused(false)};
}
