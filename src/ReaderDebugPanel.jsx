import {useEffect,useState} from 'react';
import {X} from 'lucide-react';
import ReaderRequestDiagnostics from './ReaderRequestDiagnostics.jsx';
import './reader-debug.css';

function useImage(bytes,mime='image/webp'){
 const[url,setUrl]=useState('');
 useEffect(()=>{if(!bytes){setUrl('');return;}const next=URL.createObjectURL(bytes instanceof Blob?bytes:new Blob([bytes],{type:mime}));setUrl(next);return()=>URL.revokeObjectURL(next);},[bytes,mime]);
 return url;
}
export default function ReaderDebugPanel({page,entry,progress,debug,queue,server,onClose,onRerender,onNavigate,total}){
 const[tab,setTab]=useState('detection'),[blob,setBlob]=useState(null),[error,setError]=useState('');
 useEffect(()=>{let closed=false;setBlob(null);setError('');entry?.async('blob').then(b=>!closed&&setBlob(b)).catch(()=>!closed&&setError('Не удалось получить исходник.'));return()=>{closed=true;};},[entry]);
 useEffect(()=>{const key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();onClose();}};window.addEventListener('keydown',key,true);return()=>window.removeEventListener('keydown',key,true);},[onClose]);
 const original=useImage(blob),cleaned=useImage(debug?.cleanedImage),d=progress?.diagnostics;
 const detected=progress?.detected,boxes=detected?.regions||[];
 const modelLoading=/загруз|downloading/i.test(progress?.message||''),percent=modelLoading?Number(progress.message.match(/(\d{1,3})%/)?.[1]):NaN;
 let host='не подключён',serverIp='Не указан в адресе';try{const url=new URL(server);host=url.host;const match=url.hostname.match(/^((?:\d{1,3}\.){3}\d{1,3})(?:\.sslip\.io)?$/);if(match)serverIp=match[1];}catch{}
 return <aside className="reader-debug-panel" aria-label="Отладка страницы" onPointerDown={e=>e.stopPropagation()}>
  <header><div><small>Диагностика ридера</small><strong>Страница {page+1} / {total}</strong></div><button className="reader-control" aria-label="Закрыть отладку" onClick={onClose}><X size={18}/></button></header>
  <div className="reader-debug-navigation"><button disabled={page<1} onClick={()=>onNavigate(page-1)}>Назад</button><button disabled={page>=total-1} onClick={()=>onNavigate(page+1)}>Вперёд</button></div>
  <div className="reader-debug-tabs" role="tablist" aria-label="Данные страницы">{[['detection','Рамки'],['cleaning','Очистка'],['request','Запрос'],['queue','Очередь']].map(([id,label])=><button key={id} role="tab" aria-selected={tab===id} onClick={()=>setTab(id)}>{label}</button>)}</div>
  <div className="reader-debug-body" role="tabpanel">
   {error&&<p role="alert">{error}</p>}
   {tab==='detection'&&<><p>{boxes.length} областей локального детектора. Это его фактические координаты, до корректировок Google.</p>{original&&<figure className="reader-debug-image"><img src={original} alt="Исходная страница с рамками детектора"/>{detected&&<svg viewBox={'0 0 '+detected.width+' '+detected.height} aria-label="Рамки детектора">{boxes.map((r,i)=>{const b=r.bbox;return Array.isArray(b)&&b.length===4?<g key={r.id||i}><rect x={b[0]} y={b[1]} width={b[2]-b[0]} height={b[3]-b[1]}/><text x={b[0]} y={Math.max(14,b[1]-4)}>{r.id||i+1}</text></g>:null;})}</svg>}</figure>}{!detected&&<p>Разметка пока не получена. Для результата из кэша нажми «Пересобрать отладку»; запрос Google повторяться не будет при наличии сохранённого JSON.</p>}<pre>{JSON.stringify(detected||{},null,2)}</pre></>}
   {tab==='cleaning'&&<><p>Фон после инпейнта, до нанесения перевода.</p>{cleaned?<img className="reader-debug-cleaned" src={cleaned} alt="Очищенная страница до нанесения перевода"/>:<p>Промежуточный фон не сохранён. Пересобери страницу при открытой отладке.</p>}<pre>{JSON.stringify(progress?.inpaint||{},null,2)}</pre></>}
   {tab==='request'&&(d?<ReaderRequestDiagnostics value={d} now={Date.now()}/>:<p>Запрос пока не отправлен либо результат взят из кэша. Повторная отправка ради диагностики не выполняется.</p>)}
   {tab==='queue'&&<><dl><dt>Сервер</dt><dd>{host}</dd><dt>IP сервера из адреса</dt><dd>{serverIp}</dd><dt>Исходящий IP Oracle</dt><dd>Не измерен этим запросом</dd><dt>Активные пакеты</dt><dd>{queue?.active??0}</dd><dt>Ожидают</dt><dd>{queue?.queued??0}</dd></dl><p>Показаны номера слотов, без значений API-ключей. Фаза загрузки модели отображает фактические сообщения; процент появляется только при известном размере.</p><p role="status">{progress?.message||'Нет активной обработки'}</p>{modelLoading&&(Number.isFinite(percent)?<progress aria-label="Загрузка модели" value={Math.min(100,percent)} max={100}/>:<progress aria-label="Подготовка модели"/>)}{queue?.jobs?.map(job=><div className="reader-debug-job" key={job.page}>Страница {job.page} · {{queued:'ожидает',running:'обрабатывается',done:'готово',failed:'ошибка'}[job.state]||job.state}{job.keySlot?' · '+(job.serverKey?'Oracle':'Личный ключ')+' №'+job.keySlot:''}</div>)}</>}
   <button className="reader-debug-rerender" onClick={onRerender} disabled={progress?.running}>Пересобрать отладку · очистка и набор</button>
  </div>
 </aside>;
}
