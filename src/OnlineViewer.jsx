import {useEffect,useRef,useState} from 'react';
import {ArrowLeft} from 'lucide-react';
import VideoPlayer from './VideoPlayer.jsx';
import MangaReader from './MangaReader.jsx';
import {stopLmt} from './lmt-client.js';
import './online.css';
export default function OnlineViewer({entries,initial,kind,title,service,userId,onClose,language='ru',dub='',metadata}){
 useEffect(()=>()=>stopLmt(),[]);
 const [current,setCurrent]=useState(initial),[media,setMedia]=useState(null),[busy,setBusy]=useState(true),[error,setError]=useState('');
 const items=entries.map(e=>({id:'online:'+e.url,name:title+' · '+(e.title||'Серия '+e.number),category:kind==='manga'?'manga':'video',section:kind==='manga'?'manga':'anime',episode:e.number,season:e.season||1,collectionId:'online-title',metadata:{ids:metadata?.ids},metadataId:metadata?.ids?.mal,dub,sourceURL:e.url,translationInfo:{language},episodeTitle:e.title}));
 const selected=items.find(e=>e.sourceURL===current.url)||items[0],generation=useRef(0),live=useRef(service);live.current=service;
 useEffect(()=>{const version=++generation.current,abort=new AbortController();let token;setMedia(null);setBusy(true);setError('');
  service.request('/online/prepare',{method:'POST',body:{url:current.url,kind},signal:abort.signal}).then(data=>{token=data.id;if(version!==generation.current||abort.signal.aborted){live.current.request('/online/'+token,{method:'DELETE'}).catch(()=>{});return;}setMedia(data);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>{generation.current++;abort.abort();if(token)live.current.request('/online/'+token,{method:'DELETE'}).catch(()=>{});};
 },[current.url,kind,service.server]);
 useEffect(()=>{const close=()=>onClose();addEventListener('mediavault-locked',close);const old=document.body.style.overflow;document.body.style.overflow='hidden';return()=>{document.body.style.overflow=old;removeEventListener('mediavault-locked',close);};},[onClose]);
 const catalog={items,storage:{collections:[{id:'online-title',name:title,section:kind==='manga'?'manga':'anime',metadata}]}};
 function choose(item){const e=entries.find(e=>e.url===item.sourceURL);if(e)setCurrent(e);}
 const server=service.server.replace(/\/$/,'');
 return <section className="online-viewer" role="dialog" aria-modal="true" aria-label="Онлайн без сохранения"><header><button className="icon-button" onClick={onClose} aria-label="Закрыть онлайн-просмотр"><ArrowLeft size={20}/></button><div><strong>{title}</strong><small>Онлайн · без сохранения в Google Drive</small></div></header>{busy&&<p className="online-loading" role="status"><span className="loading-ring"/>Подключаем источник…</p>}{error&&<p className="inline-error" role="alert">{error}</p>}{media&&selected&&(kind==='manga'?<MangaReader key={selected.id} item={{...selected,onlinePages:media.pages.map(p=>server+p)}} catalog={catalog} userId={userId} libraryId="online" onClose={onClose} onSelectItem={choose} readerService={service} retainLmt inline/>:<VideoPlayer key={selected.id} item={{...selected,onlineType:media.type}} source={server+media.url} catalog={catalog} userId={userId} libraryId="online" onSelectItem={choose} onError={e=>setError(e.message)}/>)}</section>;
}
