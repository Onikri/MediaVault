import {useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen,Cloud,Download} from 'lucide-react';
import UiSegmented from './UiSegmented.jsx';
import ImportReadiness,{canImport} from './ImportReadiness.jsx';
import {readRanobeChapter,providerLanguage} from './ranobe-client.js';
import {loadChapters,epubFile,textFile,saveBlob,safeFileName} from './book-export.js';
import {counted} from './title-context.js';

const CHAPTER=['глава','главы','глав'];
// Saves the chapters of the source open in the reader. On the device: one EPUB
// or text file built in this browser. In Google Drive: a server job (the VM
// fetches, encrypts and writes every chapter, with the computer off).
export default function RanobeExport({item,book,service,state,destination,onSubmitted,onOpenLibrary}){
 const isBook=item.kind==='book',episodes=book?.episodes||[];
 const [mode,setMode]=useState('all'),[first,setFirst]=useState('1'),[last,setLast]=useState(''),[format,setFormat]=useState('epub');
 const [busy,setBusy]=useState(''),[progress,setProgress]=useState(null),[error,setError]=useState(''),[done,setDone]=useState(''),abort=useRef(null);
 useEffect(()=>()=>abort.current?.abort(),[]);
 useEffect(()=>{setFirst('1');setLast(String(episodes.length||''));setDone('');setError('');},[book?.url,episodes.length]);
 const chosen=useMemo(()=>{
  if(mode==='all')return episodes;
  const a=Math.max(1,Number(first)||1),b=Math.min(episodes.length,Number(last)||a);
  return a<=b?episodes.slice(a-1,b):[];
 },[mode,first,last,episodes]);
 const ready=destination==='drive'?canImport(state,service)&&Number(service.session?.serverVersion)>=70:service?.status==='connected';
 if(!book)return <p className="export-hint">{isBook?'Открой издание в читалке на странице — здесь появится его оглавление для сохранения.':'Выбери источник в читалке на странице — сохраним главы именно этого перевода.'}</p>;
 async function saveDevice(){
  const controller=new AbortController();abort.current=controller;setBusy('local');setError('');setDone('');setProgress({done:0,total:chosen.length,failed:0});
  try{
   const rows=await loadChapters(chosen,(entry,signal)=>readRanobeChapter(service,entry.url,item,{signal}),{signal:controller.signal,onProgress:setProgress});
   const meta={title:book.title||item.title,authors:item.authors||[],language:book.language||'ru',source:book.providerName,description:String(item.description||'').replace(/<[^>]+>/g,'').slice(0,1200),cover:item.cover,chapters:rows,identifier:'mediavault:'+book.url};
   const range=mode==='all'?'':' · главы '+chosen[0].number+'–'+chosen.at(-1).number;
   const blob=format==='epub'?await epubFile(meta):textFile(meta);
   const name=safeFileName(meta.title+range)+(format==='epub'?'.epub':'.txt');
   saveBlob(blob,name);
   const failed=rows.filter(r=>r.error).length;
   setDone(failed?`Файл сохранён. Не загрузились ${counted(failed,CHAPTER)} — они отмечены в тексте.`:'Файл «'+name+'» передан браузеру для сохранения.');
  }catch(e){setError(e.name==='AbortError'?'Сохранение остановлено.':e.message||'Не удалось собрать файл.');}
  finally{setBusy('');abort.current=null;}
 }
 async function saveDrive(){
  setBusy('submit');setError('');setDone('');
  try{
   // The import server numbers files 1…N: chapter numbers like 12.5 keep
   // their order and their title, the file number is the position.
   const entries=chosen.map((entry,index)=>({number:episodes.indexOf(entry)+1||index+1,url:entry.url,title:(entry.number!=null?'Глава '+entry.number+(entry.title&&!/^глава/i.test(entry.title)?'. '+entry.title:''):entry.title||'').slice(0,180),season:Math.max(1,Math.min(1000,Number(entry.season)||1))}));
   const metadata=Object.fromEntries(['title','titles','aliases','description','cover','year','format','genres','tags','age','ageLabel','chapters','volumes','status','ids','links','kind','authors'].map(key=>[key,item[key]]).filter(([,v])=>v!=null));
   await service.submit({version:3,library_id:state.libraryId,sources:[book.url],collection:(item.title||book.title).trim().slice(0,180),season:1,episodes:'all',quality:'best',resume:true,section:isBook?'book':'ranobe',metadata,entries,provider:book.provider||'',dub:book.providerName||'',translation:{}});
   setDone('Задание принято сервером. Главы появятся в коллекции; вкладку можно закрыть.');onSubmitted?.();
  }catch(e){setError(e.message||'Сервер не принял задание.');}finally{setBusy('');}
 }
 return <form className="export-form" onSubmit={event=>{event.preventDefault();destination==='drive'?saveDrive():saveDevice();}}>
  <div className="export-field"><span>Источник</span><p className="export-source"><BookOpen size={15} aria-hidden="true"/><span><strong>{book.providerName}</strong><small>{counted(episodes.length,CHAPTER)} · {providerLanguage(book.language)}</small></span></p></div>
  <div className="export-field"><span>Главы</span><UiSegmented className="is-wide" label="Какие главы сохранить" value={mode} options={[['all','Все'],['range','Диапазон']]} onChange={setMode} disabled={!!busy}/>
   {mode==='range'&&<div className="export-row"><input className="field-input" type="number" min="1" max={episodes.length} value={first} onChange={e=>setFirst(e.target.value)} aria-label="С какой по счёту главы"/><input className="field-input" type="number" min="1" max={episodes.length} value={last} onChange={e=>setLast(e.target.value)} aria-label="По какую по счёту главу"/></div>}
   <p className="export-hint">{chosen.length?counted(chosen.length,CHAPTER)+(chosen.length?' · с '+chosen[0].number+' по '+chosen.at(-1).number:''):'В этом диапазоне глав нет.'}</p></div>
  {destination==='local'&&<div className="export-field"><span>Формат</span><UiSegmented className="is-wide" label="Формат файла" value={format} options={[['epub','EPUB · для читалок'],['txt','Текст']]} onChange={setFormat} disabled={!!busy}/></div>}
  {destination==='drive'&&<ImportReadiness state={state} service={service} onOpenLibrary={onOpenLibrary}/>}
  {destination==='drive'&&service.status==='connected'&&Number(service.session?.serverVersion)<70&&<p className="export-hint">Для сохранения текста в Google Диск обнови сервер MediaVault.</p>}
  {progress&&busy==='local'&&<div className="export-progress" role="status"><div><span>Загружаем главы · {progress.done} из {progress.total}{progress.failed?' · с ошибкой '+progress.failed:''}</span><button type="button" className="text-link" onClick={()=>abort.current?.abort()}>Остановить</button></div><div className="export-progress-bar"><i style={{width:Math.round(progress.done/Math.max(1,progress.total)*100)+'%'}}/></div></div>}
  {error&&<p className="inline-error" role="alert">{error}</p>}{done&&<p className="export-hint" role="status">{done}</p>}
  <button className="btn btn-primary export-submit" disabled={!ready||!!busy||!chosen.length}>{destination==='drive'?<Cloud size={17}/>:<Download size={17}/>}{busy==='submit'?'Отправляем…':busy==='local'?'Собираем файл…':destination==='drive'?'Сохранить в Google Диск':'Сохранить на устройство'}</button>
  <p className="export-hint">{destination==='drive'?'Сервер MediaVault сам скачивает главы, шифрует их и записывает в твой Google Диск, даже если компьютер выключен.':'Главы загружаются в этом браузере и собираются в один файл. Держи вкладку открытой до конца.'}</p>
 </form>;
}
