import DockLens from './DockLens';
import TitleSectionDock from '../../TitleSectionDock.jsx';
import NavShell,{setNavProgress} from '../../title-exact/navbar/NavShell.jsx';
import type {ReactNode} from 'react';
import {useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {CloudUpload,History,House,LayoutGrid,Search} from 'lucide-react';
import '../../section-navigation.css';
import './demo-navbar.css';
const navigationIcons={home:House,library:LayoutGrid,collection:CloudUpload,history:History};
const navIcon=(link:Link)=>{const Glyph=navigationIcons[link.id as keyof typeof navigationIcons];return link.icon??(Glyph?<Glyph/>:null);};
type Link={id:string;label:string;icon?:ReactNode};
// The design's navbar (src/title-exact/navbar/NavShell) plus the phone dock.
// --nav-t drives its morph: the title page sets it from its showcase, other pages from the scroll.
export function AnimatedNavbar({links,active,onNavigate,onSearch,onBrand,children,searchActive=false,search}:{links:Link[];active:string;onNavigate:(id:string)=>void;onSearch:()=>void;onBrand?:()=>void;brand?:ReactNode;children?:ReactNode;searchActive?:boolean;search?:ReactNode}){
 const [scrolled,setScrolled]=useState(false),[open,setOpen]=useState(false),[searchOpen,setSearchOpen]=useState(false);
 useEffect(()=>{const root=document.documentElement;let frame=0;const scroll=()=>{frame=0;setScrolled(scrollY>30);if(root.hasAttribute('data-title-exact'))return;const x=Math.min(1,Math.max(0,scrollY/200));setNavProgress(x*x*(3-2*x));};const schedule=()=>{if(!frame)frame=requestAnimationFrame(scroll);};scroll();addEventListener('scroll',schedule,{passive:true});return()=>{cancelAnimationFrame(frame);removeEventListener('scroll',schedule);};},[]);
 useEffect(()=>setOpen(false),[active]);
 useEffect(()=>{const key=(event:KeyboardEvent)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();if(document.documentElement.dataset.catalogMerged){dispatchEvent(new Event('mediavault:catalog-focus'));return;}onSearch();}if(event.key==='Escape')setOpen(false);};addEventListener('keydown',key);return()=>removeEventListener('keydown',key);},[onSearch]);
 useEffect(()=>{const start=()=>setSearchOpen(true),stop=()=>setSearchOpen(false);addEventListener('mediavault:search-open',start);addEventListener('mediavault:search-close',stop);return()=>{removeEventListener('mediavault:search-open',start);removeEventListener('mediavault:search-close',stop);};},[]);
 const go=(id:string)=>{setOpen(false);onNavigate(id);};
 return <><NavShell links={links} active={active} onNavigate={go} onBrand={onBrand||(()=>go('home'))} onSearch={onSearch} searchActive={searchActive} search={search} menuOpen={open} onMenu={setOpen} scrolled={scrolled} extra={<TitleSectionDock hidden={searchOpen||open}/>}>{children}</NavShell>
 {/* Phones: primary navigation lives in a dock under the thumb; search is its centre. */}
 {createPortal(<nav className="mobile-dock" aria-label="Навигация"><DockLens/>{links.filter(v=>v.id!=='profile').flatMap((v,i,all)=>{const item=<button type="button" key={v.id} aria-label={v.label} className={'mobile-dock-link'+(active===v.id?' is-active':'')} aria-current={active===v.id?'page':undefined} onClick={()=>go(v.id)}><span className="mobile-dock-icon" aria-hidden="true">{navIcon(v)}</span><span className="mobile-dock-label">{v.label}</span></button>;return i===Math.floor(all.length/2)?[<button type="button" key="search" className="mobile-dock-search" aria-label="Поиск" onClick={()=>{document.documentElement.dataset.searchFrom='dock';onSearch();}}><Search size={21}/></button>,item]:[item];})}</nav>,document.body)}</>;
}
