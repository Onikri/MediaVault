import {useEffect,useState} from 'react';
import {chooseModelFolder,modelFolderState,restoreModelFolder,forgetModelFolder,requestModelPersistence} from './model-folder.js';

export default function ReaderModelStorage({config}){
 const[state,setState]=useState(null),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[progress,setProgress]=useState(null);
 useEffect(()=>{let closed=false;modelFolderState().then(v=>!closed&&setState(v));return()=>{closed=true;};},[]);
 async function action(fn){setBusy(true);setMessage('');try{setState(await fn());}catch(error){if(error.name!=='AbortError')setMessage(error.message);}finally{setBusy(false);}}
 async function prepare(){
  setBusy(true);setMessage('');setProgress(null);
  try{
   if(state?.name&&state.permission!=='granted')throw Error('Сначала разреши доступ к выбранной папке моделей.');
   await requestModelPersistence();
   const {prepareReaderModels}=await import('./reader-model-pack.js');
   const result=await prepareReaderModels(config,value=>{setProgress(value);setMessage(value.message);});
   setMessage('Пакет готов: '+result+' файлов. Повторно веса не скачиваются; готовый обработчик остаётся в памяти до 2 минут, затем освобождается.');
  }catch(error){setMessage(error.message);}finally{setBusy(false);}
 }
 return <fieldset className="reader-model-storage"><legend>Модели на устройстве</legend>
  <p className="reader-hint">{state?.name?'Папка: '+state.name+' · '+(state.permission==='granted'?'доступ разрешён':'требуется повторное разрешение'):'Используется дисковый кэш браузера. В Chrome/Edge можно выбрать свою папку, например на диске D.'}</p>
  <div className="reader-model-storage-actions">{state?.supported&&<button type="button" disabled={busy} onClick={()=>action(chooseModelFolder)}>Выбрать папку моделей</button>}{state?.name&&state.permission!=='granted'&&<button type="button" disabled={busy} onClick={()=>action(restoreModelFolder)}>Разрешить доступ к папке</button>}{state?.name&&<button type="button" disabled={busy} onClick={()=>action(forgetModelFolder)}>Использовать кэш браузера</button>}<button type="button" disabled={busy} onClick={prepare}>{busy?'Подготавливаем модели…':'Скачать выбранный пакет моделей'}</button></div>
  {busy&&!(progress?.total>0)&&<progress aria-label="Подготовка модели"/>}
  {progress?.total>0&&<progress aria-label="Загрузка модели" value={progress.loaded} max={progress.total}/>}
  {message&&<p role="status">{message}</p>}
  <p className="reader-hint">В пакете — выбранный детектор и инпейнт; для локального Hy-MT2 / Index также OCR и переводчик. Веса проверяются по SHA-256. Разрешение на папку хранится в IndexedDB; браузер может запросить его повторно. Cookies не используются. API-ключи и страницы манги в папку моделей не записываются.</p>
 </fieldset>;
}
