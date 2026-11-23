import {CardRating} from './CardRating';
import {useEffect,useId,useRef,useState,type ReactNode,type PointerEvent as ReactPointerEvent} from 'react';
import {Bookmark,Tv,BookOpen,BookText,Music2,Film,Image as Photo} from 'lucide-react';
import type {Anime} from '../types/anime';
import {buildTrailerUrl,extractYouTubeId} from '../utils/trailer';
import {coverOf,subtitle} from '../utils/display';
import Artwork from '../../Artwork.jsx';
import {useAnimeSupplement} from '../useAnimeSupplement';
import {AnimeHoverPreview} from './AnimeHoverPreview';
import {translate} from '../../title-metadata.js';
import {localLabel} from '../../taxonomy.js';
import {motion,useMotionValue,useSpring,useTransform,useReducedMotion} from 'motion/react';
import './card-depth.css';

// The cover's own colour (sampled once per image) tints the card's shadow and the page glow.
const tones=new WeakMap<HTMLImageElement,string|null>();
function coverTone(img:HTMLImageElement|null):string|null{
 if(!img||!img.complete||!img.naturalWidth)return null;
 if(tones.has(img))return tones.get(img)!;
 let tone:string|null=null;
 try{const canvas=document.createElement('canvas');canvas.width=12;canvas.height=18;const ctx=canvas.getContext('2d',{willReadFrequently:true});if(ctx){ctx.drawImage(img,0,0,12,18);const d=ctx.getImageData(0,0,12,18).data;let r=0,g=0,b=0,w=0;for(let i=0;i<d.length;i+=4){const max=Math.max(d[i],d[i+1],d[i+2]),min=Math.min(d[i],d[i+1],d[i+2]),weight=(max-min)/255+.08;r+=d[i]*weight;g+=d[i+1]*weight;b+=d[i+2]*weight;w+=weight;}if(w)tone='rgb('+[r,g,b].map(v=>Math.round(v/w)).join(' ')+')';}}catch{tone=null;}
 tones.set(img,tone);return tone;
}
export const glowCard=(tone:string|null)=>dispatchEvent(new CustomEvent('mediavault:card-tone',{detail:tone}));

// AniView archive adapter: data, navigation and favorites belong to MediaVault.
export interface AnimeCardProps {
 anime:Anime;compact?:boolean;index?:number;onOpen?:()=>void;href?:string;
 onFavorite?:()=>void;favorite?:boolean;artwork?:ReactNode;detail?:ReactNode;extra?:ReactNode;
 className?:string;openLabel?:string;category?:string;titleName?:string;
 /** Tilt toward the pointer with a parallax cover and soft light (mouse only). */
 depth?:boolean;
}
export function AnimeCard({anime,compact=false,index=0,onOpen,href,onFavorite,favorite=false,artwork,detail,extra,className='',openLabel,category,titleName,depth=false}:AnimeCardProps){
 const [hovered,setHovered]=useState(false),[mounted,setMounted]=useState(false),[anchor,setAnchor]=useState<DOMRect|null>(null);
 const timer=useRef<ReturnType<typeof setTimeout>|null>(null),root=useRef<HTMLElement>(null);
 const tooltipId=useId();const [nearby,setNearby]=useState(false);
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setNearby(true);observer.disconnect();}},{rootMargin:'250px'});if(root.current)observer.observe(root.current);return()=>observer.disconnect();},[]);
 const [failedImages,setFailedImages]=useState<string[]>([]),original=coverOf(anime),broken=!!original&&failedImages.includes(original);const supplement=useAnimeSupplement(anime,hovered&&(!anime.score||!anime.synopsis||!anime.trailer?.embed_url&&!anime.trailer?.youtube_id)||nearby&&(broken||!original),category||'anime');
 const info=supplement.profile,preview={...anime,synopsis:anime.synopsis||info.description,score:anime.score??info.score,year:anime.year||info.year,episodes:anime.episodes||info.episodes,type:translate(anime.type||info.format,''),status:translate(anime.status||info.status,''),title_japanese:anime.title_japanese||info.originalTitle,genres:(anime.genres?.length?anime.genres:(info.genres||[]).map((name:string)=>({name}))).map((g:any)=>({...g,name:localLabel(g.name)}))};
 const id=extractYouTubeId(supplement.trailer)||anime.trailer?.youtube_id||null;
 const trailer=buildTrailerUrl(id,{autoplay:true,mute:true,loop:true,controls:false});
 const image=[original,supplement.cover].find(url=>url&&!failedImages.includes(url));
 function enter(){if(timer.current)clearTimeout(timer.current);setAnchor(root.current?.getBoundingClientRect()||null);timer.current=setTimeout(()=>{setHovered(true);if(!matchMedia('(prefers-reduced-motion: reduce)').matches&&!navigator.connection?.saveData)setMounted(true);},300);}
 const tiltFrame=useRef(0),reduced=useReducedMotion();
 const rx=useMotionValue(0),ry=useMotionValue(0),lift=useMotionValue(1),sx=useSpring(rx,{stiffness:260,damping:22}),sy=useSpring(ry,{stiffness:260,damping:22}),zoom=useSpring(lift,{stiffness:220,damping:26});
 const px=useTransform(sy,v=>v*-.9),py=useTransform(sx,v=>v*.9);
 const tilts=depth&&!reduced;
 function tilt(event:ReactPointerEvent<HTMLElement>){
  if(!tilts||event.pointerType!=='mouse')return;
  const node=root.current;if(!node)return;
  const rect=node.getBoundingClientRect(),x=Math.min(1,Math.max(0,(event.clientX-rect.left)/rect.width)),y=Math.min(1,Math.max(0,(event.clientY-rect.top)/rect.height));
  rx.set((.5-y)*12);ry.set((x-.5)*14);lift.set(1.08);
  if(!node.style.getPropertyValue('--tone')){const tone=coverTone(node.querySelector('.anime-cover img'));if(tone){node.style.setProperty('--tone',tone);glowCard(tone);}}
  cancelAnimationFrame(tiltFrame.current);
  tiltFrame.current=requestAnimationFrame(()=>{const set=(name:string,value:string)=>node.style.setProperty(name,value);set('--shift-x',((.5-x)*12).toFixed(1)+'px');set('--light-x',(x*100).toFixed(1)+'%');set('--light-y',(y*100).toFixed(1)+'%');node.dataset.tilting='';});
 }
 function untilt(){cancelAnimationFrame(tiltFrame.current);rx.set(0);ry.set(0);lift.set(1);const node=root.current;if(!node)return;if(node.style.getPropertyValue('--tone'))glowCard(null);delete node.dataset.tilting;node.style.removeProperty('--shift-x');node.style.removeProperty('--tone');}
 function leave(){if(timer.current)clearTimeout(timer.current);setHovered(false);setMounted(false);untilt();}
 useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current);cancelAnimationFrame(tiltFrame.current);},[]);
 useEffect(()=>{if(!hovered)return;let frame=0;const refresh=()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;const rect=root.current?.getBoundingClientRect();if(rect&&rect.bottom>0&&rect.top<innerHeight)setAnchor(rect);else leave();});};addEventListener('scroll',refresh,true);addEventListener('resize',refresh);return()=>{cancelAnimationFrame(frame);removeEventListener('scroll',refresh,true);removeEventListener('resize',refresh);};},[hovered]);
 const [KindIcon,kindLabel]=({anime:[Tv,'Аниме'],manga:[BookOpen,'Манга'],ranobe:[BookText,'Ранобэ'],book:[BookOpen,'Книга'],music:[Music2,'Музыка'],audio:[Music2,'Музыка'],video:[Film,'Видео'],movie:[Film,'Фильм'],tv:[Tv,'Сериал'],image:[Photo,'Фото'],photo:[Photo,'Фото']} as any)[category]||[Film,'Видео'];
 const contents=<><motion.div className="anime-cover" aria-hidden="true" style={tilts?{x:px,y:py,scale:zoom}:undefined}>{artwork??(image?<img src={image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailedImages(values=>[...values,image])}/>:<Artwork kind={category||'video'}/>)}</motion.div>
  {mounted&&trailer&&<div className={'anime-card-video '+(hovered?'is-visible':'')}><iframe title={anime.title+' · трейлер'} src={trailer} tabIndex={-1} allow="autoplay; encrypted-media" referrerPolicy="strict-origin-when-cross-origin"/></div>}
  <CardRating score={preview.score}/><div className="card-cover-shade"/>
  {category&&<span className="media-kind-badge" title={kindLabel} aria-label={kindLabel}><KindIcon size={12}/><span className="media-kind-label">{kindLabel}</span></span>}
  <div className="card-caption"><h3 className="media-name" translate="no">{anime.title}</h3><div className="card-caption-details"><span className="media-meta">{detail??subtitle(anime)}</span></div>{extra}</div></>;
 const tiltStyle=tilts?{rotateX:sx,rotateY:sy,transformPerspective:900}:undefined;
 return <article ref={root} className={'anime-card-shell media-card '+(compact?'anime-card-compact ':'')+className} data-category={category} data-title-name={titleName} data-depth={depth?'':undefined} style={{animationDelay:Math.min(index,12)*32+'ms'}} onPointerMove={depth?tilt:undefined} onMouseEnter={enter} onMouseLeave={leave} onFocus={enter} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))leave();}}>
  {href&&!onOpen?<motion.a href={href} className="anime-card media-open" style={tiltStyle} aria-describedby={hovered?tooltipId:undefined} aria-label={openLabel||'Открыть '+anime.title}>{contents}</motion.a>:<motion.button type="button" className="anime-card media-open" style={tiltStyle} onClick={onOpen} aria-describedby={hovered?tooltipId:undefined} aria-label={openLabel||'Открыть '+anime.title}>{contents}</motion.button>}
  {onFavorite&&<button type="button" className={'heart-action bookmark-button '+(favorite?'is-saved':'')} aria-label={favorite?'Убрать из избранного':'В избранное'} aria-pressed={favorite} onClick={onFavorite}><Bookmark size={16} fill={favorite?'currentColor':'none'}/></button>}
  <AnimeHoverPreview id={tooltipId} anime={preview} anchor={anchor} open={hovered} busy={supplement.busy}/>
 </article>;
}
