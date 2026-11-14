import CatalogIndexProgress from './CatalogIndexProgress.jsx';
import CatalogFilterDock,{SortMenu,splitTags} from './CatalogFilterDock.jsx';
import {useCatalogFavorites} from './catalog-favorites.js';
import {readOnlineTitle,onlineTitleLocation} from './title-route.js';
import {CONTENT_LANGUAGES,useContentLanguage,setContentLanguage} from './content-language.js';
import {CatalogViewControls} from './blossom/components/CatalogViewControls.tsx';
import {CatalogResultsTable} from './blossom/components/CatalogResultsTable.tsx';
import {AnimeGrid} from './blossom/components/AnimeGrid.tsx';
import {AnimeCard} from './blossom/components/AnimeCard.tsx';
import {SkeletonGrid} from './blossom/components/SkeletonCard.tsx';
import {blossomRecord} from './blossom/media-adapter.js';
import React,{useCallback,useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import Icon from './Icons.jsx';
import {BROWSE_KINDS,CATALOG_SORTS,genreLabels,matchesFilters,providers} from './catalog.js';
import {useCatalog} from './use-catalog.js';
import {catalogKinds as kinds,Poster} from './ImportParts.jsx';
import CatalogSearch from './CatalogSearch.jsx';
import CatalogPager from './CatalogPager.jsx';
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
import {useSourceOptions} from './SourceFilter.jsx';
import {worldResults} from './world-search.js';
import WorldTitlePage from './WorldTitlePage.jsx';
import './world-library.css';
import AnimeExplore from './AnimeExplore.jsx';
import {browseRoute} from './anime-navigation.js';
import {useTabIdentity} from './tab-identity.js';
const noTitles=Object.freeze([]);
const SOURCE_LANGUAGES=[['all','Все языки'],['ru','Русский'],['uk','Українська'],['en','Английский'],['ja','Японский, оригинал'],['ko','Корейский, оригинал']];
// Search results and short lists are ordered on the loaded page.
const SORTS=[['default','По совпадению'],['score','По рейтингу'],['new','Сначала новые'],['old','Сначала старые'],['title','По названию, А–Я'],['length','Больше серий и глав']];
const SORT_KEY='mediavault_catalog_sort_v1';
// The manga index orders the whole catalogue on the server.
const INDEX_SORTS=[['new','Сначала новые'],['old','Сначала старые'],['title','По названию'],['length','Больше глав'],['added','Недавно в каталоге']];
// Enough whole rows for about two dozen cards, so the last row is never ragged.
export const pageSize=columns=>{const c=Math.max(1,Math.min(10,Math.round(columns)||1));return Math.min(50,c*Math.ceil(24/c));};
const number=value=>Number.isFinite(Number(value))&&value!==null&&value!==''?Number(value):null;
// Orders the loaded titles; unknown values go last so a missing year never jumps ahead.
export function sortTitles(items,order){
 if(order==='default'||!SORTS.some(([id])=>id===order))return items;
 const pick={score:item=>number(item.score),new:item=>number(item.year),old:item=>number(item.year),length:item=>number(item.episodes??item.chapters)}[order];
 const rows=items.map((item,index)=>({item,index}));
 if(order==='title')return rows.sort((a,b)=>String(a.item.title||'').localeCompare(String(b.item.title||''),'ru')||a.index-b.index).map(row=>row.item);
 const sign=order==='old'?1:-1;
 return rows.sort((a,b)=>{const x=pick(a.item),y=pick(b.item);if(x===null||y===null)return (x===null)-(y===null)||a.index-b.index;return (x-y)*sign||a.index-b.index;}).map(row=>row.item);
}
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
  useTabIdentity('',kind,!selected&&!explore);
  const [order,setOrder]=useState(()=>{try{return localStorage.getItem(SORT_KEY)||'popular';}catch{return 'popular';}});
  const changeOrder=value=>{setOrder(value);setPage(1);try{localStorage.setItem(SORT_KEY,value);}catch{}};
  const [columns,setColumns]=useState(()=>typeof innerWidth==='number'?Math.max(2,Math.floor((Math.min(innerWidth,1760)-120)/250)):4),contentRef=useRef(null);
  useLayoutEffect(()=>{const node=contentRef.current;if(!node||typeof ResizeObserver==='undefined')return;const measure=()=>{const grid=node.querySelector('.catalog-grid');const count=grid?getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length:Math.max(2,Math.floor(node.clientWidth/250));if(count)setColumns(count);};measure();const observer=new ResizeObserver(measure);observer.observe(node);return()=>observer.disconnect();},[layout]);
  const perPage=pageSize(columns);
  const [sourceIds,setSourceIds]=useState([]),[sourceLanguage,setSourceLanguage]=useState('all'),[sourceRevision,setSourceRevision]=useState(0),[voiceOptions,setVoiceOptions]=useState([]);
  const [knownSources,setKnownSources]=useState({});
  const receiveSources=useCallback(rows=>setKnownSources(old=>({...old,...Object.fromEntries(rows.map(row=>[row.id,row]))})),[]);
  const sourceOptions=useSourceOptions(kind==='manga'?service:{status:'off'},sourceLanguage,receiveSources);

  const sourceTitles=useSourceTitles(query,kind,service,composing);
  const globalManga=useGlobalManga(query,kind,sourceLanguage,sourceIds,service,composing||!!selected,sourceRevision);
  const tagPolicyVersion=useMangaPolicy(service);
  const globalTags=globalContentPolicy();
  useEffect(()=>{if(kind!=='manga'&&!globalTags)return;setFilters(old=>{const genre=old.genre&&!mangaPolicy().key(old.genre)?'':old.genre,tag=String(old.tag||'').split(',').filter(value=>mangaPolicy().key(value.trim())).join(',');return genre===old.genre&&tag===old.tag?old:{...old,genre,tag};});},[tagPolicyVersion,kind,globalTags]);
  const browsing=!query.trim();
  const indexSpine=browsing&&kind==='manga'&&Number(service.session?.serverVersion)>=72&&service.status==='connected';
  const sorts=indexSpine?INDEX_SORTS:browsing&&BROWSE_KINDS.includes(kind)?CATALOG_SORTS:SORTS,sort=sorts.some(([id])=>id===order)?order:sorts[0][0];
  const {items:metadataItems,statuses,pages:metadataPages,loading:metadataLoading,retry}=useCatalog(query,kind,filters.year,service.server,page,composing,filters,{sort,perPage,off:indexSpine});
  const contentIndex=useContentCatalog({service,state,kind,query,filters,rows:metadataItems,revision:tagPolicyVersion,page});
  const indexed=useMangaCatalog({query,kind,filters,language:sourceLanguage,sourceIds,service,page,sort:indexSpine?sort:'',limit:indexSpine?perPage:30,paused:!!selected,composing,revision:[sourceRevision,globalManga.results?.length||0,globalManga.state,tagPolicyVersion].join(':')});
  const catalogueRows=indexed.ready?indexed.results:globalManga.results||noTitles;
  // Without a query the page is one ordered list: the manga index or the
  // browse catalogue. Other lists would repeat titles from other pages.
  const items=useMemo(()=>(browsing?indexSpine&&indexed.ready?worldResults([],catalogueRows,'',sourceIds,indexed.candidates):worldResults(metadataItems,[],'',[],[]):worldResults([...metadataItems,...contentIndex.items],[...catalogueRows,...sourceTitles.results],query,kind==='manga'?sourceIds:[],indexed.candidates)).map(contentPolicyFacts),[browsing,indexSpine,metadataItems,contentIndex.items,catalogueRows,sourceTitles.results,query,sourceIds,kind,indexed.candidates,indexed.ready,tagPolicyVersion]);
  const pagingLoading=metadataLoading||sourceTitles.loading||indexed.loading;
  const loading=pagingLoading||globalManga.state==='running'||indexed.enriching;
  useEffect(()=>onItems?.(items),[items]);
  useEffect(()=>{const abort=new AbortController();if(kind!=='anime'||service.status!=='connected'||Number(service.session?.serverVersion)<16)return;const timer=setTimeout(()=>service.request('/discovery/voices?'+new URLSearchParams({q:voice}),{signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setVoiceOptions(data.voices||[]);}).catch(()=>{}),250);return()=>{clearTimeout(timer);abort.abort();};},[kind,voice,service.status,service.server]);
  const voices=useVoices(kind==='anime'?items:noTitles,voice,service);
  const matched=useMemo(()=>items.filter(item=>(!favoritesOnly||bookmarks.has(item))&&matchesFilters(item,filters)&&item.kind===kind&&(!voice||(voices.results[item.id]?.dubs||[]).some(d=>d.toLocaleLowerCase().includes(voice.toLocaleLowerCase())))),[items,filters,kind,voice,voices.results,favoritesOnly,bookmarks]);
  const visible=useMemo(()=>browsing?matched:sortTitles(matched,sort),[matched,sort,browsing]);
  const sourceFacets=useMemo(()=>kind==='manga'?mangaFacetOptions(indexed.taxonomy,indexed.facets,{sourceIds,sources:knownSources}):[],[kind,indexed.taxonomy,indexed.facets,sourceIds,knownSources,tagPolicyVersion]);
  const genres=[...new Set([...(kind==='manga'||globalTags?[]:[filters.genre,...Object.values(genreLabels)]),...(globalTags?[...mangaPolicy().rules.values()].filter(row=>row.category==='genre'||row.genreHint).map(row=>row.label):[]),...sourceFacets.filter(t=>t.type==='genre').map(t=>t.label),...items.flatMap(item=>kind==='manga'||globalTags?item.genres:item.genres.map(localLabel))].filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ru'));
  const tagOptions=[...new Set([...(globalTags?[...mangaPolicy().rules.values()].map(row=>row.label):kind==='manga'?[]:Object.values(tagLabels)),...sourceFacets.map(t=>t.label),...items.flatMap(item=>kind==='manga'||globalTags?item.tags:item.tags.map(localLabel))])].sort((a,b)=>a.localeCompare(b,'ru'));
  const formats=[...new Set([...items.map(item=>item.format),...(kind==='manga'?['manga','manhwa','manhua','webtoon']:[])].filter(Boolean).map(f=>kind==='manga'?mangaFormatLabel(f):f))];
  const hasMore=browsing?indexSpine?!!indexed.hasMore:metadataPages?page<metadataPages:metadataItems.length>=16:!(!contentIndex.hasMore&&metadataItems.length<16&&(!indexed.ready||!indexed.hasMore));
  const pageCounts=browsing?[indexSpine?indexed.ready&&(indexed.workTotal||indexed.total)?Math.ceil((indexed.workTotal||indexed.total)/perPage):null:metadataPages].filter(n=>n>0):[metadataPages,contentIndex.pages,kind==='manga'&&indexed.ready&&indexed.total?Math.ceil(indexed.total/30):null].filter(n=>n>0);
  // Keep the last known page count while the next page loads, so the numbers do not jump.
  const pageScope=JSON.stringify([query.trim(),kind,filters,voice,sourceIds,sourceLanguage,sort,perPage]),knownPages=useRef({scope:'',pages:null});
  if(knownPages.current.scope!==pageScope)knownPages.current={scope:pageScope,pages:null};
  if(pageCounts.length)knownPages.current.pages=Math.max(...pageCounts);
  const totalPages=knownPages.current.pages?Math.max(page,knownPages.current.pages):null;
  // A new page starts at the top of the results, just under the sticky search row.
  const goPage=n=>{setPage(n);requestAnimationFrame(()=>{const heading=document.querySelector('.blossom-catalog-content>.section-heading'),bar=document.querySelector('.catalog-toolbar');if(!heading)return;const top=heading.getBoundingClientRect().top+scrollY-(bar?bar.getBoundingClientRect().height+(parseFloat(getComputedStyle(bar).top)||0)+12:120);if(top<scrollY)scrollTo({top,behavior:reduced?'instant':'smooth'});});};
  const suggestions=matched.slice(0,7),filter=(key,value)=>{setFilters(old=>({...old,[key]:value}));setPage(1);};
  function choose(item){setSelected(item);onlineTitleLocation(item);}
  useLayoutEffect(()=>{if(!selected)return;scrollTo({top:0,behavior:'instant'});const frame=requestAnimationFrame(()=>scrollTo({top:0,behavior:'instant'}));return()=>cancelAnimationFrame(frame);},[selected?.id]);
  const spelling=visible.find(item=>item.searchSpelling)?.searchSpelling;
  const unavailable=Object.values(statuses).includes('unavailable');
  if(selected)return <TitleDetails destination={destination} onOpenLibrary={onOpenLibrary} value={selected} service={service} state={state} onBack={()=>{setSelected(null);location.hash='library';}} onSubmitted={onSubmitted} onRelated={r=>choose({id:'related:'+r.kind+':'+r.id,provider:'shikimori',providerId:String(r.ids?.mal||r.id),providers:['shikimori'],kind:r.kind,title:r.title,titles:{},aliases:[r.title],genres:[],tags:[],links:[],ids:{mal:String(r.ids?.mal||r.id)},releases:[],cover:r.cover,format:r.format})}/>;
  if(explore)return <AnimeExplore route={explore} service={service} onChoose={choose} onBack={()=>{location.hash='library';setExplore(null);}}/>;
  return <><section className="world-catalog-intro"><span className="eyebrow">ОБЩАЯ БИБЛИОТЕКА</span><h2>Найди свою историю</h2><p>Смотри и читай онлайн. Сохраняй любимое в личную коллекцию.</p><CatalogIndexProgress service={service}/></section>
    <div className="catalog-kind-row" aria-label="Тип произведения">{kinds.map(([id,label])=><button key={id} className={'chip'+(kind===id?' chip-active':'')} onClick={()=>{setKind(id);setVoice('');setSourceIds([]);setFilters({year:'',genre:'',tag:'',format:'',age:''});setPage(1);}}>{label}</button>)}</div>
    <div className="blossom-catalog-body is-docked"><div className="blossom-catalog-content" ref={contentRef}>
    <CatalogFilterDock search={<CatalogSearch query={query} onQuery={value=>{setQuery(value);setPage(1);}} suggestions={suggestions} loading={loading} onChoose={choose} onComposing={setComposing}/>} kind={kind} filters={filters} onFilter={filter} sources={kind==='manga'?{options:sourceOptions.sources,error:sourceOptions.error,value:sourceIds,disabled:service.status!=='connected'||Number(service.session?.serverVersion)<16,onChange:value=>{setSourceIds(value);setPage(1);}}:null} onReset={()=>{setFilters({year:'',genre:'',tag:'',format:'',age:''});setVoice('');setPage(1);}} genres={genres} tags={tagOptions} formats={formats}
     voice={voice} onVoice={setVoice} voiceDisabled={service.status!=='connected'} voiceOptions={[...new Set([...voiceOptions.map(v=>typeof v==='string'?v:v.name),...Object.values(voices.results).flatMap(v=>v.dubs||[])])].filter(Boolean)}
     voiceNote={voice?`Проверяем озвучку найденных карточек, осталось ${voices.pending}.`:'Озвучка проверяется у первых 24 карточек страницы.'}
     language={kind==='manga'?{label:'Язык источника',value:sourceLanguage,options:SOURCE_LANGUAGES,onChange:value=>{setSourceLanguage(value);setSourceIds([]);setPage(1);},note:'Список источников ниже подстроится под этот язык.'}:['anime','movie','tv'].includes(kind)?{label:'Язык озвучки',value:contentLanguageValue,options:CONTENT_LANGUAGES,onChange:setContentLanguage,note:'Сначала покажем озвучки на этом языке.'}:null}/>
    {kind==='manga'&&globalManga.progress&&<div className="world-search-progress" role="status"><span><i className={globalManga.state==='running'?'is-searching':''}/>{globalManga.state==='running'?'Ищем в источниках':'Поиск завершён'} · {globalManga.progress.completed} / {globalManga.progress.total}{globalManga.progress.cached?' · из индекса '+globalManga.progress.cached:''}</span><small>{globalManga.progress.failed?globalManga.progress.failed+' источников не ответили':'Результаты появляются по мере готовности'}</small></div>}
    {kind==='manga'&&indexed.ready&&<p className="fine catalog-index-status" role="status">По этим условиям в индексе: {indexed.total} записей · справочник: {sourceFacets.length} тегов и жанров. Метаданные дополняются по мере поиска.</p>}
    {kind==='manga'&&indexed.error&&<p className="fine" role="status">Метаданные источников временно не отвечают. <button className="text-link" onClick={indexed.retry}>Повторить загрузку метаданных</button></p>}
    {kind==='manga'&&globalManga.error&&<p className="inline-error" role="alert">{globalManga.error} <button className="text-link" onClick={()=>setSourceRevision(v=>v+1)}>Повторить</button></p>}
    {kind==='manga'&&service.status==='connected'&&Number(service.session?.serverVersion)<16&&<p className="fine">Глобальный поиск источников включится после обновления сервера до версии 16. Сейчас доступны каталоги метаданных.</p>}
    {kind==='manga'&&<MangaSearchDiagnostics providers={globalManga.providers} key={globalManga.id}/>}
    <p className="catalog-search-hint">Подсказки появляются сразу. Источники дополняют результаты в фоне.</p>

    {spelling&&<p className="fine catalog-spelling">Также ищем по написанию «{spelling}»</p>}<div className="section-heading"><h2 className="section-title">{query?'Результаты поиска':'Тайтлы'}</h2><span className="fine" role="status" aria-live="polite">{loading?'Обновляем карточки…':visible.length?visible.length+' '+titlesWord(visible.length):''}</span><div className="catalog-provider-row" aria-label="Источники метаданных">{Object.entries(statuses).map(([id,status])=><span key={id} className={'catalog-provider provider-'+status} title={status==='unavailable'?'Сейчас недоступен; поиск идёт в остальных каталогах':providers[id]}><i/>{providers[id]}</span>)}{unavailable&&<button className="catalog-retry" disabled={loading} onClick={retry}><Icon name="refresh" size={13}/>Повторить поиск</button>}</div><span className="heading-tools"><SortMenu value={sort} options={sorts} onChange={changeOrder}/><CatalogViewControls value={layout} onChange={changeLayout}/></span></div>
    {visible.length?layout==='table'?<CatalogResultsTable items={visible} onChoose={choose}/>:<AnimeGrid className={'media-grid catalog-grid library-layout-'+layout+' catalog-layout-'+layout}>{visible.map((item,i)=><AnimeCard depth favorite={bookmarks.has(item)} onFavorite={()=>bookmarks.toggle(item)} key={item.id} index={i} anime={blossomRecord({...item,genres:kind==='manga'?item.genres:item.genres.map(g=>genreLabels[g]||g)})} className="title-card catalog-card" titleName={item.title} category={item.kind} onOpen={()=>choose(item)} openLabel={'Выбрать '+item.title} artwork={<Poster item={item}/>} detail={[item.year,item.kind==='book'?(item.authors||[]).slice(0,2).join(', ')||item.format:item.format,item.episodes?item.episodes+' сер.':item.chapters?item.chapters+' гл.':null].filter(Boolean).join(' · ')||item.providerName||providers[item.provider]}/>)}</AnimeGrid>:loading?<SkeletonGrid count={6}/>:<div className="catalog-empty">{loading?<><span className="loading-ring"/><p>Собираем ответы каталогов…</p></>:<><Icon name="search" size={32}/><p>{query?'Пока ничего не нашлось':'Начни вводить название'}</p><small>{Object.values(statuses).some(s=>s==='unavailable')?'Некоторые каталоги недоступны. Попробуй другое написание или повтори поиск позже.':'Можно искать на русском, английском, японском, китайском и корейском. Результат зависит от названий и синонимов в каталогах.'}</small></>}</div>}
    {visible.length>0&&<CatalogPager page={page} pages={totalPages} hasMore={hasMore} onPage={goPage}/>}<p className="catalog-footnote">Каталоги дополняются подключёнными источниками Suwayomi. Отсутствие ответа сайта не подтверждает отсутствие произведения. Годы, жанры и возраст фильтруются только по известным сведениям.</p>
  </div></div></>;
}
