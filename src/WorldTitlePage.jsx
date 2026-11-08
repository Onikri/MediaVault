import {useEffect,useMemo,useState,useRef,lazy,Suspense} from 'react';
import {profileForSeason} from './use-season-source.js';
import {fetchCatalog,mergeCatalog} from './catalog.js';
import {loadTitleProfile,translate} from './title-metadata.js';
import TitlePage from './TitlePage.jsx';
import ImportSelection from './ImportSelection.jsx';
import {OnlineBooks} from './OnlineLibrary.jsx';
import RanobeSources from './RanobeSources.jsx';
import {localLabel} from './taxonomy.js';
import {CloudDownload,Download} from 'lucide-react';

// Online titles use the collection's presentation, without its Drive writes.
const LocalMediaViewer=lazy(()=>import('./MediaViewer.jsx'));
const remoteArtwork=Object.freeze({});
const languageNames={ru:'Русский',en:'Английский',ja:'Японский',ko:'Корейский'};
export default function WorldTitlePage({value,service,state,onBack,onSubmitted,onOpenLibrary,destination='online',onRelated}){
 const localInput=useRef(null),[localFile,setLocalFile]=useState(null);
 const [item,setItem]=useState(value),[profile,setProfile]=useState(null),[loading,setLoading]=useState(false),[target,setTarget]=useState('online'),[viewSeason,setViewSeason]=useState(null),[seasonProfiles,setSeasonProfiles]=useState({});
 useEffect(()=>{
  const abort=new AbortController();setItem(value);setProfile(null);setViewSeason(null);setSeasonProfiles({});setTarget('online');setLoading(true);
  const tasks=[];
  if(!value.sourceOnly&&value.providerId&&!['openlibrary','youtube'].includes(value.provider))tasks.push(fetchCatalog(value.provider,{identity:value.providerId,kind:value.kind,server:service.server,signal:abort.signal}).then(rows=>{if(!abort.signal.aborted&&rows.length)setItem({...mergeCatalog([...rows,value])[0],id:value.id});}));
  if(value.ids?.mal)tasks.push(loadTitleProfile(value.ids.mal,value.kind,{server:service.server,signal:abort.signal,onPartial:data=>{if(!abort.signal.aborted)setProfile(data);}}).then(data=>{if(!abort.signal.aborted)setProfile(data);}));
  Promise.allSettled(tasks).then(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();
 },[value.id,service.server,destination]);
 const baseDisplayProfile=useMemo(()=>({
  title:item.title,cover:item.cover,description:item.description,year:item.year,format:item.format?translate(item.format):null,status:item.status?translate(item.status):null,
  sourceId:item.ids?.mal||'',source:item.ids?.mal?'shikimori':item.provider,sourceURL:item.sourceUrl||item.sourceURL,
  releases:item.releases||[],episodeImages:item.episodeImages||{},rating:item.age!=null?item.age+'+':'',genres:(item.genres||[]).map(localLabel),themes:(item.tags||[]).map(localLabel),characters:[],staff:[],related:[],screenshots:[],
  ...(profile||{})
 }),[item,profile]);
 const sceneItem=viewSeason?.item||item,sceneId=String(sceneItem.ids?.mal||''),basisId=String(item.ids?.mal||'');
 useEffect(()=>{if(!sceneId||sceneId===basisId||seasonProfiles[sceneId])return;const abort=new AbortController();loadTitleProfile(sceneId,'anime',{server:service.server,signal:abort.signal,onPartial:data=>{if(!abort.signal.aborted)setSeasonProfiles(old=>({...old,[sceneId]:data}));}}).then(data=>{if(!abort.signal.aborted)setSeasonProfiles(old=>({...old,[sceneId]:data}));}).catch(()=>{});return()=>abort.abort();},[sceneId,basisId,service.server]);
 const displayProfile=useMemo(()=>sceneId&&sceneId!==basisId?{...profileForSeason(sceneItem),...(seasonProfiles[sceneId]||{})}:baseDisplayProfile,[sceneItem,sceneId,basisId,seasonProfiles,baseDisplayProfile]);
 const title=useMemo(()=>({id:item.id,name:sceneItem.title,section:item.kind,category:item.kind==='manga'?'manga':['ranobe','book'].includes(item.kind)?'book':'video',items:[],parts:[],metadataId:sceneItem.ids?.mal,online:true,profile:displayProfile}),[item,sceneItem,displayProfile]);
 const facts=[['Доступ','Онлайн'],['Сезон просмотра',viewSeason?viewSeason.name+(viewSeason.episodes?' · '+viewSeason.episodes+' сер.':''):null],['Язык',languageNames[item.language]],['Источники',[...new Set((item.sources||[]).map(s=>s.providerName).filter(Boolean))].join(', ')||item.providerName],['Статус оригинала',displayProfile.status],['Перевод',item.language==='ru'?'Русский перевод':item.language?'Оригинал · перевод в читалке':null]];
 function destinationAction(value){setTarget(value);requestAnimationFrame(()=>document.getElementById('titleMaterials')?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'}));}
 const heroActions=!['ranobe'].includes(item.kind)&&<div className="title-save-actions" role="group" aria-label="Открыть или сохранить"><button title="Сохранить на Google Диск" aria-label="Сохранить на Google Диск" aria-pressed={target==='drive'} onClick={()=>destinationAction(target==='drive'?'online':'drive')}><CloudDownload size={18}/></button><button title="Сохранить на устройство" aria-label="Сохранить на устройство" aria-pressed={target==='local'} onClick={()=>destinationAction(target==='local'?'online':'local')}><Download size={18}/></button></div>;
 const materials=<><div className="section-heading watch-materials-heading"><h2>{item.kind==='manga'||item.kind==='ranobe'?'Читать':'Смотреть'}</h2></div>
  {item.kind==='manga'&&<details className='title-save-menu' onToggle={e=>{if(!e.currentTarget.open)setTarget('online');}}><summary>Сохранить в коллекцию или на устройство</summary><div className='world-destinations' role='group' aria-label='Открыть или сохранить'>{[['online','Онлайн'],['drive','В Google Диск'],['local','На устройство']].map(([id,label])=><button key={id} aria-pressed={target===id} onClick={()=>setTarget(id)}>{label}</button>)}</div></details>}{item.kind==='ranobe'?<RanobeSources item={item} service={service} state={state}/>:item.kind==='book'?<><p className="fine">Можно открыть EPUB, PDF, FB2 или TXT по прямой ссылке либо с устройства. Автоматический источник этой книги пока не подключён.</p><OnlineBooks userId={state.user?.sub} service={service}/></>:<ImportSelection compact key={item.id} destination={target} onOpenLibrary={onOpenLibrary} item={item} profile={baseDisplayProfile} onSeasonBrowse={setViewSeason} state={state} service={service} onSubmitted={onSubmitted}/>}
 </>;
 return <><TitlePage onLocalFile={()=>localInput.current?.click()} title={title} state={state} actions={remoteArtwork} onBack={onBack} onRelated={onRelated} online onOnlinePlay={()=>destinationAction('online')} heroActions={heroActions} onlineProfile={displayProfile} onlineBusy={loading} materials={materials} onlineFacts={facts} server={service.server} backLabel="К результатам поиска"/><input ref={localInput} type="file" accept=".cbz,.zip" hidden onChange={e=>{const file=e.target.files?.[0];if(file)setLocalFile({id:'local:'+file.name+':'+file.lastModified,name:file.name,category:'manga',size:file.size,file});e.target.value='';}}/>{localFile&&<Suspense fallback={<p role="status">Открываем файл…</p>}><LocalMediaViewer item={localFile} catalog={{items:[localFile]}} libraryId="local" userId={state.user?.sub} readWhole={()=>Promise.resolve(localFile.file)} onClose={()=>setLocalFile(null)} readerService={service}/></Suspense>}</>;
}
