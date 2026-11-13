import {useEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {ChevronDown,ChevronLeft,ChevronRight,Search} from 'lucide-react';
import UiSegmented from './UiSegmented.jsx';
import {plural} from './title-context.js';
import {currentBackdrop,paletteFromSeed,rgb} from './blossom/theme.js';
import {sourceOf} from './source-badges.jsx';
import useChapterThumbnails from './use-chapter-thumbnails.js';
import './manga-desk.css';

const CHAPTER=['глава','главы','глав'];
// Language of a source or a chapter, as short Latin codes.
export const LANGUAGE_CODES=[['all','Все'],['ru','RU'],['uk','UA'],['en','EN'],['ja','JA'],['ko','KR']];
export const languageCode=id=>LANGUAGE_CODES.find(([key])=>key===id)?.[1]||String(id||'').toUpperCase();
const spring={type:'spring',stiffness:420,damping:38};

// The title's own colour (the backdrop palette), legible on the dark desk.
function useTitleAccent(){
 const seed=useSyncExternalStore(listen=>{addEventListener('mediavault:backdrop-palette',listen);return()=>removeEventListener('mediavault:backdrop-palette',listen);},currentBackdrop,()=>null);
 return useMemo(()=>seed?rgb(paletteFromSeed(seed).blossom).join(' '):null,[seed]);
}
export function useDeskStyle(){const accent=useTitleAccent();return accent?{'--desk-accent-rgb':accent}:undefined;}

// «Том 1 Глава 3: Пролог» → «Пролог»; a bare «Глава 3» has no name of its own.
export function chapterName(entry){
 const raw=String(entry?.title||'').replace(/\s+/g,' ').trim();
 const match=raw.match(/^(?:(?:том|vol\.?|volume)\s*[\d.]+\s*[.,:·—–-]?\s*)?(?:глава|chapter|ch\.?)\s*[\d.]+\s*[.:·—–-]?\s*(.*)$/i);
 const rest=(match?match[1]:raw).trim();
 return rest&&!/^[\d.]+$/.test(rest)?rest:'';
}
const numberOf=entry=>Number.isFinite(Number(entry?.number))?String(entry.number):'—';
const hueOf=name=>{const known=sourceOf(name);if(known?.hue!=null)return known.hue;let h=0;for(const c of String(name||''))h=(h*31+c.charCodeAt(0))%360;return h;};

// Source, language, team and chapters of the online reader: the right column
// of the reading desk. One plaque names the site the pages come from.
export default function MangaDeskPanel({source,sourceLanguage,sourceChapters,sourceState='idle',sourceNote,sourceMenu,language,onLanguage,teams=[],team,onTeam,allTeamsLabel='Все команды',entries=[],current,onOpen,progress,read=new Set(),service,userId,loading=false,reading=false}){
 const reduce=useReducedMotion(),[menu,setMenu]=useState(''),panel=useRef(null);
 const toggle=name=>setMenu(old=>old===name?'':name);
 useEffect(()=>{if(menu==='team'&&teams.length<2)setMenu('');},[teams.length,menu]);
 const index=entries.findIndex(e=>e.url===current),chapter=entries[index]||null;
 const teamRows=[...teams].sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name,'ru')),maxTeam=Math.max(1,...teamRows.map(t=>t.count));
 const chosenTeam=teamRows.find(t=>t.name===team);
 const reveal=reduce?{initial:{opacity:0},animate:{opacity:1},exit:{opacity:0}}:{initial:{opacity:0,height:0},animate:{opacity:1,height:'auto'},exit:{opacity:0,height:0}};
 return <aside className="desk-panel" ref={panel} aria-label="Источник и главы">
  <section className="desk-source" data-state={sourceState}>
   <button type="button" className="desk-source-plaque" aria-expanded={menu==='source'} onClick={()=>toggle('source')}>
    {source?<span className="desk-source-tag" style={{'--source-hue':hueOf(source)}}>{source}</span>:<span className="desk-source-searching">{sourceState==='searching'&&<span className="mvx-spinner" aria-hidden="true"/>}{sourceNote||'Источник не выбран'}</span>}
    {source&&<span className="desk-source-facts">{sourceLanguage&&<b>{languageCode(sourceLanguage)}</b>}{Number.isFinite(sourceChapters)&&<span>{sourceChapters} {plural(sourceChapters,CHAPTER)}</span>}{sourceState==='verifying'&&<span className="mvx-spinner" aria-label="Проверяем страницы"/>}</span>}
    <ChevronDown className="desk-chevron" size={16} aria-hidden="true"/>
   </button>
   {source&&sourceNote&&<p className="desk-source-note" role="status">{sourceNote}</p>}
   <AnimatePresence initial={false}>{menu==='source'&&<motion.div key="sources" className="desk-reveal" {...reveal} transition={reduce?{duration:.12}:spring}><div className="desk-source-menu">{sourceMenu}</div></motion.div>}</AnimatePresence>
  </section>
  <div className="desk-language"><UiSegmented className="is-wide" label="Язык глав" value={language} options={LANGUAGE_CODES} onChange={value=>{setMenu(old=>old==='team'?'':old);onLanguage(value);}}/></div>
  {teamRows.length>1&&<section className="desk-team">
   <button type="button" className="desk-team-button" aria-expanded={menu==='team'} onClick={()=>toggle('team')}>
    <span className="desk-team-label">Перевод</span><strong>{chosenTeam?chosenTeam.name:allTeamsLabel}</strong>{chosenTeam&&<small>{chosenTeam.count} {plural(chosenTeam.count,CHAPTER)}</small>}<ChevronDown className="desk-chevron" size={15} aria-hidden="true"/>
   </button>
   <AnimatePresence initial={false}>{menu==='team'&&<motion.div key="teams" className="desk-reveal" {...reveal} transition={reduce?{duration:.12}:spring}>
    <ul className="desk-team-list" role="listbox" aria-label="Команда перевода">
     <li><button type="button" role="option" aria-selected={!team} onClick={()=>{onTeam('');setMenu('');}}><strong>{allTeamsLabel}</strong></button></li>
     {teamRows.map(row=><li key={row.name}><button type="button" role="option" aria-selected={team===row.name} onClick={()=>{onTeam(row.name);setMenu('');}} style={{'--fill':row.count/maxTeam}}><strong>{row.name}</strong><small>{row.count} {plural(row.count,CHAPTER)}</small><i aria-hidden="true"/></button></li>)}
    </ul>
   </motion.div>}</AnimatePresence>
  </section>}
  <NowReading chapter={chapter} previous={entries[index-1]} next={entries[index+1]} onOpen={onOpen} progress={progress?.url===chapter?.url?progress:null} reading={reading} reduce={reduce} service={service} userId={userId}/>
  <ChapterList entries={entries} current={current} onOpen={onOpen} read={read} loading={loading} reduce={reduce} primaryTeam={team||teamRows[0]?.name||''}/>
 </aside>;
}

function NowReading({chapter,previous,next,onOpen,progress,reading,reduce,service,userId}){
 const root=useRef(null),targets=useMemo(()=>chapter?[chapter]:[],[chapter?.url]);
 const thumbs=useChapterThumbnails(root,targets,service,userId,!!chapter&&!!service);
 if(!chapter)return null;
 const art=thumbs[chapter.url]||chapter.thumbnail,name=chapterName(chapter),fraction=progress?.total?Math.min(1,(progress.page+1)/progress.total):0;
 return <section className="desk-now" ref={root} aria-label="Текущая глава">
  <AnimatePresence mode="popLayout" initial={false}>
   <motion.div key={chapter.url} className="desk-now-body" data-preview-key={chapter.url} initial={reduce?{opacity:0}:{opacity:0,y:14}} animate={{opacity:1,y:0}} exit={reduce?{opacity:0}:{opacity:0,y:-10}} transition={reduce?{duration:.12}:spring}>
    {art&&<img className="desk-now-art" src={art} alt="" loading="lazy" referrerPolicy="no-referrer"/>}
    <div className="desk-now-copy">
     <span className="desk-now-kicker">{reading?'Читаешь':'Начнёшь с'}{Number(chapter.season)>0?' · том '+chapter.season:''}</span>
     <strong className="desk-now-number">Глава {numberOf(chapter)}</strong>
     {name&&<span className="desk-now-name">{name}</span>}
     {progress?.total>0&&<span className="desk-now-meter" style={{'--fill':fraction}}><i aria-hidden="true"/><small>Страница {progress.page+1} из {progress.total}</small></span>}
    </div>
   </motion.div>
  </AnimatePresence>
  <div className="desk-now-steps">
   <button type="button" disabled={!previous} aria-label={previous?'Предыдущая глава · '+numberOf(previous):'Предыдущей главы нет'} title="Предыдущая глава" onClick={()=>previous&&onOpen(previous)}><ChevronLeft size={18}/></button>
   <button type="button" disabled={!next} aria-label={next?'Следующая глава · '+numberOf(next):'Следующей главы нет'} title="Следующая глава" onClick={()=>next&&onOpen(next)}><ChevronRight size={18}/></button>
  </div>
 </section>;
}

// A row names its team only when it differs from the team being read.
function ChapterList({entries,current,onOpen,read,loading,reduce,primaryTeam=''}){
 const [query,setQuery]=useState(''),[limit,setLimit]=useState(150),list=useRef(null);
 useEffect(()=>{setLimit(150);},[entries[0]?.url,entries.length]);
 const needle=query.trim().toLocaleLowerCase('ru');
 const shown=useMemo(()=>{
  const rows=needle?entries.filter(e=>String(e.number).startsWith(needle)||String(e.title||'').toLocaleLowerCase('ru').includes(needle)):entries;
  const at=Math.max(0,rows.findIndex(e=>e.url===current));
  // The window always contains the chapter being read.
  const start=rows.length>limit&&at>=limit?Math.max(0,at-Math.floor(limit/2)):0;
  return {rows:rows.slice(start,start+limit),start,total:rows.length};
 },[entries,needle,limit,current]);
 const groups=useMemo(()=>{const map=new Map();for(const e of shown.rows){const v=Number(e.season)||0;if(!map.has(v))map.set(v,[]);map.get(v).push(e);}return [...map.entries()];},[shown.rows]);
 const volumes=new Set(entries.map(e=>Number(e.season)||0)).size;
 useEffect(()=>{const node=list.current?.querySelector('[aria-current="true"]');if(!node)return;const box=list.current,top=node.offsetTop-box.offsetTop;if(top<box.scrollTop||top>box.scrollTop+box.clientHeight-node.offsetHeight)box.scrollTo({top:Math.max(0,top-box.clientHeight/3),behavior:reduce?'instant':'smooth'});},[current,shown.rows.length]);
 return <section className="desk-chapters" aria-label="Главы">
  <header><h3>Главы</h3><span>{entries.length?entries.length+' '+plural(entries.length,CHAPTER)+(volumes>1?' · '+volumes+' '+plural(volumes,['том','тома','томов']):''):''}</span>
   {entries.length>24&&<label className="desk-search"><Search size={14} aria-hidden="true"/><input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Номер или название" aria-label="Найти главу"/></label>}
  </header>
  <div className="desk-chapter-scroll" ref={list}>
   {!entries.length?<p className="desk-empty" role="status">{loading?'Загружаем главы…':'Главы появятся, когда найдётся источник.'}</p>
   :!shown.rows.length?<p className="desk-empty">Такой главы нет в этом переводе.</p>
   :<>{shown.start>0&&<button type="button" className="desk-more" onClick={()=>setLimit(n=>n+shown.start)}>Показать ранние главы</button>}
    {groups.map(([volume,rows])=><div className="desk-volume" key={volume}>
     {volumes>1&&<h4>{volume?'Том '+volume:'Без тома'}</h4>}
     <ol>{rows.map(e=>{const active=e.url===current,name=chapterName(e);return <li key={e.url}>
      <button type="button" aria-current={active||undefined} data-read={read.has(e.url)||undefined} onClick={()=>onOpen(e)}>
       {active&&<motion.span layoutId="desk-current-chapter" className="desk-current" transition={reduce?{duration:0}:spring}/>}
       <span className="desk-number">{numberOf(e)}</span>
       <span className="desk-title"><span>{name||'Глава '+numberOf(e)}</span>{e.translator&&e.translator!==primaryTeam&&<small>{e.translator}</small>}</span>
      </button>
     </li>;})}</ol>
    </div>)}
    {shown.start+shown.rows.length<shown.total&&<button type="button" className="desk-more" onClick={()=>setLimit(n=>n+300)}>Показать ещё</button>}</>}
  </div>
 </section>;
}
