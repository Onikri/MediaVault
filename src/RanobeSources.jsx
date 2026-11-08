import {lazy,Suspense,useEffect,useMemo,useState} from 'react';
import {BookOpen,Check,ArrowRight,RefreshCw,Play} from 'lucide-react';
import {searchRanobe,inspectRanobe,ranobeProgress,providerLanguage} from './ranobe-client.js';
import {useContentLanguage,CONTENT_LANGUAGES,setContentLanguage} from './content-language.js';
import {OnlineBooks} from './OnlineLibrary.jsx';
import './ranobe.css';
const RanobeReader=lazy(()=>import('./RanobeReader.jsx'));

// Sources, chapters and the reader for one ranobe title on its page.
export default function RanobeSources({item,service,state}){
 const language=useContentLanguage(),userId=state.user?.sub;
 const [search,setSearch]=useState({loading:false,error:'',results:[],providers:[]}),[revision,setRevision]=useState(0);
 const [source,setSource]=useState(null),[book,setBook]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [open,setOpen]=useState(null),[count,setCount]=useState(30);
 const ready=service?.status==='connected'&&Number(service.session?.serverVersion)>=55;
 useEffect(()=>{
  if(!ready)return;const abort=new AbortController();
  setSearch(old=>({...old,loading:true,error:''}));setSource(null);setBook(null);
  searchRanobe(service,item,language,{signal:abort.signal}).then(data=>{
   setSearch({loading:false,error:'',results:data.results||[],providers:data.providers||[]});
   const saved=(data.results||[]).find(r=>ranobeProgress(userId,r.url));
   if(saved||data.results?.length===1)choose(saved||data.results[0]);
  }).catch(e=>{if(!abort.signal.aborted)setSearch({loading:false,error:e.message||'Источники ранобэ не ответили.',results:[],providers:[]});});
  return()=>abort.abort();
 },[ready,item.id,language,revision]);
 async function choose(row){
  setSource(row);setBook(null);setError('');setBusy(true);setCount(30);
  try{setBook(await inspectRanobe(service,row.url,item));}catch(e){setError(e.message||'Не удалось получить список глав.');}finally{setBusy(false);}
 }
 const progress=book?ranobeProgress(userId,book.url):null;
 const resume=useMemo(()=>progress&&book?book.episodes.findIndex(c=>c.url===progress.chapter):-1,[book,progress?.chapter]);
 if(!service||service.status!=='connected')return <p className="fine">Войди в профиль, чтобы искать ранобэ в источниках. Книгу-файл можно открыть ниже.</p>;
 if(!ready)return <p className="fine">Чтение ранобэ из источников появится после обновления сервера MediaVault.</p>;
 return <section className="ranobe-sources" aria-label="Ранобэ онлайн">
  <div className="ranobe-toolbar">
   <label>Язык перевода<select aria-label="Язык перевода ранобэ" value={language} onChange={e=>setContentLanguage(e.target.value)}>{CONTENT_LANGUAGES.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
   <button type="button" className="text-link" disabled={search.loading} onClick={()=>setRevision(v=>v+1)} aria-label="Повторить поиск ранобэ"><RefreshCw size={14}/>Повторить</button>
  </div>
  {search.loading?<p className="discovery-status" role="status"><span className="loading-ring"/>Ищем перевод в RanobeHub, Zenko и Смаколиках…</p>
  :search.error?<p className="inline-error" role="alert">{search.error}</p>
  :!search.results.length?<p className="fine">Точный перевод пока не найден{search.providers.some(p=>p.status==='unavailable')?'; часть источников не ответила':''}. Можно открыть файл книги ниже.</p>
  :<div className="manga-source-list ranobe-source-list">{search.results.map(row=><button type="button" key={row.url} aria-pressed={source?.url===row.url} disabled={busy} onClick={()=>choose(row)}>
   <span className="manga-source-icon"><BookOpen size={18}/></span><span><strong>{row.providerName}</strong><small translate="no">{row.title}{row.translator?' · '+row.translator:''}</small></span><em>{providerLanguage(row.language)}</em>{source?.url===row.url?<Check size={16}/>:<ArrowRight size={15}/>}</button>)}</div>}
  {busy&&<p className="discovery-status" role="status"><span className="loading-ring"/>Загружаем главы…</p>}
  {error&&<p className="inline-error" role="alert">{error}</p>}
  {book&&<div className="ranobe-book">
   <div className="ranobe-book-head"><div><strong translate="no">{book.title}</strong><small>{book.episodes.length} глав · {book.providerName} · {providerLanguage(book.language)}</small></div>
    {book.episodes.length>0&&<button type="button" className="btn btn-primary" onClick={()=>setOpen({index:resume>=0?resume:0,paragraph:resume>=0?progress.paragraph:0})}><Play size={16}/>{resume>=0?'Продолжить · глава '+book.episodes[resume].number:'Начать читать'}</button>}</div>
   <ol className="ranobe-chapter-list">{book.episodes.slice(0,count).map((c,i)=><li key={c.url}><button type="button" aria-current={i===resume||undefined} onClick={()=>setOpen({index:i,paragraph:0})}><span>{book.seasons?.length>1?'Т. '+c.season+' · ':''}{c.number}</span><span translate="no">{c.title}</span></button></li>)}</ol>
   {book.episodes.length>count&&<button type="button" className="btn btn-secondary" onClick={()=>setCount(n=>n+100)}>Показать ещё главы</button>}
  </div>}
  <details className="ranobe-file"><summary>Открыть книгу из файла или по ссылке</summary><OnlineBooks userId={userId}/></details>
  {open&&book&&<Suspense fallback={null}><RanobeReader book={book} item={item} start={open} service={service} userId={userId} onClose={()=>setOpen(null)}/></Suspense>}
 </section>;
}
