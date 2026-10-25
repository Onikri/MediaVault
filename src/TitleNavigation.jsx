import {useEffect,useState} from 'react';
import {BookOpen,Play,AlignLeft,Users,Layers,Star,Music2} from 'lucide-react';
export default function TitleNavigation({title,profile}){
 const [active,setActive]=useState('titleSummary');
 const sections=[['titleSummary','Обзор',AlignLeft],...(title.items.length?[['titlePlayback',title.category==='manga'?'Читать':'Смотреть',title.category==='manga'?BookOpen:Play]]:[]),...(/^\d+$/.test(String(profile.sourceId||''))?[['titleRatings','Оценки',Star]]:[]),...(title.section==='anime'&&/^\d+$/.test(String(profile.sourceId||title.metadataId||''))?[['titleMusic','Музыка',Music2]]:[]),...(profile.characters?.length?[['titleCharacters','Герои',Users]]:[]),...(profile.related?.length?[['titleRelated','Связи',Layers]]:[])];
 const key=sections.map(s=>s[0]).join(':');
 useEffect(()=>{const observer=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top);if(visible.length)setActive(visible[0].target.id);},{rootMargin:'-100px 0px -55% 0px',threshold:0});for(const [id]of sections){const node=document.getElementById(id==='titlePlayback'?'titlePlayback':id);if(node)observer.observe(node);}return()=>observer.disconnect();},[key]);
 function go(id){const target=document.getElementById(id)||document.getElementById('titleMaterials');target?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});setActive(id);}
 return <nav className="title-shortcuts" aria-label="Разделы тайтла">{sections.map(([id,label,Icon])=><button key={id} aria-current={active===id?'location':undefined} onClick={()=>go(id)}><Icon size={14}/><span>{label}</span></button>)}</nav>;
}
