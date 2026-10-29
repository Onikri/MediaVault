import React,{useCallback,useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import ServerImport from './ServerImport.jsx';
import {useImportService} from './import-service.js';
import useLibraryProfiles from './use-library-profiles.js';
import DeviceSettings,{CookieNotice} from './PrivacySettings.jsx';
import * as Dialog from '@radix-ui/react-dialog';
import LibrarySetup from './LibrarySetup.jsx';
import TitleBrowser from './TitleBrowser.jsx';
import {TitleImage} from './TitlePage.jsx';
import {clearArtworkCache} from './title-artwork.js';
import {voiceLabel} from './player-model.js';
import {buildTitles} from './library-model.js';
import './title-page.css';
import {SECTION_LABELS,sectionForItem} from './library-model.js';
import {useVault,formatSize,labels} from './vault.js';
import Icon,{BrandMark} from './Icons.jsx';
import Artwork from './Artwork.jsx';
import {MusicShelf} from './Soundtrack.jsx';
import MediaViewer from './MediaViewer.jsx';
import MiniMusicPlayer from './MiniMusicPlayer.jsx';
import {playMusic} from './music-player.js';
import OnlineLibrary from './OnlineLibrary.jsx';
import {ImportSettings} from './ImportParts.jsx';
import MusicConnections from './MusicConnections.jsx';
import './world-library.css';

const sections=[{id:'anime',art:'video',name:'Аниме',formats:'ТАЙТЛЫ · СЕЗОНЫ · СЕРИИ',icon:'video'},
  {id:'manga',art:'manga',name:'Манга',formats:'ТАЙТЛЫ · ТОМА · ГЛАВЫ',icon:'manga'},
  {id:'ranobe',art:'book',name:'Ранобэ',formats:'ТАЙТЛЫ · ТОМА',icon:'book'},
  {id:'book',art:'book',name:'Книги',formats:'АВТОРЫ · КНИГИ',icon:'book'},
  {id:'music',art:'audio',name:'Музыка',formats:'АЛЬБОМЫ · ТРЕКИ',icon:'audio'}];
const navigation=[{id:'home',label:'Главная',icon:'home'},{id:'library',label:'Библиотека',icon:'library'},{id:'collection',label:'Моя коллекция',icon:'cloud'},
  {id:'history',label:'История',icon:'history'},{id:'profile',label:'Профиль',icon:'user'}];
const filters=[{id:'all',label:'Всё'},...Object.entries(SECTION_LABELS).map(([id,label])=>({id,label}))];
const guide='https://github.com/Onikri/MediaVault/blob/main/README.md';
function readLocal(key,fallback){try{return JSON.parse(localStorage.getItem(key))||fallback;}catch{return fallback;}}
function writeLocal(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{}}
function plural(n){return n%10===1&&n%100!==11?'материал':n%10>=2&&n%10<=4&&(n%100<12||n%100>14)?'материала':'материалов';}

function relatedPage(value,catalog){
  const externalId=value.ids?.mal||value.id;
  const existing=buildTitles(catalog).find(t=>String(t.profile?.sourceId||t.metadataId)===String(externalId)&&t.section===value.kind);
  return existing||{id:'remote:'+value.kind+':'+value.id,name:value.title,section:value.kind,category:value.kind==='anime'?'video':value.kind==='manga'?'manga':'book',items:[],parts:[],metadataId:value.ids?.mal||(value.provider==='wikidata'?null:value.id),
    profile:{...value,source:value.provider==='wikidata'&&!value.ids?.mal?'wikidata':'shikimori',sourceId:externalId,sourceURL:value.sourceURL||'https://shikimori.one/'+(['manga','ranobe'].includes(value.kind)?'mangas':'animes')+'/'+value.id,cover:value.cover,language:'ru',characters:[],related:[],screenshots:[]},external:true};
}
function routedTitle(catalog,id){
  const existing=buildTitles(catalog).find(t=>t.id===id);if(existing)return existing;
  const [prefix,kind,identity]=String(id||'').split(':');if(prefix!=='remote')return null;
  for(const profile of Object.values(catalog?.titleProfiles||{})){
    const value=profile.related?.find(r=>r.kind===kind&&String(r.id)===identity);
    if(value)return relatedPage({...value,artwork:profile.artwork,savedAt:profile.savedAt},catalog);
  }
  return null;
}

function MediaCard({item,saved,onSave,onOpen,readWhole,vaultKey,displayName,detail,hideSave=false,profile,actions,libraryId}){
  const [cover,setCover]=useState('');
  const reduced=useReducedMotion();
  const card=useRef(null);
  const preview=item.previewArtwork,previewURL=preview?'drive:'+preview.id:'';
  const posterURL=hideSave?profile?.cover||previewURL:previewURL||profile?.cover;
  const artworkProfile=preview?{...profile,artwork:{...profile?.artwork,[previewURL]:preview}}:profile;
  useEffect(()=>{
    if(posterURL||!vaultKey||!['image','manga'].includes(item.category)||item.size>20*1024*1024)return;
    let url='',closed=false;const abort=new AbortController();
    const observer=new IntersectionObserver(entries=>{
      if(!entries.some(entry=>entry.isIntersecting))return;
      observer.disconnect();
      (async()=>{
        let blob=await readWhole(item,{silent:true,signal:abort.signal});
        if(item.category==='manga'){
          const {default:JSZip}=await import('jszip');
          const zip=await JSZip.loadAsync(blob);
          const page=Object.values(zip.files).filter(entry=>!entry.dir&&/\.(jpe?g|png|webp|gif)$/i.test(entry.name)).sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}))[0];
          if(!page)return;blob=await page.async('blob');
        }
        if(closed)return;url=URL.createObjectURL(blob);setCover(url);
      })().catch(()=>{});
    },{rootMargin:'180px'});
    if(card.current)observer.observe(card.current);
    return()=>{closed=true;abort.abort();observer.disconnect();if(url)URL.revokeObjectURL(url);};
  },[item.id,vaultKey,readWhole,posterURL]);
  return <motion.article ref={card} className={'media-card'+(hideSave?' title-card':'')} data-title-name={hideSave?displayName:undefined} whileHover={reduced?undefined:{y:-3}} whileTap={reduced?undefined:{scale:.985}} layout>
    <button className="media-open" onClick={()=>onOpen(item)} aria-label={'Открыть '+(displayName||item.name)}>
      <div className="media-cover">{posterURL?<TitleImage url={posterURL} profile={artworkProfile} actions={actions} libraryId={libraryId}/>:cover?<img src={cover} alt="" loading="lazy"/>:<Artwork kind={item.category}/>}
        <span className="media-category">{hideSave?SECTION_LABELS[sectionForItem(item)]:labels[item.category]}</span>
        <span className="media-open-indicator"><Icon name={item.category==='video'?'video':item.category==='audio'?'audio':'book'} size={24}/></span>
      </div>
      <h3 className="media-name">{displayName||item.name}</h3><p className="media-meta">{detail||formatSize(item.size)}</p>
    </button>
    {!hideSave&&<button className={'bookmark-button'+(saved?' is-saved':'')} onClick={()=>onSave(item.id)} aria-label={saved?'Убрать из избранного':'В избранное'} aria-pressed={saved}><Icon name="bookmark" size={18}/></button>}
  </motion.article>;
}

function EmptyState({icon='library',title,text,button,onClick}){
  return <div className="empty-state"><div className="empty-illustration"><Icon name={icon} size={42}/><span/><span/></div><h2>{title}</h2><p>{text}</p>{button&&<button className="btn btn-primary" onClick={onClick}>{button}<Icon name="arrow" size={18}/></button>}</div>;
}

export default function App(){
  const {state,actions}=useVault();
  const importService=useImportService(state,actions);
  useLibraryProfiles(state,actions,importService.server,importService.active);
  const reduced=useReducedMotion();
  const [view,setView]=useState(()=>new URLSearchParams(location.hash.slice(1)).has('title')?'collection':['home','library','collection','import','history','profile'].includes(location.hash.slice(1))?location.hash.slice(1):'home');
  const [libraryDialog,setLibraryDialog]=useState(false),[libraryIntent,setLibraryIntent]=useState('online');
  const [importTarget,setImportTarget]=useState(null);
  const [importQuery,setImportQuery]=useState(''),[importKind,setImportKind]=useState('anime');
  const [category,setCategory]=useState('all');
  const [query,setQuery]=useState('');
  const [sort,setSort]=useState('newest');
  const [favoritesOnly,setFavoritesOnly]=useState(false);
  const [favorites,setFavorites]=useState([]);
  const [history,setHistory]=useState([]);
  const [selected,setSelected]=useState(null);
  const [activeTitle,setActiveTitle]=useState(null);
  const [genre,setGenre]=useState(''),[year,setYear]=useState(''),[voice,setVoice]=useState('');
  const [libraryId,setLibraryId]=useState(state.libraryId);
  const [passphrase,setPassphrase]=useState('');
  const [again,setAgain]=useState('');
  const [inviteEmail,setInviteEmail]=useState('');
  const [inviteOpen,setInviteOpen]=useState(false);
  const [uploadCollection,setUploadCollection]=useState('');
  const [uploadSection,setUploadSection]=useState('auto'),[uploadPart,setUploadPart]=useState('');
  const search=useRef(null),fileInput=useRef(null),libraryOpener=useRef(null),vaultRef=useRef(state);vaultRef.current=state;
  const pendingRoute=useRef(/(?:^#|&)(?:episode|title)=/.test(location.hash)?location.hash:'');
  const localPrefix='mediavault_ui_'+(state.libraryId||'none');
  const items=state.catalog?.items||[];
  const busy=!!state.busy;
  const onlineAccess=libraryIntent==='online';
  useEffect(()=>{if(libraryDialog&&onlineAccess&&state.admin&&importService.status==='connected')setLibraryDialog(false);},[libraryDialog,onlineAccess,state.admin,importService.status]);
  useEffect(()=>{setLibraryId(state.libraryId);setFavorites(readLocal(localPrefix+'_saved',[]));setHistory(readLocal(localPrefix+'_history',[]));},[state.libraryId]);
  useLayoutEffect(()=>{if(!state.catalog){setSelected(null);setActiveTitle(null);}clearArtworkCache(state.catalog?state.libraryId+':'+state.user?.sub:'');},[!!state.catalog,state.libraryId,state.user?.sub]);
  function titleLocation(value,replace=false){
    const hash=value?'#'+new URLSearchParams({title:value.id}):'#collection';
    if(location.hash!==hash)window.history[replace?'replaceState':'pushState'](null,'',location.pathname+location.search+hash);
  }
  function restoreRoute(hash){
    const catalog=vaultRef.current.catalog;if(!catalog)return false;
    const params=new URLSearchParams(hash.slice(1)),episodeId=params.get('episode');
    if(episodeId){
      const item=catalog.items.find(i=>i.id===episodeId&&i.category==='video');if(!item)return false;
      const title=buildTitles(catalog).find(t=>t.items.some(i=>i.id===item.id)),point=Number(params.get('t'));
      if(Number.isFinite(point)&&point>=0)sessionStorage.setItem('mediavault_pending_time_'+item.id,String(point));
      setView('collection');setSelected(item);setActiveTitle(title);titleLocation(title,true);return true;
    }
    const title=routedTitle(catalog,params.get('title'));
    if(title){setView('collection');setSelected(current=>title.items.some(item=>item.id===current?.id)?current:null);setActiveTitle(title);titleLocation(title,true);return true;}return false;
  }
  useEffect(()=>{window.scrollTo({top:0,behavior:'instant'});},[view]);
  useEffect(()=>{
    const change=()=>{if(restoreRoute(location.hash))return;const next=location.hash.slice(1);if(['home','library','collection','import','history','profile'].includes(next)){setView(next);setActiveTitle(null);setSelected(null);}};
    window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);
  },[]);
  useEffect(()=>{
    if(!state.catalog)return;
    const resume=pendingRoute.current;
    if(resume){pendingRoute.current='';if(!restoreRoute(resume))go('collection');}
    else if(state.remembered&&['home','profile'].includes(view))go('collection');
  },[!!state.catalog,state.libraryId]);
  const go=useCallback(next=>{setView(next);setActiveTitle(null);if(location.hash!=='#'+next)location.hash=next;},[]);
  const closeViewer=useCallback(()=>setSelected(null),[]);
  function selectCategory(id){setCategory(id);setFavoritesOnly(false);setQuery('');go('library');}
  function save(id){const next=favorites.includes(id)?favorites.filter(value=>value!==id):[...favorites,id];setFavorites(next);writeLocal(localPrefix+'_saved',next);}
  function open(item){
    if(item.category==='video'){const title=buildTitles(state.catalog).find(t=>t.items.some(v=>v.id===item.id));setView('collection');setActiveTitle(title);titleLocation(title);}
    if(item.category==='audio'){setSelected(null);const queue=items.filter(i=>i.category==='audio'&&i.collectionId===item.collectionId).map(i=>({id:i.id,title:i.name.replace(/\.[^.]+$/,''),source:'library',item:i,artists:i.artists||[]}));const track=queue.find(t=>t.id===item.id);if(track)playMusic(track,queue);}else setSelected(item);
    const next=[{id:item.id,at:Date.now()},...history.filter(entry=>entry.id!==item.id)].slice(0,60);
    setHistory(next);writeLocal(localPrefix+'_history',next);
  }
  function showLibrarySetup(intent){libraryOpener.current=document.activeElement;setLibraryIntent(typeof intent==='string'?intent:view==='collection'?'drive':'online');setLibraryDialog(true);}
  async function openLibrary(create=false,stay=false){
    const resume=pendingRoute.current;
    const ok=create?await actions.createLibrary(passphrase,again):await actions.unlock(libraryId,passphrase);
    if(ok){setPassphrase('');setAgain('');setCategory('all');if(stay)setLibraryDialog(false);else if(resume)setView('collection');else go('collection');}
  }
  async function connect(){const ok=await actions.connectDrive();if(ok&&state.catalog)go('collection');}
  async function upload(event){const files=Array.from(event.target.files||[]);event.target.value='';if(importService.active){actions.error(Error("Дождись завершения серверного импорта перед добавлением файлов."));return;}if(files.length&&await actions.refreshCatalog())actions.uploadFiles(files,{collection:uploadCollection,section:uploadSection==='auto'?(category==='all'?undefined:category):uploadSection,part:uploadPart});}
  async function sendInvite(){if(await actions.invite(inviteEmail))setInviteEmail('');}
  function find(){go('library');setTimeout(()=>document.getElementById('catalogSearch')?.focus(),100);}
  const allTitles=useMemo(()=>buildTitles(state.catalog),[state.catalog]);
  const itemProfile=item=>allTitles.find(t=>t.items.some(v=>v.id===item.id))?.profile;
  const genres=[...new Set(allTitles.flatMap(t=>t.profile?.genres||[]))].sort((a,b)=>a.localeCompare(b,'ru'));
  const years=[...new Set(allTitles.map(t=>t.profile?.year).filter(Boolean))].sort((a,b)=>b-a);
  const voices=[...new Set(items.filter(i=>i.category==='video').map(i=>voiceLabel(i)))];
  const filtered=useMemo(()=>items.filter(item=>(category==='all'||sectionForItem(item)===category)&&(!genre||(itemProfile(item)?.genres||[]).includes(genre))&&(!year||String(itemProfile(item)?.year)===year)&&(!voice||voiceLabel(item)===voice)&&(!favoritesOnly||favorites.includes(item.id))&&[item.name,state.catalog?.storage?.collections?.find(group=>group.id===item.collectionId)?.name,itemProfile(item)?.title,...(itemProfile(item)?.aliases||[]),...Object.values(state.catalog?.storage?.collections?.find(group=>group.id===item.collectionId)?.metadata?.titles||{})].join(' ').toLocaleLowerCase().includes(query.toLocaleLowerCase())).sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'ru'):(new Date(b.addedAt)-new Date(a.addedAt))),[state.catalog,category,query,favoritesOnly,favorites,sort,genre,year,voice]);
  const recent=history.map(entry=>({entry,item:items.find(item=>item.id===entry.id)})).filter(record=>record.item);
  const totalSize=items.reduce((sum,item)=>sum+item.size,0);
  const card=item=><MediaCard key={item.id} item={item} saved={favorites.includes(item.id)} onSave={save} onOpen={open} readWhole={actions.readWhole} vaultKey={state.key} profile={itemProfile(item)} actions={actions} libraryId={state.libraryId}/>;
  const titleCard=(title,onOpen)=>{const cover=title.items.find(item=>item.category==='image')||title.items[0];return <MediaCard key={title.id} item={cover} displayName={title.profile?.title||title.name} detail={title.items.length+' '+plural(title.items.length)+' · '+formatSize(title.size)} hideSave onOpen={onOpen} readWhole={actions.readWhole} vaultKey={state.key} profile={title.profile} actions={actions} libraryId={state.libraryId}/>;};

  return <div className="app-shell">
    <header className="app-header"><div className="header-inner">
      <button className="brand" onClick={()=>go('home')} aria-label="MediaVault — главная"><BrandMark/><span className="brand-text">Media<span>Vault</span><small className="brand-kicker">Твои истории рядом</small></span></button>
      <nav className="desktop-nav" aria-label="Основная навигация">{navigation.slice(0,4).map(item=><button key={item.id} className={view===item.id?'nav-active':''} onClick={()=>go(item.id)}>{item.label}</button>)}</nav>
      <div className="header-actions"><button className="icon-button" onClick={find} aria-label="Найти в библиотеке"><Icon name="search"/></button><ImportSettings compact service={importService} state={state} onConnect={showLibrarySetup}/><MiniMusicPlayer service={importService} placement="nav" userId={state.user?.sub} prepareStream={actions.prepareStream} readWhole={actions.readWhole} resolveItem={id=>state.catalog?.items.find(i=>i.id===id)}/><button id="profileBtn" className={'avatar-button'+(view==='profile'?' nav-active':'')} onClick={()=>go('profile')} aria-label="Открыть профиль">{state.user?<span>{(state.user.given_name||state.user.email).slice(0,1).toUpperCase()}</span>:<Icon name="user" size={21}/>}<i className={'online-dot'+(state.driveConnected?' connected':'')}/></button></div>
    </div></header>
    <motion.main key={view} className="app-main" initial={reduced?false:{opacity:0,y:7}} animate={{opacity:1,y:0}} transition={{duration:.18}}>
      {view==='home'&&<>
        <div className="page-title-row"><div><p className="eyebrow">Личная коллекция</p><h1 className="page-title">Твоё пространство</h1></div><span className="status-pill"><Icon name="lock" size={13}/> Только для своих</span></div>
        <section className="spotlight"><div className="spotlight-copy"><span className="spotlight-label"><i/> ВСЁ, ЧТО ТЫ ЛЮБИШЬ</span><h2 className="spotlight-title">Ещё одна глава.<br/><em>Ещё один мир.</em></h2><p className="spotlight-desc">Аниме, манга, ранобэ и музыка.<br/>Твоя коллекция — всегда под рукой.</p><div className="spotlight-actions"><button className="btn btn-primary" onClick={()=>go('library')}>Открыть библиотеку<Icon name="arrow" size={18}/></button><span className="spotlight-note"><Icon name="lock" size={13}/> Личное остаётся личным</span></div></div><Artwork hero className="spotlight-art"/></section>
        {state.catalog&&recent.length>0&&<section><div className="section-heading"><h2 className="section-title">Недавно открытое</h2><button className="text-link" onClick={()=>go('history')}>Вся история<Icon name="chevron" size={15}/></button></div><div className="media-grid home-recent">{recent.slice(0,6).map(({item})=>card(item))}</div></section>}
        <button className="server-import-banner" onClick={()=>go('library')}><span className="banner-icon"><Icon name="cloud" size={25}/></span><span><strong>Весь сезон — в твоём Drive</strong><small>Автоматическое скачивание и шифрование на сервере</small></span><Icon name="arrow" size={20}/></button>
        <section><div className="section-heading"><div><h2 className="section-title">Что будем открывать?</h2><p className="page-subtitle">У каждой истории — свой формат</p></div></div><div className="category-grid">{sections.map(section=><button key={section.id} className={'category-card category-'+section.id} onClick={()=>selectCategory(section.id)}><div className="category-art"><Artwork kind={section.art}/></div><div className="category-meta"><span className="category-icon"><Icon name={section.icon} size={18}/></span><strong>{section.name}</strong><small>{section.formats}</small></div><Icon className="category-arrow" name="chevron" size={18}/></button>)}</div></section>
        {state.catalog&&items.length>0&&<section><div className="section-heading"><h2 className="section-title">Новое в коллекции</h2><button className="text-link" onClick={()=>{setCategory('all');go('collection');}}>Смотреть всё<Icon name="chevron" size={15}/></button></div><div className="media-grid">{items.slice().reverse().slice(0,6).map(card)}</div></section>}
        <div className="benefit-grid"><div className="benefit-card"><span><Icon name="lock" size={22}/></span><div><h3>Только твой круг</h3><p>Коллекция доступна тебе и тем, кого ты пригласишь.</p></div></div><div className="benefit-card"><span><Icon name="cloud" size={22}/></span><div><h3>Всё на своём месте</h3><p>Личные файлы в твоём Google Drive. Чтение и просмотр — здесь.</p></div></div></div>
        <footer className="app-footer"><BrandMark/><span>MediaVault<span>Место для любимых историй</span></span><span className="footer-version">Твоя личная медиатека</span></footer>
      </>}

      {view==='import'&&<ServerImport state={state} service={importService} initialItem={importTarget} initialQuery={importQuery} initialKind={importKind} onOpenLibrary={showLibrarySetup} onConnect={showLibrarySetup}/>}

      {['library','collection'].includes(view)&&<>
        <div className="page-title-row"><div><p className="eyebrow">Всё любимое — здесь</p><h1 className="page-title">{view==='library'?'Библиотека':'Моя коллекция'}</h1><p className="page-subtitle">{view==='library'?'Истории со всего мира. Открывай онлайн, сохраняй для себя.':<><span id="count">{items.length} файлов</span>{items.length>0?' · '+formatSize(totalSize):''}</>}</p></div><Icon name="library" size={29}/></div>
        {view==='library'?<OnlineLibrary state={state} service={importService} category={category} onCategory={setCategory} onOpenLibrary={showLibrarySetup}/>:<>
        {category==='music'&&<MusicShelf userId={state.user?.sub}/>}<div className="search-bar"><Icon name="search" size={20}/><input id="searchInput" ref={search} className="search-input" value={query} onChange={event=>{setQuery(event.target.value);setActiveTitle(null);setSelected(null);}} placeholder="Найти свою следующую историю" aria-label="Поиск в библиотеке"/>{query&&<button className="search-clear icon-button" onClick={()=>setQuery('')} aria-label="Очистить поиск"><Icon name="close" size={17}/></button>}</div>
        <div className="chip-row" aria-label="Разделы библиотеки">{filters.map(filter=><button key={filter.id} className={'chip'+(category===filter.id&&!favoritesOnly?' chip-active':'')} onClick={()=>{setCategory(filter.id);setFavoritesOnly(false);}}>{filter.label}</button>)}<button className={'chip'+(favoritesOnly?' chip-active':'')} onClick={()=>{setFavoritesOnly(!favoritesOnly);setCategory('all');}}><Icon name="bookmark" size={14}/> Избранное</button></div>
        {state.admin&&state.catalog&&<section id="adminPanel" className="admin-bar"><div className="admin-actions"><button className="btn btn-primary btn-small" disabled={busy} onClick={()=>fileInput.current?.click()}><Icon name="plus" size={18}/>Добавить файлы</button><button className="btn btn-secondary btn-small" onClick={()=>setInviteOpen(!inviteOpen)}><Icon name="share" size={17}/>Пригласить</button><button className="btn btn-secondary btn-small" onClick={()=>go('library')}><Icon name="cloud" size={17}/>Найти в библиотеке</button><button className="btn btn-secondary btn-small" disabled={busy} onClick={()=>document.getElementById('foldersInput')?.click()}><Icon name="library" size={17}/>Папка</button><button className="btn btn-secondary btn-small" disabled={busy||!importService.session?.driveConnected} onClick={()=>importService.enrichLibrary().then(()=>actions.notify("Кадры и сведения обновляются на сервере. Прогресс — во вкладке «Загрузки»." )).catch(actions.error)}><Icon name="refresh" size={16}/>Синхронизировать оформление</button><button className="icon-button" aria-label="Обновить библиотеку" disabled={busy} onClick={actions.refreshCatalog}><Icon name="refresh" size={18}/></button><input id="foldersInput" type="file" webkitdirectory="" directory="" multiple hidden onChange={upload}/><input ref={fileInput} id="filesInput" type="file" multiple hidden onChange={upload}/></div><details className="upload-options"><summary>Куда добавить файлы: раздел, тайтл и сезон</summary><div className="local-upload-settings"><div className="import-field-grid"><div className="form-field"><label className="input-label" htmlFor="uploadSection">Раздел</label><select id="uploadSection" className="field-input" value={uploadSection} onChange={event=>setUploadSection(event.target.value)}><option value="auto">По папке или формату</option>{Object.entries(SECTION_LABELS).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></div><div className="form-field"><label className="input-label" htmlFor="uploadCollection">Название тайтла / альбома</label><input id="uploadCollection" className="field-input" value={uploadCollection} onChange={event=>setUploadCollection(event.target.value)} placeholder="Например, Наруто — без номера сезона"/></div></div><label className="input-label" htmlFor="uploadPart">Сезон, том или часть</label><input id="uploadPart" className="field-input" value={uploadPart} onChange={event=>setUploadPart(event.target.value)} placeholder="Необязательно: Сезон 1, Том 2…"/><span className="fine">При выборе папки структура определяется автоматически. Ранобэ можно выбрать отдельно от книг. Все файлы одного тайтла попадут в его папку.</span></div></details>{inviteOpen&&<div className="invite-panel"><label className="input-label" htmlFor="inviteEmail">Открой коллекцию своим</label><div className="form-actions"><input id="inviteEmail" className="field-input" type="email" placeholder="Email друга" value={inviteEmail} onChange={event=>setInviteEmail(event.target.value)}/><button id="inviteBtn" className="btn btn-primary btn-small" disabled={busy} onClick={sendInvite}>Пригласить</button></div><button id="copyLinkBtn" className="text-link" onClick={actions.copyInvite}>Скопировать ссылку на библиотеку<Icon name="arrow" size={15}/></button><p className="fine">Секретную фразу передай отдельно.</p></div>}<div id="uploadQueue" className="upload-panel">{state.uploadProgress.map(progress=><div className="upload-row" key={progress.id}><div><span>{progress.status==='done'?'✓ ':progress.status==='error'?'✕ ':''}{progress.name}</span><small>{progress.status==='error'?progress.error:progress.status==='done'?'В библиотеке':({preparing:'Подготовка',encrypting:'Шифрование',uploading:'Загрузка',saving:'Сохранение каталога'}[progress.phase]||'Загрузка')+' · '+Math.min(100,Math.round(progress.loaded/(progress.total||1)*100))+'%'}</small></div><div className="progress-track"><div className="progress-fill" style={{width:(progress.loaded/(progress.total||1)*100)+'%'}}/></div></div>)}</div></section>}
        <div className={'library-workspace'+(activeTitle?' title-is-open':'')}>
        {!activeTitle&&<aside className="library-sidebar"><p className="eyebrow">Твоя библиотека</p><nav aria-label="Разделы коллекции">{filters.map(f=><button aria-label={'Раздел '+f.label} key={f.id} className={category===f.id?'is-active':''} onClick={()=>{setCategory(f.id);setFavoritesOnly(false);}}><Icon name={f.id==='all'?'library':f.id==='music'?'audio':f.id==='anime'?'video':f.id==='ranobe'?'book':f.id} size={17}/>{f.label}<small>{f.id==='all'?allTitles.length:allTitles.filter(t=>t.section===f.id).length}</small></button>)}<button aria-label="Раздел Избранное" className={favoritesOnly?'is-active':''} onClick={()=>{setFavoritesOnly(!favoritesOnly);setCategory('all');}}><Icon name="bookmark" size={17}/>Избранное</button></nav><div className="library-sidebar-filters"><h3><Icon name="filter" size={15}/>Фильтры</h3><label>Жанр<select aria-label="Фильтр по жанру" value={genre} onChange={e=>setGenre(e.target.value)}><option value="">Все жанры</option>{genres.map(value=><option key={value}>{value}</option>)}</select></label><label>Год<select aria-label="Фильтр по году" value={year} onChange={e=>setYear(e.target.value)}><option value="">Любой год</option>{years.map(value=><option key={value}>{value}</option>)}</select></label><label>Озвучка<select aria-label="Фильтр по озвучке" value={voice} onChange={e=>setVoice(e.target.value)}><option value="">Все озвучки</option>{voices.map(value=><option key={value}>{value}</option>)}</select></label>{(genre||year||voice)&&<button className="text-link" onClick={()=>{setGenre('');setYear('');setVoice('');}}>Сбросить фильтры</button>}</div><div className="library-drive-note"><Icon name="lock" size={17}/><div><strong>Личное остаётся личным</strong><p>{formatSize(totalSize)} в твоём Drive</p></div></div></aside>}
        <div className="library-workspace-main"><div className="library-toolbar"><span>{favoritesOnly?'Избранное':category==='all'?'Все тайтлы':SECTION_LABELS[category]} <small>{filtered.length?filtered.length+' '+plural(filtered.length):''}</small></span><label className="sort-label"><span className="sr-only">Порядок материалов</span><select value={sort} onChange={event=>setSort(event.target.value)}><option value="newest">Сначала новые</option><option value="name">По названию</option></select></label></div>
        <TitleBrowser catalog={state.catalog} items={filtered} sort={sort} renderFile={card} renderTitle={titleCard} state={{...state,importActive:importService.active}} actions={actions} selected={activeTitle} onSelectTitle={value=>{setActiveTitle(value);titleLocation(value);window.scrollTo({top:0,behavior:'instant'});}} onPlay={open} selectedVideo={selected?.category==='video'?selected:null} onClosePlayer={closeViewer} onImport={(name,kind,p)=>{setImportTarget(p?.sourceId?{...p,id:'shikimori:'+kind+':'+p.sourceId,provider:'shikimori',providers:['shikimori'],providerId:p.sourceId,kind:['anime','manga','ranobe','movie','tv'].includes(kind)?kind:'anime',ids:{mal:p.sourceId},titles:{ru:name},aliases:p.aliases||[],genres:p.genres||[],tags:p.themes||[],links:[],releases:[]}:null);setImportQuery(name);setImportKind(['anime','manga','ranobe','movie','tv'].includes(kind)?kind:'anime');go('import');}} onRelated={value=>{const page=relatedPage(value,state.catalog);setSelected(null);setActiveTitle(page);titleLocation(page);window.scrollTo({top:0,behavior:'smooth'});}}/>
        {!state.catalog?<EmptyState icon="lock" title="Твоя коллекция ждёт" text="Войди через Google и открой личную библиотеку. Здесь будут твои манга, фильмы, книги и музыка." button="Подключить библиотеку" onClick={()=>go('profile')}/>:filtered.length===0?<EmptyState icon={query?'search':favoritesOnly?'bookmark':'book'} title={query?'Ничего не нашлось':favoritesOnly?'Сохрани самое любимое':'У каждой коллекции есть начало'} text={query?'Попробуй другое название или выбери другой раздел.':favoritesOnly?'Нажми на закладку на обложке, чтобы добавить материал сюда.':state.admin?'Добавь первый файл — и твоя следующая история будет здесь.':'Когда владелец добавит материалы, они появятся в этом разделе.'} button={state.admin&&!query&&!favoritesOnly?'Добавить первый файл':undefined} onClick={()=>fileInput.current?.click()}/>:null}
        </div></div>
        </>}
      </>}

      {view==='history'&&<>
        <div className="page-title-row"><div><p className="eyebrow">Знакомые истории</p><h1 className="page-title">Недавно открытое</h1><p className="page-subtitle">Твоя история на этом устройстве</p></div><Icon name="history" size={29}/></div>
        {recent.length?<div className="history-list">{recent.map(({item,entry})=><button key={item.id} className="history-item" onClick={()=>open(item)}><div className="history-cover"><Artwork kind={item.category}/></div><span><strong>{item.name}</strong><small>{labels[item.category]} · {new Date(entry.at).toLocaleDateString('ru',{day:'numeric',month:'short'})}</small></span><Icon name="chevron" size={19}/></button>)}</div>:<EmptyState icon="history" title="Здесь продолжится твоя история" text={state.catalog?'Открой любой материал — и он появится здесь.':'Подключи библиотеку, чтобы возвращаться к недавно открытым материалам.'} button={state.catalog?'В мою коллекцию':'Подключить библиотеку'} onClick={()=>go(state.catalog?'collection':'profile')}/>}
      </>}

      {view==='profile'&&<>
        <div className="page-title-row"><div><p className="eyebrow">Место для своих</p><h1 className="page-title">Мой профиль</h1></div><Icon name="user" size={29}/></div>
        <section className="profile-card"><div className="profile-avatar">{state.user?(state.user.given_name||state.user.email).slice(0,1).toUpperCase():<Icon name="user" size={32}/>}</div><div className="profile-meta"><h2>{state.user?(state.user.given_name||'Твой профиль'):'Добро пожаловать'}</h2><p>{state.user?state.user.email:'Войди, чтобы открыть свою коллекцию'}</p><span id="status" className={'status-pill'+(state.catalog?' connected':'')}>{state.status}</span></div><div className="profile-actions"><button id="loginBtn" className="btn btn-primary" disabled={!!state.user||busy} onClick={actions.login}>{state.user?<><Icon name="check" size={17}/>Вход выполнен</>:<><GoogleMark/>Войти через Google</>}</button>{state.user&&(!state.driveConnected||state.catalog)&&<button id="driveBtn" className="btn btn-secondary" disabled={busy} onClick={connect}><Icon name="cloud" size={18}/>{state.driveConnected?'Обновить доступ к файлам':state.catalog?'Подключить Drive заново':'Разрешить доступ к файлам'}</button>}</div></section>
        {state.notice&&<aside id="notice" className="notice-card"><span><Icon name={state.authConfigured?'lock':'cloud'} size={21}/></span><div><h3 className="notice-title">{state.authConfigured?state.notice.title:'Остался один шаг для входа'}</h3><p>{state.authConfigured?state.notice.text:'Нужно завершить настройку Google. Пока коллекция закрыта, твои файлы остаются в твоём Drive.'}</p>{!state.authConfigured&&<a className="text-link" href={guide} target="_blank" rel="noopener noreferrer">Как подключить Google<Icon name="arrow" size={15}/></a>}</div></aside>}
        {state.driveConnected&&!state.catalog&&<LibrarySetup state={state} libraryId={libraryId} setLibraryId={setLibraryId} passphrase={passphrase} setPassphrase={setPassphrase} again={again} setAgain={setAgain} onOpen={openLibrary} onFind={actions.findMyLibrary}/>}
        {state.catalog&&<section className="settings-card"><div className="section-heading"><h2 className="section-title">Твоя коллекция</h2><span className="status-pill connected"><Icon name="check" size={13}/> Открыта</span></div><div className="profile-stats"><div><strong>{items.length}</strong><span>{plural(items.length)}</span></div><div><strong>{formatSize(totalSize)}</strong><span>в твоём Drive</span></div><div><strong>{state.admin?'Владелец':'Зритель'}</strong><span>твой доступ</span></div></div><button className="btn btn-secondary" onClick={()=>go('collection')}>В мою коллекцию<Icon name="arrow" size={17}/></button></section>}
        <MusicConnections userId={state.user?.sub}/><DeviceSettings state={state} actions={actions}/>
        <section className="settings-card about-card"><BrandMark/><div><h3>MediaVault</h3><p>Личная медиатека. Файлы шифруются перед сохранением в твоём Google Drive.</p><a className="text-link" href={guide} target="_blank" rel="noopener noreferrer">Помощь и настройка<Icon name="arrow" size={14}/></a></div></section>
        {state.user&&<button id="logoutBtn" className="btn btn-ghost logout-button" onClick={()=>{actions.logout();setPassphrase('');setAgain('');}}><Icon name="logout" size={18}/>Выйти из аккаунта</button>}
      </>}
    </motion.main>
    <CookieNotice state={state} actions={actions}/>
    <nav className="bottom-nav" aria-label="Мобильная навигация">{navigation.map(item=><button id={item.id==='profile'?'profileNav':item.id==='library'?'libraryNav':item.id==='collection'?'collectionNav':undefined} key={item.id} className={'bottom-nav-item'+(view===item.id?' is-active':'')} onClick={()=>go(item.id)}><span className="nav-icon"><Icon name={item.icon} size={22}/></span><span className="nav-label">{item.label}</span></button>)}</nav>
    <Dialog.Root open={libraryDialog} onOpenChange={value=>{setLibraryDialog(value);if(!value){setPassphrase('');setAgain('');}}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog import-library-dialog" onCloseAutoFocus={event=>{event.preventDefault();libraryOpener.current?.isConnected&&libraryOpener.current.focus({preventScroll:true});}}><Dialog.Close className="icon-button dialog-close" aria-label="Закрыть подключение библиотеки"><Icon name="close" size={18}/></Dialog.Close><Dialog.Title>{onlineAccess?'Онлайн-просмотр':'Библиотека для импорта'}</Dialog.Title><Dialog.Description>Выбранные тайтл, озвучка и серии останутся на странице.</Dialog.Description>{!state.user?<button className="btn btn-primary" disabled={busy} onClick={actions.login}><GoogleMark/>Войти через Google</button>:!state.admin?<><p>Войди владельцем: roma.shevchenko2020@gmail.com.</p><button className="btn btn-secondary" onClick={actions.logout}>Сменить аккаунт</button></>:onlineAccess?<><p>{importService.error||'Подключаем источники. Google Диск открывать не требуется.'}</p><button className="btn btn-primary" onClick={()=>importService.refresh().catch(()=>{})}>Подключить сервер</button></>:!state.driveConnected?<button className="btn btn-primary" disabled={busy} onClick={actions.connectDrive}>Разрешить доступ к библиотеке</button>:!state.catalog?<LibrarySetup state={state} libraryId={libraryId} setLibraryId={setLibraryId} passphrase={passphrase} setPassphrase={setPassphrase} again={again} setAgain={setAgain} onOpen={create=>openLibrary(create,true)} onFind={actions.findMyLibrary}/>:<button className="btn btn-primary" onClick={()=>setLibraryDialog(false)}>Библиотека открыта — продолжить</button>}</Dialog.Content></Dialog.Portal></Dialog.Root>
    {state.toast&&<div id="toast" className={'toast'+(state.toast.bad?' toast-bad':'')} role="status"><Icon name={state.toast.bad?'close':'check'} size={18}/><span>{state.toast.message}</span><button className="icon-button" aria-label="Закрыть уведомление" onClick={actions.clearToast}><Icon name="close" size={16}/></button></div>}
    {selected&&selected.category!=='video'&&state.catalog&&<MediaViewer userId={state.user?.sub} key={selected.category==='manga'?'manga-reader':selected.id} item={selected} catalog={state.catalog} libraryId={state.libraryId} onSelectItem={open} onClose={closeViewer} readWhole={actions.readWhole} readRange={actions.readRange} readerService={importService} prepareStream={actions.prepareStream} onError={actions.error}/>}
  </div>;
}

function GoogleMark(){return <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M21.8 12.2c0-.7-.1-1.4-.2-2.1H12v4h5.5a4.7 4.7 0 0 1-2.1 3.1v2.6h3.4c2-1.8 3-4.4 3-7.6ZM12 22c2.8 0 5.1-.9 6.8-2.4l-3.4-2.6a6.2 6.2 0 0 1-9.2-3.2H2.7v2.7A10.2 10.2 0 0 0 12 22ZM6.2 13.8a6.1 6.1 0 0 1 0-3.6V7.5H2.7a10 10 0 0 0 0 9l3.5-2.7ZM12 6c1.5 0 2.8.5 3.9 1.5l3-3A10.2 10.2 0 0 0 2.7 7.5l3.5 2.7A6.1 6.1 0 0 1 12 6Z"/></svg>}
