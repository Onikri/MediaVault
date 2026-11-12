import {useEffect,useMemo,useRef,useState} from 'react';
import {ChevronDown} from 'lucide-react';
import {counted} from './title-context.js';

const CHAPTER=['глава','главы','глав'],VOLUME=['том','тома','томов'];
const volumeOf=entry=>Number(entry.season)||0;
// Every chapter of the chosen source, grouped by volume, with the one being
// read marked. Lives in the reader stage's right column.
export default function ChapterIndex({entries=[],current='',onOpen,read=new Set(),loading=false,emptyText='Выбери источник слева — здесь появятся главы и тома.',volumeNames={}}){
 const [query,setQuery]=useState(''),[limits,setLimits]=useState({}),list=useRef(null);
 const groups=useMemo(()=>{const map=new Map();for(const e of entries){const v=volumeOf(e);if(!map.has(v))map.set(v,[]);map.get(v).push(e);}return [...map.entries()];},[entries]);
 const currentVolume=groups.find(([,rows])=>rows.some(e=>e.url===current))?.[0];
 const [open,setOpen]=useState(()=>new Set());
 useEffect(()=>{setOpen(new Set([currentVolume??groups[0]?.[0]]));setLimits({});},[entries[0]?.url,entries.length]);
 useEffect(()=>{if(currentVolume!=null)setOpen(old=>old.has(currentVolume)?old:new Set([...old,currentVolume]));},[currentVolume]);
 // Keep the chapter being read in view inside the column.
 useEffect(()=>{const node=list.current?.querySelector('[aria-current="true"]');node?.scrollIntoView?.({block:'nearest'});},[current,open]);
 const needle=query.trim().toLocaleLowerCase('ru');
 const match=e=>!needle||String(e.number).startsWith(needle)||String(e.title||'').toLocaleLowerCase('ru').includes(needle);
 const volumes=groups.filter(([v])=>v>0).length;
 const row=e=><li key={e.url}><button type="button" aria-current={e.url===current||undefined} data-read={read.has(e.url)||undefined} onClick={()=>onOpen(e)}>
  <span className="chapter-index-number">{Number.isFinite(Number(e.number))?e.number:'—'}</span>
  <span className="chapter-index-title">{e.title&&!/^(глава|chapter)\s*[\d.]+$/i.test(e.title.trim())?e.title:'Глава '+e.number}{e.translator&&<small>{e.translator}</small>}</span>
 </button></li>;
 return <section className="chapter-index" aria-label="Главы и тома">
  <header><h3>Главы и тома</h3>{entries.length>0&&<p>{counted(entries.length,CHAPTER)}{volumes?' · '+counted(volumes,VOLUME):''}</p>}</header>
  {entries.length>12&&<input className="chapter-index-search" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Номер или название главы" aria-label="Найти главу"/>}
  <div className="chapter-index-list" ref={list}>
   {!entries.length?<p className="chapter-index-empty" role="status">{loading?'Загружаем главы…':emptyText}</p>
   :groups.length===1||needle?<ol>{entries.filter(match).slice(0,needle?200:limits.all||120).map(row)}{!needle&&entries.length>(limits.all||120)&&<li><button type="button" className="chapter-index-more" onClick={()=>setLimits(l=>({...l,all:(l.all||120)+200}))}>Показать ещё</button></li>}</ol>
   :groups.map(([volume,rows])=>{const expanded=open.has(volume),limit=limits[volume]||100;return <div className="chapter-index-volume" key={volume} data-open={expanded||undefined}>
    <button type="button" className="chapter-index-volume-head" aria-expanded={expanded} onClick={()=>setOpen(old=>{const next=new Set(old);next.has(volume)?next.delete(volume):next.add(volume);return next;})}>
     <strong>{volume?volumeNames[volume]||'Том '+volume:'Без тома'}</strong><span>{counted(rows.length,CHAPTER)}</span><ChevronDown size={15} aria-hidden="true"/>
    </button>
    {expanded&&<ol>{rows.slice(0,limit).map(row)}{rows.length>limit&&<li><button type="button" className="chapter-index-more" onClick={()=>setLimits(l=>({...l,[volume]:limit+200}))}>Показать ещё</button></li>}</ol>}
   </div>;})}
  </div>
 </section>;
}
