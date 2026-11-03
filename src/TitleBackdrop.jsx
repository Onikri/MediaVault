import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ChevronLeft,ChevronRight,Pause,Play} from 'lucide-react';
import {useArtwork} from './title-artwork.js';
import {scenePalette} from './palette.js';
import {buildTrailerUrl,extractYouTubeId,issueYouTubeCommand} from './blossom/utils/trailer.ts';
import {seedFromPixels} from './blossom/theme.js';

function Slide({url,profile,actions,libraryId,onPalette}){
  const src=useArtwork(url,profile,actions.readArtwork,libraryId),reduced=useReducedMotion();
  return src?<motion.img src={src} alt="" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} transition={{duration:reduced?0:1.8,ease:'easeInOut'}} onLoad={event=>{
    try{const canvas=document.createElement('canvas');canvas.width=64;canvas.height=36;const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(event.currentTarget,0,0,64,36);const pixels=ctx.getImageData(0,0,64,36).data;onPalette({...scenePalette(pixels),seed:seedFromPixels(pixels)});}catch{}
  }}/>:null;
}
export default function TitleBackdrop({profile,actions,libraryId,onPalette,suspended=false,inline=false,trailer=null,sceneStyle}){
  const reduced=useReducedMotion(),[index,setIndex]=useState(0),[paused,setPaused]=useState(false),[manualPlay,setManualPlay]=useState(false),[hidden,setHidden]=useState(document.hidden),root=useRef(null),frame=useRef(null),position=useRef({x:0,y:0});
  const [visible,setVisible]=useState(true),[mediaPlaying,setMediaPlaying]=useState(false),[started,setStarted]=useState(false);
  useEffect(()=>{const update=()=>setHidden(document.hidden);document.addEventListener('visibilitychange',update);return()=>document.removeEventListener('visibilitychange',update);},[]);
  useEffect(()=>{const node=root.current;if(!node)return;const observer=new IntersectionObserver(entries=>setVisible(entries[0]?.isIntersecting!==false));observer.observe(node);return()=>observer.disconnect();},[]);
  useEffect(()=>{const update=event=>{if(event&&!event.target?.matches?.('video.mv-player-media'))return;const page=root.current?.closest('.title-page');setMediaPlaying(!!page&&[...page.querySelectorAll('video.mv-player-media')].some(v=>!v.paused&&!v.ended));};update();for(const type of ['play','pause','ended','emptied'])document.addEventListener(type,update,true);return()=>{for(const type of ['play','pause','ended','emptied'])document.removeEventListener(type,update,true);};},[]);
  const stopped=suspended||mediaPlaying||hidden||!visible;
  const slides=[...new Set([...(profile.backgrounds||[]),...(profile.screenshots||[]),profile.background])].filter(url=>url&&url!==profile.cover).slice(0,6);
  if(!slides.length&&profile.cover)slides.push(profile.cover);
  const signature=slides.join('|');
  useEffect(()=>{setIndex(0);},[signature]);
  useEffect(()=>{
    if(paused||reduced||stopped||slides.length<2)return;
    const timer=setInterval(()=>{if(!document.hidden)setIndex(value=>(value+1)%slides.length);},10000);
    return()=>clearInterval(timer);
  },[paused,reduced,stopped,signature]);
  useEffect(()=>{
    if(reduced||suspended||inline)return;let raf=0,x=position.current.x,y=position.current.y,targetX=x,targetY=y,last=performance.now();
    const schedule=()=>{if(!raf&&Math.abs(targetX-x)+Math.abs(targetY-y)>.02){last=performance.now();raf=requestAnimationFrame(tick);}};
    const pointer=event=>{if(event.pointerType==='touch')return;targetX=(event.clientX/innerWidth-.5)*14;schedule();};
    const scroll=()=>{targetY=Math.min(40,scrollY*.045);schedule();};
    const tick=now=>{raf=0;const factor=1-Math.exp(-Math.min(50,now-last)/140);last=now;x+=(targetX-x)*factor;y+=(targetY-y)*factor;position.current={x,y};root.current?.style.setProperty('--scene-x',x+'px');root.current?.style.setProperty('--scene-y',-y+'px');if(Math.abs(targetX-x)+Math.abs(targetY-y)>.02)schedule();};
    window.addEventListener('pointermove',pointer,{passive:true});window.addEventListener('scroll',scroll,{passive:true});scroll();schedule();
    return()=>{cancelAnimationFrame(raf);window.removeEventListener('pointermove',pointer);window.removeEventListener('scroll',scroll);};
  },[reduced,suspended,inline]);
  const host=document.getElementById('scene-root'),videoId=extractYouTubeId(trailer),allowed=!!videoId&&(!reduced||manualPlay)&&!navigator.connection?.saveData,shouldPlay=allowed&&!paused&&!stopped;
  useEffect(()=>{setStarted(false);},[videoId]);
  useEffect(()=>{if(shouldPlay)setStarted(true);},[shouldPlay,videoId]);
  const video=started&&allowed?buildTrailerUrl(videoId,{autoplay:true,mute:true,controls:false}):null;
  useEffect(()=>{issueYouTubeCommand(frame.current,shouldPlay?'playVideo':'pauseVideo');},[shouldPlay,video]);
  const scene=<div ref={root} className="title-scene" aria-hidden="true"><motion.div className="title-scene-images" style={sceneStyle}><AnimatePresence initial={false}>{slides.length>0&&<Slide key={slides[index%slides.length]} url={slides[index%slides.length]} profile={profile} actions={actions} libraryId={libraryId} onPalette={onPalette}/>}</AnimatePresence></motion.div>{video&&<motion.div className="title-background-video" style={sceneStyle}><iframe ref={frame} src={video} onLoad={()=>issueYouTubeCommand(frame.current,shouldPlay?'playVideo':'pauseVideo')} title="Фоновый трейлер тайтла" tabIndex={-1} allow="autoplay; encrypted-media"/></motion.div>}<div className="title-scene-shade"/></div>;
  return <>{inline?scene:host&&createPortal(scene,host)}
    {(slides.length>1||videoId)&&<div className="title-scene-controls" role="group" aria-label="Фон страницы">{slides.length>1&&<><button aria-label="Предыдущий фон" onClick={()=>setIndex(value=>(value-1+slides.length)%slides.length)}><ChevronLeft size={14}/></button><span>Кадр {index%slides.length+1} / {slides.length}</span></>}<button aria-label={paused?'Продолжить смену фона':'Остановить смену фона'} aria-pressed={paused} onClick={()=>{setManualPlay(true);setPaused(!paused);}}>{paused?<Play size={12}/>:<Pause size={12}/>}</button>{slides.length>1&&<button aria-label="Следующий фон" onClick={()=>setIndex(value=>(value+1)%slides.length)}><ChevronRight size={14}/></button>}</div>}
  </>;
}
