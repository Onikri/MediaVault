import React,{useEffect,useState} from 'react';
import {variantsFor} from './watch-session.js';
import {counted} from './title-context.js';

// Studios and subtitle tracks from every source. A studio is one row; the
// players (Kodik, Alloha, Collaps…) that carry it are chips under it, named
// the way the player names them, so the saved file's origin is visible.
export default function VoicePicker({discovery,onChoose,selected,initialVoice=''}){
 const voices=(discovery.data?.voices||[]).filter(v=>v.language!=='en'||v.kind==='original');
 const [groupId,setGroupId]=useState('');
 const group=voices.find(g=>g.id===groupId);
 // The voice already chosen in the player is preselected once it is found.
 useEffect(()=>{if(groupId||!initialVoice)return;const match=voices.find(v=>v.id===initialVoice||v.name===initialVoice);if(match)choose(match);},[initialVoice,voices.length]);
 function choose(value){setGroupId(value.id);onChoose(variantsFor(value,1)[0]||null);}
 return <section className="voice-picker export-field" aria-label="Перевод для сохранения">
  <span>Озвучка или субтитры{voices.length?' · '+voices.length:''}</span>
  {discovery.loading&&!voices.length&&<p className="export-hint" role="status"><span className="loading-ring"/>Собираем переводы со всех источников…</p>}
  {discovery.error&&<p className="inline-error" role="alert">{discovery.error} <button type="button" className="text-link" onClick={discovery.retry}>Повторить поиск</button></p>}
  {!discovery.loading&&discovery.data&&!voices.length&&<p className="export-hint">Подтверждённых переводов для этого тайтла и сезона пока нет. Другие произведения не подставляются.</p>}
  {!!voices.length&&<div className="export-choice-list" role="group" aria-label="Выбрать перевод">{voices.map(voice=><button type="button" key={voice.id} className="export-choice" aria-pressed={voice.id===groupId} onClick={()=>choose(voice)}>
   <strong>{voice.name}</strong><small>{voice.kind==='subtitles'?'Субтитры':voice.kind==='original'?'Оригинальная дорожка':'Озвучка'}{voice.language&&voice.language!=='ru'?' · '+voice.language.toUpperCase():''}</small>
   <em>{counted(voice.variants.length,['плеер','плеера','плееров'])}</em>
  </button>)}</div>}
  {group&&group.variants.length>0&&<div className="export-field"><span>Плеер</span><div className="export-players" role="group" aria-label="Плеер для сохранения">{group.variants.map(v=><button type="button" key={v.id} aria-pressed={selected?.id===v.id} title={v.sourceTitle} onClick={()=>onChoose(v)}>{v.player||v.providerName}{v.player&&v.providerName&&v.player!==v.providerName?' · '+v.providerName:''}{v.episodes?.length?' · '+v.episodes.length+' сер.':''}</button>)}</div></div>}
  {discovery.data?.complete===false&&<p className="export-hint">Часть источников ещё не проверена. <button type="button" className="text-link" onClick={discovery.retry}>Продолжить проверку</button></p>}
 </section>;
}
