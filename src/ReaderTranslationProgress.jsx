import {useEffect,useState} from 'react';
import {translationProgressDetails} from './translation-progress.js';
import ReaderRequestDiagnostics from './ReaderRequestDiagnostics.jsx';
export default function ReaderTranslationProgress({progress,fallback,onRetry,onRerender,allowRefresh=false}){
 const[now,setNow]=useState(Date.now);
 useEffect(()=>{if(!progress?.running)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[progress?.running,progress?.startedAt]);
 const details=translationProgressDetails(progress,now);
 return <div className={'reader-live-progress'+(progress?.phase==='error'?' reader-live-progress-error':'')} aria-label="Состояние перевода">
  <span role="status" aria-live="polite">{progress?.message||fallback}</span>
  {details.length>0&&<small>{details.join(' · ')}</small>}
  {progress?.running&&progress.totalRegions>0&&<progress aria-label="Обработанные области текста" max={progress.totalRegions} value={Math.min(progress.totalRegions,progress.completedRegions||0)}/>}
  {progress?.phase==='error'&&<button onClick={onRetry}>{progress?.failureStage==='render'?'Повторить очистку':'Повторить перевод'}</button>}
  {allowRefresh&&progress?.renderIncomplete&&!progress?.running&&<button onClick={onRerender}>Повторить очистку · без Google</button>}
  {allowRefresh&&!progress?.running&&progress?.phase!=='error'&&<button onClick={onRetry}>Повторить без кэша</button>}
  <ReaderRequestDiagnostics value={progress?.diagnostics} now={now}/>
 </div>;
}
