import {useEffect,useRef,useState} from 'react';
let apiPromise;
function youtubeAPI(){
 if(window.YT?.Player)return Promise.resolve(window.YT);
 if(!apiPromise)apiPromise=new Promise((resolve,reject)=>{
  const start=Date.now(),timer=setInterval(()=>{if(window.YT?.Player){clearInterval(timer);resolve(window.YT);}else if(Date.now()-start>20000){clearInterval(timer);apiPromise=null;reject(Error('Не удалось подключить управление YouTube. Используй кнопки внутри ролика.'));}},100);
  if(!document.querySelector('script[data-mv-youtube]')){const s=document.createElement('script');s.src='https://www.youtube.com/iframe_api';s.dataset.mvYoutube='true';document.head.append(s);}
 });return apiPromise;
}
export const youtubeID=value=>/^[\w-]{11}$/.test(String(value||''))?String(value):'';
export default function YouTubeEmbed({videoId,title='YouTube',autoplay=false,onReady,onState,onError,controller}){
 const frame=useRef(null),callbacks=useRef({onReady,onState,onError}),[error,setError]=useState('');callbacks.current={onReady,onState,onError};
 const id=youtubeID(videoId);
 useEffect(()=>{
  if(!id)return;let closed=false,player;setError('');
  youtubeAPI().then(YT=>{if(closed||!frame.current)return;player=new YT.Player(frame.current,{events:{onReady:e=>{if(closed)return;if(controller)controller.current=e.target;callbacks.current.onReady?.(e.target);},onStateChange:e=>!closed&&callbacks.current.onState?.(e.data),onError:e=>{if(closed)return;const message=[101,150].includes(e.data)?'Автор запретил воспроизведение на других сайтах. Открой запись на YouTube.':'YouTube не смог воспроизвести эту запись.';setError(message);callbacks.current.onError?.(message);}}});}).catch(e=>{if(!closed)setError(e.message);});
  return()=>{closed=true;if(controller)controller.current=null;try{player?.destroy();}catch{}};
 },[id]);
 if(!id)return null;
 return <div className="youtube-official"><iframe key={id} ref={frame} title={title} src={'https://www.youtube-nocookie.com/embed/'+id+'?'+new URLSearchParams({autoplay:autoplay?'1':'0',playsinline:'1',enablejsapi:'1',origin:location.origin,rel:'0'})} allow="autoplay; encrypted-media; picture-in-picture; fullscreen" referrerPolicy="strict-origin-when-cross-origin" allowFullScreen/>{error&&<p role="status">{error} <a href={'https://www.youtube.com/watch?v='+id} target="_blank" rel="noopener noreferrer">Открыть YouTube</a></p>}</div>;
}
