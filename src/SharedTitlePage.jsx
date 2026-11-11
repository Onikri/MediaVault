import {useEffect,useMemo,useRef,useState} from 'react';
import TitlePage from './TitlePage.jsx';
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
 if(error)return <main className="page-container"><p className="inline-error" role="alert">{error}</p><button className="btn btn-secondary" onClick={()=>setRetry(v=>v+1)}>Повторить</button></main>;
 if(!grant||!service)return <main className="page-container"><p role="status">Открываем тайтл…</p></main>;
 const profile={title:grant.title.name,cover:grant.title.cover,description:grant.title.description,year:grant.title.year,ids:grant.title.ids};
 const title={id:'share:'+grant.id,name:grant.title.name,category:grant.kind==='manga'?'manga':'video',section:grant.kind==='manga'?'manga':'anime',items:[],parts:[]};
 const initial=grant.entries[grant.initial];
 const materials=<OnlineViewer inline entries={grant.entries} initial={initial} kind={grant.kind}
  title={grant.title.name} service={service} userId={'share:'+grant.id} onClose={()=>{location.hash='home';}}
  language={grant.language} dub={grant.dub} quality={grant.quality} sourceUrl={grant.referer} metadata={profile}
  readerPreset={grant.translate?grant.translation:null}/>;
 return <TitlePage title={title} state={{admin:false}} actions={{}} online onlineProfile={profile} materials={materials}
  server={service.server} onBack={()=>{location.hash='home';}} backLabel="На главную"
  onOnlinePlay={()=>document.getElementById('titleMaterials')?.scrollIntoView({behavior:'smooth',block:'start'})}/>;
}
