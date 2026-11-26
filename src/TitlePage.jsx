import {alternativeTitleNames,publicationFacts} from './title-details.js';
import {useCatalogFavorites} from './catalog-favorites.js';
import {createImportClient,validateServer} from './import-service.js';
import {lazy,Suspense,useEffect,useRef,useState,useMemo,useSyncExternalStore} from 'react';
import {useRetainedWorkspace} from './RetainedMedia.jsx';
import {titleResume} from './title-resume.js';
import {requestPlaceSync} from './place-sync.js';
import {useReducedMotion} from 'motion/react';
import * as Dialog from '@radix-ui/react-dialog';
import {ArrowLeft,Play,Star,ChevronRight,RefreshCw,Cloud,CloudUpload,Users,X,ExternalLink,Film,BookOpen,Bookmark,Download,FolderOpen} from 'lucide-react';
import {useUkrainianTitle} from './use-ukrainian-title.js';
import {loadTitleProfile,loadCharacter,searchRussianTitles,russianText,hasRussian,profileNeedsRefresh,scheduleProfileRetry,imageURL,characterPortraits,withPortraits} from './title-metadata.js';
import {useArtwork,fetchArtwork} from './title-artwork.js';
import {titleParts,SECTION_LABELS} from './library-model.js';
import {episodeNumber,voiceLabel} from './player-model.js';
import Artwork from './Artwork.jsx';
import {readProgress,progressClock} from './playback-progress.js';
import TitleBackdrop from './TitleBackdrop.jsx';
import TitleShowcase,{usePhone} from './TitleShowcase.jsx';
import {mangaPolicyProfile,globalContentPolicy} from './manga-tag-policy.js';
import useMangaPolicy from './use-manga-policy.js';
import {jikan,youtubeTrailer} from './media-metadata.js';
import {jikanProfile,fillProfile} from './title-supplement.js';
import './title-sections.css';
import './title-rails.css';
import {usePlatformRatings} from './PlatformRatings.jsx';
import TitlePassport,{runtime} from './TitlePassport.jsx';
import ShareTitleButton from './ShareTitleButton.jsx';
import {useTitleShare,useTitleStats} from './title-context.js';
import './title-dossier.css';
import TitleNavigation from './TitleNavigation.jsx';
import KineticTitle from './title-exact/KineticTitle.jsx';
import {CharactersRow,Dossier} from './title-exact/sections/Characters.jsx';
import {StillsMosaic} from './title-exact/sections/Stills.jsx';
import {ScheduleSection} from './title-exact/sections/Schedule.jsx';
import {MusicSection} from './title-exact/sections/Music.jsx';
import {TrailersSection} from './title-exact/sections/Trailers.jsx';
import {RelatedRow} from './title-exact/sections/Related.jsx';
import {RouteSection} from './title-exact/sections/Route.jsx';
import {CreatorsSection} from './title-exact/sections/Creators.jsx';
const NO_RELEASES=[];
import {EpisodeCapsules} from './title-exact/RealSections.jsx';
import {useThemeMode} from './title-exact/theme-mode.js';
import {ratingColors} from './PlatformRatings.jsx';
import {passportVolume} from './title-passport-model.js';

// Background glow pair of each chapter, as in the approved design.
const CHAPTER_GLOWS={watch:['rgba(225, 29, 72, 0.24)','rgba(136, 19, 55, 0.22)'],characters:['rgba(244, 63, 94, 0.20)','rgba(107, 33, 168, 0.22)'],stills:['rgba(190, 18, 60, 0.22)','rgba(59, 7, 100, 0.24)'],schedule:['rgba(217, 119, 6, 0.18)','rgba(159, 18, 57, 0.20)'],music:['rgba(168, 85, 247, 0.22)','rgba(225, 29, 72, 0.20)'],trailers:['rgba(239, 68, 68, 0.22)','rgba(88, 28, 135, 0.20)'],related:['rgba(225, 29, 72, 0.20)','rgba(180, 83, 9, 0.18)'],order:['rgba(190, 24, 93, 0.22)','rgba(124, 45, 18, 0.18)'],creators:['rgba(244, 63, 94, 0.18)','rgba(76, 5, 25, 0.26)']};
import HoverPreview from './HoverPreview.jsx';
import {readReading} from './reading-progress.js';
import TitleEpisodeCard from './TitleEpisodeCard.jsx';
import './watch-page.css';
import {browseHref,animeSeason} from './anime-navigation.js';
import {publishBackdrop} from './blossom/theme.js';
import EpisodeMotionPreview from './EpisodeMotionPreview.jsx';
import {uiLocale,t as translateUi} from './i18n/index.js';

const day=value=>{try{return value?new Intl.DateTimeFormat(uiLocale(),{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(value)):'';}catch{return '';}};
const equivalent=value=>String(value||'').toLocaleLowerCase('ru').replace(/[^\p{L}\p{N}]/gu,'');
// Title sections sit in perspective-transformed wrappers, where IntersectionObserver
// cannot map its targets and reports them as never visible (character portraits
// never loaded). Pending images are checked by their transformed rectangle instead:
// one sweep per frame while scrolling (any scroller, captured), and each image
// leaves the sweep once it is near the viewport.
const nearViewport=new Set();let sweepQueued=false,sweepAttached=false;
function sweepNearViewport(){sweepQueued=false;const h=innerHeight,w=innerWidth,m=300;
  for(const entry of [...nearViewport]){if(!entry.node.isConnected){nearViewport.delete(entry);continue;}const r=entry.node.getBoundingClientRect();if((r.width||r.height)&&r.bottom>-m&&r.top<h+m&&r.right>-m&&r.left<w+m){nearViewport.delete(entry);entry.show();}}
  if(!nearViewport.size&&sweepAttached){sweepAttached=false;removeEventListener('scroll',queueSweep,true);removeEventListener('resize',queueSweep);}}
function queueSweep(){if(!sweepQueued){sweepQueued=true;requestAnimationFrame(sweepNearViewport);}}
function watchNearViewport(node,show){const entry={node,show};nearViewport.add(entry);if(!sweepAttached){sweepAttached=true;addEventListener('scroll',queueSweep,{capture:true,passive:true});addEventListener('resize',queueSweep);}queueSweep();setTimeout(queueSweep,400);return()=>nearViewport.delete(entry);}
// Without a fallback picture an empty anchor still stands in, so the visibility
// observer has something to watch and the image starts loading.
export function TitleImage({url,profile,actions,libraryId,alt='',className='',fallback=true,...props}){
  const anchor=useRef(null),[visible,setVisible]=useState(false);
  useEffect(()=>anchor.current?watchNearViewport(anchor.current,()=>setVisible(true)):undefined,[]);
  const source=useArtwork(url,profile,actions.readArtwork,libraryId,visible);
  const [broken,setBroken]=useState(false);useEffect(()=>setBroken(false),[source]);
  return source&&!broken?<img ref={anchor} src={source} className={(className||'')+' mv-artwork-image'} onLoad={event=>event.currentTarget.dataset.ready='true'} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={()=>setBroken(true)} {...props}/>:fallback?<Artwork ref={anchor} kind="video" className={className}/>:<span ref={anchor} className={(className||'')+' mv-artwork-pending'} aria-hidden="true"/>;
}
export function EpisodeArtwork({item,profile,actions,libraryId,index=0}){
  const asset=item.previewArtwork;
  const url=asset?'drive:'+asset.id:profile?.episodeImages?.[String(item.season||1)+':'+item.episode]||profile?.episodeImages?.[String(item.episode)]||'';
  const art=url?<TitleImage url={url} profile={asset?{artwork:{[url]:asset}}:profile} actions={actions} libraryId={libraryId}/>:<div className="episode-preview-pending"><span>{String(item.episode??index+1).padStart(2,'0')}</span><small>{item.category==='manga'?'Обложка главы':'Кадр серии'} появится после синхронизации</small></div>;
  return item.category==='video'&&actions.prepareStream?<EpisodeMotionPreview prepare={async()=>({url:await actions.prepareStream(item),type:item.onlineType})}>{art}</EpisodeMotionPreview>:<HoverPreview item={item} actions={actions}>{art}</HoverPreview>;
}
const NO_HISTORY=[],noSubscribe=()=>()=>{};
// The player and readers arrive with the first title page that needs them.
const loadViewer=()=>import('./MediaViewer.jsx'),MediaViewer=lazy(loadViewer);
export default function TitlePage({title,state,actions,onBack,onPlay,onRelated,onImport,selected,onClosePlayer,onMetadataLoaded,online=false,onlineProfile,onlineBusy=false,materials,onlineFacts=[],heroActions,onOnlinePlay,server,onLocalFile,backLabel='Библиотека',favorite,onFavorite,shareService}){
  const continuation=(title.category==='manga'?readReading:readProgress)(state.user?.sub,state.libraryId,'collection:'+title.collectionId);
  const bookmark=useCatalogFavorites(state.user?.sub);
  const bookmarkItem={kind:title.section,sourceId:onlineProfile?.sourceId||title.profile?.sourceId||title.metadataId,id:title.id};
  const isBookmarked=favorite??bookmark.has(bookmarkItem),toggleBookmark=onFavorite||(()=>bookmark.toggle(bookmarkItem));
  const [downloading,setDownloading]=useState(false);
  const continueItem=title.items.find(value=>value.id===continuation?.itemId);
  const saved=online?null:state.catalog?.titleProfiles?.[title.id],reduced=useReducedMotion(),phone=usePhone(),isNoir=useThemeMode()==='noir';
  const [profile,setProfile]=useState(online?onlineProfile:saved||title.profile||null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[candidates,setCandidates]=useState([]),[search,setSearch]=useState(title.name);
  const [character,setCharacter]=useState(null),[characterBusy,setCharacterBusy]=useState(false),[characterError,setCharacterError]=useState('');
  const [summaryOpen,setSummaryOpen]=useState(false),[namesOpen,setNamesOpen]=useState(false);
  const [palette,setPalette]=useState(null),[playing,setPlaying]=useState(false);
  useEffect(()=>()=>publishBackdrop(null),[title.id]);
  function backgroundPalette(value){setPalette(value);publishBackdrop(value);}
  const [part,setPart]=useState(''),[ratingBusy,setRatingBusy]=useState(false);
  const characterAbort=useRef(null),characterTrigger=useRef(null),abort=useRef(null),saveInProgress=useRef(false),live=useRef(state);live.current=state;
  const characterService=useMemo(()=>{let address='';try{address=validateServer(server||window.MEDIA_VAULT_CONFIG?.importServerUrl||localStorage.getItem('mediavault_import_server')||'');}catch{}return {...createImportClient(address,()=>live.current.token),server:address};},[server,state.user?.sub]);
  useMangaPolicy(characterService);
  const currentProfile=useRef(profile);currentProfile.current=profile;
  const supplementIdentity=String((online?onlineProfile?.sourceId:saved?.sourceId||title.profile?.sourceId)||title.metadataId||'');
  useEffect(()=>{
    if(!/^\d{1,12}$/.test(supplementIdentity)||!['anime','manga','ranobe'].includes(title.section))return;
    const cached=currentProfile.current;
    if(!online&&cached?.cover&&cached?.description&&cached?.characters?.length&&cached?.screenshots?.length&&cached?.trailers?.length)return;
    const controller=new AbortController(),kind=title.section==='anime'?'anime':'manga';
    jikan(kind+'/'+supplementIdentity+'/full',{server:server||window.MEDIA_VAULT_CONFIG?.importServerUrl,signal:controller.signal}).then(result=>{if(!controller.signal.aborted&&String(result.data?.mal_id)===supplementIdentity)setProfile(old=>fillProfile(old||{},jikanProfile(result.data,kind)));}).catch(()=>{});
    if(kind==='anime'&&!currentProfile.current?.characters?.length)jikan('anime/'+supplementIdentity+'/characters',{server,signal:controller.signal}).then(result=>{if(controller.signal.aborted)return;const characters=(result.data||[]).slice(0,18).map(row=>({id:String(row.character.mal_id),name:row.character.name,image:[row.character.images?.webp?.image_url,row.character.images?.jpg?.image_url].find(url=>url&&!/questionmark/i.test(url))||'',role:row.role==='Main'?'Главный герой':'Персонаж',description:''}));setProfile(old=>fillProfile(old||{},{characters}));}).catch(()=>{});
    if(kind==='anime'&&!currentProfile.current?.screenshots?.length)jikan('anime/'+supplementIdentity+'/videos',{server,signal:controller.signal}).then(result=>{if(controller.signal.aborted)return;const screenshots=(result.data?.episodes||[]).map(row=>row.images?.jpg?.image_url).filter(Boolean).slice(0,12);setProfile(old=>fillProfile(old||{},{screenshots}));}).catch(()=>{});
    return()=>controller.abort();
  },[supplementIdentity,title.section,server]);
  // A saved dossier may keep empty or placeholder portraits. The server looks the
  // title's characters up in MAL, AniList and Kitsu (exact id or exact name in
  // this title) and the admin's copy stores only the characters with their art.
  useEffect(()=>{
    const address=server||window.MEDIA_VAULT_CONFIG?.importServerUrl;
    if(online||!address||!/^\d{1,12}$/.test(supplementIdentity)||!['anime','manga','ranobe'].includes(title.section))return;
    const missing=(currentProfile.current?.characters||[]).filter(c=>!imageURL(c.image)).map(c=>c.id);
    if(!missing.length)return;
    const controller=new AbortController();
    characterPortraits(supplementIdentity,title.section,missing,{server:address,signal:controller.signal}).then(async found=>{
      if(controller.signal.aborted||!Object.keys(found).length)return;
      setProfile(old=>({...old,characters:withPortraits(old?.characters,found)}));
      if(!live.current.admin||!live.current.driveWritable)return;
      const characters=withPortraits(currentProfile.current?.characters,found);
      const {images}=await fetchArtwork({characters,artwork:currentProfile.current?.artwork},{signal:controller.signal});
      if(!controller.signal.aborted)await actions.saveTitleProfile(title.id,{characters},images,{background:true});
    }).catch(()=>{});
    return()=>controller.abort();
  },[supplementIdentity,title.section,online]);
  function saveRatings(value){setProfile(old=>({...old,ratings:value}));if(!online&&live.current.admin&&live.current.driveWritable)actions.saveTitleProfile(title.id,{ratings:value},[],{background:true});}
  useEffect(()=>{if(online)setProfile(onlineProfile||{});else if(saved)setProfile(saved);},[saved,online,onlineProfile]);
  useEffect(()=>{
    const controller=new AbortController();abort.current=controller;
    setProfile(online?onlineProfile:saved||title.profile||null);setError('');setCandidates([]);setSearch(title.name);setPart('');setCharacter(null);
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
  async function showCharacter(value,trigger){
    characterTrigger.current=trigger;
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
      if(!online&&live.current.admin&&live.current.driveWritable)actions.saveTitleProfile(title.id,{characters},[],{background:true});
    }catch(cause){if(!controller.signal.aborted)setCharacterError(cause.message||'Каталоги пока не ответили. Сохранённые сведения доступны.');
    }finally{if(!controller.signal.aborted)setCharacterBusy(false);}
  }
  const ratingKey='mediavault_rating_v1:'+String(state.user?.sub||'guest')+':'+title.id;
  const [localRating,setLocalRating]=useState(()=>{try{return Number(localStorage.getItem(ratingKey))||0;}catch{return 0;}});
  useEffect(()=>{try{setLocalRating(Number(localStorage.getItem(ratingKey))||0);}catch{setLocalRating(0);}},[ratingKey]);
  async function rate(value){
    if(online){setLocalRating(value);try{localStorage.setItem(ratingKey,String(value));}catch{}return;}
    setRatingBusy(true);setError('');
    try{const result=await actions.saveTitleProfile(title.id,{userRatings:{[state.user.sub]:value}});if(result)setProfile(result);}
    catch(cause){setError(cause.message);}finally{setRatingBusy(false);}
  }
  const ukrainian=useUkrainianTitle(server||state?.server,title.section||title.profile?.kind,title.metadataId||title.profile?.sourceId||title.profile?.ids?.mal);
  const baseProfile=ukrainian?{...(profile||{}),title:ukrainian.title,description:ukrainian.description||profile?.description}:(profile||{});
  const p=title.category==='manga'||globalContentPolicy()?mangaPolicyProfile(baseProfile,title.section||title.kind):baseProfile,name=p.title&&p.title!=='Название уточняется'?p.title:title.name,parts=titleParts(title),currentPart=parts.find(value=>value.name===part)||parts[0];
  const video=selected&&title.items.some(item=>item.id===selected.id)?selected:null;
  const voices=[...new Set(title.items.filter(i=>i.category==='video').map(i=>voiceLabel(i)))];
  const facts=[['Тип',p.format||SECTION_LABELS[title.section]||'Произведение'],['Тема',p.themes?.join(', ')],['Статус',p.status],['Выпуск',day(p.startDate)+(p.endDate?' — '+day(p.endDate):'')],['Первоисточник',p.origin],...publicationFacts(p,title.section),['Длительность',p.duration?p.duration+' мин.':null],['Рейтинг',p.ratingCode],['Возраст',p.rating],['Озвучка',voices.join(', ')],['Режиссёры',p.directors?.join(', ')],['Студия',p.studios?.join(', ')]];
  const otherNames=alternativeTitleNames(p,name);
  // The hero names the title in the scripts people search by: one Russian, one
  // original (kana/kanji/hangul) and one Latin name; the rest open on request.
  const keyNames=useMemo(()=>{const pick=test=>otherNames.find(n=>test.test(n));return [...new Set([pick(/[а-яё]/i),pick(/[぀-ヿ一-鿿가-힯]/),pick(/^[ -~]+$/)].filter(Boolean))];},[otherNames.join('|')]);
  const isAnimePage=title.section==='anime',releaseSeason=isAnimePage?animeSeason(p.startDate):null;
  const factValue=(label,value)=>!isAnimePage?value:label==='Студия'?(p.studios||[]).map(name=><a key={name} href={browseHref('studio','',p.studioRefs?.find(s=>s.name===name)?.id||'',name)}>{name}</a>):label==='Режиссёры'?(p.directors||[]).map(name=><a key={name} href={browseHref('person','',p.staff?.find(s=>s.name===name)?.id||'',name)}>{name}</a>):label==='Выпуск'&&isAnimePage?<a href={browseHref('year',String(p.year),'',String(p.year))}>{value}</a>:value;
  const ownRating=online?localRating:p.userRatings?.[state.user?.sub]||0;
  const onlineShare=useTitleShare(),published=useTitleStats();
  const sharePayload=online&&onlineShare?.title.id===title.id?onlineShare:null;
  const shareTitle={...sharePayload?.title,title:name,cover:p.cover||sharePayload?.title.cover,
    description:p.description||sharePayload?.title.description,year:p.year||sharePayload?.title.year,
    format:p.format||sharePayload?.title.format,section:title.section};
  useEffect(()=>{if(title.items?.length)loadViewer().catch(()=>{});},[title.id]);
  // The place may have moved on another device of this profile.
  useEffect(()=>{if(online)requestPlaceSync();},[title.id,online]);
  // An online title resumes where the viewer stopped: the hero button names the place.
  const workspace=useRetainedWorkspace(),viewing=useSyncExternalStore(workspace?workspace.subscribe:noSubscribe,()=>workspace?workspace.getSnapshot().history:NO_HISTORY,()=>NO_HISTORY);
  const onlineResume=online?titleResume(viewing,new URLSearchParams(location.hash.slice(1)).get('watch')):null;
  // The reader's own count wins; a page without a mounted reader still shows
  // what the last verified source published.
  const stats=published||(p.sourcePublication?{chapters:p.sourcePublication.count,sourceName:p.sourcePublication.providerName,language:p.sourcePublication.language}:null);
  const publication=Object.fromEntries(publicationFacts(p,title.section));
  const ratings=usePlatformRatings({identity:['anime','manga','ranobe'].includes(title.section)?p.sourceId:'',kind:title.section,cached:p.ratings,score:p.score,server:server||window.MEDIA_VAULT_CONFIG?.importServerUrl,onLoaded:saveRatings});
  const extraScores=ratings.valid?[]:p.scores?.length?p.scores:p.score?[{key:'score',name:title.section==='book'?'Фантлаб':'Оценка',value:p.score,votes:p.votes}]:[];
  const dates=day(p.startDate)+(p.endDate&&p.endDate!==p.startDate?' — '+day(p.endDate):'');
  const section=title.section,people=list=>(list||[]).filter(Boolean).join(', ');
  const passportFacts=[
   ['Статус',p.status],['Выпуск',dates||(p.year?String(p.year):'')],
   ...(section==='anime'?[['Студия',people(p.studios)],['Режиссёры',people(p.directors)],['Первоисточник',p.origin]]:[]),
   ...(['movie','tv'].includes(section)?[['Режиссёр',people(p.directors)],[section==='tv'?'Канал':'Студия',section==='tv'?p.network||people(p.studios):people(p.studios)],['Страна',people(p.countries)||people(p.themes)],]:[]),
   ...(['manga','ranobe'].includes(section)?[['Автор',people(p.authors)||people((p.staff||[]).filter(s=>/автор|рисов|story|art/i.test(s.role||'')).map(s=>s.name).slice(0,3))],['Издатель',people(p.publishers)],['Первоисточник',p.origin]]:[]),
   ...(section==='book'?[['Автор',people(p.authors)],['Оригинал',p.originalTitle&&p.originalTitle!==name?p.originalTitle:''],['Язык оригинала',p.originalLanguage]]:[]),
   ...(['manga','ranobe'].includes(section)?[['Последняя глава в источнике',publication['Последняя глава в источнике']]]:[]),
   ...(['anime','tv'].includes(section)&&/выход|ongoing|releasing/i.test(p.status||'')?[['Последняя серия',publication['Последняя серия']]]:[]),
   ['Возраст',p.rating||p.ageLabel],
   ...(online?onlineFacts.filter(([label])=>!['Доступ','Статус оригинала'].includes(label)):[['В коллекции',title.items.length?title.items.length+' файлов':''],['Озвучки',voices.join(', ')]]),
  ];
  const owned=online?Object.entries(state.catalog?.titleProfiles||{}).find(([key,value])=>key.startsWith(title.section+':')&&String(value.sourceId)===String(p.sourceId)&&String(p.sourceId||'')!==''):null;
  async function downloadCurrent(){if(downloading)return;const item=continueItem||title.items[0];if(!item)return;setDownloading(true);try{const blob=await actions.readWhole(item,{silent:true});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=item.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}catch(e){setError(e.message);}finally{setDownloading(false);}}
  const artProps={profile:p,actions,libraryId:state.libraryId};
  const art=(url,alt='',className,fallback=true)=><TitleImage url={url} {...artProps} alt={alt} className={className} fallback={fallback}/>;
  const chapter=id=>'chapter-'+id;
  const goTo=id=>document.getElementById(chapter(id))?.scrollIntoView({behavior:reduced?'instant':'smooth',block:'start'});
  const k=index=>({sectionIndex:index,enabled:true});
  const isVideo=title.category==='video'||(online&&!['manga','ranobe','book'].includes(section));
  // Hero call to action: the same destinations as before, in the design's pill.
  const cta=online?{label:onlineResume?'Продолжить · '+onlineResume.place:isVideo?'Смотреть онлайн':section==='manga'?'Начать читать':'Читать',icon:isVideo?undefined:<BookOpen size={14}/>,onClick:()=>{if(onOnlinePlay){onOnlinePlay();return;}goTo('watch');}}
   :title.items.length>0?{label:continueItem?(title.category==='manga'?'Продолжить · глава '+(continueItem.episode??''):'Продолжить · '+(episodeNumber(continueItem)||'')+' серия'):video?'Продолжить просмотр':title.category==='video'?'Смотреть':title.category==='audio'?'Слушать':'Читать',
     time:continueItem&&title.category!=='manga'?progressClock(continuation.time):continueItem?'стр. '+(continuation.page+1):'',progress:continuation?.duration?continuation.time/continuation.duration:0,
     onClick:()=>{onPlay(continueItem||title.items.find(i=>i.category==='video')||title.items[0]);setTimeout(()=>goTo('watch'),60);}}
   :['game','book'].includes(section)&&(p.externalURL||p.sourceURL)?{label:section==='game'?'Открыть страницу игры':'Открыть источник',icon:<ExternalLink size={14}/>,onClick:()=>window.open(p.externalURL||p.sourceURL,'_blank','noopener')}
   :{label:'Добавить в коллекцию',icon:<CloudUpload size={15}/>,onClick:()=>onImport?.(name,section,p)};
  // Telemetry ruler: one mark per episode (or chapter), watched ones lit.
  const volume=passportVolume(section,p,stats),units=Math.min(48,Number(volume.ruler?.units)||Number(p.episodes)||(isVideo?title.items.filter(i=>i.category==='video').length:0)||0);
  const released=volume.ruler?Math.round(units*Math.max(0,Math.min(1,volume.ruler.filled))):units;
  const resumeNumber=continueItem?Number(continueItem.episode??episodeNumber(continueItem))||0:Number(/(\d+)/.exec(onlineResume?.place||'')?.[1])||0;
  const pickEpisode=number=>{
   if(online){dispatchEvent(new CustomEvent('mediavault:title-episode',{detail:{episode:number}}));goTo('watch');return;}
   const item=title.items.find(i=>Number(i.episode??episodeNumber(i))===number);if(item){onPlay(item);setTimeout(()=>goTo('watch'),60);}
  };
  const episodeWord=['manga','ranobe'].includes(section)?['Глава','глав']:['Серия','серий'];
  const scoreItems=[...(ratings?.items||[]).map(item=>({key:item.provider,name:item.name,value:new Intl.NumberFormat(uiLocale(),{maximumFractionDigits:2}).format(item.normalized),rgb:ratingColors[item.provider],url:item.url})),...extraScores.map(s=>({key:s.key||s.name,name:s.name,value:s.value}))].filter(s=>Number(String(s.value).replace(',','.'))>0);
  const heroFacts=passportFacts.filter(([label,value])=>!['Статус','Возраст','Выпуск'].includes(label)&&value).slice(0,3).map(([label,value])=>[label,factValue(label,value)]);
  const nativeName=keyNames.find(n=>/[぀-ヿ一-鿿가-힯]/.test(n)),latinName=keyNames.find(n=>/^[ -~]+$/.test(n));
  const characters=(p.characters||[]).map(c=>({...c,voice:c.voiceActors?.[0]?.name}));
  const watchLabel=['manga','ranobe','book'].includes(section)?'Читать':title.category==='audio'?'Слушать':'Смотреть';
  const episodeItems=(currentPart?.items||[]).map((item,index)=>({id:item.id,source:item,number:item.category==='video'?episodeNumber(item)||index+1:item.episode??index+1,title:item.category==='video'?'Серия '+(episodeNumber(item)||index+1):item.category==='manga'?'Глава '+(item.episode??index+1):item.name,detail:item.category==='manga'?item.episodeTitle||item.dub:voiceLabel(item)}));
  const metadataTools=(!online&&(!p.sourceId||state.admin)||error)&&<section className="title-description title-metadata-tools"><div className="section-heading"><h2>Сведения о тайтле</h2>{(busy||onlineBusy)&&<span className="fine" role="status">{busy==='saving'?'Сохраняем оформление в Drive…':busy==='search'?'Ищем тайтл…':'Загружаем сведения…'}</span>}</div>
    {!online&&!p.sourceId&&<form className="title-match-form" onSubmit={find}><label htmlFor="titleLookup">Найти оформление и русское описание</label><div className="form-actions"><input id="titleLookup" className="field-input" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Название аниме или манги"/><button className="btn btn-secondary btn-small" disabled={!!busy}>Найти</button></div>{candidates.length>1&&<div className="title-match-results" translate="no">{candidates.map(value=><button key={value.sourceId} type="button" onClick={()=>hydrate(value.sourceId)}>{value.title}<small>{value.year||''} · {value.format}</small><ChevronRight size={16}/></button>)}</div>}</form>}
    {error&&<p className="inline-error" role="alert">{error}</p>}{!online&&state.admin&&p.sourceId&&<div className="title-metadata-actions"><button className="text-link" disabled={!!busy} onClick={()=>save()}><CloudUpload size={14}/>{p.savedAt?p.missingArtwork?.length?'Дозагрузить изображения':'Обновить копию в Drive':'Сохранить оформление в Drive'}</button>{p.source!=='wikidata'&&<button className="text-link" disabled={!!busy} onClick={()=>hydrate(p.sourceId)}><RefreshCw size={13}/>Обновить сведения</button>}</div>}
  </section>;
  const watchNode=<>
    {online&&materials&&<section id="titleMaterials" className={'title-stage online-title-materials title-stage-'+section}>{materials}</section>}
    {video&&<section id="titlePlayback" className="title-playback"><button className="title-close-playback circle-button" aria-label="Закрыть просмотр" title="Закрыть просмотр" onClick={onClosePlayer}><X size={17}/></button><Suspense fallback={<div className="lazy-stage" role="status" aria-label="Загружаем…"/>}><MediaViewer reveal characterService={characterService} userId={state.user?.sub} item={video} catalog={state.catalog} libraryId={state.libraryId} onSelectItem={onPlay} onClose={onClosePlayer} readWhole={actions.readWhole} prepareStream={actions.prepareStream} onError={actions.error} onPlaybackChange={setPlaying} renderEpisodeArtwork={(episode,index)=><EpisodeArtwork item={episode} index={index} {...artProps}/>} inline/></Suspense></section>}
    {!online&&title.items.length>0&&<section id={video?undefined:'titleMaterials'} className="title-episodes kt-episodes"><EpisodeCapsules k={k(0)} items={episodeItems} activeId={video?.id} unit={title.category==='manga'?'гл.':title.category==='video'?'сер.':''} label={title.category==='video'?'Серии':title.category==='manga'?'Главы':'Материалы'} onPick={onPlay} parts={parts} part={currentPart?.name||''} onPart={setPart}/></section>}
    {metadataTools}
  </>;
  const chapters=[
    {id:'watch',key:'watch',label:watchLabel,verticalLabel:watchLabel.toUpperCase(),still:true,node:watchNode},
    {id:'characters',label:['movie','tv'].includes(section)?'В ролях':'Персонажи',verticalLabel:['movie','tv'].includes(section)?'В РОЛЯХ':'ПЕРСОНАЖИ',node:<section id="titleCharacters" className="title-characters"><CharactersRow k={k(1)} isNoir={isNoir} characters={characters} onOpen={showCharacter} renderImage={c=>art(c.image,c.name||'',undefined,false)} emptyNote={p.sourceId?'Каталог пока не предоставил персонажей.':'Персонажи появятся вместе со сведениями о тайтле.'}/></section>},
    p.screenshots?.length>0&&{id:'stills',label:section==='ranobe'?'Иллюстрации':'Кадры',verticalLabel:section==='ranobe'?'АРТЫ':'КАДРЫ',node:<section id="titleGallery" className="title-gallery"><StillsMosaic k={k(2)} isNoir={isNoir} images={p.screenshots} caption={({book:'Издание',ranobe:'Иллюстрация'})[section]||'Кадр'} renderArtwork={(url,index)=>art(url,'Кадр '+(index+1))}/></section>},
    section==='anime'&&{id:'schedule',label:'Расписание',verticalLabel:'РАСПИСАНИЕ',node:<ScheduleSection k={k(3)} isNoir={isNoir} identity={String(p.sourceId||title.metadataId||'')} releases={p.releases||NO_RELEASES} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} activeEpisode={resumeNumber} total={p.episodes} onEpisode={units>1?pickEpisode:undefined}/>},
    section==='anime'&&{id:'music',label:'Музыка',verticalLabel:'МУЗЫКА',node:<MusicSection k={k(4)} isNoir={isNoir} identity={p.sourceId||title.metadataId} userId={state.user?.sub} animeTitle={name} cover={p.cover} renderArtwork={url=>art(url,'Обложка аниме')}/>},
    p.trailers?.length>0&&{id:'trailers',label:'Трейлеры',verticalLabel:'ТРЕЙЛЕРЫ',node:<section className="title-trailers"><TrailersSection k={k(5)} isNoir={isNoir} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} profile={p} userId={state.user?.sub} onPlaybackChange={setPlaying} renderArtwork={value=>art(value.image,'')}/></section>},
    p.related?.length>0&&{id:'related',label:'Связи',verticalLabel:'СВЯЗИ',node:<section id="titleRelated" className="title-related"><RelatedRow isNoir={isNoir} related={p.related} onOpen={value=>onRelated({...value,artwork:p.artwork,savedAt:p.savedAt})} renderImage={value=>art(value.cover,value.title)}/></section>},
    section==='anime'&&/^\d+$/.test(String(p.sourceId||''))&&{id:'order',label:'Порядок просмотра',verticalLabel:'ПОРЯДОК',node:<section id="titleWatchOrder"><RouteSection k={k(7)} isNoir={isNoir} renderImage={item=>art(item.cover,item.title)} identity={p.sourceId} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} cached={p.watchOrder} onRelated={onRelated} onLoaded={value=>{setProfile(old=>({...old,watchOrder:value}));if(!online&&state.admin&&state.driveWritable)actions.saveTitleProfile(title.id,{watchOrder:value},[],{background:true});}}/></section>},
    (p.staff?.length||p.characters?.some(c=>c.voiceActors?.length))&&{id:'creators',label:['manga','ranobe','book'].includes(section)?'Авторы':'Создатели',verticalLabel:['manga','ranobe','book'].includes(section)?'АВТОРЫ':'СОЗДАТЕЛИ',node:<section id="titleCredits"><CreatorsSection k={k(8)} isNoir={isNoir} kind={section} profile={p} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} renderArtwork={value=>art(value.image,value.name||'',undefined,false)}/></section>},
  ].filter(Boolean).map((c,i)=>({...c,verticalLabel:(w=>(w[0].length>2?w[0]:w.join(' ')).toUpperCase())(translateUi(c.label).split(' ')),id:chapter(c.id),key:c.id,glowPrimary:CHAPTER_GLOWS[c.id][0],glowSecondary:CHAPTER_GLOWS[c.id][1],node:c.node}));
  return <article data-kind={section} className={'kt-host kt-title-page'+(online?' online-title-page':'')} style={palette?{'--title-rgb':palette.base}:undefined}>
    {/* Marker for the site's :has(.title-page) rules that hide library chrome around a title. */}
    <span className="title-page" style={{display:'none'}} aria-hidden="true"/>
    <TitleNavigation title={title} profile={p}/>
    <KineticTitle sections={chapters} isNoir={isNoir}
      backdrop={<TitleImage url={(p.backgrounds||[])[0]||p.background||p.cover} {...artProps} alt=""/>} nativeName={nativeName}
      poster={art(p.cover,'Обложка: '+name)} posterTop={[p.format||SECTION_LABELS[section],p.year].filter(Boolean).join(' · ')} posterAge={p.rating||p.ageLabel}
      posterKicker={p.studios?.[0]||p.authors?.[0]||p.publishers?.[0]} posterTitle={name}
      sourceLabel={online?'Онлайн':p.savedAt?'Google Диск':'Твоя коллекция'} sourceDetail={online?(voices.length?voices.length+' озвучек':''):title.items.length?title.items.length+' файлов':''}
      kindLabel={({tv:'Сериал',movie:'Фильм',book:'Книга'})[section]||SECTION_LABELS[section]||'Произведение'} seasonLabel={releaseSeason?.label||(p.year?String(p.year):'')} originalName={latinName}
      name={name} score={p.score?Number(p.score).toFixed(section==='book'||['movie','tv'].includes(section)?1:2):''} scoreSource={section==='book'?'Фантлаб':['movie','tv'].includes(section)?'Кинопоиск':'Шикимори'}
      status={p.status&&p.status!=='Не указано'?p.status:''} runtimeLabel={[p.episodes?p.episodes+' эп':'',p.duration?p.duration+' мин':'',p.chapters?p.chapters+' гл.':'',p.volumes?p.volumes+' т.':''].filter(Boolean).join(' · ')}
      genres={p.genres||[]} description={(online?p.description:russianText(p.description))||'Описание пока не предоставлено каталогом.'}
      cta={cta} onTrailers={p.trailers?.length?()=>goTo('trailers'):null} bookmark={{on:isBookmarked,toggle:toggleBookmark}}
      share={<ShareTitleButton {...sharePayload} service={shareService||sharePayload?.service} title={shareTitle} userId={state.user?.sub}/>}
      onDownload={!online&&title.items.length>0&&!downloading?downloadCurrent:null}
      extraActions={<>{heroActions}{section==='manga'&&onLocalFile&&<button className="circle-button" aria-label="Открыть главу с устройства" title="Открыть главу с устройства" onClick={onLocalFile}><FolderOpen size={17}/></button>}{owned&&<button className="circle-button" aria-label="Открыть из своей коллекции" title="Открыть из своей коллекции" onClick={()=>{location.hash=new URLSearchParams({title:owned[0]}).toString();}}><FolderOpen size={17}/></button>}</>}
      episodes={units>1?{total:units,released,current:resumeNumber,word:episodeWord[0],unit:episodeWord[1],onPick:pickEpisode}:null}
      ratings={scoreItems} facts={heroFacts}
      rating={online||state.admin?{value:ownRating,onRate:rate,disabled:ratingBusy||!online&&(!!state.busy||state.importActive)}:null}
      onBack={onBack} backLabel={backLabel} backId={online?undefined:'backToTitles'}/>
    {character&&<Dossier characters={characters} character={character} busy={characterBusy} error={characterError} origin={characterTrigger.current} isNoir={isNoir} workTitle={otherNames.filter(n=>/^[ -~]+$/.test(n)).join(' ')} onPick={value=>showCharacter(value,characterTrigger.current)} onClose={()=>{characterAbort.current?.abort();setCharacter(null);const trigger=characterTrigger.current;if(trigger?.isConnected)trigger.focus({preventScroll:true});}} renderArtwork={value=><TitleImage url={value.image} {...artProps} alt={value.name} fallback={false}/>} onRelated={onRelated}/>}
  </article>;
}
