import {createContext,useContext,useEffect,useLayoutEffect,useMemo,useReducer,useRef,useState} from 'react';

export const PlayerContext=createContext(null);
export function usePlayerSpace(){
 const player=useContext(PlayerContext),[height,setHeight]=useState(innerHeight);
 useLayoutEffect(()=>{
  const host=player?.root;
  const update=()=>setHeight(Math.min(host?.clientHeight||innerHeight,innerHeight-Math.max(0,host?.getBoundingClientRect().top||0)));
  update();const observer=new ResizeObserver(update);if(host)observer.observe(host);addEventListener('resize',update);
  return()=>{observer.disconnect();removeEventListener('resize',update);};
 },[player]);
 return height;
}
export function useMediaVaultPlayer(){
 const player=useContext(PlayerContext);
 if(!player)throw Error('Модуль должен находиться внутри MediaVaultPlayer.');
 return player;
}
const initial={panel:'watch',settingsTab:'watch',theater:false};
export function playerUiReducer(state,action){
 switch(action.type){
  case 'panel':return {...state,panel:action.value};
  case 'music':return {...state,panel:(typeof action.value==='function'?action.value(state.panel==='music'):action.value)?'music':'watch'};
  case 'settingsTab':return {...state,settingsTab:action.value};
  case 'theater':return {...state,theater:typeof action.value==='function'?action.value(state.theater):!!action.value};
  default:return state;
 }
}
export function usePlayerUi(){
 const [state,dispatch]=useReducer(playerUiReducer,initial);
 return {...state,musicOpen:state.panel==='music',
  setPanel:value=>dispatch({type:'panel',value}),
  setMusicOpen:value=>dispatch({type:'music',value}),
  setSettingsTab:value=>dispatch({type:'settingsTab',value}),
  setTheater:value=>dispatch({type:'theater',value})};
}

// Stable commands always read the latest controller; extensions never own playback.
export function usePlayerSession(controller){
 const latest=useRef(controller);latest.current=controller;
 return useMemo(()=>{
  const call=(name,...args)=>latest.current[name]?.(...args);
  return {
   get media(){return latest.current.videoRef.current;},
   get root(){return latest.current.stageRef.current;},
   getSnapshot(){const c=latest.current,v=c.videoRef.current;return {
    item:c.item,source:c.source,time:v?.currentTime||0,duration:Number.isFinite(v?.duration)?v.duration:0,
    playing:!!v&&!v.paused,volume:v?.volume??1,muted:v?.muted??false,
    panel:c.panel,theater:c.theater,fullscreen:c.isFullscreen,pip:c.isPip,
    preferences:{...c.prefs},quality:c.streaming.level
   };},
   play:()=>{const c=latest.current;c.openPanel('watch');return c.videoRef.current?.play();},
   pause:()=>latest.current.videoRef.current?.pause(),
   toggle:()=>call('toggle'),seek:value=>call('seek',value),
   openPanel:value=>call('openPanel',value),preferences:value=>call('changePrefs',value),
   fullscreen:()=>call('fullscreen'),pictureInPicture:()=>call('pip'),
   theater:value=>latest.current.setTheater(value??!latest.current.theater),
   selectItem:(item,keepTime=false)=>call('choose',item,keepTime),
   next:()=>call('nextEpisode'),previous:()=>latest.current.choose(latest.current.previous),
   on(name,listener){const media=latest.current.videoRef.current;if(!media)return()=>{};media.addEventListener(name,listener);return()=>media.removeEventListener(name,listener);}
  };
 },[]);
}

export function usePlayerExtensions(api,extensions,onError){
 const active=useRef(new Map()),report=useRef(onError);report.current=onError;
 useEffect(()=>{
  const wanted=new Map();
  for(const extension of extensions||[]){
   if(!extension?.id||wanted.has(extension.id)){report.current?.(Error('У расширения плеера должен быть уникальный id.'));continue;}
   wanted.set(extension.id,extension);
  }
  for(const [id,entry] of active.current){
   if(wanted.get(id)?.setup!==entry.setup){entry.stop();active.current.delete(id);}
  }
  for(const [id,extension] of wanted){
   if(active.current.has(id))continue;
   const abort=new AbortController(),cleanups=[];
   const stop=()=>{abort.abort();for(const cleanup of cleanups.splice(0))try{cleanup();}catch(error){report.current?.(error);}};
   try{
    const result=extension.setup?.({...api,signal:abort.signal,on:(name,fn)=>{const off=api.on(name,fn);cleanups.push(off);return off;}});
    if(typeof result==='function')cleanups.push(result);
    active.current.set(id,{setup:extension.setup,stop});
   }catch(error){stop();active.current.set(id,{setup:extension.setup,stop:()=>{}});report.current?.(error);}
  }
 });
 useEffect(()=>()=>{for(const entry of active.current.values())entry.stop();active.current.clear();},[]);
}

export function usePlayerMediaSession(api){
 useEffect(()=>{
  if(!navigator.mediaSession||typeof MediaMetadata==='undefined')return;
  let metadata;
  const names=['play','pause','seekto','seekbackward','seekforward','nexttrack','previoustrack'];
  const release=()=>{if(!metadata||navigator.mediaSession.metadata!==metadata)return;for(const name of names)try{navigator.mediaSession.setActionHandler(name,null);}catch{}navigator.mediaSession.metadata=null;metadata=null;};
  const activate=()=>{
   const snapshot=api.getSnapshot(),item=snapshot.item;
   metadata=new MediaMetadata({title:item.title||item.name||'MediaVault',album:item.collectionName||''});
   navigator.mediaSession.metadata=metadata;
   const actions={play:()=>api.play()?.catch(()=>{}),pause:api.pause,seekto:e=>api.seek(e.seekTime),
    seekbackward:e=>api.seek(api.getSnapshot().time-(e.seekOffset||10)),seekforward:e=>api.seek(api.getSnapshot().time+(e.seekOffset||10)),nexttrack:api.next,previoustrack:api.previous};
   for(const [name,fn] of Object.entries(actions))try{navigator.mediaSession.setActionHandler(name,fn);}catch{}
  };
  const off=api.on('play',activate);
  return()=>{off();release();};
 },[api]);
}

// Dim siblings along the ancestor path, never the ancestor containing the video.
const dimmed=new WeakMap();
export function usePlayerTheater(root,enabled){
 useEffect(()=>{
  if(!enabled||!root.current)return;
  // Bring the whole enlarged player (with its timeline) into view.
  requestAnimationFrame(()=>root.current?.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}));
  const layout=root.current.closest('.mv-title-layout');
  layout?.classList.add('player-theater-layout');
  const siblings=[];
  for(let node=root.current;node?.parentElement;node=node.parentElement){
   for(const sibling of node.parentElement.children){
    if(sibling===node||['SCRIPT','STYLE','LINK'].includes(sibling.tagName))continue;
    const count=dimmed.get(sibling)||0;dimmed.set(sibling,count+1);
    sibling.classList.add('player-theater-dimmed');siblings.push(sibling);
   }
   if(node.parentElement===document.body)break;
  }
  return()=>{layout?.classList.remove('player-theater-layout');for(const node of siblings){const count=(dimmed.get(node)||1)-1;if(count)dimmed.set(node,count);else{dimmed.delete(node);node.classList.remove('player-theater-dimmed');}}};
 },[root,enabled]);
}
