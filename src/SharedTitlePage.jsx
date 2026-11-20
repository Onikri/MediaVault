import {useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen,ChevronDown,Play} from 'lucide-react';
import {TitleImage} from './TitlePage.jsx';
import {plural} from './title-context.js';
import './shared-title.css';
import OnlineViewer from './OnlineViewer.jsx';

const server=()=>String(window.MEDIA_VAULT_CONFIG?.importServerUrl||'').replace(/\/$/,'');

export default function SharedTitlePage({token}){
 const [grant,setGrant]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const current=useRef(null);
 useEffect(()=>{
  const abort=new AbortController();setError('');setGrant(null);
  fetch(server()+'/shares/title/'+encodeURIComponent(token),{signal:abort.signal,cache:'no-store'})
   .then(async r=>{const data=await r.json();if(!r.ok)throw Error(data.detail||'Ссылка недоступна.');return data;})
   .then(data=>{if(!abort.signal.aborted){current.current=data;setGrant(data);}})
   .catch(e=>{if(!abort.signal.aborted)setError(e.message);});
  return()=>abort.abort();
 },[token,retry]);
 const service=useMemo(()=>{
  if(!grant)return null;
  let renewal=null;
  async function renew(){
   if(!renewal)renewal=fetch(server()+'/shares/title/'+encodeURIComponent(token),{cache:'no-store'})
    .then(async r=>{const data=await r.json();if(!r.ok)throw Error(data.detail||'Ссылка закрыта владельцем.');current.current=data;})
    .finally(()=>{renewal=null;});
   return renewal;
  }
  return {server:server(),status:'connected',session:{role:'share',serverVersion:65},shared:true,
   request:async(path,options={})=>{
    if(current.current.expiresAt*1000<Date.now()+60000)await renew();
    const response=await fetch(server()+path,{method:options.method||'GET',signal:options.signal||AbortSignal.timeout(path==='/reader/google/generate'?150000:45000),
     keepalive:options.keepalive,headers:{Authorization:'Bearer '+current.current.token,...(options.body?{'Content-Type':'application/json'}:{})},
     ...(options.body?{body:JSON.stringify(options.body)}:{})});
    if(options.raw&&response.ok)return response;
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Object.assign(Error(typeof data.detail==='string'?data.detail:'Источник не ответил.'),{status:response.status});
    return data;
   }};
 },[grant,token]);
 if(error)return <main className="shared-title shared-title-state"><p className="inline-error" role="alert">{error}</p><button className="btn btn-secondary" onClick={()=>setRetry(v=>v+1)}>Повторить</button></main>;
 if(!grant||!service)return <main className="shared-title shared-title-state"><p role="status"><span className="loading-ring"/>Открываем тайтл…</p></main>;
 return <SharedTitle key={grant.id} grant={grant} service={service}/>;
}

const sectionNames={manga:'Манга',anime:'Аниме',movie:'Фильм',tv:'Сериал',ranobe:'Ранобэ',book:'Книга',audio:'Музыка',photo:'Фото',game:'Игра'};
const formatNames={manga:'Манга',manhwa:'Манхва',manhua:'Маньхуа',webtoon:'Вебтун',comic:'Комикс',rumanga:'Руманга'};
function entryLabel(entry,manga){
 const simple=(manga?'Глава ':'Серия ')+entry.number;
 const volume=entry.season>1?(manga?'Том ':'Сезон ')+entry.season:'';
 const name=entry.title?.trim();
 return [volume,simple,name&&name.toLowerCase()!==simple.toLowerCase()?name:null].filter(Boolean).join(' · ');
}

function SharedBackdrop({grant,service,paused}){
 const [pages,setPages]=useState([]);
 useEffect(()=>{
  if(grant.kind!=='manga'||navigator.connection?.saveData||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const abort=new AbortController();
  const entries=grant.entries;
  const selected=[...new Set([grant.initial,0,Math.floor(entries.length/2),entries.length-1])].slice(0,3);
  (async()=>{
   for(const index of selected){
    if(abort.signal.aborted)return;
    try{
     const data=await service.request('/manga/thumbnail',{method:'POST',body:{url:entries[index].url},
      signal:AbortSignal.any([abort.signal,AbortSignal.timeout(18000)])});
     if(!abort.signal.aborted&&data.image?.startsWith('data:image/jpeg;base64,')&&data.image.length<=150000)
      setPages(old=>[...old,data.image]);
    }catch{}
   }
  })();
  return()=>abort.abort();
 },[grant,service]);
 const art=[...pages,grant.title.cover].filter(Boolean);
 if(!art.length)return null;
 return <div className="shared-title-backdrop" data-paused={paused} aria-hidden="true">
  {[0,1,2].map(lane=><div className="shared-title-lane" key={lane}>
   {[0,1,2].map(row=><img key={row} src={art[(lane+row)%art.length]} alt="" decoding="async" referrerPolicy="no-referrer"/>)}
  </div>)}
 </div>;
}

function SharedTitle({grant,service}){
 const [open,setOpen]=useState(false),[more,setMore]=useState(false),[chapter,setChapter]=useState(grant.initial);
 const [start,setStart]=useState(grant.initial);
 const manga=grant.kind==='manga',year=Number(grant.title.year)||null,description=String(grant.title.description||'').trim();
 const profile={title:grant.title.name,cover:grant.title.cover,description,year,ids:grant.title.ids,format:grant.title.format,readingMode:grant.title.readingMode};
 const kind=formatNames[grant.title.format]||grant.title.format||sectionNames[grant.title.section]||(manga?'Манга':grant.kind==='video'?'Видео':'');
 const units=grant.entries.length,unitWord=manga?plural(units,['глава','главы','глав']):plural(units,['серия','серии','серий']);
 const chapters=grant.entries.some(entry=>entry.season>1);
 const heading=useRef(null);
 function read(){setStart(chapter);setOpen(true);}
 function close(){
  setOpen(false);
  requestAnimationFrame(()=>heading.current?.scrollIntoView({block:'start'}));
 }
 useEffect(()=>{const name=grant.title.name;const old=document.title;document.title=name;return()=>{document.title=old;};},[grant.title.name]);
 return <main className="shared-title">
  <header ref={heading} className="shared-title-hero">
   <SharedBackdrop grant={grant} service={service} paused={open}/>
   <div className="shared-title-feature">
   {grant.title.cover&&<div className="shared-title-cover"><TitleImage url={grant.title.cover} actions={{}} fallback={false} alt={'Обложка: '+grant.title.name}/></div>}
   <div className="shared-title-copy">
    <p className="shared-title-kind">{[kind,year,units?units+' '+unitWord:null,grant.dub||null].filter(Boolean).join(' · ')}</p>
    <h1>{grant.title.name}</h1>
    {description&&<><p className={'shared-title-about'+(more?' is-open':'')}>{description}</p>{description.length>220&&<button type="button" className="shared-title-more" aria-expanded={more} onClick={()=>setMore(v=>!v)}>{more?'Свернуть':'Подробнее'}</button>}</>}
    {units>0&&<div className="shared-title-actions">
     <label className="shared-title-chapters">
      <span>{manga?'Главы':'Серии'}</span>
      <select value={chapter} disabled={units===1} onChange={event=>{
       const index=Number(event.target.value);setChapter(index);if(open)setStart(index);
      }} aria-label={manga?'Выбрать главу':'Выбрать серию'}>
       {grant.entries.map((entry,index)=><option key={index} value={index} title={entry.title||undefined}>
        {chapters&&entry.season===1?(manga?'Том 1 · ':'Сезон 1 · '):''}{entryLabel(entry,manga)}
       </option>)}
      </select>
      {units>1&&<ChevronDown size={15} aria-hidden="true"/>}
     </label>
     <button type="button" className="btn btn-primary" onClick={open?()=>document.querySelector('.shared-title-reader')?.scrollIntoView({block:'start'}):read}>
      {manga?<BookOpen size={17}/>:<Play size={17}/>} {manga?'Читать':'Смотреть'}
     </button>
    </div>}
   </div>
   </div>
  </header>
  {open&&<section className="shared-title-reader" aria-label={manga?'Читалка':'Плеер'}>
   <OnlineViewer key={start} inline entries={grant.entries} initial={grant.entries[start]} kind={grant.kind}
    title={grant.title.name} service={service} userId={'share:'+grant.id} onClose={close}
    onEntryChange={entry=>{const index=grant.entries.findIndex(value=>value.url===entry.url);if(index>=0)setChapter(index);}}
    language={grant.language} dub={grant.dub} quality={grant.quality} sourceUrl={grant.referer} metadata={profile}
    readerPreset={grant.translate?grant.translation:null} scrollOnOpen/>
  </section>}
 </main>;
}
