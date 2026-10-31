import {useEffect,useMemo,useState} from 'react';
import {fetchCatalog,mergeCatalog} from './catalog.js';
import {loadTitleProfile,translate} from './title-metadata.js';
import TitlePage from './TitlePage.jsx';
import ImportSelection from './ImportSelection.jsx';
import {OnlineBooks} from './OnlineLibrary.jsx';
import {CloudDownload,Download} from 'lucide-react';

// Online titles use the collection's presentation, without its Drive writes.
const remoteArtwork=Object.freeze({});
const languageNames={ru:'Русский',en:'Английский',ja:'Японский',ko:'Корейский'};
export default function WorldTitlePage({value,service,state,onBack,onSubmitted,onOpenLibrary,destination='online',onRelated}){
 const [item,setItem]=useState(value),[profile,setProfile]=useState(null),[loading,setLoading]=useState(false),[target,setTarget]=useState('online');
 useEffect(()=>{
  const abort=new AbortController();setItem(value);setProfile(null);setTarget('online');setLoading(true);
  const tasks=[];
  if(!value.sourceOnly&&value.providerId)tasks.push(fetchCatalog(value.provider,{identity:value.providerId,kind:value.kind,server:service.server,signal:abort.signal}).then(rows=>{if(!abort.signal.aborted&&rows.length)setItem(mergeCatalog([value,...rows])[0]);}));
  if(value.ids?.mal)tasks.push(loadTitleProfile(value.ids.mal,value.kind,{server:service.server,signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setProfile(data);}));
  Promise.allSettled(tasks).then(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();
 },[value.id,service.server,destination]);
 const displayProfile=useMemo(()=>({
  title:item.title,cover:item.cover,description:item.description,year:item.year,format:item.format?translate(item.format):null,status:item.status?translate(item.status):null,
  sourceId:item.ids?.mal||'',source:item.ids?.mal?'shikimori':item.provider,sourceURL:item.sourceUrl||item.sourceURL,
  rating:item.ageLabel,genres:item.genres||[],themes:item.tags||[],characters:[],staff:[],related:[],screenshots:[],
  ...(profile||{})
 }),[item,profile]);
 const title=useMemo(()=>({id:item.id,name:item.title,section:item.kind,category:item.kind==='manga'?'manga':item.kind==='ranobe'?'book':'video',items:[],parts:[],metadataId:item.ids?.mal,online:true,profile:displayProfile}),[item,displayProfile]);
 const facts=[['Доступ','Онлайн'],['Язык',languageNames[item.language]],['Источники',[...new Set((item.sources||[]).map(s=>s.providerName).filter(Boolean))].join(', ')||item.providerName],['Статус оригинала',displayProfile.status],['Перевод',item.language==='ru'?'Русский перевод':item.language?'Оригинал · перевод в читалке':null]];
 function destinationAction(value){setTarget(value);requestAnimationFrame(()=>document.getElementById('titleMaterials')?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'}));}
 const heroActions=!['ranobe','manga'].includes(item.kind)&&<div className="title-save-actions" role="group" aria-label="Открыть или сохранить"><button title="Сохранить на Google Диск" aria-label="Сохранить на Google Диск" aria-pressed={target==='drive'} onClick={()=>destinationAction(target==='drive'?'online':'drive')}><CloudDownload size={18}/></button><button title="Сохранить на устройство" aria-label="Сохранить на устройство" aria-pressed={target==='local'} onClick={()=>destinationAction(target==='local'?'online':'local')}><Download size={18}/></button></div>;
 const materials=<><div className="section-heading watch-materials-heading"><h2>{item.kind==='manga'||item.kind==='ranobe'?'Читать':'Смотреть'}</h2></div>
  {item.kind==='manga'&&<details className='title-save-menu' onToggle={e=>{if(!e.currentTarget.open)setTarget('online');}}><summary>Сохранить в коллекцию или на устройство</summary><div className='world-destinations' role='group' aria-label='Открыть или сохранить'>{[['online','Онлайн'],['drive','В Google Диск'],['local','На устройство']].map(([id,label])=><button key={id} aria-pressed={target===id} onClick={()=>setTarget(id)}>{label}</button>)}</div></details>}{item.kind==='ranobe'?<><p className="fine">Можно открыть EPUB, PDF, FB2 или TXT по прямой ссылке либо с устройства. Автоматический источник этой книги пока не подключён.</p><OnlineBooks userId={state.user?.sub}/></>:<ImportSelection compact key={item.id} destination={target} onOpenLibrary={onOpenLibrary} item={item} profile={displayProfile} state={state} service={service} onSubmitted={onSubmitted}/>}
 </>;
 return <TitlePage title={title} state={state} actions={remoteArtwork} onBack={onBack} onRelated={onRelated} online onOnlinePlay={()=>destinationAction('online')} heroActions={heroActions} onlineProfile={displayProfile} onlineBusy={loading} materials={materials} onlineFacts={facts} server={service.server} backLabel="К результатам поиска"/>;
}
