import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Settings2,BookOpen,ArrowLeft,ArrowRight,Languages,X,Wifi,ChevronDown} from 'lucide-react';
import {openChapter} from './zip-reader.js';
import {readReading,writeReading} from './reading-progress.js';
import {readSettings,saveSettings} from './reader-settings.js';
import LmtSettings,{readLmt,saveLmt} from './LmtSettings.jsx';
import {translateLmt,stopLmt} from './lmt-client.js';
import ReaderThumbnails from './ReaderThumbnails.jsx';
import TranslationLayer from './TranslationLayer.jsx';
import './manga-reader.css';
import {translationConfig,resultConfig,translateBackend,TranslationQueue,requireRenderedPage} from './manga-translation.js';
import {translationCacheKey,getTranslation,putTranslation,clearTranslations} from './translation-cache.js';
import {translateGemmaBatch} from './gemma-translation.js';
import {GemmaQueue} from './gemma-queue.js';
import {spreadPages,turnPage} from './reader-layout.js';
function Page({index,entry,active,preload,translate,translator,onVisible,onError,font,revision,onProgress,language}){
 const host=useRef(null),[near,setNear]=useState(false),[source,setSource]=useState(''),[ratio,setRatio]=useState(0),[imageSize,setImageSize]=useState({width:0,height:0}),[regions,setRegions]=useState(null),[translated,setTranslated]=useState(''),[message,setMessage]=useState(''),[translating,setTranslating]=useState(false),[attempt,setAttempt]=useState(0),blob=useRef(null);
 useEffect(()=>{const observer=new IntersectionObserver(e=>{setNear(e.some(x=>x.isIntersecting));},{rootMargin:preload?'100% 0px':'0px'});if(host.current)observer.observe(host.current);return()=>observer.disconnect();},[preload]);
 useEffect(()=>{if(!near&&!active){setSource('');return;}let closed=false,url;entry.async('blob').then(b=>{if(closed)return;blob.current=b;url=URL.createObjectURL(b);setSource(url);}).catch(e=>!closed&&onError(e.message));return()=>{closed=true;blob.current=null;if(url)URL.revokeObjectURL(url);};},[entry,near,active]);
 useEffect(()=>{const node=host.current?.querySelector('img');if(!node)return;const observer=new ResizeObserver(entries=>{const r=entries[0].contentRect;setImageSize({width:r.width,height:r.height});});observer.observe(node);return()=>observer.disconnect();},[source]);
 useEffect(()=>{if(!source||!translate||!translator||(!near&&!active))return;let closed=false;const abort=new AbortController();setRegions(null);setTranslating(true);setMessage('Готовим перевод страницы…');let rendered;translator(blob.current,abort.signal,status=>{if(!closed){setMessage(status);onProgress?.(status);}},index).then(data=>{if(!closed){setTranslating(false);if(data.renderedImage){rendered=URL.createObjectURL(new Blob([data.renderedImage],{type:data.renderedMime||'image/webp'}));setTranslated(rendered);}setRegions(data.regions||[]);setMessage((data.warnings||[]).join(' · ')|| (data.cacheHit?'Готово · из кэша':data.message||''));onProgress?.((data.warnings||[]).join(' · ')||(data.cacheHit?'Готово · из кэша':'Перевод готов · фон восстановлен'));}}).catch(e=>{if(!closed){setTranslating(false);setMessage(e.message);onProgress?.(e.message);}});return()=>{closed=true;abort.abort();setTranslated('');if(rendered)URL.revokeObjectURL(rendered);};},[source,translate,translator,attempt,revision,near,active]);
 useEffect(()=>{const observer=new IntersectionObserver(e=>{if(e.some(x=>x.isIntersecting))onVisible(index);},{rootMargin:'-10% 0px -60% 0px'});if(host.current)observer.observe(host.current);return()=>observer.disconnect();},[index,onVisible]);
 return <figure ref={host} className="reader-page" data-page={index}>
  {source?<div className="reader-page-image"><img src={translate&&translated?translated:source} onLoad={e=>setRatio(e.currentTarget.naturalHeight/e.currentTarget.naturalWidth)} alt={'Страница '+(index+1)} decoding="async"/>{translate&&regions?.length>0&&<TranslationLayer rendered={!!translated} regions={regions} size={imageSize} font={font} sourceLanguage={language}/>}
</div>:<div className="reader-page-placeholder" style={ratio?{aspectRatio:1/ratio,minHeight:0}:undefined}>Страница {index+1}</div>}
  {translate&&message&&<figcaption role="status">{message}{!translating&&!translated&&<button onClick={()=>setAttempt(v=>v+1)}>Повторить</button>}</figcaption>}
 </figure>;
}
export default function MangaReader({item,catalog,userId,libraryId,onClose,onSelectItem,readWhole,readRange,readerService,inline=false,retainLmt=false}){
 const format=catalog?.storage?.collections?.find(v=>v.id===item.collectionId)?.metadata?.format||'';
 const [prefs,setPrefs]=useState(()=>readSettings(userId,undefined,{mode:/manhwa|webtoon|манхва|вебтун/i.test(format)?'scroll':'pages',translate:item.translationInfo?.language==='en'})),[settings,setSettings]=useState(false),[entries,setEntries]=useState([]),[page,setPage]=useState(0),[busy,setBusy]=useState(true),[error,setError]=useState(''),[translationStatus,setTranslationStatus]=useState(null);
 const [thumbnails,setThumbnails]=useState(false),[backendStatus,setBackendStatus]=useState(null);
 const scope=String(userId||'anonymous')+':'+String(libraryId||'none');
 const [lmt,setLmt]=useState(()=>{const value=readLmt(userId),language={en:'English',ja:'Japanese',jp:'Japanese',ko:'Korean',zh:'Chinese (Simplified)'}[item.translationInfo?.language];return language?{...value,language,ocr:'auto'}:value;}),lmtRef=useRef(lmt);lmtRef.current=lmt;
 useEffect(()=>()=>{if(!retainLmt)stopLmt();},[retainLmt]);
 useEffect(()=>{const language={en:'English',ja:'Japanese',jp:'Japanese',ko:'Korean',zh:'Chinese (Simplified)'}[item.translationInfo?.language];if(language)setLmt(old=>old.language===language?old:{...old,language,ocr:'auto'});},[item.id]);
 const swipe=useRef(null),[wide,setWide]=useState(()=>matchMedia('(min-width:900px)').matches);
 useEffect(()=>{const mq=matchMedia('(min-width:900px)'),update=()=>setWide(mq.matches);mq.addEventListener('change',update);return()=>mq.removeEventListener('change',update);},[]);
 const effectiveMode=prefs.mode==='spread'&&!wide?'pages':prefs.mode;
 const move=delta=>setPage(p=>turnPage(p,delta,entries.length,effectiveMode==='spread'));
 const root=useRef(null),generation=useRef(0),savedPage=useRef(0),nextEntries=useRef(null),jobs=useRef(new Map()),current=useRef(item),translatorRef=useRef(null);current.current=item;
 const chapters=(catalog?.items||[]).filter(v=>v.category==='manga'&&v.collectionId===item.collectionId&&(v.dub||'')===(item.dub||'')&&(v.translationInfo?.language||'ru')===(item.translationInfo?.language||'ru')).sort((a,b)=>(Number(a.season)||1)-(Number(b.season)||1)||(Number(a.episode)||0)-(Number(b.episode)||0));
 const index=chapters.findIndex(v=>v.id===item.id),next=chapters[index+1],saveData=navigator.connection?.saveData===true;
 function update(change){setPrefs(old=>{const value={...old,...change};saveSettings(userId,value);return value;});}
 useEffect(()=>{const previous=document.body.style.overflow;if(!inline)document.body.style.overflow='hidden';const close=()=>onClose();window.addEventListener('mediavault-locked',close);return()=>{document.body.style.overflow=previous;window.removeEventListener('mediavault-locked',close);};},[inline,onClose]);
 useEffect(()=>{const abort=new AbortController(),version=++generation.current;setBusy(true);setError('');setEntries([]);jobs.current.clear();savedPage.current=readReading(userId,libraryId,item.id)?.page||0;
  (async()=>{const saved=nextEntries.current;nextEntries.current=null;let data;try{data=saved?.id===item.id?await saved.promise:await openChapter(item,readWhole,readRange,abort.signal);}catch(e){if(saved?.id!==item.id||abort.signal.aborted)throw e;data=await openChapter(item,readWhole,readRange,abort.signal);}const blobs=new Map();data=data.map((entry,n)=>({...entry,async:()=>{if(!blobs.has(n)){const task=entry.async('blob');task.catch(()=>blobs.delete(n));blobs.set(n,task);while(blobs.size>5)blobs.delete(blobs.keys().next().value);}return blobs.get(n);}}));if(abort.signal.aborted||version!==generation.current)return;setEntries(data);setPage(Math.min(savedPage.current,data.length-1));setBusy(false);})().catch(e=>{if(!abort.signal.aborted){setBusy(false);setError(e.message);}});
  return()=>abort.abort();
 },[item.id,userId,libraryId,readWhole,readRange]);
 useEffect(()=>{if(!entries.length)return;writeReading(userId,libraryId,item,effectiveMode==='spread'?spreadPages(page,entries.length).at(-1):page,entries.length);},[page,entries.length,item.id,effectiveMode]);
 useEffect(()=>{if(!entries.length||!prefs.preload||saveData)return;const timer=setTimeout(()=>{for(let i=page+1;i<=Math.min(entries.length-1,page+prefs.preload);i++)if(!jobs.current.has(i)){const task=entries[i].async('blob').catch(()=>null);jobs.current.set(i,task);}for(const key of jobs.current.keys())if(key<page-1||key>page+prefs.preload)jobs.current.delete(key);},150);return()=>clearTimeout(timer);},[page,entries,prefs.preload,saveData]);
 useEffect(()=>{if(!prefs.nextChapter||saveData||!next||!readRange||!entries.length||page<entries.length-3)return;const abort=new AbortController();const promise=openChapter(next,readWhole,readRange,abort.signal);promise.catch(()=>{});nextEntries.current={id:next.id,promise};return()=>abort.abort();},[next?.id,prefs.nextChapter,saveData,page>=entries.length-3,entries.length]);
 useEffect(()=>{const key=e=>{if(e.defaultPrevented||e.target.closest?.('input,select,textarea'))return;if(e.key==='Escape'){if(settings)setSettings(false);else onClose();}if(['ArrowLeft','ArrowRight'].includes(e.key)&&effectiveMode!=='scroll'){e.preventDefault();const delta=(e.key==='ArrowRight'?1:-1)*(prefs.direction==='rtl'?-1:1);move(delta);}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[entries.length,prefs.direction,effectiveMode,settings,onClose]);
 useEffect(()=>{if(prefs.mode==='scroll'&&entries.length){const timer=setTimeout(()=>root.current?.querySelector('[data-page="'+savedPage.current+'"]')?.scrollIntoView({block:'start'}),60);return()=>clearTimeout(timer);}},[entries,prefs.mode]);
 const visibleRef=useRef(null);visibleRef.current=n=>{if(prefs.mode==='scroll')setPage(n);};const onVisible=useRef(n=>visibleRef.current(n)).current;
 const serviceRef=useRef(readerService);serviceRef.current=readerService;
 const queueRef=useRef(null),revision=JSON.stringify(resultConfig(lmt));
 useEffect(()=>{let closed=false;const server=readerService?.server||window.MEDIA_VAULT_CONFIG?.importServerUrl;if(!server)return;fetch(server+'/reader/lmt/status',{signal:AbortSignal.timeout(10000)}).then(async r=>{if(!r.ok)throw Error('Полный LMT ещё не установлен на ВМ. Старый обработчик с метками больше не используется.');return r.json();}).then(v=>{if(!closed){setBackendStatus(v);if(v.gemma?.promptVersion)setLmt(old=>old.gemmaPromptVersion===v.gemma.promptVersion?old:{...old,gemmaPromptVersion:v.gemma.promptVersion});}}).catch(e=>{if(!closed)setBackendStatus({ready:false,message:e.message});});return()=>{closed=true;};},[readerService?.server]);
 useLayoutEffect(()=>{queueRef.current?.close();
  const runGemma=async(inputs,signal,status)=>{
   const results=Array(inputs.length),pending=[],indices=[],keys=[];
   for(const [i,input]of inputs.entries()){
    signal.throwIfAborted();const key=await translationCacheKey(input.blob,input.config,scope);keys[i]=key;
    const cached=input.config.cache?await getTranslation(key,scope):null;
    if(cached){results[i]=cached;status(i,'Готово · из кэша');}else{pending.push(input);indices.push(i);}
   }
   if(pending.length){
    const until=Date.now()+20000;while(serviceRef.current?.status==='connecting'&&Date.now()<until){signal.throwIfAborted();await new Promise(r=>setTimeout(r,200));}
    let translated;try{translated=await translateGemmaBatch(pending,serviceRef.current,signal,(n,text)=>status(indices[n],text));}catch(error){translated=pending.map(()=>error);}
    for(const [n,result]of translated.entries()){
     const i=indices[n];results[i]=result;signal.throwIfAborted();
     if(!(result instanceof Error)&&inputs[i].config.cache)await putTranslation(keys[i],scope,result);
    }
   }
   signal.throwIfAborted();return results;
  };
  queueRef.current=lmt.engine==='gemma'?new GemmaQueue(runGemma):new TranslationQueue(async({blob,config},signal,status)=>{
  signal.throwIfAborted();const cacheKey=await translationCacheKey(blob,config,scope);signal.throwIfAborted();
  if(config.cache){const cached=await getTranslation(cacheKey,scope);signal.throwIfAborted();if(cached){status('Готово · из кэша');return cached;}}
  let result;
  if(config.engine==='backend'){
   const until=Date.now()+20000;while(serviceRef.current?.status==='connecting'&&Date.now()<until){signal.throwIfAborted();await new Promise(r=>setTimeout(r,200));}
   result=await translateBackend(blob,config,serviceRef.current,signal,status);
  }else result=requireRenderedPage(await translateLmt(blob,config,signal,status));
  signal.throwIfAborted();if(config.cache)await putTranslation(cacheKey,scope,result);signal.throwIfAborted();return result;
 });const queue=queueRef.current;return()=>{queue.close();stopLmt();};},[item.id,revision,scope,prefs.translate]);
 if(!translatorRef.current)translatorRef.current=async(blob,signal,status,pageIndex,background=false)=>{
  signal.throwIfAborted();const config={...translationConfig(lmtRef.current),pageIndex,contextKey:current.current.metadataId||current.current.collectionId||current.current.id};
  const queue=queueRef.current;if(!queue)throw Error('Переводчик запускается.');
  const key=current.current.id+':'+pageIndex+':'+JSON.stringify(resultConfig(config));
  return queue.request(key,{blob,config},{background,status});
 };
 useEffect(()=>{if(!prefs.translate||!entries.length||saveData||!lmt.prefetch)return;const controller=new AbortController();const timer=setTimeout(()=>{
  const count=lmtRef.current.prefetch||0;for(let i=page+1;i<=Math.min(entries.length-1,page+count);i++)entries[i].async('blob').then(blob=>{controller.signal.throwIfAborted();return translatorRef.current(blob,controller.signal,null,i,true);}).catch(()=>{});
 },600);return()=>{clearTimeout(timer);controller.abort();};},[page,entries,prefs.translate,lmt.prefetch,revision,saveData]);
 useEffect(()=>{if(!prefs.translate){queueRef.current?.close();queueRef.current=null;stopLmt();}},[prefs.translate]);
 async function enableTranslation(){
  if(prefs.translate){update({translate:false});return;}
  if(lmtRef.current.engine!=='backend'&&!lmtRef.current.allowDownloads){setTranslationStatus('Разреши загрузку моделей на устройство.');return;}
  // A cached page can be read even when the VM is unavailable. New work gives
  // a clear actionable error; it never silently falls back to text markers.
  update({translate:true});setTranslationStatus('Запускаем полный перевод с восстановлением фона.');
 }
 const indices=effectiveMode==='scroll'?Array.from({length:entries.length},(_,i)=>i):effectiveMode==='spread'?spreadPages(page,entries.length):[page];
 return <section id="viewer" ref={root} className={'mv-viewer manga-reader reader-theme-'+prefs.theme+(inline?' mv-viewer-inline':'')} role={inline?'region':'dialog'} aria-modal={inline?undefined:'true'} aria-label={item.name}>
  <header className="mv-viewer-head reader-toolbar"><button className="mv-icon-button" aria-label="Закрыть просмотр" onClick={onClose}><ArrowLeft size={20}/></button><div className="mv-viewer-title"><small><BookOpen size={12}/> Читалка · {prefs.mode==='scroll'?'Вебтун':'Манга'}</small><strong>{item.name}</strong></div><button className="mv-icon-button" aria-label={prefs.translate?"Показать оригинал страницы":"Перевести страницу на русский"} aria-pressed={prefs.translate} onClick={enableTranslation}><Languages size={20}/></button><button className="mv-icon-button" aria-label="Настройки читалки" aria-expanded={settings} onClick={()=>setSettings(!settings)}><Settings2 size={20}/></button></header>
  {prefs.translate&&<div className="reader-translation-notice"><Languages size={13}/><span>{translationStatus||(lmt.engine==='gemma'?'Gemma 4 → RU · детекция и LaMa на устройстве':lmt.engine==='backend'?'Hy-MT2 → RU · полный перевод на ВМ':lmt.mode==='api'?'LMT · свой LLM-сервер':'LMT · перевод на устройстве')}</span><button onClick={()=>update({translate:false})}>Оригинал</button></div>}
  {settings&&<aside className="reader-settings" aria-label="Настройки читалки"><div className="reader-settings-heading"><strong>Твой ритм чтения</strong><button aria-label="Закрыть настройки читалки" onClick={()=>setSettings(false)}><X size={18}/></button></div><LmtSettings value={lmt} backendStatus={backendStatus} onClearCache={()=>clearTranslations(scope).then(()=>setTranslationStatus('Кэш перевода очищен.')).catch(()=>setTranslationStatus('Не удалось открыть кэш браузера.'))} onChange={value=>{setLmt(value);saveLmt(userId,value);}}/><button className="reader-translate-toggle" aria-pressed={prefs.translate} onClick={enableTranslation}><Languages size={17}/>{prefs.translate?'Показать оригинал':'Перевести страницу на русский'}</button><small role="status">{translationStatus||(lmt.engine==='gemma'?'Детекция, перевод Gemma, LaMa и набор по стилю оригинала.':'OCR, перевод, восстановление фона и автовёрстка. Результат сохраняется отдельно от оригинала.')}</small><details className="reader-layout-settings"><summary>Вид и навигация</summary>{onSelectItem&&chapters.length>1&&<label>Глава / том<select aria-label="Перейти к главе" value={item.id} onChange={e=>onSelectItem(chapters.find(v=>v.id===e.target.value))}>{chapters.map(v=><option key={v.id} value={v.id}>Том {v.season||1} · Глава {v.episode??'?'}{v.episodeTitle?' · '+v.episodeTitle:''}</option>)}</select></label>}<label>Режим<select aria-label="Режим чтения" value={prefs.mode} onChange={e=>update({mode:e.target.value})}><option value="pages">По страницам</option><option value="spread">Книжный разворот · 2 страницы</option><option value="scroll">Вебтун · непрерывная лента</option></select></label><label>Масштаб<select aria-label="Масштаб страницы" value={prefs.fit} onChange={e=>update({fit:e.target.value})}><option value="width">По выбранной ширине</option><option value="page">Вписать страницу целиком</option></select></label><label>Направление<select aria-label="Направление чтения" value={prefs.direction} onChange={e=>update({direction:e.target.value})}><option value="ltr">Слева направо</option><option value="rtl">Справа налево</option></select></label><label>Ширина<select aria-label="Ширина страницы" value={prefs.width} onChange={e=>update({width:Number(e.target.value)})}>{[640,900,1200,1600].map(v=><option key={v} value={v}>{v} px</option>)}</select></label><label>Тема<select value={prefs.theme} onChange={e=>update({theme:e.target.value})}><option value="dark">Тёмная</option><option value="black">Чёрная · OLED</option><option value="paper">Бумага</option></select></label><label>Предзагрузка страниц<select aria-label="Предзагрузка страниц" value={prefs.preload} onChange={e=>update({preload:Number(e.target.value)})}>{[0,1,2,4].map(n=><option key={n} value={n}>{n||'Выключена'}</option>)}</select></label><label className="reader-checkbox"><input type="checkbox" checked={prefs.nextChapter} onChange={e=>update({nextChapter:e.target.checked})}/>Подготовить следующую главу</label><p className="reader-hint"><Wifi size={13}/>{saveData?'Экономия трафика устройства: предзагрузка отключена.':'Загружаются нужные части CBZ. Кэш расшифрованных страниц — только в памяти.'} Для меньших файлов выбери экономное качество при импорте.</p></details></aside>}
  <div id="viewerContent" onPointerDown={e=>{if(e.pointerType==='touch'&&!e.isPrimary)swipe.current=null;if(e.pointerType==='touch'&&e.isPrimary&&effectiveMode!=='scroll')swipe.current={x:e.clientX,y:e.clientY};}} onPointerCancel={()=>{swipe.current=null;}} onPointerUp={e=>{const point=swipe.current;swipe.current=null;if(!point||effectiveMode==='scroll')return;const dx=e.clientX-point.x,dy=e.clientY-point.y;if(Math.abs(dx)>70&&Math.abs(dy)<45)move((dx<0?1:-1)*(prefs.direction==='rtl'?-1:1));}} className={'mv-viewer-body mv-viewer-manga reader-content reader-mode-'+effectiveMode+' reader-fit-'+prefs.fit+(prefs.direction==='rtl'?' reader-rtl':'')} style={{'--reader-width':prefs.width+'px'}}>{busy&&<div className="mv-viewer-loading" role="status">Открываем главу…</div>}{error&&<p className="mv-viewer-error" role="alert">{error}</p>}{!busy&&indices.map(i=>entries[i]&&<Page language={lmt.language} onProgress={setTranslationStatus} revision={revision} font={lmt.font||'comic-relief'} key={item.id+':'+i} entry={entries[i]} index={i} active={effectiveMode!=='scroll'} preload={prefs.preload} translate={prefs.translate} translator={translatorRef.current} onVisible={onVisible} onError={setError}/>)}</div>
  {thumbnails&&<ReaderThumbnails entries={entries} page={page} onChoose={n=>{setPage(n);if(effectiveMode==='scroll')root.current.querySelector('[data-page="'+n+'"]')?.scrollIntoView({behavior:'smooth'});}}/>}<footer className="mv-viewer-tools reader-bottom"><button className="mv-button mv-button-secondary" aria-expanded={thumbnails} onClick={()=>setThumbnails(v=>!v)}>Превью страниц</button>{onSelectItem&&chapters.length>1&&<button className="mv-button mv-button-secondary" disabled={index<=0} onClick={()=>onSelectItem(chapters[index-1])} aria-label="Предыдущая глава">← Глава</button>}<button className="mv-button mv-button-secondary" disabled={!entries.length||page===0||busy} onClick={()=>{if(prefs.mode==='scroll')root.current.querySelector('[data-page="'+(page-1)+'"]')?.scrollIntoView({behavior:'smooth'});else move(-1);}}>← Назад</button><span aria-live="polite">{entries.length?(effectiveMode==='spread'&&indices.length>1?indices[0]+1+'–'+(indices.at(-1)+1):page+1):0} / {entries.length}</span><button className="mv-button mv-button-secondary" disabled={!entries.length||indices.at(-1)>=entries.length-1||busy} onClick={()=>{if(prefs.mode==='scroll')root.current.querySelector('[data-page="'+(page+1)+'"]')?.scrollIntoView({behavior:'smooth'});else move(1);}}>Вперёд →</button>{onSelectItem&&chapters.length>1&&<button className="mv-button mv-button-secondary" disabled={!next} onClick={()=>onSelectItem(next)} aria-label="Следующая глава">Глава →</button>}</footer>
 </section>;
}
