import {lazy,Suspense,useEffect,useMemo,useRef,useState} from 'react';
import {RetainedMediaSlot,useRetainedWorkspace} from './RetainedMedia.jsx';
import {BookOpen,RefreshCw} from 'lucide-react';
import ChapterIndex from './ChapterIndex.jsx';
import PlaybackReveal from './PlaybackReveal.jsx';
import {FilterGroup,SourceList} from './ReaderFilters.jsx';
import {rankSources,useSourceFavorites} from './source-ranking.js';
import {publishTitleStats} from './title-context.js';
import {searchRanobe,inspectRanobe,ranobeProgress,providerLanguage,readerInAddress,addressWithReader} from './ranobe-client.js';
import {useContentLanguage,CONTENT_LANGUAGES} from './content-language.js';
import {OnlineBooks} from './OnlineLibrary.jsx';
import './ranobe.css';
const RanobeReader=lazy(()=>import('./RanobeReader.jsx'));
// A reader minimized to the tray outlives its title page. «Вернуться к чтению»
// reopens it through the page that is mounted now, or navigates back to the
// title page, which then reopens it at once from the kept book.
const reopeners=new Map(),pendingReopen=new Set();
function rememberReader(index){const hash=addressWithReader(location.hash,index);if(hash&&hash!==location.hash)history.replaceState(history.state,'',location.pathname+location.search+hash);}

// Sources, chapters and the reader for one ranobe or book title on its page.
// Ranobe: fan translations (RanobeHub, Zenko, Smakolyky, Baka).
// Books: public-domain full texts (Project Gutenberg and Wikisource).
export default function RanobeSources({item,service,state,expected=0}){
 const defaultLanguage=useContentLanguage(),userId=state.user?.sub,isBook=item.kind==='book';
 const [readingLanguage,setReadingLanguage]=useState(null);
 const extendedLanguages=Number(service?.session?.serverVersion)>=61;
 const languages=extendedLanguages?[...CONTENT_LANGUAGES,...(isBook?[['en','English'],['ja','日本語'],['ko','한국어']]:[['ja','日本語']])]:CONTENT_LANGUAGES;
 const language=languages.some(([id])=>id===readingLanguage)?readingLanguage:defaultLanguage==='all'?'ru':defaultLanguage;
 const [search,setSearch]=useState({loading:false,error:'',results:[],providers:[]}),[revision,setRevision]=useState(0);
 const [source,setSource]=useState(null),[opened,setOpened]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [open,setOpenState]=useState(null),restored=useRef(false),inspection=useRef(null);
 const [books,setBooks]=useState({}),favorites=useSourceFavorites(userId,isBook?'book':'ranobe'),picked=useRef(false);
 function setOpen(value){setOpenState(value);rememberReader(value?value.index:-1);}
 const workspace=useRetainedWorkspace(),retainedId='ranobe:'+(userId||'guest')+':'+item.id;
 // Read, not subscribed: the slot writes its element into the store on every
 // render, so a subscription here would loop.
 const held=workspace?.rows.get(retainedId)||null;
 useEffect(()=>{
  const reopen=()=>{const row=workspace?.rows.get(retainedId);if(row?.data)setOpen(row.data.start||{index:0,paragraph:0});};
  reopeners.set(retainedId,reopen);if(pendingReopen.delete(retainedId))reopen();
  return()=>{if(reopeners.get(retainedId)===reopen)reopeners.delete(retainedId);};
 },[retainedId]);
 const minimize=()=>setOpen(null);
 const close=()=>{if(workspace?.rows.has(retainedId))workspace.close(retainedId);else setOpen(null);};
 const restore=()=>{const reopen=reopeners.get(retainedId);if(reopen){reopen();return;}pendingReopen.add(retainedId);const route=workspace?.rows.get(retainedId)?.route;if(route&&location.hash!==route)location.hash=route;};
 const ready=service?.status==='connected'&&Number(service.session?.serverVersion)>=(isBook?56:55);
 useEffect(()=>{
  if(!ready)return;const abort=new AbortController();
  setSearch({loading:true,error:'',results:[],providers:[]});setSource(null);setOpened(null);setBusy(false);setError('');
  setBooks({});picked.current=false;
  searchRanobe(service,item,language,{signal:abort.signal}).then(async data=>{
   if(abort.signal.aborted)return;
   const results=data.results||[];
   setSearch({loading:false,error:'',results,providers:data.providers||[],fallback:data.fallback==='all'});
   const saved=results.find(r=>ranobeProgress(userId,r.url));
   // A book being read, or a favourite site, opens at once; otherwise every
   // source is measured first and the most complete translation opens.
   const first=saved||rankSources(results,{favorites:favorites.list}).find(r=>favorites.has(r));
   if(first){picked.current=true;choose(first);}
   let next=0;const measured={};
   async function worker(){while(next<Math.min(results.length,8)){const row=results[next++];try{const book=await inspectRanobe(service,row.url,item,{signal:abort.signal});measured[row.url]=book;setBooks(old=>({...old,[row.url]:book}));}catch(e){if(abort.signal.aborted)return;measured[row.url]={error:e.message||'Источник не открылся',episodes:[]};setBooks(old=>({...old,[row.url]:measured[row.url]}));}}}
   await Promise.all([worker(),worker(),worker()]);
   if(abort.signal.aborted||picked.current)return;
   const best=rankSources(results.filter(r=>measured[r.url]?.episodes?.length),{favorites:favorites.list,expected,count:r=>measured[r.url]?.episodes?.length})[0]||results[0];
   if(best){picked.current=true;choose(best);}
  }).catch(e=>{if(!abort.signal.aborted)setSearch({loading:false,error:e.message||'Источники не ответили.',results:[],providers:[]});});
  return()=>{abort.abort();inspection.current?.abort();};
 },[ready,item.id,language,revision]);
 async function choose(row){
  inspection.current?.abort();picked.current=true;
  const abort=new AbortController();inspection.current=abort;
  setSource(row);setOpened(null);setError('');setBusy(true);
  try{const book=books[row.url]?.episodes?.length?books[row.url]:await inspectRanobe(service,row.url,item,{signal:abort.signal});if(!abort.signal.aborted)setOpened(book);}
  catch(e){if(!abort.signal.aborted)setError(e.message||'Не удалось получить список глав.');}
  finally{if(inspection.current===abort){inspection.current=null;if(!abort.signal.aborted)setBusy(false);}}
 }
 const progress=opened?ranobeProgress(userId,opened.url):null;
 useEffect(()=>{if(!opened)return;publishTitleStats({kind:isBook?'book':'ranobe',chapters:opened.episodes.length,volumes:new Set(opened.episodes.map(e=>e.season).filter(Boolean)).size||null,source:opened.url,sourceName:opened.providerName,language:opened.language,book:{...opened,provider:source?.provider||opened.provider}});},[opened?.url,opened?.episodes?.length]);
 useEffect(()=>()=>publishTitleStats(null),[]);
 const resume=useMemo(()=>progress&&opened?opened.episodes.findIndex(c=>c.url===progress.chapter):-1,[opened,progress?.chapter]);
 // After a reload: reopen the reader that was open, at the saved place.
 useEffect(()=>{
  if(restored.current||!opened?.episodes?.length||open)return;
  const index=readerInAddress();if(index<0){restored.current=true;return;}
  restored.current=true;
  setOpenState(resume>=0?{index:resume,paragraph:progress.paragraph||0}:{index:Math.min(index,opened.episodes.length-1),paragraph:0});
 },[opened,resume]);
 const files=<details className="ranobe-file"><summary>{isBook?'Открыть свой файл книги или ссылку':'Открыть книгу из файла или по ссылке'}</summary><OnlineBooks userId={userId} service={service}/></details>;
 if(!service||service.status!=='connected')return <><p className="fine">{isBook?'Войди в профиль, чтобы искать полный текст книги.':'Войди в профиль, чтобы искать ранобэ в источниках.'} Свой файл можно открыть ниже.</p>{files}</>;
 if(!ready)return <><p className="fine">{isBook?'Чтение книг из библиотек':'Чтение ранобэ из источников'} появится после обновления сервера MediaVault.</p>{files}</>;
 const ranked=rankSources(search.results,{favorites:favorites.list,expected:Number(expected)||0,count:r=>books[r.url]?.episodes?.length});
 const shown=ranked.filter(r=>!books[r.url]?.error||r.url===source?.url),pending=search.results.slice(0,8).filter(r=>!books[r.url]).length;
 const entries=opened?.episodes||[],current=open?entries[open.index]?.url:resume>=0?entries[resume]?.url:'';
 const reading=!!open&&!!(opened||held?.data?.book);
 const start=index=>setOpen({index,paragraph:index===resume&&progress?progress.paragraph||0:0});
 return <section className="reader-stage ranobe-stage ranobe-sources" data-reading={reading||undefined} aria-label={isBook?'Книга онлайн':'Ранобэ онлайн'}>
  <aside className="reader-stage-filters" aria-label="Фильтры чтения">
   <FilterGroup legend={isBook?'Язык текста':'Язык перевода'} value={language} options={languages} onChange={setReadingLanguage}/>
   <SourceList sources={shown} value={source?.url} favorites={favorites} expected={Number(expected)||0} loading={search.loading} pending={search.loading?0:pending}
    info={r=>({chapters:books[r.url]?.episodes?.length,error:!!books[r.url]?.error,translator:r.translator})} onChoose={row=>{setOpen(null);choose(row);}} noun={isBook?['раздел','раздела','разделов']:['глава','главы','глав']}/>
   {search.error&&<p className="inline-error" role="alert">{search.error}</p>}
   {!search.loading&&!search.error&&!search.results.length&&<p className="reader-filter-note">{isBook?'Свободный текст книги пока не найден':'Доступное издание пока не найдено'}.{search.providers.some(p=>p.status==='unavailable')?' Часть источников не ответила.':''}</p>}
   {search.fallback&&<p className="reader-filter-note">{isBook?'На выбранном языке свободного текста нет — показаны издания на других языках.':'На выбранном языке перевода нет — показаны издания на других языках.'}</p>}
   <button type="button" className="text-link" disabled={search.loading} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={13}/>Искать заново</button>
   {files}
  </aside>
  <div className="reader-stage-main">
   {error&&<p className="inline-error" role="alert">{error}</p>}
   <PlaybackReveal active={reading}>{reading?<RetainedMediaSlot id={retainedId} kind="reader" userId={userId} label={(opened||held.data.book).title} data={{book:opened||held.data.book,start:open}} restore={restore}>
    <Suspense fallback={<div className="reader-idle-loading" role="status">Открываем читалку…</div>}><RanobeReader embed book={opened||held.data.book} item={item} start={open} service={service} userId={userId} onClose={close} onMinimize={workspace?minimize:undefined} onStop={()=>setOpenState(null)}/></Suspense>
   </RetainedMediaSlot>
   :<div className="watch-idle mv-player mvx mvx-idle reader-idle" style={item.cover?{'--watch-poster':`url("${String(item.cover).replace(/["\\]/g,'')}")`}:undefined}>
    <div className="mvx-idle-poster" aria-hidden="true"/>
    <div className="mvx-overview mvx-idle-overview">
     <strong className="reader-idle-title" translate="no">{opened?.title||item.title}</strong>
     <p className="mvx-meta" role="status">{busy?<><span className="mvx-spinner"/><span>{isBook?'Готовим книгу и оглавление':'Загружаем главы'}</span></>
      :opened?<><span>{entries.length} {isBook?'разделов':'глав'}</span><span>{opened.providerName}</span><span>{providerLanguage(opened.language)}</span></>
      :search.loading||pending?<><span className="mvx-spinner"/><span>{isBook?'Ищем полный текст в библиотеках':'Ищем переводы и сравниваем источники'}</span></>
      :<span>Выбери источник слева</span>}</p>
     {opened&&entries.length>0&&<button type="button" className="mvx-primary" onClick={()=>start(resume>=0?resume:0)}><BookOpen size={16}/>{resume>=0?'Продолжить · '+(isBook?entries[resume].title:'глава '+entries[resume].number):'Начать читать'}</button>}
    </div>
   </div>}</PlaybackReveal>
  </div>
  <ChapterIndex entries={entries} current={current} loading={busy} onOpen={entry=>start(entries.indexOf(entry))} emptyText={isBook?'Выбери издание слева — здесь появится оглавление.':'Выбери источник слева — здесь появятся главы и тома.'}/>
 </section>;
}
