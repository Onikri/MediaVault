import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Heart,Star} from 'lucide-react';
import type {Anime} from '../types/anime';
import {buildTrailerUrl,extractYouTubeId} from '../utils/trailer';
import {coverOf,scoreLabel,subtitle} from '../utils/display';
import {AnimeHoverPreview} from './AnimeHoverPreview';

// AniView archive adapter: data, navigation and favorites belong to MediaVault.
export interface AnimeCardProps {
 anime:Anime;compact?:boolean;index?:number;onOpen?:()=>void;href?:string;
 onFavorite?:()=>void;favorite?:boolean;artwork?:ReactNode;detail?:ReactNode;extra?:ReactNode;
 className?:string;openLabel?:string;category?:string;titleName?:string;
}
export function AnimeCard({anime,compact=false,index=0,onOpen,href,onFavorite,favorite=false,artwork,detail,extra,className='',openLabel,category,titleName}:AnimeCardProps){
 const [hovered,setHovered]=useState(false),[mounted,setMounted]=useState(false),[anchor,setAnchor]=useState<DOMRect|null>(null);
 const timer=useRef<ReturnType<typeof setTimeout>|null>(null),root=useRef<HTMLElement>(null);
 const id=extractYouTubeId(anime.trailer?.embed_url)||anime.trailer?.youtube_id||null;
 const trailer=buildTrailerUrl(id,{autoplay:true,mute:true,loop:true,controls:false});
 const image=coverOf(anime),hasScore=typeof anime.score==='number'&&Number.isFinite(anime.score);
 function enter(){if(timer.current)clearTimeout(timer.current);setAnchor(root.current?.getBoundingClientRect()||null);timer.current=setTimeout(()=>{setHovered(true);if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&!navigator.connection?.saveData)setMounted(true);},300);}
 function leave(){if(timer.current)clearTimeout(timer.current);setHovered(false);setMounted(false);}
 useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current);},[]);
 const contents=<><div className="anime-cover" aria-hidden="true">{artwork??(image?<img src={image} alt="" loading="lazy" referrerPolicy="no-referrer"/>:null)}<span className="anime-fallback-title">{anime.title}</span></div>
  {mounted&&trailer&&<div className={'anime-card-video '+(hovered?'is-visible':'')}><iframe title={anime.title+' · трейлер'} src={trailer} tabIndex={-1} allow="autoplay; encrypted-media" referrerPolicy="strict-origin-when-cross-origin"/></div>}
  {hasScore&&<span className="card-score"><Star size={14} fill="currentColor"/>{scoreLabel(anime.score)}</span>}<div className="card-cover-shade"/>
  <div className="card-caption"><h3 className="media-name">{anime.title}</h3><span className="media-meta">{detail??subtitle(anime)}</span>{extra}</div></>;
 return <article ref={root} className={'anime-card-shell media-card '+(compact?'anime-card-compact ':'')+className} data-category={category} data-title-name={titleName} style={{animationDelay:Math.min(index,12)*32+'ms'}} onMouseEnter={enter} onMouseLeave={leave} onFocus={enter} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))leave();}}>
  {href&&!onOpen?<a href={href} className="anime-card media-open" aria-label={openLabel||'Открыть '+anime.title}>{contents}</a>:<button type="button" className="anime-card media-open" onClick={onOpen} aria-label={openLabel||'Открыть '+anime.title}>{contents}</button>}
  {onFavorite&&<button type="button" className={'heart-action bookmark-button '+(favorite?'is-saved':'')} aria-label={favorite?'Убрать из избранного':'В избранное'} aria-pressed={favorite} onClick={onFavorite}><Heart size={16} fill={favorite?'currentColor':'none'}/></button>}
  <AnimeHoverPreview anime={anime} anchor={anchor} open={hovered&&!!anime.synopsis}/>
 </article>;
}
