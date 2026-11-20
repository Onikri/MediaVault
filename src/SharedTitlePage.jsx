import {useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen} from 'lucide-react';
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
 return <SharedTitle grant={grant} service={service}/>;
}

// The recipient sees one title and its reader: no header, no back button and
// no links to the rest of the site. Closing the reader keeps them on this page.
function SharedTitle({grant,service}){
 const [open,setOpen]=useState(true),[more,setMore]=useState(false),[session,setSession]=useState(0);
 const manga=grant.kind==='manga',year=Number(grant.title.year)||null,description=String(grant.title.description||'').trim();
 const profile={title:grant.title.name,cover:grant.title.cover,description,year,ids:grant.title.ids};
 const initial=grant.entries[grant.initial];
 const units=grant.entries.length,unitWord=manga?plural(units,['глава','главы','глав']):plural(units,['серия','серии','серий']);
 useEffect(()=>{const name=grant.title.name;const old=document.title;document.title=name;return()=>{document.title=old;};},[grant.title.name]);
 return <main className="shared-title">
  <header className="shared-title-hero">
   {grant.title.cover&&<div className="shared-title-cover"><TitleImage url={grant.title.cover} actions={{}} fallback={false} alt={'Обложка: '+grant.title.name}/></div>}
   <div className="shared-title-copy">
    <p className="shared-title-kind">{[manga?'Манга':'Видео',year,units+' '+unitWord,grant.dub||null].filter(Boolean).join(' · ')}</p>
    <h1>{grant.title.name}</h1>
    {description&&<><p className={'shared-title-about'+(more?' is-open':'')}>{description}</p>{description.length>220&&<button type="button" className="shared-title-more" aria-expanded={more} onClick={()=>setMore(v=>!v)}>{more?'Свернуть':'Подробнее'}</button>}</>}
    {!open&&<button type="button" className="btn btn-primary shared-title-resume" onClick={()=>{setSession(n=>n+1);setOpen(true);}}><BookOpen size={16}/>{manga?'Читать':'Смотреть'}</button>}
   </div>
  </header>
  {open&&<section className="shared-title-reader" aria-label={manga?'Читалка':'Плеер'}>
   <OnlineViewer key={session} inline entries={grant.entries} initial={initial} kind={grant.kind}
    title={grant.title.name} service={service} userId={'share:'+grant.id} onClose={()=>setOpen(false)}
    language={grant.language} dub={grant.dub} quality={grant.quality} sourceUrl={grant.referer} metadata={profile}
    readerPreset={grant.translate?grant.translation:null} scrollOnOpen={session>0}/>
  </section>}
 </main>;
}
