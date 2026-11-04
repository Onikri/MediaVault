import {useEffect,useId,useRef,useState,type ReactNode} from 'react';
import {Bookmark,Star,Tv,BookOpen,BookText,Music2,Film,Image as Photo} from 'lucide-react';
import type {Anime} from '../types/anime';
import {buildTrailerUrl,extractYouTubeId} from '../utils/trailer';
import {coverOf,scoreLabel,subtitle} from '../utils/display';
import Artwork from '../../Artwork.jsx';
import {useAnimeSupplement} from '../useAnimeSupplement';
import {AnimeHoverPreview} from './AnimeHoverPreview';
import {translate} from '../../title-metadata.js';
import {localLabel} from '../../taxonomy.js';

// AniView archive adapter: data, navigation and favorites belong to MediaVault.
export interface AnimeCardProps {
 anime:Anime;compact?:boolean;index?:number;onOpen?:()=>void;href?:string;
 onFavorite?:()=>void;favorite?:boolean;artwork?:ReactNode;detail?:ReactNode;extra?:ReactNode;
 className?:string;openLabel?:string;category?:string;titleName?:string;
}
export function AnimeCard({anime,compact=false,index=0,onOpen,href,onFavorite,favorite=false,artwork,detail,extra,className='',openLabel,category,titleName}:AnimeCardProps){
 const [hovered,setHovered]=useState(false),[mounted,setMounted]=useState(false),[anchor,setAnchor]=useState<DOMRect|null>(null);
 const timer=useRef<ReturnType<typeof setTimeout>|null>(null),root=useRef<HTMLElement>(null);
 const tooltipId=useId();const [nearby,setNearby]=useState(false);
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setNearby(true);observer.disconnect();}},{rootMargin:'250px'});if(root.current)observer.observe(root.current);return()=>observer.disconnect();},[]);
 const [failedImages,setFailedImages]=useState<string[]>([]),original=coverOf(anime),broken=!!original&&failedImages.includes(original);const supplement=useAnimeSupplement(anime,hovered&&(!anime.synopsis||!anime.trailer?.embed_url&&!anime.trailer?.youtube_id)||nearby&&(broken||!original),category||'anime');
 const info=supplement.profile,preview={...anime,synopsis:anime.synopsis||info.description,score:anime.score??info.score,year:anime.year||info.year,episodes:anime.episodes||info.episodes,type:translate(anime.type||info.format,''),status:translate(anime.status||info.status,''),title_japanese:anime.title_japanese||info.originalTitle,genres:(anime.genres?.length?anime.genres:(info.genres||[]).map((name:string)=>({name}))).map((g:any)=>({...g,name:localLabel(g.name)}))};
 const id=extractYouTubeId(supplement.trailer)||anime.trailer?.youtube_id||null;
 const trailer=buildTrailerUrl(id,{autoplay:true,mute:true,loop:true,controls:false});
 const image=[original,supplement.cover].find(url=>url&&!failedImages.includes(url)),hasScore=typeof anime.score==='number'&&Number.isFinite(anime.score);
 function enter(){if(timer.current)clearTimeout(timer.current);setAnchor(root.current?.getBoundingClientRect()||null);timer.current=setTimeout(()=>{setHovered(true);if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&!navigator.connection?.saveData)setMounted(true);},300);}
 function leave(){if(timer.current)clearTimeout(timer.current);setHovered(false);setMounted(false);}
 useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current);},[]);
 useEffect(()=>{if(!hovered)return;let frame=0;const refresh=()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;const rect=root.current?.getBoundingClientRect();if(rect&&rect.bottom>0&&rect.top<innerHeight)setAnchor(rect);else leave();});};addEventListener('scroll',refresh,true);addEventListener('resize',refresh);return()=>{cancelAnimationFrame(frame);removeEventListener('scroll',refresh,true);removeEventListener('resize',refresh);};},[hovered]);
 const contents=<><div className="anime-cover" aria-hidden="true">{artwork??(image?<img src={image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailedImages(values=>[...values,image])}/>:<Artwork kind={category||'video'}/>)}</div>
  {mounted&&trailer&&<div className={'anime-card-video '+(hovered?'is-visible':'')}><iframe title={anime.title+' · трейлер'} src={trailer} tabIndex={-1} allow="autoplay; encrypted-media" referrerPolicy="strict-origin-when-cross-origin"/></div>}
  <div className="card-cover-shade"/>
  {category&&<span className="media-kind-badge">{(()=>{const [Icon,label]=({anime:[Tv,'Аниме'],manga:[BookOpen,'Манга'],ranobe:[BookText,'Ранобэ'],book:[BookOpen,'Книга'],music:[Music2,'Музыка'],audio:[Music2,'Музыка'],video:[Film,'Видео'],movie:[Film,'Фильм'],tv:[Tv,'Сериал'],image:[Photo,'Фото'],photo:[Photo,'Фото']} as any)[category]||[Film,'Видео'];return <><Icon size={12}/><span className="media-kind-label">{label}</span></>;})()}</span>}
  <div className="card-caption"><h3 className="media-name">{anime.title}</h3><div className="card-caption-details"><span className="media-meta">{detail??subtitle(anime)}</span>{hasScore&&<span className="card-score" aria-label={'Оценка '+scoreLabel(anime.score)}><Star size={12} fill="currentColor"/>{scoreLabel(anime.score)}</span>}</div>{extra}</div></>;
 return <article ref={root} className={'anime-card-shell media-card '+(compact?'anime-card-compact ':'')+className} data-category={category} data-title-name={titleName} style={{animationDelay:Math.min(index,12)*32+'ms'}} onMouseEnter={enter} onMouseLeave={leave} onFocus={enter} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))leave();}}>
  {href&&!onOpen?<a href={href} className="anime-card media-open" aria-describedby={hovered?tooltipId:undefined} aria-label={openLabel||'Открыть '+anime.title}>{contents}</a>:<button type="button" className="anime-card media-open" onClick={onOpen} aria-describedby={hovered?tooltipId:undefined} aria-label={openLabel||'Открыть '+anime.title}>{contents}</button>}
  {onFavorite&&<button type="button" className={'heart-action bookmark-button '+(favorite?'is-saved':'')} aria-label={favorite?'Убрать из избранного':'В избранное'} aria-pressed={favorite} onClick={onFavorite}><Bookmark size={16} fill={favorite?'currentColor':'none'}/></button>}
  <AnimeHoverPreview id={tooltipId} anime={preview} anchor={anchor} open={hovered} busy={supplement.busy}/>
 </article>;
}
