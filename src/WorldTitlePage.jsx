import {useEffect,useMemo,useState,useRef,useCallback,lazy,Suspense} from 'react';
import {mergeTitleIdentity,preserveCatalogFacts} from './title-details.js';
import {profileForSeason} from './use-season-source.js';
import {fetchCatalog,mergeCatalog,normalized} from './catalog.js';
import {loadTitleProfile,translate} from './title-metadata.js';
import TitlePage from './TitlePage.jsx';
import ImportSelection from './ImportSelection.jsx';
import {OnlineBooks} from './OnlineLibrary.jsx';
import RanobeSources from './RanobeSources.jsx';
import {localLabel} from './taxonomy.js';
import ExportSheet,{ExportTrigger,DESTINATIONS} from './ExportSheet.jsx';
import RanobeExport from './RanobeExport.jsx';
import {filmSupplement} from './film-supplement.js';
import {bookSupplement} from './book-supplement.js';
import {useTitleShare,useTitleStats} from './title-context.js';
import {onlineTitleLocation} from './title-route.js';
import useMangaPolicy from './use-manga-policy.js';
import {sameMangaTitle} from './manga-source-identity.js';

// Online titles use the collection's presentation, without its Drive writes.
const LocalMediaViewer=lazy(()=>import('./MediaViewer.jsx'));
const remoteArtwork=Object.freeze({});
const emptyValue=v=>v==null||v===''||(Array.isArray(v)&&!v.length);
// Catalog values win; a supplement adds what they lack (cast, crew, seasons…).
// Airing status and episode counts are fresher in TVmaze than in Kinopoisk.
const SUPPLEMENT_FIRST=new Set(['status','statusCode','episodes','episodesAired','seasons']);
function withSupplement(base,extra){const result={...base};for(const [key,value] of Object.entries(extra||{}))if(!emptyValue(value)&&(emptyValue(base[key])||SUPPLEMENT_FIRST.has(key)))result[key]=value;return result;}
const languageNames={ru:'Русский',en:'Английский',ja:'Японский',ko:'Корейский'};
export default function WorldTitlePage({value,service,state,onBack,onSubmitted,onOpenLibrary,destination='online',onRelated}){
 const localInput=useRef(null),[localFile,setLocalFile]=useState(null);
 const [item,setItem]=useState(value),[profile,setProfile]=useState(null),[supplement,setSupplement]=useState(null),[loading,setLoading]=useState(false),[saveOpen,setSaveOpen]=useState(false),[saveTo,setSaveTo]=useState('local'),[viewSeason,setViewSeason]=useState(null),[seasonProfiles,setSeasonProfiles]=useState({});
 const tagPolicyVersion=useMangaPolicy(service,value.kind==='manga');
 const [indexedFacts,setIndexedFacts]=useState(null);
 const factIds=[...new Set([value.catalogId,...(value.catalogIds||[]),...(value.sources||[]).map(source=>source.catalogId)].filter(id=>typeof id==='string'&&/^[a-f0-9]{32}$/.test(id)))].slice(0,100).join(',');
 const factUrls=[...new Set([value.sourceUrl,value.sourceURL,value.url].filter(url=>typeof url==='string'&&url.startsWith('https://')))].join('\n');
 useEffect(()=>{
  setIndexedFacts(null);if(value.kind!=='manga'||!factIds&&!factUrls)return;
  const abort=new AbortController();
  const pending=factIds?factIds.split(',').map(id=>service.request('/manga/catalog/'+id,{signal:abort.signal}).then(row=>row.catalogId===id&&sameMangaTitle(value,row)?[row]:[])):[service.request('/manga/catalog?'+new URLSearchParams({q:value.title,limit:'100'}),{signal:abort.signal}).then(result=>(result.items||[]).filter(row=>factUrls.split('\n').some(url=>url===row.url||url===row.sourceUrl)&&sameMangaTitle(value,row)))];
  Promise.allSettled(pending).then(results=>{
   if(abort.signal.aborted)return;
   const rows=results.filter(result=>result.status==='fulfilled').flatMap(result=>result.value);
   setIndexedFacts({id:value.id,genres:[...new Set(rows.flatMap(row=>row.genres||[]))],themes:[...new Set(rows.flatMap(row=>row.tags||[]))]});
  });return()=>abort.abort();
 },[value.id,factIds,factUrls,tagPolicyVersion,service.server]);
 useEffect(()=>{
  const abort=new AbortController();setItem(value);setProfile(null);setSupplement(null);setViewSeason(null);setSeasonProfiles({});setSaveOpen(false);setLoading(true);
  const tasks=[];
  if(!value.sourceOnly&&value.providerId&&!['youtube'].includes(value.provider)&&!(value.provider==='openlibrary'&&!/^OL\d+W$/.test(value.providerId)))tasks.push(fetchCatalog(value.provider,{identity:value.providerId,kind:value.kind,server:service.server,signal:abort.signal}).then(rows=>{if(!abort.signal.aborted&&rows.length)setItem(old=>({...mergeCatalog(value.kind==='book'?[old,...rows]:[...rows,old])[0],id:value.id}));}));
  // Books: the Russian description and edition from Fantlab, the same work by ID.
  if(value.kind==='book'&&value.provider!=='fantlab'){
   const same=row=>[row.titles?.en,row.titles?.ru].some(t=>t&&(value.aliases||[value.title]).some(a=>normalized(a)===normalized(t)));
   const id=value.ids?.fantlab?Promise.resolve(value.ids.fantlab):fetchCatalog('fantlab',{query:value.titles?.en||value.title,kind:'book',signal:abort.signal}).then(rows=>rows.find(same)?.providerId);
   // Not awaited by the page: the description fills in when Fantlab answers.
   id.then(found=>found&&fetchCatalog('fantlab',{identity:found,kind:'book',signal:abort.signal})).then(rows=>{if(!abort.signal.aborted&&rows?.length)setItem(old=>({...mergeCatalog([old,{...rows[0],ids:{...old.ids,...rows[0].ids}}])[0],id:value.id}));}).catch(()=>{});
  }
  if(value.ids?.mal)tasks.push(loadTitleProfile(value.ids.mal,value.kind,{server:service.server,signal:abort.signal,onPartial:data=>{if(!abort.signal.aborted)setProfile(data);}}).then(data=>{if(!abort.signal.aborted)setProfile(data);}));
  Promise.allSettled(tasks).then(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();
 },[value.id,service.server,destination]);
 const [sourcePublication,setSourcePublication]=useState(null);
 const receivePublication=useCallback(value=>setSourcePublication({id:item.id,value}),[item.id]);
 const searchItem=useMemo(()=>mergeTitleIdentity(item,profile||{}),[item,profile]);

 const supplementKey=item.kind+':'+(item.ids?.kinopoisk||'')+':'+(item.ids?.imdb||'')+':'+(item.ids?.fantlab||'');
 useEffect(()=>{
  if(!['movie','tv','book'].includes(item.kind))return;
  const abort=new AbortController();
  (item.kind==='book'?bookSupplement(item,{signal:abort.signal}):filmSupplement(item,{signal:abort.signal})).then(data=>{if(!abort.signal.aborted)setSupplement(data&&Object.keys(data).length?data:null);}).catch(()=>{});
  return()=>abort.abort();
 },[supplementKey]);
 const baseDisplayProfile=useMemo(()=>{const base={
  title:item.title,cover:item.cover,description:item.description,year:item.year,format:item.format?translate(item.format):null,status:item.status?translate(item.status):null,
  sourceId:item.ids?.mal||'',source:item.ids?.mal?'shikimori':item.provider,sourceURL:item.sourceUrl||item.sourceURL||item.links?.find(l=>l.provider===item.provider)?.url||item.links?.[0]?.url,
  episodes:item.episodes||null,episodesAired:item.episodesAired||null,chapters:item.chapters||null,volumes:item.volumes||null,duration:item.duration||null,startDate:item.startDate||'',endDate:item.endDate||'',scores:item.scores||[],countries:item.countries||[],authors:item.authors||[],background:item.background||'',
  releases:item.releases||[],episodeImages:item.episodeImages||{},rating:item.age!=null?item.age+'+':'',genres:item.kind==='manga'?item.genres||[]:(item.genres||[]).map(localLabel),themes:item.kind==='manga'?item.tags||[]:(item.tags||[]).map(localLabel),characters:[],staff:[],related:[],screenshots:[],

 };const result=withSupplement({...base,...(profile||{}),...preserveCatalogFacts(item,profile||{}),aliases:searchItem.aliases,sourcePublication:sourcePublication?.id===item.id?sourcePublication.value:null},supplement);
 if(item.kind==='manga'&&indexedFacts?.id===item.id)for(const field of ['genres','themes'])result[field]=[...new Set([...(result[field]||[]),...indexedFacts[field]])];
 return result;},[item,profile,supplement,searchItem,sourcePublication,indexedFacts]);
 const sceneItem=viewSeason?.item||item,sceneId=String(sceneItem.ids?.mal||''),basisId=String(item.ids?.mal||'');
 useEffect(()=>{if(!sceneId||sceneId===basisId||seasonProfiles[sceneId])return;const abort=new AbortController();loadTitleProfile(sceneId,'anime',{server:service.server,signal:abort.signal,onPartial:data=>{if(!abort.signal.aborted)setSeasonProfiles(old=>({...old,[sceneId]:data}));}}).then(data=>{if(!abort.signal.aborted)setSeasonProfiles(old=>({...old,[sceneId]:data}));}).catch(()=>{});return()=>abort.abort();},[sceneId,basisId,service.server]);
 const displayProfile=useMemo(()=>sceneId&&sceneId!==basisId?{...profileForSeason(sceneItem),...(seasonProfiles[sceneId]||{})}:baseDisplayProfile,[sceneItem,sceneId,basisId,seasonProfiles,baseDisplayProfile]);
 const title=useMemo(()=>({id:item.id,name:sceneItem.title,section:item.kind,category:item.kind==='manga'?'manga':['ranobe','book'].includes(item.kind)?'book':'video',items:[],parts:[],metadataId:sceneItem.ids?.mal,online:true,profile:displayProfile}),[item,sceneItem,displayProfile]);
 const facts=[['Сезон просмотра',viewSeason?viewSeason.name+(viewSeason.episodes?' · '+viewSeason.episodes+' сер.':''):null],['Язык',languageNames[item.language]],['Источники',[...new Set((item.sources||[]).map(s=>s.providerName).filter(Boolean))].join(', ')||item.providerName],['Перевод',item.language==='ru'?'Русский перевод':item.language?'Оригинал · перевод в читалке':null]];
 function destinationAction(){requestAnimationFrame(()=>document.getElementById('titleMaterials')?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'}));}
 const share=useTitleShare(),stats=useTitleStats();
 const sheetTitle=item.kind==='manga'?'Сохранить главы':['ranobe','book'].includes(item.kind)?'Сохранить книгу':item.kind==='movie'?'Сохранить фильм':'Сохранить серии';
 const heroActions=<ExportSheet open={saveOpen} onOpenChange={setSaveOpen} title={sheetTitle} subtitle={displayProfile.title||item.title} destination={saveTo} onDestination={setSaveTo} destinations={DESTINATIONS} trigger={<ExportTrigger label={sheetTitle}/>}>
  {['ranobe','book'].includes(item.kind)
   ?<RanobeExport key={saveTo} item={{...item,description:displayProfile.description,authors:displayProfile.authors||item.authors}} book={stats?.book} service={service} state={state} destination={saveTo} onOpenLibrary={onOpenLibrary} onSubmitted={onSubmitted}/>
   :<ImportSelection sheet key={item.id+':'+saveTo} destination={saveTo} initialVoice={share?.voiceName||''} preferredSource={stats?.kind==='manga'?stats.source:''} onOpenLibrary={onOpenLibrary} item={searchItem} profile={baseDisplayProfile} state={state} service={service} onSubmitted={()=>{setSaveOpen(false);onSubmitted?.();}}/>}
 </ExportSheet>;
 // Related works from Fantlab (other books of the cycle, adaptations) and
 // Wikidata (sequels) open by their own catalog; anime and manga keep Shikimori.
 async function openRelated(value){
  if(value.fantlab){onlineTitleLocation({kind:'book',provider:'fantlab',providerId:value.fantlab,title:value.title,ids:{fantlab:value.fantlab},cover:value.cover});return;}
  if(['movie','tv','wikidata'].includes(value.kind)&&!value.ids?.mal){
   try{
    const rows=await fetchCatalog('kinobox',{query:value.originalTitle||value.title,kind:value.kind==='tv'?'tv':'movie',server:service.server});
    const wanted=[value.title,value.originalTitle].filter(Boolean).map(normalized);
    const match=rows.find(r=>(!value.year||!r.year||Number(r.year)===Number(value.year))&&r.aliases.some(a=>wanted.includes(normalized(a))))||rows.find(r=>r.aliases.some(a=>wanted.includes(normalized(a))));
    if(match){onlineTitleLocation(match);return;}
   }catch{}
   location.hash=new URLSearchParams({search:value.title}).toString();return;
  }
  onRelated?.(value);
 }
 const materials=<><div className="section-heading watch-materials-heading"><h2>{['manga','ranobe','book'].includes(item.kind)?'Читать':'Смотреть'}</h2></div>
  {['ranobe','book'].includes(item.kind)?<RanobeSources item={searchItem} service={service} state={state} expected={displayProfile.chapters}/>:<ImportSelection compact key={item.id} destination="online" onOpenLibrary={onOpenLibrary} item={searchItem} profile={baseDisplayProfile} expected={displayProfile.chapters} onMangaPublication={receivePublication} onSeasonBrowse={setViewSeason} state={state} service={service} onSubmitted={onSubmitted}/>}
 </>;
 return <><TitlePage onLocalFile={()=>localInput.current?.click()} title={title} state={state} actions={remoteArtwork} onBack={onBack} onRelated={openRelated} online onOnlinePlay={destinationAction} heroActions={heroActions} onlineProfile={displayProfile} onlineBusy={loading} materials={materials} onlineFacts={facts} server={service.server} backLabel="К результатам поиска"/><input ref={localInput} type="file" accept=".cbz,.zip" hidden onChange={e=>{const file=e.target.files?.[0];if(file)setLocalFile({id:'local:'+file.name+':'+file.lastModified,name:file.name,category:'manga',size:file.size,file});e.target.value='';}}/>{localFile&&<Suspense fallback={<p role="status">Открываем файл…</p>}><LocalMediaViewer item={localFile} catalog={{items:[localFile]}} libraryId="local" userId={state.user?.sub} readWhole={()=>Promise.resolve(localFile.file)} onClose={()=>setLocalFile(null)} readerService={service}/></Suspense>}</>;
}
