import './interface-refinement.css';
import {alternativeTitleNames,publicationFacts} from './title-details.js';
import {useCatalogFavorites} from './catalog-favorites.js';
import {createImportClient,validateServer} from './import-service.js';
import {useEffect,useRef,useState,useMemo} from 'react';
import {useReducedMotion} from 'motion/react';
import * as Dialog from '@radix-ui/react-dialog';
import {ArrowLeft,Play,Star,ChevronRight,RefreshCw,Cloud,CloudUpload,Users,X,ExternalLink,Film,BookOpen,Bookmark,Download,FolderOpen} from 'lucide-react';
import {useUkrainianTitle} from './use-ukrainian-title.js';
import {loadTitleProfile,loadCharacter,searchRussianTitles,russianText,hasRussian,profileNeedsRefresh,scheduleProfileRetry} from './title-metadata.js';
import {useArtwork,fetchArtwork} from './title-artwork.js';
import {titleParts,SECTION_LABELS} from './library-model.js';
import {episodeNumber,voiceLabel} from './player-model.js';
import MediaViewer from './MediaViewer.jsx';
import Artwork from './Artwork.jsx';
import WatchOrder from './WatchOrder.jsx';
import {readProgress,progressClock} from './playback-progress.js';
import TitleBackdrop from './TitleBackdrop.jsx';
import TitleShowcase from './TitleShowcase.jsx';
import {jikan,youtubeTrailer} from './media-metadata.js';
import {jikanProfile,fillProfile} from './title-supplement.js';
import ReleaseTimeline from './blossom/ReleaseTimeline.tsx';
import CreditsPanel from './CreditsPanel.jsx';
import Soundtrack from './Soundtrack.jsx';
import Trailers from './Trailers.jsx';
import CharacterDialog from './CharacterDialog.jsx';
import TitleGallery from './TitleGallery.jsx';
import './title-sections.css';
import PlatformRatings from './PlatformRatings.jsx';
import TitleNavigation from './TitleNavigation.jsx';
import HoverPreview from './HoverPreview.jsx';
import {readReading} from './reading-progress.js';
import TitleEpisodeCard from './TitleEpisodeCard.jsx';
import './watch-page.css';
import {browseHref,animeSeason} from './anime-navigation.js';
import {publishBackdrop} from './blossom/theme.js';
import './player-refinement.css';
import EpisodeMotionPreview from './EpisodeMotionPreview.jsx';
import {uiLocale} from './i18n/index.js';

const day=value=>{try{return value?new Intl.DateTimeFormat(uiLocale(),{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(value)):'';}catch{return '';}};
const equivalent=value=>String(value||'').toLocaleLowerCase('ru').replace(/[^\p{L}\p{N}]/gu,'');
export function TitleImage({url,profile,actions,libraryId,alt='',className='',fallback=true,...props}){
  const anchor=useRef(null),[visible,setVisible]=useState(false);
  useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'300px'});if(anchor.current)observer.observe(anchor.current);return()=>observer.disconnect();},[]);
  const source=useArtwork(url,profile,actions.readArtwork,libraryId,visible);
  const [broken,setBroken]=useState(false);useEffect(()=>setBroken(false),[source]);
  return source&&!broken?<img ref={anchor} src={source} className={(className||'')+' mv-artwork-image'} onLoad={event=>event.currentTarget.dataset.ready='true'} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={()=>setBroken(true)} {...props}/>:fallback?<Artwork ref={anchor} kind="video" className={className}/>:null;
}
export function EpisodeArtwork({item,profile,actions,libraryId,index=0}){
  const asset=item.previewArtwork;
  const url=asset?'drive:'+asset.id:profile?.episodeImages?.[String(item.season||1)+':'+item.episode]||profile?.episodeImages?.[String(item.episode)]||'';
  const art=url?<TitleImage url={url} profile={asset?{artwork:{[url]:asset}}:profile} actions={actions} libraryId={libraryId}/>:<div className="episode-preview-pending"><span>{String(item.episode??index+1).padStart(2,'0')}</span><small>{item.category==='manga'?'Обложка главы':'Кадр серии'} появится после синхронизации</small></div>;
  return item.category==='video'&&actions.prepareStream?<EpisodeMotionPreview prepare={async()=>({url:await actions.prepareStream(item),type:item.onlineType})}>{art}</EpisodeMotionPreview>:<HoverPreview item={item} actions={actions}>{art}</HoverPreview>;
}
export default function TitlePage({title,state,actions,onBack,onPlay,onRelated,onImport,selected,onClosePlayer,onMetadataLoaded,online=false,onlineProfile,onlineBusy=false,materials,onlineFacts=[],heroActions,onOnlinePlay,server,onLocalFile,backLabel='Библиотека',favorite,onFavorite}){
  const continuation=(title.category==='manga'?readReading:readProgress)(state.user?.sub,state.libraryId,'collection:'+title.collectionId);
  const bookmark=useCatalogFavorites(state.user?.sub);
  const bookmarkItem={kind:title.section,sourceId:onlineProfile?.sourceId||title.profile?.sourceId||title.metadataId,id:title.id};
  const isBookmarked=favorite??bookmark.has(bookmarkItem),toggleBookmark=onFavorite||(()=>bookmark.toggle(bookmarkItem));
  const [downloading,setDownloading]=useState(false);
  const continueItem=title.items.find(value=>value.id===continuation?.itemId);
  const saved=online?null:state.catalog?.titleProfiles?.[title.id],reduced=useReducedMotion();
  const [profile,setProfile]=useState(online?onlineProfile:saved||title.profile||null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[candidates,setCandidates]=useState([]),[search,setSearch]=useState(title.name);
  const [character,setCharacter]=useState(null),[characterBusy,setCharacterBusy]=useState(false),[characterError,setCharacterError]=useState('');
  const [summaryOpen,setSummaryOpen]=useState(false);
  const [palette,setPalette]=useState(null),[playing,setPlaying]=useState(false);
  useEffect(()=>()=>publishBackdrop(null),[title.id]);
  function backgroundPalette(value){setPalette(value);publishBackdrop(value);}
  const [characterLimit,setCharacterLimit]=useState(6);
  const [part,setPart]=useState(''),[ratingBusy,setRatingBusy]=useState(false);
  const characterAbort=useRef(null),abort=useRef(null),saveInProgress=useRef(false),live=useRef(state);live.current=state;
  const characterService=useMemo(()=>{let address='';try{address=validateServer(server||window.MEDIA_VAULT_CONFIG?.importServerUrl||localStorage.getItem('mediavault_import_server')||'');}catch{}return {...createImportClient(address,()=>live.current.token),server:address};},[server,state.user?.sub]);
  const currentProfile=useRef(profile);currentProfile.current=profile;
  const supplementIdentity=String((online?onlineProfile?.sourceId:saved?.sourceId||title.profile?.sourceId)||title.metadataId||'');
  useEffect(()=>{
    if(!/^\d{1,12}$/.test(supplementIdentity)||!['anime','manga','ranobe'].includes(title.section))return;
    const cached=currentProfile.current;
    if(!online&&cached?.cover&&cached?.description&&cached?.characters?.length&&cached?.screenshots?.length&&cached?.trailers?.length)return;
    const controller=new AbortController(),kind=title.section==='anime'?'anime':'manga';
    jikan(kind+'/'+supplementIdentity+'/full',{server:server||window.MEDIA_VAULT_CONFIG?.importServerUrl,signal:controller.signal}).then(result=>{if(!controller.signal.aborted&&String(result.data?.mal_id)===supplementIdentity)setProfile(old=>fillProfile(old||{},jikanProfile(result.data,kind)));}).catch(()=>{});
    if(kind==='anime'&&!currentProfile.current?.characters?.length)jikan('anime/'+supplementIdentity+'/characters',{server,signal:controller.signal}).then(result=>{if(controller.signal.aborted)return;const characters=(result.data||[]).slice(0,18).map(row=>({id:String(row.character.mal_id),name:row.character.name,image:row.character.images?.webp?.image_url||row.character.images?.jpg?.image_url||'',role:row.role==='Main'?'Главный герой':'Персонаж',description:''}));setProfile(old=>fillProfile(old||{},{characters}));}).catch(()=>{});
    if(kind==='anime'&&!currentProfile.current?.screenshots?.length)jikan('anime/'+supplementIdentity+'/videos',{server,signal:controller.signal}).then(result=>{if(controller.signal.aborted)return;const screenshots=(result.data?.episodes||[]).map(row=>row.images?.jpg?.image_url).filter(Boolean).slice(0,12);setProfile(old=>fillProfile(old||{},{screenshots}));}).catch(()=>{});
    return()=>controller.abort();
  },[supplementIdentity,title.section,server]);
  function saveRatings(value){setProfile(old=>({...old,ratings:value}));if(!online&&live.current.admin&&live.current.driveWritable)actions.saveTitleProfile(title.id,{ratings:value},[],{background:true});}
  useEffect(()=>{if(online)setProfile(onlineProfile||{});else if(saved)setProfile(saved);},[saved,online,onlineProfile]);
  useEffect(()=>{
    const controller=new AbortController();abort.current=controller;
    setProfile(online?onlineProfile:saved||title.profile||null);setError('');setCandidates([]);setSearch(title.name);setPart('');setCharacter(null);setCharacterLimit(6);
    if(online)return()=>controller.abort();
    // Opening a page refreshes a dossier only when its retry is due; the save
    // then runs quietly. Manual refresh and search keep their visible status.
    if(profileNeedsRefresh(saved)){
      const identity=title.metadataId||title.metadata?.ids?.mal;
      if(identity)hydrate(identity,controller.signal,{background:true});
    }
    return()=>controller.abort();
  },[title.id,online]);
  async function hydrate(id,signal=abort.current?.signal,{background=false}={}){
    if(online)return;
    setBusy('loading');setError('');
    try{
      const result=await loadTitleProfile(id,title.section==='manga'?'manga':title.section==='ranobe'?'ranobe':'anime',{signal,server:server||window.MEDIA_VAULT_CONFIG?.importServerUrl,refresh:!!profile?.sourceId,onPartial:value=>{if(!signal?.aborted)setProfile(value);}});
      signal?.throwIfAborted();setProfile(result);onMetadataLoaded?.(title.id,result);
      const scheduled=scheduleProfileRetry(result,saved);
      if(state.admin&&state.driveWritable)await (background?saveQuietly(scheduled,signal):save(scheduled,signal));
    }catch(cause){if(!signal?.aborted)setError(cause.message||'Не удалось получить русское описание.');}finally{if(!signal?.aborted)setBusy('');}
  }
  async function find(event){
    event?.preventDefault();setBusy('search');setError('');
    try{
      const values=await searchRussianTitles(search,title.section, {signal:abort.current?.signal});setCandidates(values);
      const match=values.filter(value=>[value.title,...value.aliases].some(alias=>equivalent(alias)===equivalent(search)));
      if(match.length===1)await hydrate(match[0].sourceId);
      else if(!values.length)setError('Тайтл пока не найден. Попробуй другое название.');
    }catch(cause){if(!abort.current?.signal.aborted)setError(cause.message);}finally{if(!abort.current?.signal.aborted)setBusy('');}
  }
  async function save(value=profile,signal=abort.current?.signal){
    if(online)return;
    if(!value||saveInProgress.current)return;saveInProgress.current=true;setBusy('saving');
    try{
      const {images,failed}=await fetchArtwork(value,{signal});signal?.throwIfAborted();
      const result=await actions.saveTitleProfile(title.id,{...value,missingArtwork:failed},images);
      if(result&&!signal?.aborted){setProfile(result);if(failed.length)setError('Описание сохранено. Часть изображений источник пока не отдал; их можно загрузить повторно.');}
    }catch(cause){if(!signal?.aborted)setError(cause.message);}finally{saveInProgress.current=false;if(!signal?.aborted)setBusy('');}
  }
  async function saveQuietly(value,signal){
    if(online||!value||saveInProgress.current)return;saveInProgress.current=true;
    try{
      const {images,failed}=await fetchArtwork(value,{signal});signal?.throwIfAborted();
      const result=await actions.saveTitleProfile(title.id,{...value,missingArtwork:failed},images,{background:true});
      if(result&&!signal?.aborted)setProfile(result);
    }catch{}finally{saveInProgress.current=false;}
  }
  useEffect(()=>()=>characterAbort.current?.abort(),[]);
  async function showCharacter(value){
    characterAbort.current?.abort();const controller=new AbortController();characterAbort.current=controller;
    setCharacter(value);setCharacterError('');setCharacterBusy(true);
    try{
      const address=server||window.MEDIA_VAULT_CONFIG?.importServerUrl,opts={signal:controller.signal,server:address};
      let detail;
      if(address)try{const r=await fetch(address+'/metadata/character-profile/'+value.id,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(16000)])});if(r.ok)detail=await r.json();}catch(e){controller.signal.throwIfAborted();}
      if(!detail||String(detail.id)!==String(value.id))detail=await loadCharacter(value.id,opts);
      if(controller.signal.aborted)return;
      const merged={...value,...detail,name:[detail.name,value.name].find(hasRussian)||detail.name||value.name,description:detail.description||value.description,image:detail.image||value.image};
      setCharacter(merged);
      // The dossier may have finished loading while this character was fetched:
      // merge into the newest profile and store only the characters, so a stale
      // copy of the page state never overwrites links and stills in Drive.
      const withCharacter=source=>({...source,characters:(source?.characters||[]).map(c=>c.id===value.id?{...c,...merged}:c)});
      const characters=withCharacter(currentProfile.current).characters;setProfile(old=>withCharacter(old));
      if(!online&&live.current.admin&&live.current.driveWritable&&!saveInProgress.current)actions.saveTitleProfile(title.id,{characters},[],{background:true});
    }catch(cause){if(!controller.signal.aborted)setCharacterError(cause.message||'Каталоги пока не ответили. Сохранённые сведения доступны.');
    }finally{if(!controller.signal.aborted)setCharacterBusy(false);}
  }
  const ratingKey='mediavault_rating_v1:'+String(state.user?.sub||'guest')+':'+title.id;
  const [localRating,setLocalRating]=useState(()=>{try{return Number(localStorage.getItem(ratingKey))||0;}catch{return 0;}});
  useEffect(()=>{try{setLocalRating(Number(localStorage.getItem(ratingKey))||0);}catch{setLocalRating(0);}},[ratingKey]);
  async function rate(value){
    if(online){setLocalRating(value);try{localStorage.setItem(ratingKey,String(value));}catch{}return;}
    setRatingBusy(true);setError('');
    try{const result=await actions.saveTitleProfile(title.id,{...(profile||{}),userRatings:{...(profile?.userRatings||{}),[state.user.sub]:value}});if(result)setProfile(result);}
    catch(cause){setError(cause.message);}finally{setRatingBusy(false);}
  }
  const ukrainian=useUkrainianTitle(server||state?.server,title.section||title.profile?.kind,title.metadataId||title.profile?.sourceId||title.profile?.ids?.mal);
  const p=ukrainian?{...(profile||{}),title:ukrainian.title,description:ukrainian.description||profile?.description}:(profile||{}),name=p.title&&p.title!=='Название уточняется'?p.title:title.name,parts=titleParts(title),currentPart=parts.find(value=>value.name===part)||parts[0];
  const video=selected&&title.items.some(item=>item.id===selected.id)?selected:null;
  const voices=[...new Set(title.items.filter(i=>i.category==='video').map(i=>voiceLabel(i)))];
  const facts=[['Тип',p.format||SECTION_LABELS[title.section]||'Произведение'],['Тема',p.themes?.join(', ')],['Статус',p.status],['Выпуск',day(p.startDate)+(p.endDate?' — '+day(p.endDate):'')],['Первоисточник',p.origin],...publicationFacts(p,title.section),['Длительность',p.duration?p.duration+' мин.':null],['Рейтинг',p.ratingCode],['Возраст',p.rating],['Озвучка',voices.join(', ')],['Режиссёры',p.directors?.join(', ')],['Студия',p.studios?.join(', ')]];
  const otherNames=alternativeTitleNames(p,name);
  const isAnimePage=title.section==='anime',releaseSeason=isAnimePage?animeSeason(p.startDate):null;
  const factValue=(label,value)=>label==='Студия'?(p.studios||[]).map(name=><a key={name} href={browseHref('studio','',p.studioRefs?.find(s=>s.name===name)?.id||'',name)}>{name}</a>):label==='Режиссёры'?(p.directors||[]).map(name=><a key={name} href={browseHref('person','',p.staff?.find(s=>s.name===name)?.id||'',name)}>{name}</a>):label==='Выпуск'&&isAnimePage?<a href={browseHref('year',String(p.year),'',String(p.year))}>{value}</a>:value;
  const ownRating=online?localRating:p.userRatings?.[state.user?.sub]||0;
  const owned=online?Object.entries(state.catalog?.titleProfiles||{}).find(([key,value])=>key.startsWith(title.section+':')&&String(value.sourceId)===String(p.sourceId)&&String(p.sourceId||'')!==''):null;
  async function downloadCurrent(){if(downloading)return;const item=continueItem||title.items[0];if(!item)return;setDownloading(true);try{const blob=await actions.readWhole(item,{silent:true});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=item.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}catch(e){setError(e.message);}finally{setDownloading(false);}}
  const artProps={profile:p,actions,libraryId:state.libraryId};
  return <article data-kind={title.section} className={'title-page'+(online?' online-title-page':'')+(title.category==='video'?' watch-title-page':'')} style={palette?{'--title-rgb':palette.base}:undefined}>
    <button id={online?undefined:'backToTitles'} className="text-link title-page-back" onClick={onBack}><ArrowLeft size={16}/>{backLabel}</button>
    <TitleShowcase background={sceneStyle=><TitleBackdrop enhance={title.section==='manga'} server={server} identity={title.section==='anime'?p.sourceId||title.metadataId:null} sceneStyle={sceneStyle} inline profile={{...p,backgrounds:[...(p.backgrounds||[]),p.background,p.trailers?.[0]?.image,p.cover].filter(Boolean)}} actions={actions} libraryId={state.libraryId} onPalette={backgroundPalette} suspended={playing} trailer={p.trailers?.find(t=>/youtube/.test(t.url||''))?.url}/>}>
      <><div className="title-poster"><TitleImage url={p.cover} {...artProps} alt={'Обложка: '+name}/>{p.rating&&<span>{p.rating}</span>}</div><div className="poster-actions">{online?<button className="btn btn-primary" onClick={()=>{if(onOnlinePlay){onOnlinePlay();return;}document.getElementById('titleMaterials')?.scrollIntoView({behavior:reduced?'instant':'smooth',block:'start'});}}>{title.category==='video'?<Play size={16}/>:<BookOpen size={16}/>}{title.category==='video'?'Смотреть онлайн':title.section==='manga'?'Начать читать':'Читать'}</button>:title.items.length>0?<button className="btn btn-primary" onClick={()=>{onPlay(continueItem||title.items.find(i=>i.category==='video')||title.items[0]);setTimeout(()=>document.getElementById('titlePlayback')?.scrollIntoView({behavior:reduced?'instant':'smooth',block:'center'}),60);}}><Play size={16} fill="currentColor"/>{continueItem?title.category==='manga'?'Продолжить · глава '+(continueItem.episode??'')+' · стр. '+(continuation.page+1):'Продолжить · серия '+(episodeNumber(continueItem)||'')+' · '+progressClock(continuation.time):video?'Продолжить просмотр':title.category==='video'?'Смотреть онлайн':title.category==='audio'?'Слушать':'Читать'}</button>:['game','book'].includes(title.section)?<a className="btn btn-primary" href={p.externalURL||p.sourceURL} target="_blank" rel="noopener noreferrer"><ExternalLink size={16}/>{title.section==='game'?'Открыть страницу игры':'Открыть источник'}</a>:<button className="btn btn-primary" onClick={()=>onImport?.(name,title.section,p)}><CloudUpload size={17}/>Добавить в коллекцию</button>}<small>{online?'Онлайн':p.savedAt?'Из твоего Google Диска':'Из твоей коллекции'}</small><div className="poster-action-icons"><button className="circle-button" aria-label={isBookmarked?'Убрать тайтл из избранного':'В избранное'} aria-pressed={isBookmarked} onClick={toggleBookmark}><Bookmark size={17}/></button>{heroActions}{!online&&title.items.length>0&&<button className="circle-button" aria-label="Скачать текущий файл" title="Скачать текущий файл" disabled={downloading} onClick={downloadCurrent}><Download size={17}/></button>}{title.section==='manga'&&onLocalFile&&<button className="circle-button" aria-label="Открыть главу с устройства" title="Открыть главу с устройства" onClick={onLocalFile}><FolderOpen size={17}/></button>}{owned&&<button className="circle-button" aria-label="Открыть из своей коллекции" title="Открыть из своей коллекции" onClick={()=>{location.hash=new URLSearchParams({title:owned[0]}).toString();}}><FolderOpen size={17}/></button>}</div></div></>
      <div className="title-hero-copy"><p className="eyebrow">{SECTION_LABELS[title.section]||'Произведение'}{p.year&&<> · {isAnimePage?<a href={browseHref('year',String(p.year),'',String(p.year))}>{p.year}</a>:p.year}</>}{p.format&&p.format!==SECTION_LABELS[title.section]?' · '+p.format:''}</p><h1 translate="no">{name}</h1>{otherNames.length>0&&<p className="title-alternative-names" aria-label="Альтернативные названия" translate="no">{otherNames.join(' · ')}</p>}<div className="title-hero-status">{p.score&&<span className="title-score"><Star size={15} fill="currentColor"/>{p.score.toFixed(2)}<small>Шикимори</small></span>}{p.status&&!isAnimePage&&<span>{p.status}</span>}{p.status&&isAnimePage&&p.status!=='Не указано'&&<a className={'anime-status status-'+(p.statusCode||'')} href={browseHref('status',p.statusCode||(/заверш|вышел/i.test(p.status)?'released':/анонс/i.test(p.status)?'anons':'ongoing'),'',p.status)}><i/>{p.status}</a>}{releaseSeason&&<a className='anime-season' href={browseHref('season',releaseSeason.value,'',releaseSeason.label)}>{releaseSeason.label}</a>}<span>{title.items.length?title.items.length+' файлов в коллекции':'В мировом каталоге'}</span></div>
        <p className="title-hero-description" id="titleSummary" translate="no">{(online?p.description:russianText(p.description))||'Описание пока не предоставлено каталогом.'}</p><button className="title-summary-more text-link" onClick={()=>setSummaryOpen(true)}>Полное описание</button>
        <div className="title-genre-list">{(p.genres||[]).map(genre=>isAnimePage?<a key={genre} href={browseHref('genre',genre,p.genreRefs?.find(g=>g.name===genre)?.id||'',genre)}>{genre}</a>:<span key={genre}>{genre}</span>)}</div>
        <dl className="title-hero-facts">{facts.filter(([label,value])=>value&&(title.category!=='video'||['Выпуск','Эпизоды','Выпущено серий','Последняя серия','Серий запланировано','Длительность'].includes(label))).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{factValue(label,value)}</dd></div>)}{title.category!=='video'&&p.characters?.length>0&&<div><dt>Главные герои</dt><dd className="hero-character-links">{p.characters.filter(c=>/главн/i.test(c.role)).slice(0,5).map(c=><button key={c.id} onClick={()=>showCharacter(c)}>{c.name}</button>)}</dd></div>}</dl>
      </div>
      <section className="title-facts"><h2>{online?'Информация':'В твоей коллекции'}</h2><dl>{online?onlineFacts.filter(([,value])=>value).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{factValue(label,value)}</dd></div>):<><div><dt>Сохранено</dt><dd>{title.items.length} файлов</dd></div>{voices.length>0&&<div><dt>Озвучки</dt><dd>{voices.join(', ')}</dd></div>}</>}{title.category==='video'&&facts.filter(([label,value])=>value&&['Студия','Первоисточник','Режиссёры','Рейтинг','Возраст'].includes(label)).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{factValue(label,value)}</dd></div>)}</dl>{p.themes?.length>0&&<><h3>Темы</h3><div className="title-genre-list">{p.themes.map(value=><span key={value}>{value}</span>)}</div></>}
</section>
    </TitleShowcase>
    <TitleNavigation title={title} profile={p}/>
    <div className="title-page-columns mv-title-layout"><div className="title-page-main">
      {online&&materials&&<section id="titleMaterials" className="title-episodes online-title-materials">{materials}</section>}
      {(!online&&(!p.sourceId||state.admin)||error)&&<section className="title-description title-metadata-tools"><div className="section-heading"><h2>Сведения о тайтле</h2>{(busy||onlineBusy)&&<span className="fine" role="status">{busy==='saving'?'Сохраняем оформление в Drive…':busy==='search'?'Ищем тайтл…':'Загружаем сведения…'}</span>}</div>
        {!online&&!p.sourceId&&<form className="title-match-form" onSubmit={find}><label htmlFor="titleLookup">Найти оформление и русское описание</label><div className="form-actions"><input id="titleLookup" className="field-input" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Название аниме или манги"/><button className="btn btn-secondary btn-small" disabled={!!busy}>Найти</button></div>{candidates.length>1&&<div className="title-match-results" translate="no">{candidates.map(value=><button key={value.sourceId} type="button" onClick={()=>hydrate(value.sourceId)}>{value.title}<small>{value.year||''} · {value.format}</small><ChevronRight size={16}/></button>)}</div>}</form>}
        {error&&<p className="inline-error" role="alert">{error}</p>}{!online&&state.admin&&p.sourceId&&<div className="title-metadata-actions"><button className="text-link" disabled={!!busy} onClick={()=>save()}><CloudUpload size={14}/>{p.savedAt?p.missingArtwork?.length?'Дозагрузить изображения':'Обновить копию в Drive':'Сохранить оформление в Drive'}</button>{p.source!=='wikidata'&&<button className="text-link" disabled={!!busy} onClick={()=>hydrate(p.sourceId)}><RefreshCw size={13}/>Обновить сведения</button>}</div>}
      </section>}
      {video&&<section id="titlePlayback" className="title-playback"><button className="title-close-playback circle-button" aria-label="Закрыть просмотр" title="Закрыть просмотр" onClick={onClosePlayer}><X size={17}/></button><MediaViewer reveal characterService={characterService} userId={state.user?.sub} item={video} catalog={state.catalog} libraryId={state.libraryId} onSelectItem={onPlay} onClose={onClosePlayer} readWhole={actions.readWhole} prepareStream={actions.prepareStream} onError={actions.error} onPlaybackChange={setPlaying} renderEpisodeArtwork={(episode,index)=><EpisodeArtwork item={episode} index={index} {...artProps}/>} inline/></section>}
      {!video&&title.items.length>0&&<section id="titleMaterials" className="title-episodes"><div className="section-heading"><h2>{title.category==='video'?'Эпизоды':title.category==='manga'?'Главы':'Материалы'}</h2>{parts.length>1&&<select aria-label="Сезон или том" value={currentPart?.name||''} onChange={event=>setPart(event.target.value)}>{parts.map(value=><option key={value.name}>{value.name}</option>)}</select>}</div><div className="title-episode-grid">{currentPart?.items.map((item,index)=><TitleEpisodeCard key={item.id} number={item.episode??index+1} manga={item.category==='manga'} title={item.category==='video'?'Серия '+(episodeNumber(item)||index+1):item.category==='manga'?'Глава '+(item.episode??index+1):item.name} detail={item.category==='manga'?(item.episodeTitle||item.dub||(item.translationInfo?.language==='en'?'EN → RU · автоперевод':'Русский перевод')):voiceLabel(item)} onClick={()=>onPlay(item)} artwork={<EpisodeArtwork item={item} index={index} {...artProps}/>}/>)}</div></section>}
      <section id="titleCharacters" className="title-characters"><div className="section-heading"><h2>Персонажи</h2><Users size={17}/></div>{p.characters?.length?<><div className="title-character-grid" translate="no">{p.characters.slice(0,characterLimit).map(value=><button key={value.id} onClick={()=>showCharacter(value)}><TitleImage url={value.image} {...artProps} alt=""/><span><strong>{value.name}</strong><small>{value.role}</small></span></button>)}</div>{p.characters.length>characterLimit&&<button className='text-link character-more' onClick={()=>setCharacterLimit(n=>n+6)}>Ещё персонажи</button>}</>:<p className="title-empty-note">{p.sourceId?'Каталог пока не предоставил персонажей.':'Персонажи появятся вместе со сведениями о тайтле.'}</p>}</section>
      {p.screenshots?.length>0&&<TitleGallery images={p.screenshots} profile={p} actions={actions} libraryId={state.libraryId} manga={title.category==='manga'} renderArtwork={(url,index)=><TitleImage url={url} {...artProps} alt={'Кадр '+(index+1)}/>}/>}
      {title.section==='anime'&&<ReleaseTimeline identity={p.sourceId||title.metadataId} releases={p.releases||[]} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl}/>}
      {title.section==='anime'&&<Soundtrack identity={p.sourceId||title.metadataId} userId={state.user?.sub} animeTitle={name} cover={p.cover} renderArtwork={url=><TitleImage url={url} {...artProps} alt="Обложка аниме"/>}/>}
      <Trailers server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} profile={p} userId={state.user?.sub} libraryId={state.libraryId} onPlaybackChange={setPlaying} renderArtwork={value=><TitleImage url={value.image} {...artProps} alt=""/>}/>
      {p.related?.length>0&&<section id="titleRelated" className="title-related"><div className="section-heading"><h2>В этой вселенной</h2><span className="fine">Сезоны · Фильмы · Манга · Книги · Игры</span></div><div className="title-horizontal">{p.related.map(value=><button key={value.kind+value.id} onClick={()=>onRelated({...value,artwork:p.artwork,savedAt:p.savedAt})}><span className="related-poster"><TitleImage url={value.cover} {...artProps} alt={value.title}/><small>{value.format}</small></span><strong>{value.title}</strong><small>{value.relation}</small></button>)}</div></section>}
      <section id="titleDiscussion" className="title-discussion"><div><h2>Обсуждение и обзоры</h2><p>Отзывы читателей и зрителей — на странице произведения.</p></div>{p.sourceURL&&<a className="text-link" href={p.sourceURL} target="_blank" rel="noopener noreferrer">{p.source==='wikidata'?'Открыть источник':'Читать на Шикимори'}<ExternalLink size={14}/></a>}</section>
    </div><aside className="title-sidebar"><section className="title-rating-section">      {(online||state.admin)&&<div className="title-rating"><h3>Твоя оценка</h3><p>{ownRating?ownRating+' из 10':'Как тебе эта история?'}</p><div role="group" aria-label="Оценить произведение">{Array.from({length:10},(_,index)=><button key={index} aria-label={'Оценка '+(index+1)} aria-pressed={ownRating===index+1} disabled={ratingBusy||!online&&(!!state.busy||state.importActive)} onClick={()=>rate(index+1)}>{index+1}</button>)}</div><small>{online?'Сохраняется на этом устройстве.':'Сохраняется в зашифрованном каталоге.'}</small></div>}
    </section><PlatformRatings identity={p.sourceId} kind={title.section} cached={p.ratings} score={p.score} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} onLoaded={saveRatings}/>{title.section==='anime'&&/^\d+$/.test(String(p.sourceId||''))&&<WatchOrder identity={p.sourceId} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} cached={p.watchOrder} onRelated={onRelated} onLoaded={value=>{setProfile(old=>({...old,watchOrder:value}));if(!online&&state.admin&&state.driveWritable)actions.saveTitleProfile(title.id,{watchOrder:value},[],{background:true});}}/>}<CreditsPanel kind={title.section} profile={p} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} renderArtwork={value=><TitleImage url={value.image} {...artProps} alt=""/>}/></aside></div>
    <Dialog.Root open={summaryOpen} onOpenChange={setSummaryOpen}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog title-summary-dialog"><header className="entity-dialog-heading"><Dialog.Title>{name}</Dialog.Title><Dialog.Close className="circle-button" aria-label="Закрыть описание"><X size={20}/></Dialog.Close></header><Dialog.Description className="entity-biography">{(online?p.description:russianText(p.description))||'Описание пока не предоставлено каталогом.'}</Dialog.Description></Dialog.Content></Dialog.Portal></Dialog.Root>
    <CharacterDialog character={character} busy={characterBusy} error={characterError} onClose={()=>{characterAbort.current?.abort();setCharacter(null);}} renderArtwork={value=><TitleImage url={value.image} {...artProps} alt={value.name}/>} onRelated={onRelated}/>
  </article>;
}
