import {useEffect,useState,type ReactNode} from 'react';
import {Play,Pause,ChevronLeft,ChevronRight} from 'lucide-react';
import {buildTrailerUrl,extractYouTubeId} from '../utils/trailer';
import Artwork from '../../Artwork.jsx';
import {useArtwork} from '../../title-artwork.js';
import {imageSeed,publishBackdrop} from '../theme.js';
export function HeroBanner({title,description,onOpen,artwork,poster,trailer,metadata,children,kicker='Релизы',index=0,count=1,onPrevious,onNext,variant='home'}:{title?:ReactNode;description?:ReactNode;onOpen?:()=>void;artwork?:string;poster?:ReactNode;trailer?:string|null;metadata?:ReactNode;children?:ReactNode;kicker?:string;index?:number;count?:number;onPrevious?:()=>void;onNext?:()=>void;variant?:'home'|'title'}){
 const [visible,setVisible]=useState(false),[playing,setPlaying]=useState(()=>!matchMedia('(prefers-reduced-motion: reduce)').matches),[hidden,setHidden]=useState(document.hidden);
 useEffect(()=>{setVisible(false);const t=setTimeout(()=>setVisible(true),80);return()=>clearTimeout(t);},[title]);
 useEffect(()=>{const update=()=>setHidden(document.hidden);addEventListener('visibilitychange',update);return()=>removeEventListener('visibilitychange',update);},[]);
 const photo=useArtwork(artwork,null,null,null),[broken,setBroken]=useState(false);useEffect(()=>setBroken(false),[photo]);
 useEffect(()=>()=>{if(variant==='home')publishBackdrop(null);},[artwork,variant]);
 const id=extractYouTubeId(trailer),video=id&&playing&&!hidden&&!navigator.connection?.saveData?buildTrailerUrl(id,{autoplay:true,mute:true,controls:false}):null;
 if(variant==='title')return <section className="hero-stage title-hero title-feature is-revealed">{children}</section>;
 return <section className={'hero-stage home-feature '+(visible?'is-revealed':'')} aria-label="Релизы аниме">
  <div className="hero-photo">{photo&&!broken?<img src={photo} alt="" referrerPolicy="no-referrer" onLoad={event=>{try{publishBackdrop({seed:imageSeed(event.currentTarget)});}catch{}}} onError={()=>setBroken(true)}/>:<Artwork kind="video"/>}</div>{video&&<div className="hero-video-wrap"><iframe src={video} title="Фоновый трейлер" tabIndex={-1} allow="autoplay; encrypted-media"/></div>}<div className="hero-vignette"/>
  <div className="hero-content"><span className="eyebrow">{kicker}</span>{poster&&<button className="hero-small-poster" aria-label="Открыть выбранный тайтл" onClick={onOpen}>{poster}</button>}<div className="hero-metadata">{metadata}</div><h1>{title||'Релизы аниме'}</h1>{description&&<p>{description}</p>}<div className="hero-bottom"><button className="hero-cta" onClick={onOpen}><Play size={16} fill="currentColor"/>Смотреть сейчас</button>{id&&<button className="circle-button" aria-label={playing?'Остановить фоновый трейлер':'Включить фоновый трейлер'} onClick={()=>setPlaying(!playing)}>{playing?<Pause size={15}/>:<Play size={15}/>}</button>}</div></div>
  {count>1&&<div className="hero-gallery-controls"><div className="hero-gallery-dots">{Array.from({length:count},(_,i)=><span key={i} className={i===index?'active':''}/>)}</div><button className="circle-button" aria-label="Предыдущий релиз" onClick={onPrevious}><ChevronLeft size={18}/></button><button className="circle-button" aria-label="Следующий релиз" onClick={onNext}><ChevronRight size={18}/></button></div>}
 </section>;
}
