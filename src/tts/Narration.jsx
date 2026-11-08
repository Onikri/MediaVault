import {useEffect,useMemo,useRef,useState} from 'react';
import {Play,Pause,SkipBack,SkipForward,Users,Headphones,X} from 'lucide-react';
import {TTS_BYTES,ttsConsent,setTtsConsent,PRESET_VOICES} from './model.js';
import {startNarrationEngine,engineReady} from './engine.js';
import {heuristicRoles,modelRoles} from './roles.js';
import {castVoices,savedCast,saveCast,voiceLabel} from './voices.js';
import {createNarrator,utterancesOf} from './player.js';
import './narration.css';

const PREFS='mediavault_tts_prefs_v1';
function readPrefs(){try{return {pace:1,narrator:'M2',roles:true,...JSON.parse(localStorage.getItem(PREFS)||'{}')};}catch{return {pace:1,narrator:'M2',roles:true};}}
const mb=bytes=>Math.round(bytes/1048576);
const ROLE_CACHE=new Map();
const voiceName=v=>(v[0]==='F'?'Женский ':'Мужской ')+v.slice(1);

// Narration for one chapter. onSpeaking({p,segment}) highlights the text;
// onFinished() lets the reader open the next chapter and continue.
export default function Narration({paragraphs,language,bookKey,chapterKey,title,service,userId,startParagraph=0,autoplay=false,onSpeaking,onFinished,onAutoplayHandled}){
 const [prefs,setPrefs]=useState(readPrefs),[phase,setPhase]=useState('idle'),[progress,setProgress]=useState(null),[error,setError]=useState('');
 const [segments,setSegments]=useState([]),[characters,setCharacters]=useState([]),[analysis,setAnalysis]=useState(''),[cast,setCast]=useState(()=>savedCast(bookKey));
 const [state,setState]=useState({playing:false,index:0,total:0}),[provider,setProvider]=useState(''),[castOpen,setCastOpen]=useState(false),[consent,setConsent]=useState(ttsConsent);
 const narrator=useRef(null),live=useRef({}),rowsRef=useRef([]),wantPlay=useRef(false);live.current={onSpeaking,onFinished};
 function update(change){setPrefs(old=>{const next={...old,...change};try{localStorage.setItem(PREFS,JSON.stringify(next));}catch{}return next;});}

 // Instant heuristic roles, then (optionally) the model pass in the background.
 useEffect(()=>{
  const key=chapterKey,cached=ROLE_CACHE.get(key);
  const base=cached?.segments||heuristicRoles(paragraphs);setSegments(base);setCharacters(cached?.characters||[]);setAnalysis(cached?'model':'');
  if(cached||!prefs.roles||!service||!paragraphs.length)return;
  const abort=new AbortController();setAnalysis('running');
  modelRoles(base,{known:characters,context:{title,language},service,userId,signal:abort.signal}).then(result=>{
   if(abort.signal.aborted)return;ROLE_CACHE.set(key,result);while(ROLE_CACHE.size>20)ROLE_CACHE.delete(ROLE_CACHE.keys().next().value);
   setSegments(result.segments);setCharacters(old=>[...old,...result.characters.filter(c=>!old.some(o=>o.name===c.name))]);setAnalysis('model');
  }).catch(e=>{if(!abort.signal.aborted)setAnalysis('heuristic:'+(e.message||''));});
  return()=>abort.abort();
 },[chapterKey,prefs.roles]);

 const voices=useMemo(()=>castVoices(segments,characters,{narrator:prefs.narrator,saved:cast}),[segments,characters,prefs.narrator,cast]);
 useEffect(()=>{saveCast(bookKey,voices);},[bookKey,voices]);
 const rows=useMemo(()=>utterancesOf(segments,{cast:voices,narrator:prefs.narrator,pace:prefs.pace}),[segments,voices,prefs.narrator,prefs.pace]);
 rowsRef.current=rows;

 useEffect(()=>{
  // CPU: 4 flow steps (measured CER: 3 steps ru 1.6% / uk 4.7%, 5 steps 0.5% / 0.8%).
  narrator.current=createNarrator({language,steps:provider==='wasm'?4:5,
   onSegment:row=>live.current.onSpeaking?.(row),onState:setState,onEnd:()=>live.current.onFinished?.(),onError:e=>{setError(e.message||'Озвучка остановилась.');}});
  const rows=rowsRef.current,first=Math.max(0,rows.findIndex(r=>r.p>=startParagraph));
  narrator.current.load(rows,{start:first,label:title});
  if(wantPlay.current&&provider){wantPlay.current=false;narrator.current.play();}
  return()=>narrator.current?.destroy();
 },[language,provider]);
 // Re-queue when roles, voices or pace change, keeping the current position.
 useEffect(()=>{
  const player=narrator.current;if(!player)return;
  const current=player.queue[player.index],was=player.playing;
  const start=current?Math.max(0,rows.findIndex(r=>r.p>=current.p)):Math.max(0,rows.findIndex(r=>r.p>=startParagraph));
  player.load(rows,{start:start<0?0:start,label:title});
  if(was)player.play();
 },[rows]);

 async function begin(agreed=consent){
  setError('');
  if(!agreed){setPhase('consent');return;}
  try{
   if(!engineReady())setPhase('downloading');
   const loaded=await startNarrationEngine({progress:value=>{if(value.phase==='start')setPhase('starting');else setProgress(value);}});
   setPhase('ready');
   if(loaded.provider===provider)narrator.current?.play();else{wantPlay.current=true;setProvider(loaded.provider);}
  }catch(e){setPhase('idle');setError(e.message||'Не удалось запустить озвучку.');}
 }
 useEffect(()=>{if(autoplay&&rows.length){onAutoplayHandled?.();if(engineReady())narrator.current?.play();else begin();}},[autoplay,rows.length,provider]);
 function accept(){setTtsConsent(true);setConsent(true);setPhase('idle');begin(true);}

 const people=Object.entries(voices);
 const busy=phase==='downloading'||phase==='starting';
 return <div className="narration" role="region" aria-label="Озвучка главы">
  {phase==='consent'&&<div className="narration-consent">
   <p><strong>Озвучка работает на этом устройстве.</strong> Один раз загрузится нейросеть Supertonic 3 — около {mb(TTS_BYTES)} МБ. Дальше она работает без сервера и сохраняется в кэше браузера.</p>
   <p className="fine">Голоса синтезированы нейросетью (лицензия OpenRAIL-M: нельзя выдавать синтез за живую речь и имитировать реальных людей).</p>
   <div className="narration-actions"><button type="button" className="btn btn-primary" onClick={accept}>Загрузить и слушать</button><button type="button" className="btn btn-secondary" onClick={()=>setPhase('idle')}>Не сейчас</button></div>
  </div>}
  <div className="narration-bar">
   {phase==='ready'||state.playing?<>
    <button type="button" className="narration-main" aria-label={state.playing?'Пауза озвучки':'Продолжить озвучку'} onClick={()=>state.playing?narrator.current?.pause():narrator.current?.play()}>{state.playing?<Pause size={18}/>:<Play size={18}/>}</button>
    <button type="button" aria-label="Предыдущая фраза" onClick={()=>narrator.current?.skip(-1)}><SkipBack size={16}/></button>
    <button type="button" aria-label="Следующая фраза" onClick={()=>narrator.current?.skip(1)}><SkipForward size={16}/></button>
   </>:<button type="button" className="narration-start" disabled={busy||!rows.length} onClick={()=>begin()}><Headphones size={17}/>{busy?(phase==='starting'?'Запускаем голос…':'Загружаем голос '+Math.round((progress?.loaded||0)/Math.max(1,progress?.total||TTS_BYTES)*100)+'%'):'Слушать главу'}</button>}
   <label className="narration-pace">Темп<select aria-label="Темп озвучки" value={prefs.pace} onChange={e=>update({pace:Number(e.target.value)})}>{[.8,.9,1,1.1,1.2,1.35].map(v=><option key={v} value={v}>{v}×</option>)}</select></label>
   <button type="button" aria-label="Роли и голоса" aria-expanded={castOpen} onClick={()=>setCastOpen(v=>!v)}><Users size={16}/><span>{people.length}</span></button>
   {state.playing&&<small className="narration-status">{state.buffering?'Готовим фразу…':provider==='webgpu'?'Видеокарта':'Процессор'}</small>}
  </div>
  {error&&<p className="inline-error" role="alert">{error}</p>}
  {castOpen&&<div className="narration-cast">
   <header><strong>Роли</strong><button type="button" aria-label="Закрыть роли" onClick={()=>setCastOpen(false)}><X size={15}/></button></header>
   <p className="fine">{analysis==='running'?'Определяем персонажей и эмоции через Google…':analysis==='model'?'Персонажи и эмоции определены моделью Google.':analysis.startsWith('heuristic:')?'Роли определены по тексту без модели: '+analysis.slice(10):'Роли определены по тексту главы.'}</p>
   <label className="narration-switch"><input type="checkbox" checked={prefs.roles} onChange={e=>update({roles:e.target.checked})}/>Уточнять роли и эмоции через Google (по твоему ключу)</label>
   <label>Рассказчик<select aria-label="Голос рассказчика" value={prefs.narrator} onChange={e=>update({narrator:e.target.value})}>{PRESET_VOICES.map(v=><option key={v} value={v}>{voiceName(v)}</option>)}</select></label>
   <ul>{people.map(([name,value])=><li key={name}><span translate="no">{name}</span><select aria-label={'Голос: '+name} value={Object.keys(value.voice).length===1?Object.keys(value.voice)[0]:''} onChange={e=>setCast(old=>({...voices,...old,[name]:{...value,voice:{[e.target.value]:1}}}))}>{Object.keys(value.voice).length>1&&<option value="">Смесь · {voiceLabel(value.voice)}</option>}{PRESET_VOICES.map(v=><option key={v} value={v}>{voiceName(v)}</option>)}</select></li>)}</ul>
   {!people.length&&<p className="fine">В этой главе нет реплик персонажей — читает рассказчик.</p>}
  </div>}
 </div>;
}
