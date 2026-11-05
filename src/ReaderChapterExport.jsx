import {useEffect,useRef,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {Download,LoaderCircle,X} from 'lucide-react';
import MangaExportSettings from './MangaExportSettings.jsx';
import {defaultMangaExport,exportTranslation} from './manga-export-options.js';
import {cachedChapterPages} from './translation-cache.js';
import {exportLocally} from './local-export.js';

export default function ReaderChapterExport({item,scope,total,entries,settings,service,container}){
 const [open,setOpen]=useState(false),[value,setValue]=useState({...defaultMangaExport,...exportTranslation(settings),mode:'cached'}),[cache,setCache]=useState(null),[busy,setBusy]=useState(false),[status,setStatus]=useState(''),[error,setError]=useState(''),abort=useRef(null);
 useEffect(()=>()=>abort.current?.abort(),[item.id]);
 useEffect(()=>{if(!open)return;let closed=false;setCache(null);setError('');cachedChapterPages({scope,chapter:item.id,url:item.sourceURL,total}).then(result=>{if(!closed)setCache(result);}).catch(()=>{if(!closed)setError('Кэш перевода браузера недоступен.');});return()=>{closed=true;};},[open,item.id,scope,total]);
 async function save(){
  setBusy(true);setError('');const controller=new AbortController();abort.current=controller;
  try{
   if(!cache)throw Error('Дождись проверки кэша.');
   await exportLocally({entries:[{url:item.sourceURL,number:item.episode??1,season:item.season||1,title:item.episodeTitle||item.name}],kind:'manga',service,manga:value,cacheContext:{name:item.name,cache,scope,chapter:item.id,total,entries},signal:controller.signal,onProgress:setStatus});
   setStatus('Файл передан браузеру для сохранения.');
  }catch(cause){setError(cause.name==='AbortError'?'Скачивание остановлено.':cause.message);}finally{setBusy(false);}
 }
 return <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Trigger className="reader-control" aria-label="Скачать главу с переводом"><Download size={19}/></Dialog.Trigger><Dialog.Portal container={container||undefined}><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="server-dialog reader-export-panel"><header className="entity-dialog-heading"><Dialog.Title>Сохранить главу</Dialog.Title><Dialog.Close className="circle-button" aria-label="Закрыть скачивание"><X size={18}/></Dialog.Close></header><Dialog.Description className="fine">{cache?'Готово в кэше: '+cache.pages.length+' / '+total+' страниц.':'Проверяем готовые страницы…'}</Dialog.Description><MangaExportSettings chapterOnly value={value} onChange={setValue} disabled={busy}/>{error&&<p className="inline-error" role="alert">{error}</p>}{status&&<p className="fine" role="status">{status}</p>}<div className="form-actions">{busy?<button className="btn btn-secondary" onClick={()=>abort.current?.abort()}>Остановить</button>:null}<button className="btn btn-primary" disabled={busy||!cache||!total||!service} onClick={save}>{busy?<LoaderCircle className="reader-translation-spinner" size={16}/>:<Download size={16}/>}Сохранить на устройство</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>;
}
