import {useEffect,useMemo,useRef,useState} from 'react';
import {Upload,FolderOpen,Check} from 'lucide-react';
import {catalogProviders,fetchCatalog,mergeCatalog} from './catalog.js';
import {fetchArtwork} from './title-artwork.js';
import {formatSize} from './vault.js';
import {LOCAL_KINDS,localKind,suggestedTitle,acceptedFiles,mangaChapters,packCbz,cardProfile,malIdentity} from './local-title.js';
import './local-title.css';

// «Добавить тайтл с компьютера»: files or a folder → encrypted upload into the
// owner's Drive collection → the chosen catalogue card becomes the title's
// profile, so the title page, enrichment and source search work as for an
// imported title.
export default function LocalTitleUpload({state,actions,service,onOpenLibrary,initialKind='book'}){
 const [kind,setKind]=useState(LOCAL_KINDS.some(k=>k[0]===initialKind)?initialKind:'book');
 const [files,setFiles]=useState([]),[rejected,setRejected]=useState(0),[title,setTitle]=useState(''),[edited,setEdited]=useState(false),[part,setPart]=useState('');
 const [cards,setCards]=useState([]),[card,setCard]=useState(null),[searching,setSearching]=useState(false),[phase,setPhase]=useState(''),[error,setError]=useState(''),[done,setDone]=useState(null);
 const filesInput=useRef(null),folderInput=useRef(null);
 const [,,section,catalogKind,accept]=localKind(kind);
 const size=useMemo(()=>files.reduce((sum,f)=>sum+(f.size||0),0),[files]);
 const pages=kind==='manga'?mangaChapters(files):[];
 function choose(list){
  const {files:ok,rejected:bad}=acceptedFiles(kind,list);setFiles(ok);setRejected(bad.length);setDone(null);setError('');
  if(!edited)setTitle(suggestedTitle(ok));
 }
 useEffect(()=>{setFiles([]);setRejected(0);setCards([]);setCard(null);setDone(null);},[kind]);
 // Catalogue cards for the typed name (the same catalogues the site searches).
 useEffect(()=>{
  setCards([]);setCard(null);const query=title.trim();if(!catalogKind||query.length<2)return;
  const abort=new AbortController(),timer=setTimeout(async()=>{
   setSearching(true);
   try{
    const providers=catalogProviders(catalogKind,query,service?.server).slice(0,3);
    const rows=(await Promise.allSettled(providers.map(p=>fetchCatalog(p,{query,kind:catalogKind,server:service?.server,signal:abort.signal})))).flatMap(r=>r.status==='fulfilled'?r.value:[]);
    if(!abort.signal.aborted)setCards(mergeCatalog(rows.filter(r=>r.kind===catalogKind)).slice(0,6));
   }catch{}finally{if(!abort.signal.aborted)setSearching(false);}
  },500);
  return()=>{clearTimeout(timer);abort.abort();};
 },[title,catalogKind,service?.server]);

 async function submit(event){
  event.preventDefault();setError('');setDone(null);
  if(!files.length){setError('Выбери файлы или папку.');return;}
  if(!title.trim()){setError('Укажи название тайтла.');return;}
  try{
   let upload=files;
   if(kind==='manga'&&pages.length){
    const packed=[];
    for(const [i,chapter] of pages.entries()){setPhase('Собираем главу '+(i+1)+' из '+pages.length+'…');packed.push(await packCbz(chapter.name,chapter.pages));}
    upload=[...files.filter(f=>/\.(cbz|zip)$/i.test(f.name)),...packed];
   }
   setPhase('Шифруем и загружаем на Google Диск…');
   if(!await actions.refreshCatalog({silent:true}))throw Error('Не удалось перечитать коллекцию с Google Диска. Повтори после подключения Drive.');
   const results=await actions.uploadFiles(upload,{section,collection:title.trim(),part:part.trim(),metadataId:malIdentity(card)});
   if(!results)throw Error('Загрузка не началась. Дождись завершения текущей операции.');
   const saved=results.filter(r=>r.ok),collectionId=saved[0]?.item?.collectionId;
   if(collectionId&&card){
    setPhase('Сохраняем обложку и описание…');
    const profile=cardProfile(card),{images}=await fetchArtwork(profile).catch(()=>({images:[]}));
    await actions.saveTitleProfile(section+':'+collectionId,profile,images);
   }
   setDone({saved:saved.length,total:upload.length,failed:results.filter(r=>!r.ok).map(r=>r.name+': '+r.error)});
   if(saved.length){setFiles([]);setPart('');}
  }catch(cause){setError(cause.message||String(cause));}
  finally{setPhase('');}
 }

 if(!state.catalog)return <div className="local-title"><p className="fine">Тайтл с компьютера сохраняется в твою зашифрованную коллекцию на Google Диске. Сначала открой её.</p><button type="button" className="btn btn-primary" onClick={()=>onOpenLibrary?.('drive')}>Открыть коллекцию</button></div>;
 if(!state.admin)return <p className="fine local-title">Добавлять тайтлы в коллекцию может её владелец.</p>;
 const busy=!!phase||!!state.busy;
 return <form className="local-title" onSubmit={submit} aria-label="Добавить тайтл с компьютера">
  <div className="local-title-kinds" role="radiogroup" aria-label="Тип произведения">{LOCAL_KINDS.map(([id,label])=><button type="button" role="radio" aria-checked={kind===id} key={id} onClick={()=>setKind(id)} disabled={busy}>{label}</button>)}</div>
  <div className="local-title-files">
   <button type="button" className="btn btn-secondary" disabled={busy} onClick={()=>filesInput.current?.click()}><Upload size={16}/>Выбрать файлы</button>
   <button type="button" className="btn btn-secondary" disabled={busy} onClick={()=>folderInput.current?.click()}><FolderOpen size={16}/>Выбрать папку</button>
   <input ref={filesInput} type="file" multiple accept={accept} hidden aria-label="Файлы тайтла" onChange={e=>{choose(Array.from(e.target.files||[]));e.target.value='';}}/>
   <input ref={folderInput} type="file" webkitdirectory="" directory="" multiple hidden aria-label="Папка тайтла" onChange={e=>{choose(Array.from(e.target.files||[]));e.target.value='';}}/>
   <span className="fine" role="status">{files.length?files.length+' файл. · '+formatSize(size)+(pages.length?' · глав из картинок: '+pages.length:''):'Форматы: '+accept.replaceAll(',',' ')}{rejected?' · пропущено неподходящих: '+rejected:''}</span>
  </div>
  <div className="import-field-grid">
   <label className="form-field"><span className="input-label">Название тайтла</span><input className="field-input" value={title} onChange={e=>{setTitle(e.target.value);setEdited(true);}} placeholder="Как называется произведение" required maxLength={300}/></label>
   <label className="form-field"><span className="input-label">{['book','ranobe','manga'].includes(kind)?'Том или часть':kind==='music'?'Альбом или диск':'Сезон или часть'}</span><input className="field-input" value={part} onChange={e=>setPart(e.target.value)} placeholder="Необязательно" maxLength={200}/></label>
  </div>
  {catalogKind&&<fieldset className="local-title-cards"><legend className="input-label">Карточка в каталоге</legend>
   <p className="fine">По карточке подтянутся обложка и описание, а на странице тайтла — онлайн-источники и сведения.</p>
   {searching&&<p className="fine" role="status"><span className="loading-ring"/>Ищем в каталогах…</p>}
   <div className="local-title-card-list">{cards.map(c=><button type="button" key={c.id} aria-pressed={card?.id===c.id} onClick={()=>setCard(card?.id===c.id?null:c)}>
    {c.cover?<img src={c.cover} alt="" loading="lazy" referrerPolicy="no-referrer"/>:null}<span><strong>{c.title}</strong><small>{[c.year,(c.authors||[]).slice(0,2).join(', ')||c.format].filter(Boolean).join(' · ')}</small></span>{card?.id===c.id&&<Check size={16}/>}</button>)}</div>
   {!searching&&title.trim().length>=2&&!cards.length&&<p className="fine">Карточка не найдена — тайтл сохранится с твоим названием.</p>}
  </fieldset>}
  {error&&<p className="inline-error" role="alert">{error}</p>}
  {phase&&<p className="discovery-status" role="status"><span className="loading-ring"/>{phase}</p>}
  {done&&<p className={done.failed.length?'inline-error':'fine'} role="status">Сохранено файлов: {done.saved} из {done.total}.{done.failed.length?' Не загрузились: '+done.failed.slice(0,3).join('; '):' Тайтл появился в коллекции Google Диска.'}</p>}
  <button className="btn btn-primary" disabled={busy||!files.length||!title.trim()}><Upload size={17}/>Сохранить в коллекцию</button>
 </form>;
}
