import {createPortal} from 'react-dom';
import {useLayoutEffect,useRef,useState} from 'react';
import {Captions} from 'lucide-react';
import type {Anime} from '../types/anime';
import {safeSynopsis} from '../utils/display';
export interface AnimeHoverPreviewProps {anime:Anime;anchor:DOMRect|null;open:boolean;busy?:boolean;id?:string}
// Portaled so catalog grids and horizontal rails never clip the detail card.
export function AnimeHoverPreview({anime,anchor,open,busy=false,id}:AnimeHoverPreviewProps){
 const root=useRef<HTMLElement>(null),[position,setPosition]=useState({left:12,top:12,width:325});
 useLayoutEffect(()=>{
  if(!open||!anchor||!root.current)return;
  const update=()=>{const width=Math.min(350,innerWidth-24),height=Math.min(root.current?.offsetHeight||320,innerHeight-24),right=anchor.right+13,left=right+width<=innerWidth-12?right:anchor.left-width-13,next={width,left:Math.max(12,Math.min(left,innerWidth-width-12)),top:Math.max(12,Math.min(anchor.top+(anchor.height-height)/2,innerHeight-height-12))};setPosition(old=>old.left===next.left&&old.top===next.top&&old.width===next.width?old:next);};
  update();const observer=new ResizeObserver(update);observer.observe(root.current);return()=>observer.disconnect();
 },[open,anchor?.left,anchor?.top,anchor?.height,anchor?.right]);
 if(!anchor||!open)return null;
 const summary=safeSynopsis(anime);
 return createPortal(<aside ref={root} id={id} className="anime-preview is-portal is-open" style={{...position,transform:'none'}} role="tooltip">
  <div className="preview-head"><h3>{anime.title}</h3></div>
  <p className="preview-synopsis">{summary||(busy?'Загружаем описание…':'Описание пока не предоставлено каталогом.')}</p>
  {anime.episodes&&<div className="preview-chips"><span><Captions size={14}/>{anime.episodes} сер.</span></div>}
  <dl className="preview-specs"><dt>Оригинал</dt><dd>{anime.title_japanese||'—'}</dd><dt>Выпуск</dt><dd>{anime.aired?.string||anime.year||'—'}</dd><dt>Статус</dt><dd>{anime.status||'—'}</dd><dt>Жанры</dt><dd>{anime.genres?.map(g=>g.name).join(', ')||'—'}</dd></dl>
 </aside>,document.body);
}
