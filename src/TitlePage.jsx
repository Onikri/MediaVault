import {useEffect,useRef,useState} from 'react';
import {useReducedMotion} from 'motion/react';
import * as Dialog from '@radix-ui/react-dialog';
import {ArrowLeft,Play,Star,ChevronRight,RefreshCw,Cloud,CloudUpload,Users,X,ExternalLink,Film,BookOpen} from 'lucide-react';
import {loadTitleProfile,loadCharacter,searchRussianTitles,russianText,hasRussian} from './title-metadata.js';
import {useArtwork,fetchArtwork} from './title-artwork.js';
import {titleParts,SECTION_LABELS} from './library-model.js';
import {episodeNumber,voiceLabel} from './player-model.js';
import MediaViewer from './MediaViewer.jsx';
import Artwork from './Artwork.jsx';
import WatchOrder from './WatchOrder.jsx';
import {readProgress,progressClock} from './playback-progress.js';
import TitleBackdrop from './TitleBackdrop.jsx';
import CreditsPanel from './CreditsPanel.jsx';
import Soundtrack from './Soundtrack.jsx';
import Trailers from './Trailers.jsx';
import PlatformRatings from './PlatformRatings.jsx';
import TitleNavigation from './TitleNavigation.jsx';
import HoverPreview from './HoverPreview.jsx';
import {readReading} from './reading-progress.js';
import TitleEpisodeCard from './TitleEpisodeCard.jsx';

const day=value=>{try{return value?new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(value)):'';}catch{return '';}};
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
  const url=asset?'drive:'+asset.id:profile?.episodeImages?.[String(item.episode)]||'';
  return <HoverPreview item={item} actions={actions}>{url?<TitleImage url={url} profile={asset?{artwork:{[url]:asset}}:profile} actions={actions} libraryId={libraryId}/>:<div className="episode-preview-pending"><span>{String(item.episode??index+1).padStart(2,'0')}</span><small>{item.category==='manga'?'Обложка главы':'Кадр серии'} появится после синхронизации</small></div>}</HoverPreview>;
}
export default function TitlePage({title,state,actions,onBack,onPlay,onRelated,onImport,selected,onClosePlayer,onMetadataLoaded,online=false,onlineProfile,onlineBusy=false,materials,onlineFacts=[],server,backLabel='Библиотека'}){
  const continuation=(title.category==='manga'?readReading:readProgress)(state.user?.sub,state.libraryId,'collection:'+title.collectionId);
  const continueItem=title.items.find(value=>value.id===continuation?.itemId);
  const saved=online?null:state.catalog?.titleProfiles?.[title.id],hero=useRef(null),reduced=useReducedMotion();
  const [profile,setProfile]=useState(online?onlineProfile:saved||title.profile||null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[candidates,setCandidates]=useState([]),[search,setSearch]=useState(title.name);
  const [character,setCharacter]=useState(null),[characterBusy,setCharacterBusy]=useState(false),[characterError,setCharacterError]=useState('');
  const [palette,setPalette]=useState(null),[playing,setPlaying]=useState(false);
  const [part,setPart]=useState(''),[ratingBusy,setRatingBusy]=useState(false);
  const abort=useRef(null),saveInProgress=useRef(false),live=useRef(state);live.current=state;
  const currentProfile=useRef(profile);currentProfile.current=profile;
  function saveRatings(value){const next={...(currentProfile.current||{}),ratings:value};setProfile(next);if(!online&&live.current.admin&&live.current.driveWritable)actions.saveTitleProfile(title.id,{ratings:value}).catch(()=>{});}
  useEffect(()=>{if(online)setProfile(onlineProfile||{});else if(saved)setProfile(saved);},[saved,online,onlineProfile]);
  useEffect(()=>{
    const controller=new AbortController();abort.current=controller;
    setProfile(online?onlineProfile:saved||title.profile||null);setError('');setCandidates([]);setSearch(title.name);setPart('');setCharacter(null);
    if(online)return()=>controller.abort();
    if(!saved?.sourceId||saved.version<4||(saved.partial||!saved.genres?.length)&&Date.now()>(saved.retryAfter||0)){
      const identity=title.metadataId||title.metadata?.ids?.mal;
      if(identity)hydrate(identity,controller.signal);
    }
    return()=>controller.abort();
  },[title.id,online]);
  async function hydrate(id,signal=abort.current?.signal){
    if(online)return;
    setBusy('loading');setError('');
    try{
      const result=await loadTitleProfile(id,title.section==='manga'?'manga':title.section==='ranobe'?'ranobe':'anime',{signal,server:server||window.MEDIA_VAULT_CONFIG?.importServerUrl,refresh:!!profile?.sourceId});
      signal?.throwIfAborted();setProfile(result);onMetadataLoaded?.(title.id,result);
      if(state.admin&&state.driveWritable)await save(result,signal);
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
  async function showCharacter(value){
    setCharacter(value);setCharacterError('');if(value.description)return;setCharacterBusy(true);
    try{
      const detail=await loadCharacter(value.id,{signal:abort.current?.signal,server:server||window.MEDIA_VAULT_CONFIG?.importServerUrl});setCharacter({...value,...detail});
      const updated={...profile,characters:profile.characters.map(c=>c.id===value.id?{...c,...detail}:c)};setProfile(updated);
      if(!online&&state.admin&&state.driveWritable&&!saveInProgress.current)await actions.saveTitleProfile(title.id,updated);
    }catch(cause){if(!abort.current?.signal.aborted)setCharacterError(cause.message);}finally{setCharacterBusy(false);}
  }
  async function rate(value){
    if(online)return;
    setRatingBusy(true);setError('');
    try{const result=await actions.saveTitleProfile(title.id,{...(profile||{}),userRatings:{...(profile?.userRatings||{}),[state.user.sub]:value}});if(result)setProfile(result);}
    catch(cause){setError(cause.message);}finally{setRatingBusy(false);}
  }
  const p=profile||{},name=p.title&&p.title!=='Название уточняется'?p.title:title.name,parts=titleParts(title),currentPart=parts.find(value=>value.name===part)||parts[0];
  const video=selected&&title.items.some(item=>item.id===selected.id)?selected:null;
  const voices=[...new Set(title.items.filter(i=>i.category==='video').map(i=>voiceLabel(i)))];
  const facts=[['Тип',p.format||SECTION_LABELS[title.section]||'Произведение'],['Тема',p.themes?.join(', ')],['Статус',p.status],['Выпуск',day(p.startDate)+(p.endDate?' — '+day(p.endDate):'')],['Первоисточник',p.origin],['Эпизоды',p.episodes?[p.episodesAired&&p.episodesAired!==p.episodes?p.episodesAired+' из':'',p.episodes].filter(Boolean).join(' '):null],['Длительность',p.duration?p.duration+' мин.':null],['Рейтинг',p.ratingCode],['Возраст',p.rating],['Озвучка',voices.join(', ')],['Режиссёры',p.directors?.join(', ')],['Студия',p.studios?.join(', ')]];
  const ownRating=p.userRatings?.[state.user?.sub]||0;
  const artProps={profile:p,actions,libraryId:state.libraryId};
  return <article className={'title-page'+(online?' online-title-page':'')} style={palette?{'--title-rgb':palette.base,'--accent':palette.accentCSS,'--title-accent':palette.accentCSS}:undefined}>
    <TitleBackdrop profile={p} actions={actions} libraryId={state.libraryId} onPalette={setPalette} suspended={playing}/>
    <button id={online?undefined:'backToTitles'} className="text-link title-page-back" onClick={onBack}><ArrowLeft size={16}/>{backLabel}</button>
    <section className="title-hero" ref={hero}>
      <div className="title-hero-shade"/>
      <div className="title-poster"><TitleImage url={p.cover} {...artProps} alt={'Обложка: '+name}/>{p.rating&&<span>{p.rating}</span>}</div>
      <div className="title-hero-copy"><p className="eyebrow">{[...new Set([SECTION_LABELS[title.section]||'Произведение',p.year,p.format].filter(Boolean))].join(' · ')}</p><h1>{name}</h1><div className="title-hero-status">{p.score&&<span className="title-score"><Star size={15} fill="currentColor"/>{p.score.toFixed(2)}<small>Шикимори</small></span>}{p.status&&<span>{p.status}</span>}<span>{title.items.length?title.items.length+' файлов в коллекции':'В мировом каталоге'}</span></div>
        <div className="title-genre-list">{(p.genres||[]).map(genre=><span key={genre}>{genre}</span>)}</div>
        <dl className="title-hero-facts">{facts.filter(([,value])=>value).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}{p.characters?.length>0&&<div><dt>Главные герои</dt><dd className="hero-character-links">{p.characters.filter(c=>/главн/i.test(c.role)).slice(0,5).map(c=><button key={c.id} onClick={()=>showCharacter(c)}>{c.name}</button>)}</dd></div>}</dl><div className="title-hero-actions">{online?<button className="btn btn-primary" onClick={()=>document.getElementById('titleMaterials')?.scrollIntoView({behavior:reduced?'instant':'smooth',block:'start'})}>{title.category==='video'?<Play size={16}/>:<BookOpen size={16}/>}{title.category==='video'?'Смотреть онлайн':'Читать'}</button>:title.items.length>0?<button className="btn btn-primary" onClick={()=>{onPlay(continueItem||title.items.find(i=>i.category==='video')||title.items[0]);setTimeout(()=>document.getElementById('titlePlayback')?.scrollIntoView({behavior:reduced?'instant':'smooth',block:'center'}),60);}}><Play size={16} fill="currentColor"/>{continueItem?title.category==='manga'?'Продолжить · глава '+(continueItem.episode??'')+' · стр. '+(continuation.page+1):'Продолжить · серия '+(episodeNumber(continueItem)||'')+' · '+progressClock(continuation.time):video?'Продолжить просмотр':title.category==='video'?'Смотреть онлайн':title.category==='audio'?'Слушать':'Читать'}</button>:['game','book'].includes(title.section)?<a className="btn btn-primary" href={p.externalURL||p.sourceURL} target="_blank" rel="noopener noreferrer"><ExternalLink size={16}/>{title.section==='game'?'Открыть страницу игры':'Открыть источник'}</a>:<button className="btn btn-primary" onClick={()=>onImport?.(name,title.section,p)}><CloudUpload size={17}/>Добавить в коллекцию</button>}{!online&&p.savedAt&&<span className="title-saved"><Cloud size={14}/>Из твоего Drive</span>}</div>
      </div>
    </section>
    <TitleNavigation title={title} profile={p}/>
    <div className="title-page-columns"><div className="title-page-main">
      <section id="titleSummary" className="title-description"><div className="section-heading"><h2>О произведении</h2>{(busy||onlineBusy)&&<span className="fine" role="status">{busy==='saving'?'Сохраняем оформление в Drive…':busy==='search'?'Ищем тайтл…':'Загружаем сведения…'}</span>}</div><p>{(online?p.description:russianText(p.description))||'Описание пока не загружено.'}</p>
        {!online&&!p.sourceId&&<form className="title-match-form" onSubmit={find}><label htmlFor="titleLookup">Найти оформление и русское описание</label><div className="form-actions"><input id="titleLookup" className="field-input" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Название аниме или манги"/><button className="btn btn-secondary btn-small" disabled={!!busy}>Найти</button></div>{candidates.length>1&&<div className="title-match-results">{candidates.map(value=><button key={value.sourceId} type="button" onClick={()=>hydrate(value.sourceId)}>{value.title}<small>{value.year||''} · {value.format}</small><ChevronRight size={16}/></button>)}</div>}</form>}
        {error&&<p className="inline-error" role="alert">{error}</p>}{!online&&state.admin&&p.sourceId&&<div className="title-metadata-actions"><button className="text-link" disabled={!!busy} onClick={()=>save()}><CloudUpload size={14}/>{p.savedAt?p.missingArtwork?.length?'Дозагрузить изображения':'Обновить копию в Drive':'Сохранить оформление в Drive'}</button>{p.source!=='wikidata'&&<button className="text-link" disabled={!!busy} onClick={()=>hydrate(p.sourceId)}><RefreshCw size={13}/>Обновить сведения</button>}</div>}
      </section>
      <PlatformRatings identity={p.sourceId} kind={title.section} cached={p.ratings} score={p.score} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} onLoaded={saveRatings}/>
      {online&&materials&&<section id="titleMaterials" className="title-episodes online-title-materials">{materials}</section>}
      {video&&<section id="titlePlayback" className="title-playback"><MediaViewer userId={state.user?.sub} key={video.id} item={video} catalog={state.catalog} libraryId={state.libraryId} onSelectItem={onPlay} onClose={onClosePlayer} readWhole={actions.readWhole} prepareStream={actions.prepareStream} onError={actions.error} onPlaybackChange={setPlaying} renderEpisodeArtwork={(episode,index)=><EpisodeArtwork item={episode} index={index} {...artProps}/>} inline/></section>}
      {!video&&title.items.length>0&&<section id="titleMaterials" className="title-episodes"><div className="section-heading"><h2>{title.category==='video'?'Эпизоды':title.category==='manga'?'Главы':'Материалы'}</h2>{parts.length>1&&<select aria-label="Сезон или том" value={currentPart?.name||''} onChange={event=>setPart(event.target.value)}>{parts.map(value=><option key={value.name}>{value.name}</option>)}</select>}</div><div className="title-episode-grid">{currentPart?.items.map((item,index)=><TitleEpisodeCard key={item.id} number={item.episode??index+1} manga={item.category==='manga'} title={item.category==='video'?'Серия '+(episodeNumber(item)||index+1):item.category==='manga'?'Глава '+(item.episode??index+1):item.name} detail={item.category==='manga'?(item.episodeTitle||item.dub||(item.translationInfo?.language==='en'?'EN → RU · автоперевод':'Русский перевод')):voiceLabel(item)} onClick={()=>onPlay(item)} artwork={<EpisodeArtwork item={item} index={index} {...artProps}/>}/>)}</div></section>}
      {title.section==='anime'&&/^\d+$/.test(String(p.sourceId||''))&&<WatchOrder identity={p.sourceId} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} cached={p.watchOrder} onRelated={onRelated} onLoaded={value=>{const next={...p,watchOrder:value};setProfile(next);if(!online&&state.admin&&state.driveWritable&&!live.current.busy)actions.saveTitleProfile(title.id,{watchOrder:value}).catch(()=>{});}}/>}
      {p.screenshots?.length>0&&<section className="title-stills"><div className="section-heading"><h2>{title.category==='manga'?'Страницы манги':'Кадры из аниме'}</h2><Film size={17}/></div><div className="title-horizontal">{p.screenshots.map((url,index)=><TitleImage key={url} url={url} {...artProps} alt={'Кадр '+(index+1)}/>)}</div></section>}
      <section id="titleCharacters" className="title-characters"><div className="section-heading"><h2>Персонажи</h2><Users size={17}/></div>{p.characters?.length?<div className="title-character-grid">{p.characters.map(value=><button key={value.id} onClick={()=>showCharacter(value)}><TitleImage url={value.image} {...artProps} alt=""/><span><strong>{value.name}</strong><small>{value.role}</small></span></button>)}</div>:<p className="title-empty-note">{p.sourceId?'Каталог пока не предоставил персонажей.':'Персонажи появятся вместе со сведениями о тайтле.'}</p>}</section>
      {title.section==='anime'&&<Soundtrack identity={p.sourceId||title.metadataId} userId={state.user?.sub} animeTitle={name}/>}
      <Trailers profile={p} userId={state.user?.sub} libraryId={state.libraryId} onPlaybackChange={setPlaying} renderArtwork={value=><TitleImage url={value.image} {...artProps} alt=""/>}/>
      <CreditsPanel kind={title.section} profile={p} server={server||window.MEDIA_VAULT_CONFIG?.importServerUrl} renderArtwork={value=><TitleImage url={value.image} {...artProps} alt=""/>}/>
      {p.related?.length>0&&<section id="titleRelated" className="title-related"><div className="section-heading"><h2>В этой вселенной</h2><span className="fine">Сезоны · Фильмы · Манга · Книги · Игры</span></div><div className="title-horizontal">{p.related.map(value=><button key={value.kind+value.id} onClick={()=>onRelated({...value,artwork:p.artwork,savedAt:p.savedAt})}><span className="related-poster"><TitleImage url={value.cover} {...artProps} alt={value.title}/><small>{value.format}</small></span><strong>{value.title}</strong><small>{value.relation}</small></button>)}</div></section>}
      <section className="title-discussion"><div><h2>Обсуждение и обзоры</h2><p>Отзывы читателей и зрителей — на странице произведения.</p></div>{p.sourceURL&&<a className="text-link" href={p.sourceURL} target="_blank" rel="noopener noreferrer">{p.source==='wikidata'?'Открыть источник':'Читать на Шикимори'}<ExternalLink size={14}/></a>}</section>
    </div><aside className="title-facts"><h2>{online?'О произведении':'В твоей коллекции'}</h2><dl>{online?onlineFacts.filter(([,value])=>value).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>):<><div><dt>Сохранено</dt><dd>{title.items.length} файлов</dd></div>{voices.length>0&&<div><dt>Озвучки</dt><dd>{voices.join(', ')}</dd></div>}</>}</dl>{p.themes?.length>0&&<><h3>Темы</h3><div className="title-genre-list">{p.themes.map(value=><span key={value}>{value}</span>)}</div></>}
      {!online&&state.admin&&<div className="title-rating"><h3>Твоя оценка</h3><p>{ownRating?ownRating+' из 10':'Как тебе эта история?'}</p><div role="group" aria-label="Оценить произведение">{Array.from({length:10},(_,index)=><button key={index} aria-label={'Оценка '+(index+1)} aria-pressed={ownRating===index+1} disabled={ratingBusy||!!state.busy||state.importActive} onClick={()=>rate(index+1)}>{index+1}</button>)}</div><small>Сохраняется в зашифрованном каталоге.</small></div>}
    </aside></div>
    <Dialog.Root open={!!character} onOpenChange={open=>{if(!open)setCharacter(null);}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog character-dialog"><Dialog.Close className="icon-button dialog-close" aria-label="Закрыть персонажа"><X size={18}/></Dialog.Close><Dialog.Title>{character?.name}</Dialog.Title><Dialog.Description className="sr-only">Описание персонажа на русском языке</Dialog.Description>{character&&<><TitleImage url={character.image} {...artProps} alt={character.name}/>{character.actors?.length>0&&<p className="character-actors">Сэйю: {character.actors.join(', ')}</p>}<p>{characterBusy?'Загружаем описание…':character.description||'Русское описание пока отсутствует в источнике.'}</p>{characterError&&<p className="inline-error" role="alert">{characterError}</p>}</>}</Dialog.Content></Dialog.Portal></Dialog.Root>
  </article>;
}
