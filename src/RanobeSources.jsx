import {lazy,Suspense,useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen,Check,ArrowRight,RefreshCw,Play} from 'lucide-react';
import {searchRanobe,inspectRanobe,ranobeProgress,providerLanguage,readerInAddress,addressWithReader} from './ranobe-client.js';
import {useContentLanguage,CONTENT_LANGUAGES,setContentLanguage} from './content-language.js';
import {OnlineBooks} from './OnlineLibrary.jsx';
import './ranobe.css';
const RanobeReader=lazy(()=>import('./RanobeReader.jsx'));
function rememberReader(index){const hash=addressWithReader(location.hash,index);if(hash&&hash!==location.hash)history.replaceState(history.state,'',location.pathname+location.search+hash);}

// Sources, chapters and the reader for one ranobe or book title on its page.
// Ranobe: fan translations (RanobeHub, Zenko, Smakolyky, Baka).
// Books: public-domain full texts (Project Gutenberg, Wikisource ru/uk).
export default function RanobeSources({item,service,state}){
 const language=useContentLanguage(),userId=state.user?.sub,isBook=item.kind==='book';
 const [search,setSearch]=useState({loading:false,error:'',results:[],providers:[]}),[revision,setRevision]=useState(0);
 const [source,setSource]=useState(null),[opened,setOpened]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [open,setOpenState]=useState(null),[count,setCount]=useState(30),restored=useRef(false);
 function setOpen(value){setOpenState(value);rememberReader(value?value.index:-1);}
 const ready=service?.status==='connected'&&Number(service.session?.serverVersion)>=(isBook?56:55);
 useEffect(()=>{
  if(!ready)return;const abort=new AbortController();
  setSearch(old=>({...old,loading:true,error:''}));setSource(null);setOpened(null);
  searchRanobe(service,item,language,{signal:abort.signal}).then(data=>{
   setSearch({loading:false,error:'',results:data.results||[],providers:data.providers||[]});
   const saved=(data.results||[]).find(r=>ranobeProgress(userId,r.url));
   if(saved||data.results?.length)choose(saved||data.results[0]);
  }).catch(e=>{if(!abort.signal.aborted)setSearch({loading:false,error:e.message||'Источники не ответили.',results:[],providers:[]});});
  return()=>abort.abort();
 },[ready,item.id,language,revision]);
 async function choose(row){
  setSource(row);setOpened(null);setError('');setBusy(true);setCount(30);
  try{setOpened(await inspectRanobe(service,row.url,item));}catch(e){setError(e.message||'Не удалось получить список глав.');}finally{setBusy(false);}
 }
 const progress=opened?ranobeProgress(userId,opened.url):null;
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
 return <section className="ranobe-sources" aria-label={isBook?'Книга онлайн':'Ранобэ онлайн'}>
  <div className="ranobe-toolbar">
   <label>{isBook?'Язык текста':'Язык перевода'}<select aria-label={isBook?'Язык текста книги':'Язык перевода ранобэ'} value={language} onChange={e=>setContentLanguage(e.target.value)}>{CONTENT_LANGUAGES.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
   <button type="button" className="text-link" disabled={search.loading} onClick={()=>setRevision(v=>v+1)} aria-label="Повторить поиск текста"><RefreshCw size={14}/>Повторить</button>
  </div>
  {search.loading?<p className="discovery-status" role="status"><span className="loading-ring"/>{isBook?'Ищем полный текст в Project Gutenberg и Викитеке…':'Ищем перевод в RanobeLib, RanobeHub, Jaomix, Rulate, Zenko, Смаколиках и Баке…'}</p>
  :search.error?<p className="inline-error" role="alert">{search.error}</p>
  :!search.results.length?<p className="fine">{isBook?'Свободного текста этой книги в Project Gutenberg и Викитеке нет: обычно это значит, что книга ещё под авторским правом':'Точный перевод пока не найден'}{search.providers.some(p=>p.status==='unavailable')?'; часть источников не ответила':''}. Можно открыть свой файл ниже.</p>
  :<div className="manga-source-list ranobe-source-list">{search.results.map(row=><button type="button" key={row.url} aria-pressed={source?.url===row.url} disabled={busy} onClick={()=>choose(row)}>
   <span className="manga-source-icon"><BookOpen size={18}/></span><span><strong>{row.providerName}</strong><small translate="no">{row.title}{row.translator?' · '+row.translator:''}</small></span><em>{providerLanguage(row.language)}</em>{source?.url===row.url?<Check size={16}/>:<ArrowRight size={15}/>}</button>)}</div>}
  {busy&&<p className="discovery-status" role="status"><span className="loading-ring"/>{isBook?'Готовим книгу и оглавление…':'Загружаем главы…'}</p>}
  {error&&<p className="inline-error" role="alert">{error}</p>}
  {opened&&<div className="ranobe-book">
   <div className="ranobe-book-head"><div><strong translate="no">{opened.title}</strong><small>{opened.episodes.length} {isBook?'разделов':'глав'} · {opened.providerName} · {providerLanguage(opened.language)}</small></div>
    {opened.episodes.length>0&&<button type="button" className="btn btn-primary" onClick={()=>setOpen({index:resume>=0?resume:0,paragraph:resume>=0?progress.paragraph:0})}><Play size={16}/>{resume>=0?'Продолжить · '+(isBook?opened.episodes[resume].title:'глава '+opened.episodes[resume].number):'Начать читать'}</button>}</div>
   <ol className="ranobe-chapter-list">{opened.episodes.slice(0,count).map((c,i)=><li key={c.url}><button type="button" aria-current={i===resume||undefined} onClick={()=>setOpen({index:i,paragraph:0})}><span>{!isBook&&opened.seasons?.length>1?'Т. '+c.season+' · ':''}{c.number}</span><span translate="no">{c.title}</span></button></li>)}</ol>
   {opened.episodes.length>count&&<button type="button" className="btn btn-secondary" onClick={()=>setCount(n=>n+100)}>{isBook?'Показать всё оглавление':'Показать ещё главы'}</button>}
  </div>}
  {files}
  {open&&opened&&<Suspense fallback={null}><RanobeReader book={opened} item={item} start={open} service={service} userId={userId} onClose={()=>setOpen(null)}/></Suspense>}
 </section>;
}
