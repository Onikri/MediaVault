import ChapterIndex from './ChapterIndex.jsx';
import PlaybackReveal from './PlaybackReveal.jsx';
import UiSegmented from './UiSegmented.jsx';
import {FilterGroup,defaultReadingLanguage} from './ReaderFilters.jsx';
import {betterSource,rankSources,useSourceFavorites} from './source-ranking.js';
import {publishTitleShare,publishTitleStats} from './title-context.js';
import MangaExportSettings from './MangaExportSettings.jsx';
import {defaultMangaExport,exportTranslation} from './manga-export-options.js';
import {readLmt} from './LmtSettings.jsx';
import {useRetainedMedia} from './RetainedMedia.jsx';
import {useEffect,useRef,useState} from 'react';
import {BookOpen,Globe,Check,ArrowRight,ShieldCheck,RefreshCw} from 'lucide-react';
import ImportReadiness,{canImport} from './ImportReadiness.jsx';
import {selectChapters,mangaMetadata,MANGA_LANGUAGES,MANGA_FORMATS,mangaLanguageName} from './manga-import.js';
import OnlineViewer from './OnlineViewer.jsx';
import useGlobalManga from './use-global-manga.js';
import MangaSearchDiagnostics from './MangaSearchDiagnostics.jsx';
import {exportLocally} from './local-export.js';
import ChapterChooser from './ChapterChooser.jsx';
import MangaSourceManager from './MangaSourceManager.jsx';
import {kinds} from './ImportParts.jsx';
import TitleSourcePicker from './TitleSourcePicker.jsx';
import SourceFilter from './SourceFilter.jsx';
import useMangaSourceInfo from './use-manga-source-info.js';
import {matchingMangaSources} from './manga-source-identity.js';
import {mangaPublication} from './title-details.js';
export default function MangaImport({state,service,item,onSubmitted,onOpenLibrary,manual,onKindChange,destination='drive',compact=false,sheet=false,preferredSource='',expected=0,onPublication,initialLanguage=''}){
 const localAbort=useRef(null);
 const [exportSettings,setExportSettings]=useState(()=>({...defaultMangaExport,...exportTranslation(readLmt(state.user?.sub))}));
 useEffect(()=>()=>localAbort.current?.abort(),[]);
 const [online,setOnline]=useState(false),[localProgress,setLocalProgress]=useState(''),[bridgeWindow,setBridgeWindow]=useState(null),[moreSearching,setMoreSearching]=useState(false);
 const searchAbort=useRef(null);
 const [format,setFormat]=useState('all'),[language,setLanguage]=useState(()=>initialLanguage||(compact&&destination==='online'?defaultReadingLanguage():'all')),[quality,setQuality]=useState('best'),[sources,setSources]=useState([]),[providers,setProviders]=useState([]),[searching,setSearching]=useState(false),[revision,setRevision]=useState(0),[inspection,setInspection]=useState(null),[url,setUrl]=useState(''),[collection,setCollection]=useState(item?.title||''),[volume,setVolume]=useState('all'),[team,setTeam]=useState(''),[mode,setMode]=useState('all'),[one,setOne]=useState(''),[first,setFirst]=useState('0'),[last,setLast]=useState('20'),[list,setList]=useState(''),[busy,setBusy]=useState(''),[error,setError]=useState('');
 useEffect(()=>{const language={ja:'Japanese',en:'English',ko:'Korean',zh:'Chinese (Simplified)'}[inspection?.language];if(language)setExportSettings(v=>({...v,language}));},[inspection?.language]);
 const placement=useRetainedMedia(online,{label:collection||item?.title||'Манга',kind:'reader'},()=>setOnline(false));
 const [sourceIds,setSourceIds]=useState([]);
 const searchTitle=item?Object.fromEntries(['id','kind','title','titles','aliases','ids','year'].map(k=>[k,item[k]])):null;
 const identityKey=JSON.stringify(searchTitle);
 useEffect(()=>{onPublication?.(mangaPublication(inspection));},[onPublication,inspection]);
 const globalSearch=useGlobalManga(item?.title||'','manga',language,sourceIds,service,false,revision,searchTitle);
 const favorites=useSourceFavorites(state.user?.sub,'manga');
 // Favourite sites are checked first; once chapter counts arrive the most
 // complete translation (closest to the work's total) moves up.
 const visibleSources=rankSources(sources.filter(s=>(language==='all'||s.language===language)&&(!sourceIds.length||sourceIds.includes(s.sourceId||s.provider?.split(':')[1]))),{favorites:favorites.list});
 const sourceInfo=useMangaSourceInfo(visibleSources,searchTitle,service,revision,{enabled:!online&&placement!=='hidden',priority:url});
 const usableSources=visibleSources.filter(s=>Number(service.session?.serverVersion)<47||sourceInfo[s.url]?.readable===true);
 const displayInfo={...sourceInfo,...(inspection?{[url]:{inspection,state:inspection.readable===false?'error':inspection.readable===true?'ready':'verifying',readable:inspection.readable,chapterCount:new Set(inspection.episodes.map(e=>(e.season||1)+':'+e.number)).size,volumeCount:inspection.seasons?.length||1}}:{})};
 const rankedSources=rankSources(visibleSources,{favorites:favorites.list,expected,count:s=>displayInfo[s.url]?.chapterCount});
 const attempted=useRef(new Set()),manualSource=useRef(false);
 // A dossier may supply its Russian name after the first source request. Only
 // failed/absent inspections are retried; a reader already playing stays put.
 useEffect(()=>{attempted.current.clear();if(!inspection||inspection.readable===false){setInspection(null);setError('');}},[identityKey]);
 const generation=useRef(0),ready=canImport(state,service),supported=Number(service.session?.serverVersion||0)>=8,languageAware=Number(service.session?.serverVersion||0)>=10,rawAware=Number(service.session?.serverVersion||0)>=12;
 const names=[item?.titles?.en,item?.titles?.en_jp,item?.title,...item?.aliases||[]].filter(v=>typeof v==='string');const englishName=names.find(v=>/[a-z]/i.test(v)&&!/[а-яё]/i.test(v))||item?.title||'';
 const englishSearch='https://mangapill.com/search?'+new URLSearchParams({q:englishName});
 useEffect(()=>{generation.current++;attempted.current.clear();manualSource.current=false;setOnline(false);setBusy('');setInspection(null);setUrl('');setSources(matchingMangaSources(item,item?.sources||[],{attached:true}));setProviders([]);setBridgeWindow(null);setMoreSearching(false);setCollection(item?.title||'');setError('');setSourceIds([]);if(preferredSource)inspect(preferredSource);},[item?.id,service.server]);
 useEffect(()=>{
  if(!item||service.status!=='connected'||!supported||sourceIds.length)return;
  const abort=new AbortController();searchAbort.current=abort;setSearching(true);
  service.request('/manga/search',{method:'POST',body:{title:searchTitle,...(languageAware?{language}:{}),...(rawAware?{format}:{})},signal:AbortSignal.any([abort.signal,AbortSignal.timeout(45000)])}).then(data=>{if(!abort.signal.aborted){setSources(old=>[...new Map([...old,...matchingMangaSources(item,data.results||[])].map(s=>[s.url,s])).values()]);setProviders(data.providers||[]);setBridgeWindow(data.bridgeSearch||null);}}).catch(cause=>{if(!abort.signal.aborted)setError(cause.message);}).finally(()=>{if(!abort.signal.aborted)setSearching(false);});return()=>abort.abort();
 },[identityKey,service.status,supported,languageAware,rawAware,language,format,revision,JSON.stringify(sourceIds)]);
 useEffect(()=>{const rows=matchingMangaSources(item,[...(item?.sources||[]),...(globalSearch.results||[])],{attached:!!item?.sources?.length});if(rows.length)setSources(old=>[...new Map([...old,...rows].map(s=>[s.url,s])).values()]);},[identityKey,globalSearch.results,item?.sources]);
 useEffect(()=>{
  if(!url||!sources.some(s=>s.url===url)||visibleSources.some(s=>s.url===url))return;
  generation.current++;attempted.current.clear();manualSource.current=false;setOnline(false);setBusy('');setInspection(null);setUrl('');setError('');
 },[language,JSON.stringify(sourceIds)]);
 useEffect(()=>{if(!item||service.status!=='connected'||manualSource.current||inspection&&inspection.readable!==false||busy)return;const next=rankedSources.find(s=>!attempted.current.has(s.url)&&(Number(service.session?.serverVersion)<47||sourceInfo[s.url]?.readable===true||sourceInfo[s.url]?.state!=='error'&&sourceInfo[s.url]?.inspection?.episodes?.length));if(next){attempted.current.add(next.url);inspect(next.url,true);}},[item?.id,visibleSources.map(s=>s.url).join('\n'),service.status,inspection,busy,revision,Object.entries(sourceInfo).map(([key,v])=>key+':'+v.state+':'+v.readable+':'+!!v.inspection).join('|')]);
 // An automatic choice follows the ranking: when a better source (a favourite
 // or a more complete translation) proves readable before the reader opens,
 // it replaces the one that merely answered first.
 const readableKey=rankedSources.map(s=>s.url+':'+(sourceInfo[s.url]?.readable??'')+':'+(sourceInfo[s.url]?.chapterCount??'')).join('|');
 useEffect(()=>{
  if(manualSource.current||online||busy||!inspection||!url)return;
  const usable=s=>Number(service.session?.serverVersion)<47?!!sourceInfo[s.url]?.inspection?.episodes?.length:sourceInfo[s.url]?.readable===true;
  const best=rankedSources.find(usable),current=rankedSources.find(s=>s.url===url);
  const options={favorites:favorites.list,expected,count:s=>displayInfo[s.url]?.chapterCount};
  if(best&&best.url!==url&&(!current||betterSource(best,current,options))){attempted.current.add(best.url);inspect(best.url,true);}
 },[readableKey,online,busy]);
 async function moreSources(){
  if(!bridgeWindow?.hasMore||moreSearching)return;const version=generation.current,requestSignal=searchAbort.current?.signal;setMoreSearching(true);setError('');
  try{const data=await service.request('/manga/bridge/search',{method:'POST',body:{title:item,language,format,bridgeOffset:bridgeWindow.nextOffset},signal:requestSignal});if(version!==generation.current)return;
   setSources(old=>[...new Map([...old,...(data.results||[])].map(v=>[v.url,v])).values()]);setProviders(old=>[...new Map([...old,...(data.providers||[])].map(v=>[v.provider,v])).values()]);setBridgeWindow(data.window||null);
   if(!data.window?.checked&&data.window?.hasMore)setError('Источники заняты. Повтори проверку оставшихся.');
  }catch(cause){if(version===generation.current&&!searchAbort.current?.signal.aborted)setError(cause.message);}finally{if(!requestSignal?.aborted)setMoreSearching(false);}
 }
 const sourceReady=Number(service.session?.serverVersion||0)<47||inspection?.readable===true;
 useEffect(()=>{const result=sourceInfo[url];if(!result||!inspection?.fromSourceInfo)return;if(result.readable!==undefined||result.state==='error'){
  setInspection(old=>old?.fromSourceInfo?{...old,readable:result.readable===true,readabilityError:result.readabilityError||result.error,verifiedChapterUrl:result.verifiedChapterUrl}:old);
  if(result.readable===false||result.state==='error')setError(result.readabilityError||result.error||'Источник не отдал страницу.');
 }},[url,sourceInfo[url]?.readable,sourceInfo[url]?.state]);
 async function inspect(value,automatic=false,targetChapter=null){
  if(!value)return;if(!automatic){manualSource.current=true;setOnline(false);}const version=++generation.current;setUrl(value);setBusy('inspect');setInspection(null);setError('');
  try{
   const cached=automatic||targetChapter?sourceInfo[value]:null;
   const data=cached?.inspection||await service.request('/manga/inspect',{method:'POST',body:{url:value,...(item?{title:searchTitle}:{}),verifyPages:false,refresh:!automatic}});
   if(version!==generation.current)return;
   if(!['ru','uk','en','ja','ko'].includes(data.language))throw Error('Источник вернул язык, который пока не поддерживает читалка.');
   if(!data.episodes?.length)throw Error('У этого тайтла нет открытых глав на языке «'+mangaLanguageName(data.language)+'».');
   setInspection({...data,readable:undefined,...(cached?{readable:cached.readable,readabilityError:cached.readabilityError,verifiedChapterUrl:cached.verifiedChapterUrl,fromSourceInfo:true}:{})});setVolume('all');setTeam('');setOne(data.episodes[0].url);setFirst(String(data.episodes[0].number));setLast(String(data.episodes.at(-1).number));if(!item)setCollection(data.title);setBusy('');
   if(cached){
    if(targetChapter&&cached.readable&&data.episodes.some(e=>e.url===targetChapter)){
     setMode('single');setOne(targetChapter);setOnline(true);
    }
    return;
   }
   const result=await service.request('/manga/summary',{method:'POST',body:{url:value,...(item?{title:searchTitle}:{}),verifyPages:Number(service.session?.serverVersion)>=47,refresh:!automatic}});
   if(version!==generation.current)return;setInspection(old=>old?{...old,...result}:old);
   if(result.readable===false)setError(result.readabilityError||'Источник не отдал страницу.');
  }catch(cause){if(version===generation.current){setError(cause.message);setInspection(old=>old?{...old,readable:false,readabilityError:cause.message}:old);}}finally{if(version===generation.current)setBusy('');}
 }
 function startReader(){if(!sourceReady){setError(inspection?.readabilityError||'Главы получены. Проверяем загрузку страницы…');return;}setOnline(true);}

 const selection=mode==='range'?first+'-'+last:mode==='list'?list:'all';let chosen=[],selectionError='';try{chosen=selectChapters(inspection?.episodes||[],{volume,team,selection,language:inspection?.language||'ru'});if(mode==='single')chosen=chosen.filter(e=>e.url===one);}catch(cause){selectionError=cause.message;}
 // The VM translates Drive chapters too (server 71+, renderer assets installed).
 const driveTranslation=destination==='drive'&&sheet&&service.session?.mangaDriveTranslation===true;
 const driveTranslate=driveTranslation&&exportSettings.mode==='translate';
 async function submit(event){event.preventDefault();setError('');if(!sourceReady){setError(inspection?.readabilityError||'Проверяем доступность страниц.');return;}if(destination==='online'){if(chosen.length&&!selectionError)startReader();return;}if(destination==='local'){if(!chosen.length||selectionError){setError(selectionError||'Выбери главы.');return;}setBusy('local');const controller=new AbortController();localAbort.current=controller;try{await exportLocally({signal:controller.signal,entries:chosen,kind:'manga',quality,service,manga:exportSettings,cacheContext:{name:collection,userId:state.user?.sub},onProgress:setLocalProgress});setLocalProgress('Файлы переданы браузеру для сохранения.');}catch(e){setError(e.message);}finally{setBusy('');}return;}if(!ready||!supported||!inspection)return;if(selectionError){setError(selectionError);return;}if(!chosen.length){setError('Выбранные главы не опубликованы в этом переводе.');return;}if(chosen.length>1000){setError('Выбери до 1000 глав за один импорт.');return;}
  const job={version:3,library_id:state.libraryId,sources:[inspection.url||url],collection:collection.trim(),season:volume==='all'?1:Number(volume),episodes:'all',quality,resume:true,section:'manga',metadata:{...mangaMetadata(item),format:inspection.format||item?.format||'manga',readingMode:inspection.readingMode,sourceLanguage:inspection.language,...(!item?{title:collection.trim(),cover:inspection.cover}: {})},dub:team,translation:{name:team||(inspection.language==='ru'?'Перевод':'Оригинал · '+inspection.language.toUpperCase()),kind:'manga',language:inspection.language},
   // A translated chapter is its own «translation» of the title next to the original.
   ...(driveTranslate?{quality:'best',render:exportTranslation(exportSettings),dub:('Перевод MediaVault'+(team?' · '+team:'')).slice(0,120),translation:{name:'Перевод MediaVault',kind:'manga',language:'ru'}}:{}),provider:inspection.provider,entries:chosen.map(e=>({number:e.number,url:e.url,title:e.title||'Глава '+e.number,season:Number(e.season||1)}))};
  setBusy('submit');try{await service.submit(job);onSubmitted?.();}catch(cause){setError(cause.message);}finally{setBusy('');}
 }
 const readerEntries=inspection&&compact?selectChapters(inspection.episodes,{volume,team,language:inspection.language}):chosen;
 const selectedChapter=compact?readerEntries.find(e=>e.url===one)||readerEntries[0]:readerEntries[0];
 const verifiedChapter=mode==='all'&&inspection?.verifiedChapterUrl&&selectedChapter?.url===inspection.episodes?.[0]?.url
  ?readerEntries.find(e=>e.url===inspection.verifiedChapterUrl):null;
 const initialChapter=verifiedChapter||selectedChapter;
 const alternateSources=visibleSources.filter(source=>source.url!==url&&sourceInfo[source.url]?.readable===true);
 function chapterAlternatives(chapter){
  return alternateSources.flatMap(source=>{
   const candidate=sourceInfo[source.url].inspection;
   if(candidate?.language!==inspection.language)return [];
   const match=candidate.episodes.find(entry=>Number(entry.number)===Number(chapter.number)&&Number(entry.season||1)===Number(chapter.season||1));
   return match?[<button key={source.url} type="button" className="btn btn-secondary" onClick={()=>inspect(source.url,false,match.url)}>
    {source.providerName} · глава {chapter.number}
   </button>]:[];
  }).slice(0,3);
 }
 // The hero's share button and chapter counts read what this reader chose.
 const shareKey=inspection?[inspection.url,team,initialChapter?.url,readerEntries.length,collection].join('|'):'';
 useEffect(()=>{
  if(!compact||destination!=='online'||!inspection)return;
  publishTitleShare({service,title:{...item,title:collection},kind:'manga',entries:readerEntries,initial:initialChapter,referer:inspection.url,dub:team,language:inspection.language,userId:state.user?.sub});
  const chapters=new Set(inspection.episodes.map(e=>(e.season||1)+':'+e.number)).size;
  publishTitleStats({kind:'manga',chapters,volumes:inspection.seasons?.length||null,source:inspection.url||url,sourceName:visibleSources.find(s=>s.url===url)?.providerName||inspection.providerName||'',language:inspection.language});
 },[shareKey]);
 useEffect(()=>()=>{if(compact&&destination==='online'){publishTitleShare(null);publishTitleStats(null);}},[]);
 const reader=online&&inspection&&<OnlineViewer inline={compact} onEntryChange={e=>setOne(e.url)} kind="manga" entries={readerEntries} initial={initialChapter} title={collection} service={service} userId={state.user?.sub} language={inspection.language} errorActions={chapterAlternatives} metadata={{...item,format:inspection.format||item?.format,readingMode:inspection.readingMode}} onClose={()=>setOnline(false)}/>;
 const requireVerified=Number(service.session?.serverVersion)>=47,stateOf=s=>displayInfo[s.url]||{};
 const failedSource=s=>stateOf(s).state==='error'||stateOf(s).readable===false||stateOf(s).chapterCount===0;
 const shownSources=rankedSources.filter(s=>s.url===url||!failedSource(s)&&(!requireVerified||stateOf(s).readable===true||stateOf(s).inspection?.episodes?.length));
 const pendingSources=rankedSources.filter(s=>!failedSource(s)&&!shownSources.includes(s)).length;
 const chapterEntries=inspection?selectChapters(inspection.episodes,{volume:'all',team,language:inspection.language}):[];
 const current=chapterEntries.find(e=>e.url===one)||initialChapter;
 const searchingSources=searching||globalSearch.state==='running';
 if(compact&&destination==='online')return <div className="reader-stage manga-stage" data-reading={online||undefined}>
  <aside className="reader-stage-filters" aria-label="Фильтры чтения">
   <FilterGroup legend="Язык глав" value={language} options={MANGA_LANGUAGES.map(([id,label])=>[id,label.replace(/ · .*$/,'')])} onChange={value=>{setLanguage(value);setSourceIds([]);}}/>
   {inspection?.translations?.length>0&&<FilterGroup legend="Переводчик" value={team} options={[['',inspection.language==='ru'?'Все переводчики':'Оригинал'],...inspection.translations.map(v=>[v,v])]} onChange={value=>{setOnline(false);setTeam(value);}}/>}
   <TitleSourcePicker requireVerified={requireVerified} key={item?.id||'manual'} sources={rankedSources} value={url} info={displayInfo} loading={searchingSources} favorites={favorites} expected={Number(expected)||0} onChoose={value=>{setOnline(false);inspect(value);}}/>
   {!searchingSources&&!pendingSources&&!shownSources.length&&<p className="reader-filter-note">{language!=='all'?<>На этом языке глав пока нет. <button type="button" className="text-link" onClick={()=>{setLanguage('all');setSourceIds([]);}}>Искать на всех языках</button></>:'Работающий источник для этого тайтла пока не найден.'}</p>}
   <SourceFilter label="Только эти сайты" service={service} language={language} value={sourceIds} onChange={setSourceIds}/>
   {globalSearch.progress&&<p className="reader-filter-note" role="status">{globalSearch.state==='running'?'Поиск источников':'Поиск завершён'}: {globalSearch.progress.completed} / {globalSearch.progress.total}{globalSearch.progress.failed?' · не ответили: '+globalSearch.progress.failed:''}. Найденные источники сохранены.</p>}
   {globalSearch.error&&<p className="inline-error" role="alert">{globalSearch.error} <button type="button" className="text-link" onClick={()=>setRevision(n=>n+1)}>Повторить поиск источников</button></p>}
   <MangaSearchDiagnostics providers={globalSearch.providers} key={globalSearch.id}/>
   <details className="title-source-tools"><summary>Другой источник или своя ссылка</summary><div className="form-actions"><input className="field-input" aria-label="Ссылка на мангу" type="url" value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://…"/><button type="button" className="btn btn-secondary" disabled={!url||!!busy} onClick={()=>inspect(url)}>Проверить</button></div><button type="button" className="text-link" onClick={()=>setRevision(n=>n+1)}>Обновить источники</button></details>
  </aside>
  <div className="reader-stage-main">
   {error&&<div className="inline-error" role="alert"><p>{error}</p>{alternateSources.slice(0,3).map(source=><button key={source.url} type="button" className="btn btn-secondary" onClick={()=>inspect(source.url)}>{source.providerName}</button>)}</div>}
   <PlaybackReveal active={online}>{reader||<div className="watch-idle mv-player mvx mvx-idle reader-idle" style={item?.cover?{'--watch-poster':`url("${String(item.cover).replace(/["\\]/g,'')}")`}:undefined}>
    <div className="mvx-idle-poster" aria-hidden="true"/>
    <div className="mvx-overview mvx-idle-overview">
     <strong className="reader-idle-title">{collection||item?.title}</strong>
     <p className="mvx-meta" role="status">{busy==='inspect'?<><span className="mvx-spinner"/><span>Загружаем главы</span></>
      :inspection?<>{current&&<span>Глава {current.number}</span>}<span>{visibleSources.find(s=>s.url===url)?.providerName||inspection.providerName||'Источник'}</span><span>{mangaLanguageName(inspection.language)}{inspection.language!=='ru'?' · перевод в читалке':''}</span></>
      :searchingSources||pendingSources?<><span className="mvx-spinner"/><span>Ищем главы на сайтах</span></>
      :<span>Выбери источник слева</span>}</p>
     {inspection&&<button type="button" className="mvx-primary" disabled={!sourceReady||!chapterEntries.length} onClick={()=>{setMode('single');setOne(current?.url||chapterEntries[0]?.url);startReader();}}><BookOpen size={16}/>{!sourceReady?'Проверяем страницы…':'Читать сейчас'}</button>}
    </div>
   </div>}</PlaybackReveal>
   {inspection&&<ChapterChooser active={sourceReady&&!online} cards entries={chapterEntries} value={one} onChoose={e=>{setMode('single');setOne(e.url);startReader();}} service={service} userId={state.user?.sub}/>}
  </div>
  <ChapterIndex entries={chapterEntries} current={one} loading={busy==='inspect'} onOpen={e=>{setMode('single');setOne(e.url);startReader();}}/>
 </div>;
 const translateChoice=[['original','Оригинал'],['translate','С переводом']];
 return <>{!sheet&&reader}<form className={(sheet?"export-form ":"")+"import-selection import-compact manga-import export-workspace destination-"+destination} onSubmit={submit}>
  <div className="section-heading"><div><span className="eyebrow">ОТ СТРАНИЦЫ К ИСТОРИИ</span><h3>Манга · Манхва · Вебтуны</h3></div><span className="manga-language">{language==='all'?(rawAware?'RU · EN · JA · KO':'RU · EN'):language.toUpperCase()}</span></div>
  <ol className="import-step-rail" aria-label="Этапы выбора"><li data-active={!inspection}>Источник</li><li data-active={!!inspection}>Главы и перевод</li><li>{destination==='online'?'Чтение':destination==='local'?'На устройство':'Google Диск'}</li></ol>
  {!compact&&<label className="form-field input-label">Язык глав<select className="field-input" aria-label="Язык источника манги" value={language} disabled={busy==='submit'} onChange={e=>setLanguage(e.target.value)}>{MANGA_LANGUAGES.map(([id,label])=><option key={id} value={id} disabled={['ja','ko'].includes(id)&&!rawAware}>{label}</option>)}</select></label>}
  {!compact&&!sheet&&<label className="form-field input-label">Формат произведения<select aria-label="Формат манги" className="field-input" value={format} disabled={!rawAware||!!busy} onChange={e=>setFormat(e.target.value)}>{MANGA_FORMATS.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>}
  {!rawAware&&!sheet&&<p className="fine">Для японских равок, корейских глав и фильтра манхвы требуется обновление парсеров на Oracle.</p>}
  {!languageAware&&language!=='ru'&&<p className="fine">Сервер пока ищет английские главы только при отсутствии русских. Английскую версию уже можно импортировать по прямой ссылке ниже.</p>}
  {manual&&<label className="form-field input-label">Тип произведения<select className="field-input" value="manga" onChange={e=>onKindChange?.(e.target.value)}>{kinds.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>}
  {service.status==='connected'&&!supported&&<p className="fine">Для импорта манги требуется обновление сервера. Видео и существующая библиотека работают как раньше.</p>}
  {!compact&&!sheet&&Number(service.session?.serverVersion)>=14&&<MangaSourceManager service={service} onInstalled={()=>setRevision(v=>v+1)}/>}
  {item&&<details className="world-alt-sources" open={compact||sheet?undefined:true}><summary>{sheet?(inspection?'Источник · '+(visibleSources.find(s=>s.url===url)?.providerName||inspection.providerName||'выбран'):'Источник')+' · сменить':'Другие источники · '+usableSources.length}</summary><div className="manga-sources-heading"><label className="input-label">{language==='all'?'Источники на всех языках':mangaLanguageName(language)}</label><button type="button" className="text-link" disabled={searching||!supported} onClick={()=>setRevision(v=>v+1)} aria-label="Повторить поиск манги"><RefreshCw size={13}/></button></div>{searching?<p className="discovery-status" role="status"><span className="loading-ring"/>Проверяем читалки по названию произведения…</p>:visibleSources.length?<div className="manga-source-list">{usableSources.map(source=><button type="button" key={source.url} aria-pressed={url===source.url} disabled={busy==='submit'||busy==='local'} onClick={()=>inspect(source.url)}><span className="manga-source-icon"><BookOpen size={18}/></span><span><strong>{source.providerName}</strong><small>{source.title}{source.language&&source.language!=='ru'?' · '+source.language.toUpperCase():''}</small></span>{url===source.url?<Check size={16}/>:<ArrowRight size={15}/>}</button>)}</div>:<p className="fine">{supported?'Точное совпадение пока не найдено. Можно проверить ссылку на тайтл ниже.':'Здесь появятся найденные русские переводы.'}</p>}</details>}
  {item&&Number(service.session?.serverVersion)<16&&bridgeWindow&&<div className="manga-search-window"><p className="fine" role="status">Дополнительные источники: проверено {bridgeWindow.nextOffset} из {bridgeWindow.totalSources}.</p>{bridgeWindow.hasMore&&<button type="button" className="btn btn-secondary btn-small" disabled={searching||moreSearching||!!busy} onClick={moreSources}>{moreSearching?'Проверяем следующие источники…':'Проверить следующие источники'}</button>}</div>}
  {!compact&&!sheet&&['all','en'].includes(language)&&item&&<a className="text-link" href={englishSearch} target="_blank" rel="noopener noreferrer"><Globe size={14}/>Открыть поиск MangaPill на английском</a>}
  <details className="manual-source" open={!sheet&&(!item||['en','ja','ko'].includes(language))}><summary>Ссылка на мангу или главу</summary><div className="form-actions"><input aria-label="Ссылка на мангу" className="field-input" type="url" value={url} onChange={e=>{setUrl(e.target.value);setInspection(null);}} placeholder="https://…"/><button type="button" className="btn btn-secondary btn-small" disabled={!url||!!busy||!supported||service.status!=='connected'} onClick={()=>inspect(url)}>Проверить</button></div></details>
  {busy==='inspect'&&<p className="discovery-status" role="status"><span className="loading-ring"/>Собираем опубликованные главы и тома…</p>}
  {inspection&&<><ChapterChooser active={sourceReady&&!online} userId={state.user?.sub} cards={compact} entries={selectChapters(inspection.episodes,{volume,team,language:inspection.language})} value={one} onChoose={e=>{setMode('single');setOne(e.url);if(compact&&destination==='online')startReader();}} service={service}/><div className="manga-inspected"><BookOpen size={15}/><span><b>{inspection.episodes.length}</b> глав · {inspection.seasons?.length||1} томов</span><small>{mangaLanguageName(inspection.language)+(inspection.language!=='ru'?' · перевод в настройках читалки':'')}</small></div>{inspection.truncated&&<p className="fine">Источник вернул часть списка глав. Для остальных можно проверить прямую ссылку.</p>}
   <label className="form-field input-label">Переводчик<select aria-label="Переводчик" className="field-input" value={team} onChange={e=>setTeam(e.target.value)}><option value="">{inspection.language!=='ru'?mangaLanguageName(inspection.language)+' · оригинал':'Доступный русский перевод'}</option>{(inspection.translations||[]).map(v=><option key={v}>{v}</option>)}</select></label>
   <div className={compact?"import-field-grid world-save-fields":"import-field-grid"}>{destination!=='online'&&<label className="form-field input-label">Название в коллекции<input className="field-input" value={collection} onChange={e=>setCollection(e.target.value)} required/></label>}<label className="form-field input-label">Том<select aria-label="Том" className="field-input" value={volume} onChange={e=>setVolume(e.target.value)}><option value="all">Все тома</option>{inspection.seasons?.map(v=><option key={v.number} value={v.number}>{v.name}</option>)}</select></label></div>
   {!(compact&&destination==='online')&&<div className="episode-selection"><p className="episode-selection-legend">Выбрать главы</p><div className="chip-row">{[['all','Все'],['single','Одна'],['range','Диапазон'],['list','Список']].map(([id,label])=><button type="button" key={id} className={'chip'+(mode===id?' chip-active':'')} onClick={()=>setMode(id)}>{label}</button>)}</div>
    {mode==='single'&&<select className="field-input" aria-label="Номер главы" value={one} onChange={e=>setOne(e.target.value)}>{selectChapters(inspection.episodes,{volume,team,language:inspection.language}).map(e=><option key={e.season+':'+e.number} value={e.url}>{e.title||'Глава '+e.number}</option>)}</select>}
    {mode==='range'&&<div className="import-field-grid"><input className="field-input" type="number" step="any" min="0" aria-label="Первая глава" value={first} onChange={e=>setFirst(e.target.value)}/><input className="field-input" type="number" step="any" min="0" aria-label="Последняя глава" value={last} onChange={e=>setLast(e.target.value)}/></div>}
    {mode==='list'&&<input className="field-input" aria-label="Список глав" placeholder="0, 1-20, 25.5" value={list} onChange={e=>setList(e.target.value)}/>}
    <p className="fine">{selectionError||'К добавлению: '+chosen.length+' глав. Дробные главы и экстра сохраняются отдельно.'}</p>
   </div>}</>}
  {sheet&&inspection&&(destination==='drive'&&!driveTranslation?<p className="export-hint">В Google Диск сервер сохраняет исходные страницы глав. Для перевода в Google Диск обнови сервер MediaVault.</p>
   :destination!=='online'&&<div className="export-field"><span>Что сохранить</span><UiSegmented className="is-wide" label="Что сохранить" value={exportSettings.mode==='original'?'original':'translate'} options={translateChoice} disabled={!!busy} onChange={mode=>setExportSettings(v=>({...v,mode}))}/></div>)}
  {destination==='local'&&inspection&&<MangaExportSettings hideMode={sheet} value={exportSettings} onChange={setExportSettings} disabled={!!busy}/>}
  {driveTranslate&&inspection&&<><MangaExportSettings translationOnly value={exportSettings} onChange={setExportSettings} disabled={!!busy}/><p className="export-hint">Сервер переводит главы на ВМ теми же моделями, что и читалка, затем шифрует и записывает их в Google Диск отдельным переводом рядом с оригиналом, даже если компьютер выключен.</p></>}
  {destination!=='online'&&inspection&&(destination==='drive'?!driveTranslate:exportSettings.mode==='original')&&<label className="form-field input-label">{destination==='local'?'Изображения в файле':'Изображения в Drive'}<select aria-label="Качество страниц манги" className="field-input" value={quality} onChange={e=>setQuality(e.target.value)}><option value="best">Оригинал · без изменений</option><option value="1920">Сбалансированно · до 1920 px</option><option value="1280">Экономия трафика · до 1280 px</option></select><small className="fine">{destination==='local'?'Сжатие выполняет сервер перед сохранением файла.':'Сжатие выполняет сервер до шифрования.'} Исходные размеры при уменьшении не восстановить.</small></label>}
  {destination!=='online'&&Number(service.session?.serverVersion)>=11&&chosen.length>0&&<button type="button" className="btn btn-secondary online-launch" disabled={!!busy||service.status!=='connected'} onClick={startReader}><BookOpen size={17}/>Читать сейчас · без импорта</button>}
  {destination==='drive'&&<ImportReadiness state={state} service={service} onOpenLibrary={onOpenLibrary}/>}{localProgress&&<p className="world-local-progress" role="status">{localProgress}{busy==='local'&&<button type="button" className="text-link" onClick={()=>localAbort.current?.abort(new DOMException('Скачивание остановлено','AbortError'))}>Остановить</button>}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}
  <button className="btn btn-primary import-submit" id="importMangaBtn" type="submit" disabled={(destination==='drive'?!ready||!!state.busy:service.status!=='connected')||!supported||!!busy||!chosen.length||!!selectionError}><BookOpen size={17}/>{busy==='submit'?'Отправляем…':destination==='online'?'Читать сейчас':destination==='local'?(busy==='local'?'Подготавливаем файлы…':'Сохранить на устройство'):chosen.length?'Добавить '+chosen.length+' '+(chosen.length%100>=11&&chosen.length%100<=14?'глав':chosen.length%10===1?'главу':chosen.length%10>=2&&chosen.length%10<=4?'главы':'глав')+' в коллекцию':'Импортировать главы'}<ArrowRight size={16}/></button>
  {globalSearch.progress&&<p className="fine" role="status">Источники: {globalSearch.progress.completed} / {globalSearch.progress.total}. Главы появляются по мере ответа.</p>}<p className="manga-server-note"><ShieldCheck size={13}/><span>{destination==='online'?'Страницы загружаются по мере чтения. Главы не сохраняются в Google Диск.':destination==='local'?'Сервер собирает главы в файлы и передаёт их браузеру для сохранения.':'Главы собираются и шифруются на сервере, затем сохраняются в твоём Drive.'}</span></p>
  {providers.length>0&&<details className="provider-diagnostics"><summary>Проверенные читалки · {providers.length}</summary>{providers.map(p=><p key={p.provider}><b>{p.name}</b><span>{p.status==='ok'?'Найден точный тайтл':p.status==='empty'?'Совпадений нет':p.message||'Временно недоступен'}</span></p>)}</details>}
 </form></>;
}
