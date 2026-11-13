import {useEffect,useMemo,useRef,useState} from 'react';
import {BookOpen,Cloud,Download} from 'lucide-react';
import UiSegmented from './UiSegmented.jsx';
import ImportReadiness,{canImport} from './ImportReadiness.jsx';
import {readRanobeChapter,providerLanguage} from './ranobe-client.js';
import {loadChapters,epubFile,textFile,saveBlob,safeFileName} from './book-export.js';
import {counted} from './title-context.js';
import {AUDIOBOOK_LANGUAGES,saveChapterAudiobooks} from './ranobe-audiobook.js';

const CHAPTER=['глава','главы','глав'];
const CONTENT=[['text','Текст'],['audio','Аудиокнига'],['both','Текст и аудио']];
// The reader's voices for this book, sent with a Drive job. The title bible
// can grow large; without it the VM studies the book itself.
async function driveDirection(bookKey,language){
 const {bookDirection}=await import('./tts/chapter-script.js');
 const value={...bookDirection(bookKey),language};
 if(JSON.stringify(value).length>150000)value.bible=null;
 return value;
}

// Saves the chapters of the source open in the reader as text, as an
// audiobook voiced like the reader (title bible, roles, the book's cast), or
// both. On the device: built in this browser. In Google Drive: a server job
// (the VM fetches, directs, voices, encrypts and writes every chapter, with
// the computer off).
export default function RanobeExport({item,book,service,state,destination,onSubmitted,onOpenLibrary}){
 const isBook=item.kind==='book',episodes=book?.episodes||[],language=book?.language||'ru',userId=state?.user?.sub;
 const [mode,setMode]=useState('all'),[first,setFirst]=useState('1'),[last,setLast]=useState(''),[format,setFormat]=useState('epub'),[content,setContent]=useState('text');
 const [busy,setBusy]=useState(''),[progress,setProgress]=useState(null),[voiceProgress,setVoiceProgress]=useState(null),[error,setError]=useState(''),[done,setDone]=useState(''),abort=useRef(null);
 useEffect(()=>()=>abort.current?.abort(),[]);
 useEffect(()=>{setFirst('1');setLast(String(episodes.length||''));setDone('');setError('');},[book?.url,episodes.length]);
 const chosen=useMemo(()=>{
  if(mode==='all')return episodes;
  const a=Math.max(1,Number(first)||1),b=Math.min(episodes.length,Number(last)||a);
  return a<=b?episodes.slice(a-1,b):[];
 },[mode,first,last,episodes]);
 const connected=service?.status==='connected',version=Number(service?.session?.serverVersion)||0;
 // Audio only where it works: Russian or Ukrainian text, Gemini voices on the
 // server (59+), and for Drive a server that has the VM narration director.
 const audioLanguage=AUDIOBOOK_LANGUAGES.includes(language);
 const audioReady=audioLanguage&&(destination==='drive'?service?.session?.ranobeDriveAudio===true:connected&&version>=59);
 const output=audioReady?content:'text',withText=output!=='audio',withAudio=output!=='text';
 const ready=destination==='drive'?canImport(state,service)&&version>=70:connected;
 if(!book)return <p className="export-hint">{isBook?'Открой издание в читалке на странице — здесь появится его оглавление для сохранения.':'Выбери источник в читалке на странице — сохраним главы именно этого перевода.'}</p>;
 const meta={title:item.title||book.title,aliases:item.aliases||[],authors:item.authors||[],description:item.description||'',year:item.year||null,kind:item.kind||'ranobe',language};

 async function saveText(controller){
  setProgress({done:0,total:chosen.length,failed:0});
  const rows=await loadChapters(chosen,(entry,signal)=>readRanobeChapter(service,entry.url,item,{signal}),{signal:controller.signal,onProgress:setProgress});
  const info={title:book.title||item.title,authors:item.authors||[],language,source:book.providerName,description:String(item.description||'').replace(/<[^>]+>/g,'').slice(0,1200),cover:item.cover,chapters:rows,identifier:'mediavault:'+book.url};
  const range=mode==='all'?'':' · главы '+chosen[0].number+'–'+chosen.at(-1).number;
  const name=safeFileName(info.title+range)+(format==='epub'?'.epub':'.txt');
  saveBlob(format==='epub'?await epubFile(info):textFile(info),name);
  setProgress(null);
  return {name,failed:rows.filter(r=>r.error).length};
 }
 async function saveAudio(controller){
  const [{chapterScript},{geminiClip}]=await Promise.all([import('./tts/chapter-script.js'),import('./tts/gemini-voice.js')]);
  const signal=controller.signal;
  setVoiceProgress({chapter:0,chapters:chosen.length,phase:'script',files:0});
  return saveChapterAudiobooks({entries:chosen,book:{title:meta.title,authors:meta.authors},language,signal,save:saveBlob,onProgress:setVoiceProgress,
   // The reader's own path: the same paragraphs, keys and cast, so roles the
   // reader already marked on this device are reused without new requests.
   prepare:async entry=>{
    const value=await readRanobeChapter(service,entry.url,item,{signal});
    const script=await chapterScript({paragraphs:value.paragraphs||[],bookKey:book.url,chapterKey:entry.url,meta,service,userId});
    return {title:value.title||entry.title,...script};
   },
   make:(row,i,abortSignal,lang)=>geminiClip({service,userId,text:row.text,voice:row.voice,style:row.style,language:lang,signal:abortSignal})});
 }
 async function saveDevice(){
  const controller=new AbortController();abort.current=controller;setBusy('local');setError('');setDone('');
  const lines=[];
  try{
   if(withText){const text=await saveText(controller);lines.push(text.failed?`Текст сохранён. Не загрузились ${counted(text.failed,CHAPTER)} — они отмечены в файле.`:'Текст «'+text.name+'» передан браузеру.');}
   if(withAudio){
    const audio=await saveAudio(controller);
    lines.push('Аудиокнига: '+counted(audio.files.length,['файл','файла','файлов'])+' передано браузеру'+(audio.failed?` · не загрузились ${counted(audio.failed,CHAPTER)}`:'')+(audio.partial.length?' · роли размечены частично в '+counted(audio.partial.length,CHAPTER):'')+'.');
   }
   setDone(lines.join(' '));
  }catch(e){
   const saved=e?.saved?.length?' Уже сохранено: '+counted(e.saved.length,['файл','файла','файлов'])+'.':'';
   setError((e.name==='AbortError'?'Сохранение остановлено.':e.message||'Не удалось собрать файл.')+saved);
  }
  finally{setBusy('');setProgress(null);setVoiceProgress(null);abort.current=null;}
 }
 async function saveDrive(){
  setBusy('submit');setError('');setDone('');
  try{
   // The import server numbers files 1…N: chapter numbers like 12.5 keep
   // their order and their title, the file number is the position.
   const entries=chosen.map((entry,index)=>({number:episodes.indexOf(entry)+1||index+1,url:entry.url,title:(entry.number!=null?'Глава '+entry.number+(entry.title&&!/^глава/i.test(entry.title)?'. '+entry.title:''):entry.title||'').slice(0,180),season:Math.max(1,Math.min(1000,Number(entry.season)||1))}));
   const metadata=Object.fromEntries(['title','titles','aliases','description','cover','year','format','genres','tags','age','ageLabel','chapters','volumes','status','ids','links','kind','authors'].map(key=>[key,item[key]]).filter(([,v])=>v!=null));
   await service.submit({version:3,library_id:state.libraryId,sources:[book.url],collection:(item.title||book.title).trim().slice(0,180),season:1,episodes:'all',quality:'best',resume:true,section:isBook?'book':'ranobe',metadata,entries,provider:book.provider||'',dub:book.providerName||'',translation:{},
    ...(withAudio?{output,voice:await driveDirection(book.url,language)}:{})});
   setDone(withAudio?'Задание принято сервером. Он озвучит главы голосами из читалки; файлы появятся в коллекции по одной главе. Вкладку можно закрыть.':'Задание принято сервером. Главы появятся в коллекции; вкладку можно закрыть.');onSubmitted?.();
  }catch(e){setError(e.message||'Сервер не принял задание.');}finally{setBusy('');}
 }
 const label=busy==='submit'?'Отправляем…':busy==='local'?(voiceProgress?'Озвучиваем главы…':'Собираем файл…'):destination==='drive'?'Сохранить в Google Диск':'Сохранить на устройство';
 const hint=destination==='drive'
  ?(withAudio?'Сервер MediaVault сам размечает роли и озвучивает главы голосами из читалки, шифрует и записывает их в твой Google Диск, даже если компьютер выключен. Каждая глава — отдельный файл; при исчерпании квоты Google задание подождёт и продолжит само.':'Сервер MediaVault сам скачивает главы, шифрует их и записывает в твой Google Диск, даже если компьютер выключен.')
  :(withAudio?'Главы озвучиваются в этом браузере по одной, голосами и ролями из читалки; каждая глава сохраняется отдельным файлом. Держи вкладку открытой до конца.':'Главы загружаются в этом браузере и собираются в один файл. Держи вкладку открытой до конца.');
 return <form className="export-form" onSubmit={event=>{event.preventDefault();destination==='drive'?saveDrive():saveDevice();}}>
  <div className="export-field"><span>Источник</span><p className="export-source"><BookOpen size={15} aria-hidden="true"/><span><strong>{book.providerName}</strong><small>{counted(episodes.length,CHAPTER)} · {providerLanguage(book.language)}</small></span></p></div>
  <div className="export-field"><span>Главы</span><UiSegmented className="is-wide" label="Какие главы сохранить" value={mode} options={[['all','Все'],['range','Диапазон']]} onChange={setMode} disabled={!!busy}/>
   {mode==='range'&&<div className="export-row"><input className="field-input" type="number" min="1" max={episodes.length} value={first} onChange={e=>setFirst(e.target.value)} aria-label="С какой по счёту главы"/><input className="field-input" type="number" min="1" max={episodes.length} value={last} onChange={e=>setLast(e.target.value)} aria-label="По какую по счёту главу"/></div>}
   <p className="export-hint">{chosen.length?counted(chosen.length,CHAPTER)+' · с '+chosen[0].number+' по '+chosen.at(-1).number:'В этом диапазоне глав нет.'}</p></div>
  {audioReady&&<div className="export-field"><span>Что сохранить</span><UiSegmented className="is-wide" label="Что сохранить" value={content} options={CONTENT} onChange={setContent} disabled={!!busy}/></div>}
  {!audioLanguage&&<p className="export-hint">Аудиокнига озвучивается для русского и украинского текста.</p>}
  {destination==='local'&&withText&&<div className="export-field"><span>Формат текста</span><UiSegmented className="is-wide" label="Формат файла" value={format} options={[['epub','EPUB · для читалок'],['txt','Текст']]} onChange={setFormat} disabled={!!busy}/></div>}
  {destination==='drive'&&<ImportReadiness state={state} service={service} onOpenLibrary={onOpenLibrary}/>}
  {destination==='drive'&&connected&&version<70&&<p className="export-hint">Для сохранения в Google Диск обнови сервер MediaVault.</p>}
  {progress&&busy==='local'&&<div className="export-progress" role="status"><div><span>Загружаем главы · {progress.done} из {progress.total}{progress.failed?' · с ошибкой '+progress.failed:''}</span><button type="button" className="text-link" onClick={()=>abort.current?.abort()}>Остановить</button></div><div className="export-progress-bar"><i style={{width:Math.round(progress.done/Math.max(1,progress.total)*100)+'%'}}/></div></div>}
  {voiceProgress&&busy==='local'&&<div className="export-progress" role="status"><div><span>{voiceProgress.phase==='script'?'Глава '+Math.max(1,voiceProgress.chapter)+' из '+voiceProgress.chapters+' · размечаем роли':'Глава '+voiceProgress.chapter+' из '+voiceProgress.chapters+' · фраза '+voiceProgress.phrases+' из '+voiceProgress.phrasesTotal}{voiceProgress.files?' · готово файлов: '+voiceProgress.files:''}</span><button type="button" className="text-link" onClick={()=>abort.current?.abort()}>Остановить</button></div><div className="export-progress-bar"><i style={{width:Math.round(((Math.max(1,voiceProgress.chapter)-1)+(voiceProgress.phrasesTotal?voiceProgress.phrases/voiceProgress.phrasesTotal:0))/Math.max(1,voiceProgress.chapters)*100)+'%'}}/></div></div>}
  {error&&<p className="inline-error" role="alert">{error}</p>}{done&&<p className="export-hint" role="status">{done}</p>}
  <button className="btn btn-primary export-submit" disabled={!ready||!!busy||!chosen.length}>{destination==='drive'?<Cloud size={17}/>:<Download size={17}/>}{label}</button>
  <p className="export-hint">{hint}</p>
 </form>;
}
