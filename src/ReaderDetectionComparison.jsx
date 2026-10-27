import {useEffect,useRef,useState} from 'react';
const seconds=n=>Number.isFinite(n)?(n/1000).toFixed(2)+' с':'—';
export default function ReaderDetectionComparison({pageKey,paused,onPause,getBlob,run}){
 const [queued,setQueued]=useState(false),[report,setReport]=useState(null),[progress,setProgress]=useState(null),[error,setError]=useState(''),[selected,setSelected]=useState('annotated'),[source,setSource]=useState(''),[message,setMessage]=useState(''),abort=useRef(null),latest=useRef({getBlob,run});latest.current={getBlob,run};
 useEffect(()=>{setReport(null);setProgress(null);setError('');setSource('');setQueued(false);},[pageKey]);
 useEffect(()=>{
  if(!queued||!paused)return;let closed=false,url;const control=new AbortController();abort.current=control;
  (async()=>{await new Promise(resolve=>setTimeout(resolve,0));control.signal.throwIfAborted();const blob=await latest.current.getBlob();control.signal.throwIfAborted();url=URL.createObjectURL(blob);setSource(url);const result=await latest.current.run(blob,control.signal,value=>{if(!closed)setProgress(value);});if(!closed)setReport(result);})().catch(e=>{if(!closed)setError(control.signal.aborted?'Сравнение остановлено.':e.message);}).finally(()=>{if(!closed)setQueued(false);});
  return()=>{closed=true;control.abort(new DOMException('Сравнение закрыто','AbortError'));};
 },[queued,paused,pageKey]);
 useEffect(()=>()=>{if(source)URL.revokeObjectURL(source);},[source]);
 const rows=report?.results||progress?.results||[],active=rows.find(r=>r.input===selected),regions=active?.regions||[];
 async function copy(){try{await navigator.clipboard.writeText(JSON.stringify(report,null,2));setMessage('Отчёт скопирован, без API-ключа.');}catch{setMessage('Не удалось скопировать: используй скачивание отчёта.');}}
 function download(){const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='manga-detection-comparison.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 return <details className="reader-detection-comparison"><summary>Сравнить разметку и поиск Google</summary>
  <p className="reader-hint">Текущая страница, выбранная модель, три отдельных запроса: с рамками, с координатами и без детектора. Обычный перевод будет остановлен. Тест расходует квоту твоего ключа; кэш и инпейнт в сравнении не используются.</p>
  <button type="button" disabled={queued} onClick={()=>{setReport(null);setProgress(null);setError('');setMessage('');onPause();setQueued(true);}}>Сравнить три варианта на этой странице</button>
  {queued&&<button type="button" onClick={()=>abort.current?.abort(new DOMException('Отменено','AbortError'))}>Остановить сравнение</button>}
  <p role="status">{error||progress?.message||''}</p>
  {rows.length>0&&<div className="reader-comparison-table"><table><thead><tr><th>Вариант</th><th>Google</th><th>Блоки</th><th>Запрос</th></tr></thead><tbody>{rows.map(r=><tr key={r.input}><th><button onClick={()=>setSelected(r.input)} aria-pressed={selected===r.input}>{r.input==='annotated'?'Рамки':r.input==='coordinates'?'Координаты':'Сам Google'}</button></th><td>{r.state==='running'?'Идёт…':seconds(r.ms)}</td><td>{r.boxes??'—'}</td><td>{r.requestBytes?(r.requestBytes/1024).toFixed(1)+' КБ':'—'}</td></tr>)}</tbody></table></div>}
  {active?.error&&<p className="reader-request-error">{active.error}</p>}
  {report&&<p className="reader-hint">Подготовка двух копий: {seconds(report.prepareMs)}. {report.notice}</p>}
  {report&&source&&<div className="reader-comparison-image"><img src={source} alt="Страница с координатами выбранного варианта"/><svg viewBox={'0 0 '+report.width+' '+report.height} aria-label="Проверка текстовых координат">{regions.map((r,i)=>{const [x,y,x2,y2]=r.text_bbox;return <g key={r.uid}><rect x={x} y={y} width={x2-x} height={y2-y} fill="none" stroke="#ff496a" strokeWidth="2"/><text x={x} y={Math.max(14,y-3)} fill="#ff496a" stroke="#111" strokeWidth=".5" fontSize="16">{i+1}</text></g>;})}</svg></div>}
  {regions.length>0&&<details><summary>Перевод и координаты · {regions.length} блоков</summary><ol>{regions.map(r=><li key={r.uid}>{r.ru_translation}<small>{r.text_bbox.join(', ')}</small></li>)}</ol></details>}
  {active?.agreement&&<p className="reader-hint">Совпало с локальным детектором: {active.agreement.matched} / {active.agreement.reference}, среднее IoU {(active.agreement.meanIou*100).toFixed(0)}%. Это согласие двух методов, а не проверка правильности по ручной разметке.</p>}
  {report&&<><button type="button" onClick={copy}>Скопировать сравнение без ключа</button><button type="button" onClick={download}>Скачать сравнение</button><small role="status">{message}</small></>}
 </details>;
}
