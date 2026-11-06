import {useEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ScanFace,RotateCcw,X} from 'lucide-react';
import {depthSize,shadowCutoff,depthSurface,videoRect,characterAtDepthPoint} from './pause-depth-model.js';
import {depthRenderer} from './pause-depth-renderer.js';
import {guidedRefine,luminance,blurredCopy,softMask} from './pause-depth-refine.js';
import {warmCharacterModel} from './character-recognition.js';
import {characterRoster} from './pause-character-context.js';
import {recognizePauseFrame} from './pause-recognition.js';
import './pause-frame.css';

export default function PauseFrameEffects({videoRef,source,paused,enabled,modelAllowed=true,strength=.82,breathPeriod=10,breathAmplitude=.22,autoRecognize=false,visible=true,characterContext={},characterService,userId}){
 const contextRef=useRef(characterContext);contextRef.current=characterContext;
 const canvas=useRef(null),worker=useRef(null),busy=useRef(false),sequence=useRef(0),frame=useRef(null),cache=useRef(new Map()),renderer=useRef(null),recognition=useRef(null),cooldown=useRef(0),idleTimer=useRef(null),usedPause=useRef(false),settings=useRef({strength,enabled});settings.current={strength,enabled,breathPeriod,breathAmplitude};
 const [view,setView]=useState({phase:'idle'}),[chars,setChars]=useState({phase:'idle',values:[]}),[selected,setSelected]=useState(null),[hovered,setHovered]=useState(null),[host,setHost]=useState(null),[rect,setRect]=useState(null),[retry,setRetry]=useState(0);
 const terminate=()=>{worker.current?.terminate();worker.current=null;busy.current=false;};
 useEffect(()=>()=>{clearTimeout(idleTimer.current);terminate();recognition.current?.abort();},[]);
 useEffect(()=>{cache.current.clear();frame.current=null;setSelected(null);setHovered(null);setView({phase:'idle'});setChars({phase:'idle',values:[]});},[source]);
 useEffect(()=>{
  const video=videoRef.current,screen=video?.closest('.mv-player-screen');if(!video||!screen)return;setHost(screen);
  const update=()=>{if(video.videoWidth)setRect(videoRect(screen.clientWidth,screen.clientHeight,video.videoWidth,video.videoHeight));};
  update();const observer=new ResizeObserver(update);observer.observe(screen);video.addEventListener('loadedmetadata',update);
  return()=>{observer.disconnect();video.removeEventListener('loadedmetadata',update);};
 },[videoRef,source]);
 async function recognize(current=frame.current,automatic=false){
  if(!current||!videoRef.current?.paused)return;
  const hit=cache.current.get(current.key)?.characters;if(hit){setChars({phase:'ready',values:hit});return;}
  if(Date.now()<cooldown.current){if(!automatic)setChars(old=>({...old,phase:'error',message:'Подожди несколько секунд перед новым кадром.'}));return;}
  recognition.current?.abort();const abort=new AbortController();recognition.current=abort;const id=sequence.current;
  cooldown.current=Date.now()+(automatic?10000:2000);setChars({phase:'loading',values:[]});
  try{
   const result=await recognizePauseFrame(current.full||current.image,current.context||{},{signal:abort.signal,service:characterService,userId,onPartial:values=>{if(!abort.signal.aborted&&id===sequence.current)setChars({phase:'verifying',values});}});
   if(abort.signal.aborted||id!==sequence.current)return;
   if(result.complete){cache.current.set(current.key,{...cache.current.get(current.key),characters:result.values});while(cache.current.size>4)cache.current.delete(cache.current.keys().next().value);}
   setChars({phase:'ready',values:result.values,message:result.message});
  }catch(error){if(!abort.signal.aborted&&id===sequence.current)setChars(old=>({...old,phase:'error',message:error.name==='TimeoutError'?'Служба распознавания не ответила вовремя.':/[А-Яа-яЁё]/.test(error.message||'')?error.message:'Не удалось связаться со службой распознавания.'}));}
 }
 useEffect(()=>{if(!paused)return;const abort=new AbortController();warmCharacterModel();characterRoster(characterContext,{server:characterService?.server||window.MEDIA_VAULT_CONFIG?.importServerUrl,signal:abort.signal}).catch(()=>{});return()=>abort.abort();},[paused,source,characterContext.malId]);
 // Prepare verified weights off the playback thread and reuse initialization on pause.
 // The 27 MB model must not compete with the stream's first buffer: warm it
 // during playback only after a pause has shown the viewer uses the effect,
 // and never on a data-saving or slow connection.
 useEffect(()=>{if(!source)return;if(!paused)usedPause.current=usedPause.current||'played';else if(usedPause.current==='played')usedPause.current=true;},[paused,source]);
 useEffect(()=>{
  const network=navigator.connection;
  if(paused||usedPause.current!==true||network?.saveData||/(?:^|-)2g$|^3g$/.test(network?.effectiveType||'')||!enabled||!modelAllowed||!source||document.hidden)return;
  const timer=setTimeout(()=>{
   if(worker.current||busy.current||document.hidden)return;
   worker.current=new Worker(new URL('./pause-depth.worker.js',import.meta.url),{type:'module'});
   worker.current.onerror=()=>terminate();worker.current.postMessage({id:0,type:'warm'});
  },1800);
  return()=>clearTimeout(timer);
 },[paused,enabled,modelAllowed,source]);
 useEffect(()=>{
  const video=videoRef.current;if(!video||!source)return;let timer,closed=false;clearTimeout(idleTimer.current);if(!enabled||!modelAllowed)terminate();
  if(!paused){sequence.current++;recognition.current?.abort();setView({phase:'idle'});setChars({phase:'idle',values:[]});setSelected(null);setHovered(null);frame.current=null;
   if(busy.current)terminate();else if(!enabled||!modelAllowed)idleTimer.current=setTimeout(terminate,15000);return;
  }
  const capture=()=>{
   clearTimeout(timer);timer=setTimeout(()=>{
    if(closed||document.hidden||!video.paused||video.readyState<2||!video.videoWidth)return;
    const id=++sequence.current,key=source+':'+video.currentTime.toFixed(3)+':'+video.videoWidth+'x'+video.videoHeight;
    recognition.current?.abort();frame.current=null;setSelected(null);setHovered(null);renderer.current?.surface(null);setView({phase:enabled?'capture':'idle'});setChars({phase:'idle',values:[]});
    try{
     const scale=Math.min(1,960/Math.max(video.videoWidth,video.videoHeight)),image=document.createElement('canvas');image.width=Math.max(1,Math.round(video.videoWidth*scale));image.height=Math.max(1,Math.round(video.videoHeight*scale));
     const context=image.getContext('2d',{willReadFrequently:true});context.drawImage(video,0,0,image.width,image.height);context.getImageData(0,0,1,1);
     // Recognition crops faces from a sharper copy (≤1600 px) than depth needs.
     const fullScale=Math.min(1,1600/Math.max(video.videoWidth,video.videoHeight)),full=fullScale>scale?document.createElement('canvas'):image;if(full!==image){full.width=Math.max(1,Math.round(video.videoWidth*fullScale));full.height=Math.max(1,Math.round(video.videoHeight*fullScale));full.getContext('2d').drawImage(video,0,0,full.width,full.height);}
     frame.current={key,image,full,context:{...contextRef.current,timeSeconds:Math.round(video.currentTime*1000)/1000,timecode:new Date(video.currentTime*1000).toISOString().slice(11,19)}};const hit=cache.current.get(key);if(hit?.characters)setChars({phase:'ready',values:hit.characters});
     if(autoRecognize)recognize(frame.current,true);
     if(!enabled||!modelAllowed){setView({phase:'idle'});return;}
     if(hit?.depth){setView({phase:'ready',...hit.depth});return;}
     if(busy.current)terminate();if(!worker.current)worker.current=new Worker(new URL('./pause-depth.worker.js',import.meta.url),{type:'module'});
     const size=depthSize(image.width,image.height),small=document.createElement('canvas');small.width=size.width;small.height=size.height;const ctx=small.getContext('2d');ctx.drawImage(image,0,0,size.width,size.height);const pixels=ctx.getImageData(0,0,size.width,size.height).data;
     busy.current=true;setView({phase:'initialize'});
     worker.current.onmessage=({data})=>{
      if(closed||data.id!==sequence.current)return;
      if(data.type==='status')setView(data);
      if(data.type==='error'){busy.current=false;setView({phase:'error',message:data.message});}
      if(data.type==='result'){busy.current=false;const depth={data:new Uint8Array(data.depth),width:data.width,height:data.height,inferenceMs:data.inferenceMs};cache.current.set(key,{...cache.current.get(key),depth});while(cache.current.size>4)cache.current.delete(cache.current.keys().next().value);setView({phase:'ready',...depth});}
     };
     worker.current.onerror=()=>{if(!closed&&id===sequence.current){terminate();setView({phase:'error',message:'Не удалось запустить модель глубины.'});}};
     worker.current.postMessage({id,...size,pixels:pixels.buffer},[pixels.buffer]);
    }catch(error){setView({phase:'error',message:error.name==='SecurityError'?'Источник не разрешает анализ стоп-кадра.':error.message});}
   },180);
  };
  const invalidate=()=>{sequence.current++;recognition.current?.abort();frame.current=null;setSelected(null);setHovered(null);setView({phase:'idle'});setChars({phase:'idle',values:[]});};
  capture();video.addEventListener('loadeddata',capture);video.addEventListener('seeked',capture);video.addEventListener('seeking',invalidate);document.addEventListener('visibilitychange',capture);
  return()=>{closed=true;sequence.current++;clearTimeout(timer);recognition.current?.abort();video.removeEventListener('loadeddata',capture);video.removeEventListener('seeked',capture);video.removeEventListener('seeking',invalidate);document.removeEventListener('visibilitychange',capture);};
 },[source,paused,enabled,modelAllowed,autoRecognize,retry,videoRef]);
 // Depth is refined once per still at the frame's resolution so its edges
 // follow the drawn contours instead of the model's ~392 px grid.
 const refined=useMemo(()=>{
  if(view.phase!=='ready')return {data:view.data,width:view.width,height:view.height};
  const image=frame.current?.image;if(!image)return {data:view.data,width:view.width,height:view.height};
  try{const pixels=image.getContext('2d',{willReadFrequently:true}).getImageData(0,0,image.width,image.height).data,guide=luminance(pixels,image.width,image.height);return {data:guidedRefine(view.data,view.width,view.height,guide,image.width,image.height,{radius:6,eps:.0015}),width:image.width,height:image.height,guide};}
  catch{return {data:view.data,width:view.width,height:view.height};}
 },[view.data,view.phase]);
 useEffect(()=>{
  if(!paused||!enabled||view.phase!=='ready'||!canvas.current)return;
  const element=canvas.current,video=videoRef.current,scale=960/Math.max(video.videoWidth,video.videoHeight);element.width=Math.round(video.videoWidth*scale);element.height=Math.round(video.videoHeight*scale);
  const image=frame.current?.image;let render;
  try{render=depthRenderer(element,refined.width,refined.height);render.depth(refined.data);if(image){render.frame(image);render.blur(blurredCopy(image,7));}renderer.current=render;}
  catch(error){setView({phase:'error',message:error.message});return;}
  let raf=0,last=0,elapsed=0,pointerAt=0;const reduced=matchMedia('(prefers-reduced-motion: reduce)'),aim=[0,0],eased=[0,0];
  // Parallax follows the pointer; without one it drifts in a slow orbit.
  const screen=video.closest('.mv-player-screen');
  const point=event=>{if(event.pointerType==='touch')return;const r=element.getBoundingClientRect();aim[0]=((event.clientX-r.left)/r.width-.5)*2;aim[1]=((event.clientY-r.top)/r.height-.5)*2;pointerAt=performance.now();};
  screen?.addEventListener('pointermove',point);
  const draw=now=>{raf=0;if(document.hidden)return;if(!last)last=now;if(now-last>=33||reduced.matches){const step=(now-last)/1000;elapsed+=step;last=now;
    if(!reduced.matches){const idle=now-pointerAt>2500,tx=idle?Math.sin(elapsed*.35)*.55:aim[0],ty=idle?Math.sin(elapsed*.23+1)*.35:aim[1],k=1-Math.exp(-step*4);eased[0]+=(tx-eased[0])*k;eased[1]+=(ty-eased[1])*k;render.parallax(eased[0],eased[1]);}
    render.draw(reduced.matches ? .48 : shadowCutoff(elapsed,{period:settings.current.breathPeriod,amplitude:settings.current.breathAmplitude}),settings.current.strength);}if(!reduced.matches)raf=requestAnimationFrame(draw);};
  const restart=()=>{cancelAnimationFrame(raf);last=0;if(!document.hidden){render.draw(reduced.matches ? .48 : shadowCutoff(elapsed,{period:settings.current.breathPeriod,amplitude:settings.current.breathAmplitude}),settings.current.strength);raf=requestAnimationFrame(draw);}};
  document.addEventListener('visibilitychange',restart);reduced.addEventListener('change',restart);restart();
  return()=>{cancelAnimationFrame(raf);screen?.removeEventListener('pointermove',point);document.removeEventListener('visibilitychange',restart);reduced.removeEventListener('change',restart);renderer.current=null;render.dispose();};
 },[paused,enabled,view.phase,view.data,refined]);
 // Masks are flood-filled on the refined depth: its edges follow the drawing,
 // so the fill no longer leaks into background that the coarse map blurred in.
 const masks=useMemo(()=>{if(view.phase!=='ready')return new Map();return new Map(chars.values.map(c=>[c.id,depthSurface(refined.data,refined.width,refined.height,c.box,c.bodyBox,{tolerance:26})]));},[refined,view.phase,chars.values]);
 const currentCharacter=value=>chars.values.find(c=>c.id===value?.id||(value?.nameRu&&c.nameRu===value.nameRu));
 const pinned=currentCharacter(selected),focused=currentCharacter(hovered)||pinned;
 const soft=useMemo(()=>new Map(),[masks]);
 const surfaceFor=character=>{const mask=character&&masks.get(character.id);if(!mask)return null;if(!soft.has(mask))soft.set(mask,softMask(mask,refined.width,refined.height));return soft.get(mask);};
 useEffect(()=>{if(renderer.current&&view.phase==='ready'){renderer.current.surface(focused?surfaceFor(focused):null,{immediate:matchMedia('(prefers-reduced-motion: reduce)').matches});renderer.current.draw(undefined,strength);}},[focused,masks,view.data,strength]);
 useEffect(()=>{
  if(!host||!paused||!visible||!rect)return;let active=null;
  const move=event=>{if(event.pointerType==='touch'||event.target.closest?.('button,input,select'))return;const r=host.getBoundingClientRect(),x=(event.clientX-r.left-rect.left)/rect.width,y=(event.clientY-r.top-rect.top)/rect.height;
   const hit=characterAtDepthPoint(chars.values,masks,refined.width,refined.height,x,y);
   if(active!==hit?.id){active=hit?.id;setHovered(hit||null);}
  };const leave=()=>{active=null;setHovered(null);};host.addEventListener('pointermove',move);host.addEventListener('pointerleave',leave);return()=>{host.removeEventListener('pointermove',move);host.removeEventListener('pointerleave',leave);};
 },[host,paused,visible,rect,chars.values,masks,refined]);
 const loading=enabled&&!['idle','ready','error'].includes(view.phase),message=view.phase==='download'?'Глубина · загрузка '+Math.min(100,Math.round(view.loaded/view.total*100))+'%':view.phase==='inference'?'Глубина · анализ кадра…':'Глубина · запуск модели…';
 return <><canvas ref={canvas} className={'pause-depth-shadow'+(paused&&enabled&&view.phase==='ready'?' is-ready':'')} aria-hidden="true" data-model="Depth Anything V2 Small"/>{paused&&visible&&host&&createPortal(<div className="pause-frame-ui">
   <div className="pause-frame-tools" onPointerDown={e=>e.stopPropagation()} onClick={e=>e.stopPropagation()}>
    <button type="button" className="pause-recognize" disabled={['loading','verifying'].includes(chars.phase)||!frame.current} aria-busy={['loading','verifying'].includes(chars.phase)} onClick={()=>recognize()} aria-label="Распознать персонажей на стоп-кадре" title={chars.phase==='loading'?'Ищем персонажей…':chars.phase==='verifying'?'Проверяем весь кадр…':'Распознать персонажей'}><ScanFace size={16}/></button>
    {loading&&modelAllowed&&<span className="pause-depth-status" role="status">{message}</span>}
    {view.phase==='error'&&enabled&&<button className="pause-depth-status" onClick={()=>setRetry(n=>n+1)} title={view.message} aria-label="Повторить карту глубины"><RotateCcw size={13}/>{view.message}</button>}
    {(chars.phase==='error'||chars.message)&&<span role="status">{chars.message}</span>}{chars.phase==='ready'&&!chars.values.length&&<span className="sr-only" role="status">Персонажи не распознаны</span>}
    {chars.values.length>0&&<button aria-label="Скрыть персонажей" onClick={()=>{setChars({phase:'idle',values:[]});setSelected(null);setHovered(null);}}><X size={14}/></button>}
   </div>
   {rect&&chars.values.map(character=>{const x=Math.max(0,Math.min(rect.width-150,(character.box[0]+character.box[2])*.5*rect.width-60)),y=Math.max(50,Math.min(rect.height-120,character.box[3]*rect.height+9));return <button key={character.id} className={'pause-character'+(focused?.id===character.id?' is-selected':'')} style={{left:rect.left+x,top:rect.top+y}} aria-pressed={pinned?.id===character.id} onPointerEnter={()=>setHovered(character)} onPointerLeave={()=>setHovered(null)} onFocus={()=>setHovered(character)} onBlur={()=>setHovered(null)} onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();setSelected(pinned?.id===character.id?null:character);}} title={[character.reasonRu,...character.candidates.map(c=>(c.nameRu||c.name)+' · '+c.work)].filter(Boolean).join('\n')}><strong>{character.nameRu||'Персонаж не уточнён'}</strong></button>;})}
  </div>,host)}</>;
}
