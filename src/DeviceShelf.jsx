import {useEffect,useState} from 'react';
import {FolderOpen,HardDrive,Play,Music2,FileText,ImageIcon,RefreshCw,X} from 'lucide-react';
import MediaVaultPlayer from './MediaVaultPlayer.jsx';
import {chooseDeviceFolder,deviceFolderState,fileKind,forgetDeviceFolder,listDeviceLibrary,reconnectDeviceFolder} from './device-library.js';
import './device-shelf.css';

const ICON={video:Play,audio:Music2,image:ImageIcon,pdf:FileText,file:FileText};
// The collection's own shelf for what is saved on this device. It reads the
// folder directly, so it works with no network and no Google session.
export default function DeviceShelf({userId}){
 const [state,setState]=useState(null),[titles,setTitles]=useState([]),[error,setError]=useState(''),[playing,setPlaying]=useState(null);
 async function refresh(){try{const next=await deviceFolderState();setState(next);setTitles(next.ready?await listDeviceLibrary():[]);}catch(e){setError(e.message);}}
 useEffect(()=>{refresh();const update=()=>refresh();addEventListener('mediavault-device-library',update);return()=>removeEventListener('mediavault-device-library',update);},[]);
 useEffect(()=>()=>{if(playing?.url)URL.revokeObjectURL(playing.url);},[playing?.url]);
 async function act(run){setError('');try{setState(await run());setTitles(await listDeviceLibrary());}catch(e){if(e?.name!=='AbortError')setError(e.message||'Не получилось.');}}
 async function open(title,entry){
  const file=await entry.handle.getFile(),kind=fileKind(entry.name),url=URL.createObjectURL(file);
  if(kind==='video'||kind==='audio'){setPlaying({url,kind,name:entry.name,title:title.title});return;}
  window.open(url,'_blank','noopener');setTimeout(()=>URL.revokeObjectURL(url),60000);
 }
 if(!state)return null;
 const item=playing&&{id:'device:'+playing.title+':'+playing.name,name:playing.name.replace(/\.[^.]+$/,''),category:playing.kind==='audio'?'audio':'video',section:'video',onlineType:'mp4'};
 return <section className="device-shelf" aria-labelledby="device-shelf-title">
  <header className="device-shelf-head">
   <span className="device-shelf-icon" aria-hidden="true"><HardDrive size={20}/></span>
   <div><h2 id="device-shelf-title">На этом устройстве</h2><p>{state.mode==='folder'?<>Папка «{state.name}». Сохранённое лежит без шифрования и открывается без интернета.</>:state.mode==='browser'?'Память браузера на этом устройстве. Сохранённое открывается без интернета.':'Выбери, куда сохранять серии, главы, книги и музыку. Зашифрованная копия остаётся только на Google Диске.'}</p></div>
   <div className="device-shelf-actions">
    {state.mode==='none'&&<button type="button" className="btn btn-primary" onClick={()=>act(chooseDeviceFolder)}><FolderOpen size={16}/>{state.canPick?'Выбрать папку':'Хранить в браузере'}</button>}
    {state.mode==='folder'&&!state.ready&&<button type="button" className="btn btn-primary" onClick={()=>act(reconnectDeviceFolder)}><RefreshCw size={16}/>Открыть доступ к папке</button>}
    {state.mode!=='none'&&<button type="button" className="text-link" onClick={()=>act(async()=>{await forgetDeviceFolder();return deviceFolderState();})}>Отключить</button>}
   </div>
  </header>
  {error&&<p className="inline-error" role="alert">{error}</p>}
  {playing&&<div className="device-shelf-player"><button type="button" className="circle-button" aria-label="Закрыть" onClick={()=>setPlaying(null)}><X size={17}/></button><MediaVaultPlayer key={item.id} item={item} source={playing.url} userId={userId} libraryId="device" autoPlay catalog={{items:[item]}}/></div>}
  {state.ready&&(titles.length?<div className="device-shelf-titles">{titles.map(title=><article key={title.id} className="device-title"><h3>{title.title}<small>{title.folder}</small></h3><ol>{title.files.slice(0,60).map(entry=>{const Icon=ICON[fileKind(entry.name)];return <li key={entry.name}><button type="button" onClick={()=>open(title,entry).catch(e=>setError(e.message))}><Icon size={14} aria-hidden="true"/><span>{entry.name}</span></button></li>;})}</ol></article>)}</div>
   :<p className="device-shelf-empty">Пока пусто. Нажми «Сохранить» на странице тайтла и выбери «На устройство».</p>)}
 </section>;
}
