import {useEffect,useState} from 'react';
import {translationProgressDetails} from './translation-progress.js';
import ReaderRequestDiagnostics from './ReaderRequestDiagnostics.jsx';
export default function ReaderTranslationProgress({progress,fallback,onRetry,onRerender,allowRefresh=false,showDiagnostics=false}){
 const[now,setNow]=useState(Date.now);
 useEffect(()=>{if(!progress?.running)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[progress?.running,progress?.startedAt]);
 const details=translationProgressDetails(progress,now);
 const message=showDiagnostics?progress?.message||fallback:progress?.phase==='error'?progress.message:progress?.renderIncomplete?'Часть областей сохранена в оригинале':progress?.running?({cleaning:'Восстанавливаем фон…',rendering:'Готовим русскую страницу…',translating:'Переводим страницу…'}[progress.phase]||'Переводим страницу…'):null;
 if(!message&&!showDiagnostics)return null;
 return <div className={'reader-live-progress'+(progress?.phase==='error'?' reader-live-progress-error':'')} aria-label="Состояние перевода">
  <span role="status" aria-live="polite">{message}</span>
  {showDiagnostics&&details.length>0&&<small>{details.join(' · ')}</small>}
  {progress?.running&&progress.totalRegions>0&&<progress aria-label="Обработанные области текста" max={progress.totalRegions} value={Math.min(progress.totalRegions,progress.completedRegions||0)}/>}
  {progress?.phase==='error'&&<button onClick={onRetry}>{progress?.failureStage==='render'?'Повторить очистку':'Повторить перевод'}</button>}
  {allowRefresh&&progress?.renderIncomplete&&!progress?.running&&<button onClick={onRerender}>Повторить очистку · без Google</button>}
  {showDiagnostics&&allowRefresh&&!progress?.running&&progress?.phase!=='error'&&<button onClick={onRetry}>Повторить без кэша</button>}
  {showDiagnostics&&progress?.inpaint?.regions?.some(r=>r.execution)&&<details className="reader-request-diagnostics"><summary>Выполнение инпейнта</summary><p>Фактический провайдер: WASM / CPU. Наличие видеокарты не означает использование GPU этим графом LaMa.</p>{progress.inpaint.regions.filter(r=>r.execution).map((r,i)=>{const e=r.execution;return <p key={r.uid||i}>Область {i+1} · {e.inputSizes.map(s=>s.join('×')).join(', ')} · запуск {(e.startupMs/1000).toFixed(3)} с · инференс {(e.inferenceMs/1000).toFixed(3)} с · всего {(e.totalMs/1000).toFixed(3)} с · {e.threads} поток(а)</p>;})}</details>}
  {showDiagnostics&&<ReaderRequestDiagnostics value={progress?.diagnostics} now={now}/>}
 </div>;
}
