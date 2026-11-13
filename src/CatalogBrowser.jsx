import CatalogIndexProgress from './CatalogIndexProgress.jsx';
import CatalogFilterDock,{splitTags} from './CatalogFilterDock.jsx';
import {useCatalogFavorites} from './catalog-favorites.js';
import {readOnlineTitle,onlineTitleLocation} from './title-route.js';
import {CONTENT_LANGUAGES,useContentLanguage,setContentLanguage} from './content-language.js';
import {CatalogViewControls} from './blossom/components/CatalogViewControls.tsx';
import {CatalogResultsTable} from './blossom/components/CatalogResultsTable.tsx';
import {AnimeGrid} from './blossom/components/AnimeGrid.tsx';
import {AnimeCard} from './blossom/components/AnimeCard.tsx';
import {SkeletonGrid} from './blossom/components/SkeletonCard.tsx';
import {blossomRecord} from './blossom/media-adapter.js';
import React,{useCallback,useEffect,useLayoutEffect,useMemo,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import Icon from './Icons.jsx';
import {genreLabels,matchesFilters,providers} from './catalog.js';
import {useCatalog} from './use-catalog.js';
import {catalogKinds as kinds,Poster} from './ImportParts.jsx';
import CatalogSearch from './CatalogSearch.jsx';
import {tagLabels,localLabel} from './taxonomy.js';
import {useVoices} from './use-voices.js';
import useGlobalManga from './use-global-manga.js';
import useMangaCatalog from './use-manga-catalog.js';
import {mangaFacetOptions,mangaFormatLabel} from './manga-catalog.js';
import {contentPolicyFacts,mangaPolicy,globalContentPolicy} from './manga-tag-policy.js';
import useContentCatalog from './use-content-catalog.js';
import useMangaPolicy from './use-manga-policy.js';
import MangaSearchDiagnostics from './MangaSearchDiagnostics.jsx';
import useSourceTitles from './use-source-titles.js';
import SourceFilter from './SourceFilter.jsx';
import {worldResults} from './world-search.js';
import WorldTitlePage from './WorldTitlePage.jsx';
import './world-library.css';
import AnimeExplore from './AnimeExplore.jsx';
import {browseRoute} from './anime-navigation.js';
const noTitles=Object.freeze([]);
const SOURCE_LANGUAGES=[['all','Все языки'],['ru','Русский'],['uk','Українська'],['en','Английский'],['ja','Японский, оригинал'],['ko','Корейский, оригинал']];
const titlesWord=n=>{const t=n%10,h=n%100;return t===1&&h!==11?'тайтл':t>=2&&t<=4&&(h<12||h>14)?'тайтла':'тайтлов';};

export function TitleDetails(props){return <WorldTitlePage {...props}/>;}

export default function CatalogBrowser({service,state,onSubmitted,onItems,onOpenLibrary,initialQuery,initialFilters,initialKind,initialTarget,initialItem,destination,favoritesOnly=false}){
 const contentLanguageValue=useContentLanguage();
  const bookmarks=useCatalogFavorites(state.user?.sub);
  const [layout,setLayout]=useState(()=>{try{const value=localStorage.getItem('mediavault_catalog_view_v2');return ['grid','compact','list','table'].includes(value)?value:'grid';}catch{return 'grid';}});
  const changeLayout=value=>{setLayout(value);try{localStorage.setItem('mediavault_catalog_view_v2',value);}catch{}};
  const [explore,setExplore]=useState(()=>browseRoute());
  useEffect(()=>{const update=()=>{setExplore(browseRoute());const route=readOnlineTitle();if(route)setSelected(route);else if(browseRoute()||location.hash==='#library')setSelected(null);};addEventListener('hashchange',update);return()=>removeEventListener('hashchange',update);},[]);
  const preset=initialTarget||initialItem;
  const [query,setQuery]=useState(initialQuery||''),[kind,setKind]=useState(initialKind||'anime'),[selected,setSelected]=useState(()=>readOnlineTitle()||preset||null);
  const [filters,setFilters]=useState(()=>({year:'',genre:'',tag:'',format:'',age:'',...Object.fromEntries(Object.entries(initialFilters||{}).filter(([key,value])=>['year','genre'].includes(key)&&value))})),[voice,setVoice]=useState(''),[showFilters,setShowFilters]=useState(true),[page,setPage]=useState(1),[composing,setComposing]=useState(false);
  useEffect(()=>{if(preset){setSelected(preset);onlineTitleLocation(preset,true);}},[preset]);
  const reduced=useReducedMotion();
  const [sourceIds,setSourceIds]=useState([]),[sourceLanguage,setSourceLanguage]=useState('all'),[sourceRevision,setSourceRevision]=useState(0),[voiceOptions,setVoiceOptions]=useState([]);
  const [knownSources,setKnownSources]=useState({});
  const receiveSources=useCallback(rows=>setKnownSources(old=>({...old,...Object.fromEntries(rows.map(row=>[row.id,row]))})),[]);
  const {items:metadataItems,statuses,loading:metadataLoading,retry}=useCatalog(query,kind,filters.year,service.server,page,composing,filters);
  const sourceTitles=useSourceTitles(query,kind,service,composing);
  const globalManga=useGlobalManga(query,kind,sourceLanguage,sourceIds,service,composing||!!selected,sourceRevision);
  const tagPolicyVersion=useMangaPolicy(service);
  const globalTags=globalContentPolicy();
  useEffect(()=>{if(kind!=='manga'&&!globalTags)return;setFilters(old=>{const genre=old.genre&&!mangaPolicy().key(old.genre)?'':old.genre,tag=String(old.tag||'').split(',').filter(value=>mangaPolicy().key(value.trim())).join(',');return genre===old.genre&&tag===old.tag?old:{...old,genre,tag};});},[tagPolicyVersion,kind,globalTags]);
  const contentIndex=useContentCatalog({service,state,kind,query,filters,rows:metadataItems,revision:tagPolicyVersion,page});
  const indexed=useMangaCatalog({query,kind,filters,language:sourceLanguage,sourceIds,service,page,paused:!!selected,composing,revision:[sourceRevision,globalManga.results?.length||0,globalManga.state,tagPolicyVersion].join(':')});
  const catalogueRows=indexed.ready?indexed.results:globalManga.results||noTitles;
  const items=useMemo(()=>worldResults([...metadataItems,...contentIndex.items],[...catalogueRows,...sourceTitles.results],query,kind==='manga'?sourceIds:[],indexed.candidates).map(contentPolicyFacts),[metadataItems,contentIndex.items,catalogueRows,sourceTitles.results,query,sourceIds,kind,indexed.candidates,tagPolicyVersion]);
  const pagingLoading=metadataLoading||sourceTitles.loading||indexed.loading;
  const loading=pagingLoading||globalManga.state==='running'||indexed.enriching;
  useEffect(()=>onItems?.(items),[items]);
  useEffect(()=>{const abort=new AbortController();if(kind!=='anime'||service.status!=='connected'||Number(service.session?.serverVersion)<16)return;const timer=setTimeout(()=>service.request('/discovery/voices?'+new URLSearchParams({q:voice}),{signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setVoiceOptions(data.voices||[]);}).catch(()=>{}),250);return()=>{clearTimeout(timer);abort.abort();};},[kind,voice,service.status,service.server]);
  const voices=useVoices(kind==='anime'?items:noTitles,voice,service);
  const visible=useMemo(()=>items.filter(item=>(!favoritesOnly||bookmarks.has(item))&&matchesFilters(item,filters)&&item.kind===kind&&(!voice||(voices.results[item.id]?.dubs||[]).some(d=>d.toLocaleLowerCase().includes(voice.toLocaleLowerCase())))),[items,filters,kind,voice,voices.results,favoritesOnly,bookmarks]);
  const sourceFacets=useMemo(()=>kind==='manga'?mangaFacetOptions(indexed.taxonomy,indexed.facets,{sourceIds,sources:knownSources}):[],[kind,indexed.taxonomy,indexed.facets,sourceIds,knownSources,tagPolicyVersion]);
  const genres=[...new Set([...(kind==='manga'||globalTags?[]:[filters.genre,...Object.values(genreLabels)]),...(globalTags?[...mangaPolicy().rules.values()].filter(row=>row.category==='genre'||row.genreHint).map(row=>row.label):[]),...sourceFacets.filter(t=>t.type==='genre').map(t=>t.label),...items.flatMap(item=>kind==='manga'||globalTags?item.genres:item.genres.map(localLabel))].filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ru'));
  const tagOptions=[...new Set([...(globalTags?[...mangaPolicy().rules.values()].map(row=>row.label):kind==='manga'?[]:Object.values(tagLabels)),...sourceFacets.map(t=>t.label),...items.flatMap(item=>kind==='manga'||globalTags?item.tags:item.tags.map(localLabel))])].sort((a,b)=>a.localeCompare(b,'ru'));
  const formats=[...new Set([...items.map(item=>item.format),...(kind==='manga'?['manga','manhwa','manhua','webtoon']:[])].filter(Boolean).map(f=>kind==='manga'?mangaFormatLabel(f):f))];
  const suggestions=visible.slice(0,7),filter=(key,value)=>{setFilters(old=>({...old,[key]:value}));setPage(1);};
  function choose(item){setSelected(item);onlineTitleLocation(item);}
  useLayoutEffect(()=>{if(!selected)return;scrollTo({top:0,behavior:'instant'});const frame=requestAnimationFrame(()=>scrollTo({top:0,behavior:'instant'}));return()=>cancelAnimationFrame(frame);},[selected?.id]);
  const spelling=visible.find(item=>item.searchSpelling)?.searchSpelling;
  const unavailable=Object.values(statuses).includes('unavailable');
  if(selected)return <TitleDetails destination={destination} onOpenLibrary={onOpenLibrary} value={selected} service={service} state={state} onBack={()=>{setSelected(null);location.hash='library';}} onSubmitted={onSubmitted} onRelated={r=>choose({id:'related:'+r.kind+':'+r.id,provider:'shikimori',providerId:String(r.ids?.mal||r.id),providers:['shikimori'],kind:r.kind,title:r.title,titles:{},aliases:[r.title],genres:[],tags:[],links:[],ids:{mal:String(r.ids?.mal||r.id)},releases:[],cover:r.cover,format:r.format})}/>;
  if(explore)return <AnimeExplore route={explore} service={service} onChoose={choose} onBack={()=>{location.hash='library';setExplore(null);}}/>;
  return <><section className="world-catalog-intro"><span className="eyebrow">ОБЩАЯ БИБЛИОТЕКА</span><h2>Найди свою историю</h2><p>Смотри и читай онлайн. Сохраняй любимое в личную коллекцию.</p><CatalogIndexProgress service={service}/></section>
    <div className="catalog-kind-row" aria-label="Тип произведения">{kinds.map(([id,label])=><button key={id} className={'chip'+(kind===id?' chip-active':'')} onClick={()=>{setKind(id);setVoice('');setSourceIds([]);setFilters({year:'',genre:'',tag:'',format:'',age:''});setPage(1);}}>{label}</button>)}</div>
    <div className="blossom-catalog-body is-docked"><div className="blossom-catalog-content">
    <CatalogFilterDock search={<CatalogSearch query={query} onQuery={value=>{setQuery(value);setPage(1);}} suggestions={suggestions} loading={loading} showFilters={showFilters} onToggleFilters={()=>setShowFilters(value=>!value)} onChoose={choose} onComposing={setComposing}/>} open={showFilters} kind={kind} filters={filters} onFilter={filter} onReset={()=>{setFilters({year:'',genre:'',tag:'',format:'',age:''});setVoice('');setPage(1);}} genres={genres} tags={tagOptions} formats={formats}
     voice={voice} onVoice={setVoice} voiceDisabled={service.status!=='connected'} voiceOptions={[...new Set([...voiceOptions.map(v=>typeof v==='string'?v:v.name),...Object.values(voices.results).flatMap(v=>v.dubs||[])])].filter(Boolean)}
     voiceNote={voice?`Проверяем озвучку найденных карточек, осталось ${voices.pending}.`:'Озвучка проверяется у первых 24 карточек страницы.'}
     language={kind==='manga'?{label:'Язык источника',value:sourceLanguage,options:SOURCE_LANGUAGES,onChange:value=>{setSourceLanguage(value);setSourceIds([]);setPage(1);},note:'Список источников ниже подстроится под этот язык.'}:['anime','movie','tv'].includes(kind)?{label:'Язык озвучки',value:contentLanguageValue,options:CONTENT_LANGUAGES,onChange:setContentLanguage,note:'Сначала покажем озвучки на этом языке.'}:null}/>
    {kind==='manga'&&<div className="world-discovery-controls"><SourceFilter service={service} language={sourceLanguage} value={sourceIds} onOptions={receiveSources} onChange={value=>{setSourceIds(value);setPage(1);}}/></div>}
    {kind==='manga'&&globalManga.progress&&<div className="world-search-progress" role="status"><span><i className={globalManga.state==='running'?'is-searching':''}/>{globalManga.state==='running'?'Ищем в источниках':'Поиск завершён'} · {globalManga.progress.completed} / {globalManga.progress.total}{globalManga.progress.cached?' · из индекса '+globalManga.progress.cached:''}</span><small>{globalManga.progress.failed?globalManga.progress.failed+' источников не ответили':'Результаты появляются по мере готовности'}</small></div>}
    {kind==='manga'&&indexed.ready&&<p className="fine catalog-index-status" role="status">По этим условиям в индексе: {indexed.total} записей · справочник: {sourceFacets.length} тегов и жанров. Метаданные дополняются по мере поиска.</p>}
    {kind==='manga'&&indexed.error&&<p className="fine" role="status">Метаданные источников временно не отвечают. <button className="text-link" onClick={indexed.retry}>Повторить загрузку метаданных</button></p>}
    {kind==='manga'&&globalManga.error&&<p className="inline-error" role="alert">{globalManga.error} <button className="text-link" onClick={()=>setSourceRevision(v=>v+1)}>Повторить</button></p>}
    {kind==='manga'&&service.status==='connected'&&Number(service.session?.serverVersion)<16&&<p className="fine">Глобальный поиск источников включится после обновления сервера до версии 16. Сейчас доступны каталоги метаданных.</p>}
    {kind==='manga'&&<MangaSearchDiagnostics providers={globalManga.providers} key={globalManga.id}/>}
    <p className="catalog-search-hint">Подсказки появляются сразу. Источники дополняют результаты в фоне.</p>

    {spelling&&<p className="fine catalog-spelling">Также ищем по написанию «{spelling}»</p>}<div className="section-heading"><h2 className="section-title">{query?'Результаты поиска':'Тайтлы'}</h2><span className="fine" role="status" aria-live="polite">{loading?'Обновляем карточки…':visible.length?visible.length+' '+titlesWord(visible.length):''}</span><div className="catalog-provider-row" aria-label="Источники метаданных">{Object.entries(statuses).map(([id,status])=><span key={id} className={'catalog-provider provider-'+status} title={status==='unavailable'?'Сейчас недоступен; поиск идёт в остальных каталогах':providers[id]}><i/>{providers[id]}</span>)}{unavailable&&<button className="catalog-retry" disabled={loading} onClick={retry}><Icon name="refresh" size={13}/>Повторить поиск</button>}</div><CatalogViewControls value={layout} onChange={changeLayout}/></div>
    {visible.length?layout==='table'?<CatalogResultsTable items={visible} onChoose={choose}/>:<AnimeGrid className={'media-grid catalog-grid library-layout-'+layout+' catalog-layout-'+layout}>{visible.map((item,i)=><AnimeCard depth favorite={bookmarks.has(item)} onFavorite={()=>bookmarks.toggle(item)} key={item.id} index={i} anime={blossomRecord({...item,genres:kind==='manga'?item.genres:item.genres.map(g=>genreLabels[g]||g)})} className="title-card catalog-card" titleName={item.title} category={item.kind} onOpen={()=>choose(item)} openLabel={'Выбрать '+item.title} artwork={<Poster item={item}/>} detail={[item.year,item.kind==='book'?(item.authors||[]).slice(0,2).join(', ')||item.format:item.format,item.episodes?item.episodes+' сер.':item.chapters?item.chapters+' гл.':null].filter(Boolean).join(' · ')||item.providerName||providers[item.provider]}/>)}</AnimeGrid>:loading?<SkeletonGrid count={6}/>:<div className="catalog-empty">{loading?<><span className="loading-ring"/><p>Собираем ответы каталогов…</p></>:<><Icon name="search" size={32}/><p>{query?'Пока ничего не нашлось':'Начни вводить название'}</p><small>{Object.values(statuses).some(s=>s==='unavailable')?'Некоторые каталоги недоступны. Попробуй другое написание или повтори поиск позже.':'Можно искать на русском, английском, японском, китайском и корейском. Результат зависит от названий и синонимов в каталогах.'}</small></>}</div>}
    {visible.length>0&&<div className="catalog-pagination"><button className="btn btn-secondary" disabled={page===1} onClick={()=>setPage(p=>p-1)}>Назад</button><span>Страница {page}</span><button className="btn btn-secondary" disabled={!contentIndex.hasMore&&metadataItems.length<16&&(!indexed.ready||!indexed.hasMore)} onClick={()=>setPage(p=>p+1)}>Дальше<Icon name="arrow" size={15}/></button></div>}<p className="catalog-footnote">Каталоги дополняются подключёнными источниками Suwayomi. Отсутствие ответа сайта не подтверждает отсутствие произведения. Годы, жанры и возраст фильтруются только по известным сведениям.</p>
  </div></div></>;
}
