import {useEffect, useRef, useState} from 'react';
import MangaReader from './MangaReader.jsx';
import BookReader from './BookReader.jsx';
import VideoPlayer from './VideoPlayer.jsx';
import {readReading,writeReading} from './reading-progress.js';

const names={video:'Видео',audio:'Музыка',image:'Изображение',manga:'Манга',book:'Книга'};
async function libraryReady(name,signal){
  for(let attempt=0;attempt<60;attempt++){
    if(signal.aborted)throw new DOMException('Операция отменена','AbortError');
    if(window[name])return window[name];
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw Error('Не удалось загрузить обработчик книги или архива. Проверь подключение к сети.');
}

function LegacyMediaViewer({item,catalog,libraryId,userId,onSelectItem,onClose,readWhole,prepareStream,onError,inline=false,renderEpisodeArtwork,onPlaybackChange}) {
  const [source,setSource]=useState('');
  const [text,setText]=useState('');
  const [busy,setBusy]=useState(true);
  const [error,setError]=useState('');
  const [page,setPage]=useState(0);
  const [pageCount,setPageCount]=useState(0);
  const [rendition,setRendition]=useState(null);
  const panelRef=useRef(null);
  const mediaRef=useRef(null);
  const epubHost=useRef(null);
  const bookRef=useRef(null);
  const entriesRef=useRef([]);
  const urls=useRef(new Set());
  const generation=useRef(0);
  const pageRequest=useRef(0);
  const pageUrl=useRef('');
  const mediaUrl=useRef('');
  const loadAbort=useRef(null);
  const methods=useRef({readWhole,prepareStream,onError});
  methods.current={readWhole,prepareStream,onError};
  const extension=item.name.toLowerCase().split('.').pop();
  const isMedia=item.category==='video'||item.category==='audio';
  const chapters=item.category==='manga'?(catalog?.items||[]).filter(value=>value.category==='manga'&&value.collectionId===item.collectionId&&(!item.dub||value.dub===item.dub)).sort((a,b)=>(Number(a.season)||1)-(Number(b.season)||1)||(Number(a.episode)||0)-(Number(b.episode)||0)):[];
  const chapterIndex=chapters.findIndex(value=>value.id===item.id);
  useEffect(()=>{if(item.category!=='manga'||!pageCount)return;const handler=event=>{if(event.defaultPrevented||event.target.closest?.('input,textarea,select,[contenteditable=true]')||inline&&!panelRef.current?.contains(document.activeElement))return;if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();setPage(value=>Math.max(0,Math.min(pageCount-1,value+(event.key==='ArrowRight'?1:-1))));};window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler);},[item.category,pageCount,inline]);

  function report(cause){
    const message=cause?.message||String(cause);
    setError(message);setBusy(false);methods.current.onError?.(cause);
  }
  function objectUrl(blob){
    const url=URL.createObjectURL(blob);urls.current.add(url);return url;
  }

  useEffect(()=>{
    const previousOverflow=document.body.style.overflow;
    if(!inline)document.body.style.overflow='hidden';
    const onKey=event=>{if(inline&&!panelRef.current?.contains(document.activeElement))return;const dialog=event.target.closest?.('[role="dialog"]');if(event.key==='Escape'&&!event.defaultPrevented&&(!dialog||dialog===panelRef.current))onClose();};
    window.addEventListener('keydown',onKey);
    return ()=>{document.body.style.overflow=previousOverflow;window.removeEventListener('keydown',onKey);};
  },[onClose,inline]);

  useEffect(()=>{
    const current=++generation.current;
    const abort=new AbortController();
    loadAbort.current=abort;
    const activeMedia=mediaRef.current;
    const active=()=>generation.current===current&&!abort.signal.aborted;
    setSource('');setText('');setBusy(true);setError('');
    setPage(0);setPageCount(0);setRendition(null);entriesRef.current=[];
    (async()=>{
      if(isMedia){
        const stream=await methods.current.prepareStream(item);
        if(active()){setSource(stream||'');setBusy(false);if(!stream)setError('Потоковый просмотр недоступен: браузер не активировал Service Worker или отсутствует сеанс Drive. Переподключи Google Drive, обнови страницу либо используй резервную загрузку.');}
        return;
      }
      // The signal also lets a reader that supports cancellation stop its download.
      const blob=await methods.current.readWhole(item,{signal:abort.signal});
      if(!active())return;
      if(item.category==='image'||extension==='pdf'){
        setSource(objectUrl(blob));
      }else if(item.category==='manga'){
        const {default:JSZip}=await import('jszip');
        const zip=await JSZip.loadAsync(blob);
        if(!active())return;
        const entries=Object.values(zip.files).filter(entry=>!entry.dir&&/\.(jpe?g|png|webp|gif|avif)$/i.test(entry.name))
          .sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
        if(!entries.length)throw Error('В архиве нет изображений.');
        entriesRef.current=entries;const saved=readReading(userId,libraryId,item.id);setPage(saved&&saved.page<entries.length?saved.page:0);setPageCount(entries.length);
      }else if(extension==='txt'){
        const content=await blob.text();if(active())setText(content);
      }else if(extension==='epub'){
        const ePub=await libraryReady('ePub',abort.signal);
        const data=await blob.arrayBuffer();if(!active())return;
        const book=ePub(data);bookRef.current=book;
        const view=book.renderTo(epubHost.current,{width:'100%',height:'100%',flow:'paginated',allowScriptedContent:false});
        await view.display();if(active())setRendition(view);
      }else throw Error('Для книг поддерживаются PDF, EPUB и TXT.');
      if(active())setBusy(false);
    })().catch(cause=>{if(active()&&cause?.name!=='AbortError')report(cause);});
    return ()=>{
      abort.abort();generation.current++;pageRequest.current++;
      const media=activeMedia;
      if(media){media.pause();media.removeAttribute('src');media.load();}
      if(bookRef.current){
        // EPUB.js 0.3.93 revokes archive cache keys rather than their Blob URLs.
        for(const url of Object.values(bookRef.current.archive?.urlCache||{})){
          if(typeof url==='string'&&url.startsWith('blob:'))URL.revokeObjectURL(url);
        }
        try{bookRef.current.destroy();}catch{}bookRef.current=null;
      }
      for(const url of urls.current)URL.revokeObjectURL(url);
      urls.current.clear();pageUrl.current='';mediaUrl.current='';entriesRef.current=[];
    };
  },[item.id]);

  useEffect(()=>{
    if(!pageCount)return;
    const request=++pageRequest.current;
    const current=generation.current;
    setBusy(true);
    entriesRef.current[page].async('blob').then(blob=>{
      if(request!==pageRequest.current||current!==generation.current)return;
      const next=objectUrl(blob);
      if(pageUrl.current){URL.revokeObjectURL(pageUrl.current);urls.current.delete(pageUrl.current);}
      pageUrl.current=next;setSource(next);setBusy(false);writeReading(userId,libraryId,item,page,pageCount);
    }).catch(cause=>{if(request===pageRequest.current&&current===generation.current)report(cause);});
  },[page,pageCount]);

  async function fallback(){
    const current=generation.current;
    setBusy(true);setError('');
    try{
      const blob=await methods.current.readWhole(item,{signal:loadAbort.current?.signal});
      if(current!==generation.current)return;
      const media=mediaRef.current;if(media)media.pause();
      const next=objectUrl(blob);
      if(mediaUrl.current){URL.revokeObjectURL(mediaUrl.current);urls.current.delete(mediaUrl.current);}
      mediaUrl.current=next;setSource(next);setBusy(false);
    }catch(cause){if(current===generation.current)report(cause);}
  }

  return <section id="viewer" ref={panelRef} className={'mv-viewer'+(inline?' mv-viewer-inline':'')} role={inline?'region':'dialog'} aria-modal={inline?undefined:'true'} aria-label={item.name}>
    <header className="mv-viewer-head">
      <button id="closeViewer" className="mv-icon-button" aria-label="Закрыть просмотр" onClick={onClose}>←</button>
      <div className="mv-viewer-title"><small>{names[item.category]||'Файл'}</small><strong>{item.name}</strong></div>
    </header>
    <div id="viewerContent" className={'mv-viewer-body'+(item.category==='manga'?' mv-viewer-manga':item.category==='video'?' mv-viewer-video':'')}>
      {busy&&<div className="mv-viewer-loading" role="status">Расшифровка на устройстве…</div>}
      {error&&<div className="mv-viewer-error" role="alert">{error}</div>}
      {isMedia&&(item.category==='video'
        ?<VideoPlayer userId={userId} item={item} source={source} catalog={catalog} libraryId={libraryId} mediaRef={mediaRef} onSelectItem={onSelectItem} onError={report} busy={busy} renderEpisodeArtwork={renderEpisodeArtwork} onPlaybackChange={onPlaybackChange}/>
        :<audio ref={mediaRef} src={source||undefined} controls preload="metadata" onError={()=>source&&report(Error('Браузер не смог воспроизвести аудио. Попробуй загрузить файл целиком.'))}/>)}
      {isMedia&&!source&&!busy&&!error&&<p>Потоковое воспроизведение недоступно. Загрузи файл целиком.</p>}
      {(item.category==='image'||item.category==='manga')&&source&&<img src={source} alt={item.category==='manga'?'Страница '+(page+1):item.name}/>}
      {item.category==='book'&&extension==='pdf'&&source&&<iframe src={source} title={item.name}/>}
      {item.category==='book'&&extension==='txt'&&!busy&&<pre>{text}</pre>}
      {item.category==='book'&&extension==='epub'&&<div className="mv-epub-host" ref={epubHost}/>}
    </div>
    <footer className="mv-viewer-tools">
      {isMedia&&<button className="mv-button mv-button-secondary" disabled={busy} onClick={fallback}>Загрузить файл целиком (резервный режим)</button>}
      {item.category==='manga'&&pageCount>0&&<>
        {onSelectItem&&chapters.length>1&&<button className="mv-button mv-button-secondary manga-chapter-switch" disabled={chapterIndex<=0} onClick={()=>onSelectItem(chapters[chapterIndex-1])} aria-label="Предыдущая глава">← Глава</button>}
        <button className="mv-button mv-button-secondary" disabled={page===0||busy} onClick={()=>setPage(value=>Math.max(0,value-1))}>← Назад</button>
        <span aria-live="polite">{page+1} / {pageCount}</span>
        <button className="mv-button mv-button-secondary" disabled={page===pageCount-1||busy} onClick={()=>setPage(value=>Math.min(pageCount-1,value+1))}>Вперёд →</button>
        {onSelectItem&&chapters.length>1&&<button className="mv-button mv-button-secondary manga-chapter-switch" disabled={chapterIndex<0||chapterIndex>=chapters.length-1} onClick={()=>onSelectItem(chapters[chapterIndex+1])} aria-label="Следующая глава">Глава →</button>}
      </>}
      {rendition&&<>
        <button className="mv-button mv-button-secondary" onClick={()=>rendition.prev().catch(report)}>← Назад</button>
        <button className="mv-button mv-button-secondary" onClick={()=>rendition.next().catch(report)}>Вперёд →</button>
      </>}
    </footer>
  </section>;
}

export default function MediaViewer(props){return props.item.category==='manga'?<MangaReader {...props}/>:props.item.category==='book'?<BookReader {...props}/>:<LegacyMediaViewer {...props}/>;}
