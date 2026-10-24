import {useEffect,useRef,useState} from 'react';
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
export function gestureIntent(dx,dy,zone){
  if(Math.hypot(dx,dy)<12)return null;
  if(Math.abs(dx)>Math.abs(dy)*1.15)return 'seek';
  if(Math.abs(dy)<=Math.abs(dx)*1.15)return null;
  return zone<.33?'brightness':zone>.67?'volume':dy<0?'episodes':'settings';
}
export default function usePlayerGestures({videoRef,volume,setVolume,openPanel,toggle,reveal}){
  const [brightness,setBrightness]=useState(1),[feedback,setFeedback]=useState(null);
  const active=useRef(null),dismiss=useRef(null),suppressClick=useRef(0);
  const clearLater=()=>{clearTimeout(dismiss.current);dismiss.current=setTimeout(()=>setFeedback(null),850);};
  useEffect(()=>()=>clearTimeout(dismiss.current),[]);
  const down=event=>{
    if(event.pointerType!=='touch'||!matchMedia('(pointer: coarse), (any-pointer: coarse)').matches)return;
    if(active.current){active.current=null;suppressClick.current=performance.now()+600;setFeedback(null);return;}
    const box=event.currentTarget.getBoundingClientRect();
    active.current={id:event.pointerId,x:event.clientX,y:event.clientY,zone:(event.clientX-box.left)/box.width,width:box.width,height:box.height,time:videoRef.current?.currentTime||0,volume,brightness,mode:null};
    event.currentTarget.setPointerCapture(event.pointerId);clearTimeout(dismiss.current);reveal();
  };
  const move=event=>{
    const g=active.current;if(!g||g.id!==event.pointerId)return;
    const dx=event.clientX-g.x,dy=event.clientY-g.y;
    if(Math.hypot(dx,dy)>=12)g.moved=true;
    if(!g.mode)g.mode=gestureIntent(dx,dy,g.zone);
    if(!g.mode)return;
    event.preventDefault();reveal();
    if(g.mode==='seek'){
      const duration=videoRef.current?.duration;
      if(!Number.isFinite(duration))return;
      g.target=clamp(g.time+dx/g.width*Math.min(120,duration),0,duration);
      setFeedback({type:'seek',value:g.target,delta:g.target-g.time});
    }else if(g.mode==='brightness'){
      const value=clamp(g.brightness-dy/g.height*1.5,.2,1.5);setBrightness(value);setFeedback({type:g.mode,value});
    }else if(g.mode==='volume'){
      const value=clamp(g.volume-dy/g.height*1.5,0,1);setVolume(value);setFeedback({type:g.mode,value});
    }else{
      g.distance=Math.abs(dy);setFeedback({type:g.mode,value:clamp(Math.abs(dy)/100,0,1)});
    }
  };
  const finish=(event,cancel=false)=>{
    const g=active.current;if(!g||g.id!==event.pointerId)return;
    active.current=null;suppressClick.current=performance.now()+600;
    if(!cancel){
      if(g.mode==='seek'&&Number.isFinite(g.target))videoRef.current.currentTime=g.target;
      else if(['episodes','settings'].includes(g.mode)&&g.distance>=55){openPanel(g.mode);setFeedback(null);}
      else if(!g.mode&&!g.moved)toggle();
    }
    clearLater();
  };
  return {brightness,feedback,surface:{onPointerDown:down,onPointerMove:move,onPointerUp:event=>finish(event),onPointerCancel:event=>finish(event,true),onLostPointerCapture:event=>finish(event,true),onClick:event=>{if(performance.now()<suppressClick.current)return;reveal();toggle();}}};
}
