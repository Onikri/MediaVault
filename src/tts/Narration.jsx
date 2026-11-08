import {useEffect,useMemo,useRef,useState} from 'react';
import {Play,Pause,SkipBack,SkipForward,Users,Headphones,X,Volume2,RefreshCw,KeyRound} from 'lucide-react';
import {TTS_BYTES,ttsConsent,setTtsConsent,PRESET_VOICES} from './model.js';
import {startNarrationEngine,engineReady,synthesize} from './engine.js';
import {heuristicRoles,modelRoles,ROLE_MODEL} from './roles.js';
import {castVoices,narratorCast,savedCast,saveCast,PRESET_TRAITS} from './voices.js';
import {createNarrator,utterancesOf,playClip} from './player.js';
import {buildBible,savedBible,saveBible,forgetBible,applyLexicon,TIMBRES,AGES} from './bible.js';
import {ROLE_MODELS,BIBLE_MODELS,personalKey,savePersonalKey} from './google.js';
import {roleColors,emotionLabel} from './RoleText.jsx';
import './narration.css';

const PREFS='mediavault_tts_prefs_v2';
const DEFAULTS={pace:1,narrator:'auto',roles:true,rolesModel:ROLE_MODEL,bibleModel:'gemini-3.5-flash-lite'};
// Only models offered in the panel are kept (non-Lite Flash is never used).
function readPrefs(){try{const value={...DEFAULTS,...JSON.parse(localStorage.getItem(PREFS)||'{}')};if(!BIBLE_MODELS.some(([id])=>id===value.bibleModel))value.bibleModel=DEFAULTS.bibleModel;if(!ROLE_MODELS.some(([id])=>id===value.rolesModel))value.rolesModel=DEFAULTS.rolesModel;return value;}catch{return {...DEFAULTS};}}
const mb=bytes=>Math.round(bytes/1048576);
const ROLE_CACHE=new Map();
const voiceName=v=>(v[0]==='F'?'Женский ':'Мужской ')+v.slice(1);
const TIMBRE_LABELS={neutral:'обычный',warm:'тёплый',bright:'звонкий',dark:'низкий, глухой',breathy:'с придыханием',rough:'хрипловатый',nasal:'носовой',soft:'мягкий'};
const AGE_LABELS={child:'ребёнок',teen:'подросток',young:'молодой',adult:'взрослый',old:'пожилой'};
const SAMPLE={ru:'Здравствуй. Так звучит мой голос в этой книге.',uk:'Привіт. Так звучить мій голос у цій книжці.'};
const wait=(ms,signal)=>new Promise((resolve,reject)=>{const t=setTimeout(resolve,ms);signal?.addEventListener('abort',()=>{clearTimeout(t);reject(signal.reason);},{once:true});});

// Narration for one chapter. onSpeaking({p,segment}) highlights the text;
// onFinished() lets the reader open the next chapter and continue.
// book: {title, aliases, authors, description, year, kind} for the title bible.
export default function Narration({paragraphs,language,bookKey,chapterKey,title,book,service,userId,startParagraph=0,autoplay=false,onSpeaking,onFinished,onAutoplayHandled,onScript,commandRef,onPlaying,caption=true}){
 const [prefs,setPrefs]=useState(readPrefs),[phase,setPhase]=useState('idle'),[progress,setProgress]=useState(null),[error,setError]=useState('');
 const [segments,setSegments]=useState([]),[characters,setCharacters]=useState([]),[analysis,setAnalysis]=useState(''),[cast,setCast]=useState(()=>savedCast(bookKey));
 const [bible,setBible]=useState(()=>savedBible(bookKey)),[bibleState,setBibleState]=useState(''),[bibleRevision,setBibleRevision]=useState(0);
 const [state,setState]=useState({playing:false,index:0,total:0}),[provider,setProvider]=useState(''),[castOpen,setCastOpen]=useState(false),[consent,setConsent]=useState(ttsConsent);
 const [hasKey,setHasKey]=useState(null),[keyDraft,setKeyDraft]=useState(''),[sampling,setSampling]=useState('');
 const narrator=useRef(null),live=useRef({}),rowsRef=useRef([]),wantPlay=useRef(false);live.current={onSpeaking,onFinished};
 function update(change){setPrefs(old=>{const next={...old,...change};try{localStorage.setItem(PREFS,JSON.stringify(next));}catch{}return next;});}
 const meta=useMemo(()=>({title:book?.title||title,aliases:book?.aliases||[],authors:book?.authors||[],description:book?.description||'',year:book?.year||null,kind:book?.kind||'book',language}),[book?.title,title,language]);

 // 1. Title bible: once per book, the strongest free model studies the cast.
 useEffect(()=>{
  if(!prefs.roles||!service||!paragraphs.length||bible)return;
  const abort=new AbortController();setBibleState('running');
  buildBible({book:meta,sample:paragraphs.join('\n'),service,userId,model:prefs.bibleModel,signal:abort.signal})
   .then(value=>{saveBible(bookKey,value);setBible(value);setBibleState('');})
   .catch(e=>{if(!abort.signal.aborted)setBibleState('error:'+(e.message||''));});
  return()=>abort.abort();
 },[bookKey,prefs.roles,prefs.bibleModel,bibleRevision,!!bible]);

 // 2. Instant heuristic roles; the chapter pass runs at once (with the bible if it is ready).
 useEffect(()=>{
  const key=chapterKey+'|'+prefs.rolesModel,cached=ROLE_CACHE.get(key);
  const base=cached?.segments||heuristicRoles(paragraphs);setSegments(base);setCharacters(cached?.characters||[]);setAnalysis(cached?'model':'');
  if(cached||!prefs.roles||!service||!paragraphs.length)return;
  const abort=new AbortController();setAnalysis('running');
  modelRoles(base,{bible,known:[],context:{title:meta.title,language,tone:bible?.tone},service,userId,model:prefs.rolesModel,signal:abort.signal}).then(result=>{
   if(abort.signal.aborted)return;ROLE_CACHE.set(key,result);while(ROLE_CACHE.size>20)ROLE_CACHE.delete(ROLE_CACHE.keys().next().value);
   setSegments(result.segments);setCharacters(result.characters);setAnalysis('model');
  }).catch(e=>{if(!abort.signal.aborted)setAnalysis('heuristic:'+(e.message||''));});
  return()=>abort.abort();
 },[chapterKey,prefs.roles,prefs.rolesModel]);

 // Names from the title bible carry their stress marks.
 const spoken=useMemo(()=>segments.map(s=>({...s,spoken:applyLexicon(s.text,bible)})),[segments,bible]);
 const voices=useMemo(()=>castVoices(segments,characters,{narrator:prefs.narrator,saved:cast,bible}),[segments,characters,prefs.narrator,cast,bible]);
 const narratorVoice=useMemo(()=>narratorCast(bible,prefs.narrator),[bible,prefs.narrator]);
 useEffect(()=>{saveCast(bookKey,voices);},[bookKey,voices]);
 const rows=useMemo(()=>utterancesOf(spoken,{cast:voices,narrator:narratorVoice,pace:prefs.pace}),[spoken,voices,narratorVoice,prefs.pace]);
 rowsRef.current=rows;
 const colors=useMemo(()=>roleColors(voices),[voices]);
 // The reader draws the same roles in the text (names, colours, emotions).
 useEffect(()=>{onScript?.({segments,cast:voices,colors,narrator:prefs.narrator,analysis});},[segments,voices,colors,prefs.narrator,analysis]);

 useEffect(()=>{
  // CPU: 4 flow steps (measured CER: 3 steps ru 1.6% / uk 4.7%, 5 steps 0.5% / 0.8%).
  narrator.current=createNarrator({language,steps:provider==='wasm'?4:5,
   onSegment:row=>live.current.onSpeaking?.(row),onState:setState,onEnd:()=>live.current.onFinished?.(),onError:e=>{setError(e.message||'Озвучка остановилась.');}});
  const rows=rowsRef.current,first=Math.max(0,rows.findIndex(r=>r.p>=startParagraph));
  narrator.current.load(rows,{start:first,label:title});
  if(wantPlay.current&&provider){wantPlay.current=false;narrator.current.play();}
  return()=>narrator.current?.destroy();
 },[language,provider]);
 // Re-queue when roles, voices or pace change, keeping the position.
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
 function toggle(){if(narrator.current?.playing)narrator.current.pause();else if(phase==='ready'&&engineReady())narrator.current?.play();else begin();}
 if(commandRef)commandRef.current={toggle,playing:state.playing,busy:phase==='downloading'||phase==='starting'};
 useEffect(()=>{onPlaying?.(state.playing);},[state.playing]);
 useEffect(()=>{if(castOpen)personalKey(userId).then(k=>setHasKey(!!k)).catch(()=>setHasKey(false));},[castOpen,userId]);

 async function preview(name,value){
  if(!engineReady()){begin();return;}
  setSampling(name);
  try{
   const result=await synthesize({text:SAMPLE[language]||SAMPLE.ru,lang:language,voice:value.voice,steps:provider==='wasm'?4:5,speed:(value.pace||1)/(value.rate||1),seed:3});
   await playClip(result,{rate:value.rate,eq:value.eq,gain:value.gain});
  }catch(e){setError(e.message||'Не удалось проиграть пример голоса.');}
  finally{setSampling('');}
 }
 function change(name,patch){
  setCast(old=>{const base={...voices[name],...old[name]};const next={...base,...patch,saved:true};
   if('pitch' in patch)next.rate=Math.pow(2,next.pitch/12);
   if('timbre' in patch){const eq={neutral:{low:0,mid:0,high:0},warm:{low:3,mid:-1,high:-2},bright:{low:-1,mid:2,high:3},dark:{low:2,mid:-1,high:-4},breathy:{low:-2,mid:-1,high:4},rough:{low:1,mid:3,high:-1},nasal:{low:-2,mid:4,high:-1,midFreq:1100},soft:{low:1,mid:-2,high:-1}}[patch.timbre];next.eq=eq;}
   return {...old,[name]:next};});
 }
 async function saveKey(event){
  event.preventDefault();
  try{await savePersonalKey(userId,keyDraft);setKeyDraft('');setHasKey(true);setBibleRevision(v=>v+1);}catch(e){setError(e.message||'Не удалось сохранить ключ.');}
 }
 function restudy(){forgetBible(bookKey);setBible(null);setBibleRevision(v=>v+1);}

 const people=Object.entries(voices).filter(([name])=>segments.some(s=>s.speaker===name));
 const busy=phase==='downloading'||phase==='starting';
 const current=state.playing||phase==='ready'?rows[state.index]:null,currentSegment=current&&segments.find(x=>x.id===current.segment);
 const who=currentSegment&&currentSegment.kind!=='narration'?currentSegment.speaker||(currentSegment.gender==='f'?'Героиня':currentSegment.gender==='m'?'Герой':'Персонаж'):'Рассказчик';
 const modelName=id=>[...ROLE_MODELS,...BIBLE_MODELS].find(([m])=>m===id)?.[1]||id;
 return <div className="narration" role="region" aria-label="Озвучка главы">
  {phase==='consent'&&<div className="narration-consent">
   <p><strong>Озвучка работает на этом устройстве.</strong> Один раз загрузится нейросеть Supertonic 3 — около {mb(TTS_BYTES)} МБ. Дальше она работает без сервера и сохраняется в кэше браузера.</p>
   <p className="fine">Голоса синтезированы нейросетью (лицензия OpenRAIL-M: нельзя выдавать синтез за живую речь и имитировать реальных людей).</p>
   <div className="narration-actions"><button type="button" className="btn btn-primary" onClick={accept}>Загрузить и слушать</button><button type="button" className="btn btn-secondary" onClick={()=>setPhase('idle')}>Не сейчас</button></div>
  </div>}
  {caption&&current&&<p className="narration-caption" aria-live="off"><b style={currentSegment?.speaker&&colors[currentSegment.speaker]?{color:colors[currentSegment.speaker]}:undefined} translate={currentSegment?.speaker?'no':undefined}>{who}</b>{emotionLabel(currentSegment)&&<i>{emotionLabel(currentSegment)}</i>}<span translate="no">{current.text}</span></p>}
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
   <header><strong>Роли и голоса</strong><button type="button" aria-label="Закрыть роли" onClick={()=>setCastOpen(false)}><X size={15}/></button></header>
   <dl className="narration-facts">
    <dt>Персонажи книги</dt><dd>{bibleState==='running'?'Изучаем героев: '+modelName(prefs.bibleModel)+'…':bible?modelName(bible.model)+(bible.tone?' · '+bible.tone:''):bibleState.startsWith('error:')?'Не получилось: '+bibleState.slice(6):prefs.roles?'Ждём ключ Google':'Выключено'}</dd>
    <dt>Роли и эмоции</dt><dd>{analysis==='running'?'Размечаем главу: '+modelName(prefs.rolesModel)+'…':analysis==='model'?modelName(prefs.rolesModel):analysis.startsWith('heuristic:')?'По тексту без модели: '+analysis.slice(10):'По тексту главы'}</dd>
   </dl>
   {hasKey===false&&<form className="narration-key" onSubmit={saveKey}><label><KeyRound size={14}/>Личный ключ Google<input type="password" autoComplete="off" value={keyDraft} onChange={e=>setKeyDraft(e.target.value)} placeholder="Ключ из Google AI Studio"/></label><button className="btn btn-primary" disabled={!keyDraft.trim()}>Сохранить</button><small>Ключ хранится зашифрованным на этом устройстве и отправляется в Google через сервер MediaVault только вместе с запросом. Без ключа работают ключи владельца сервера.</small></form>}
   {hasKey&&<p className="fine">Используется личный ключ Google с этого устройства.</p>}
   <label className="narration-switch"><input type="checkbox" checked={prefs.roles} onChange={e=>update({roles:e.target.checked})}/>Разбирать персонажей, роли и эмоции моделями Google</label>
   <label>Роли и эмоции<select aria-label="Модель разметки ролей" value={prefs.rolesModel} onChange={e=>update({rolesModel:e.target.value})}>{ROLE_MODELS.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
   <label>Персонажи книги<select aria-label="Модель карточки персонажей" value={prefs.bibleModel} onChange={e=>update({bibleModel:e.target.value})}>{BIBLE_MODELS.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
   {prefs.roles&&<button type="button" className="text-link narration-restudy" disabled={bibleState==='running'} onClick={restudy}><RefreshCw size={13}/>Изучить персонажей заново</button>}
   <label>Рассказчик<span className="narration-voice-controls"><button type="button" className="narration-sample" aria-label="Пример голоса рассказчика" disabled={!!sampling} onClick={()=>preview('narrator',narratorVoice)}><Volume2 size={15}/></button><select aria-label="Голос рассказчика" value={prefs.narrator} onChange={e=>update({narrator:e.target.value})}><option value="auto">{bible?.narrator?'По книге · '+(TIMBRE_LABELS[bible.narrator.timbre]||''):'Автоматически'}</option>{PRESET_VOICES.map(v=><option key={v} value={v}>{voiceName(v)}</option>)}</select></span></label>
   <ul>{people.map(([name,value])=><li key={name}>
    <div className="narration-person"><span translate="no" style={{color:colors[name]}}>{name}</span><small>{[value.gender==='f'?'женский':value.gender==='m'?'мужской':'',AGE_LABELS[value.age]].filter(Boolean).join(', ')}{value.traits?' · ':''}<span translate="no">{value.traits}</span></small></div>
    <span className="narration-voice-controls">
     <button type="button" className="narration-sample" aria-label={'Пример голоса: '+name} aria-pressed={sampling===name} disabled={!!sampling} onClick={()=>preview(name,value)}><Volume2 size={15}/></button>
     <select aria-label={'Голос: '+name} value={Object.keys(value.voice)[0]} onChange={e=>change(name,{voice:{[e.target.value]:1}})}>{PRESET_VOICES.map(v=><option key={v} value={v}>{voiceName(v)} · {PRESET_TRAITS[v].f0} Гц</option>)}</select>
     <select aria-label={'Высота голоса: '+name} value={Math.round(value.pitch||0)} onChange={e=>change(name,{pitch:Number(e.target.value)})}>{[-4,-3,-2,-1,0,1,2,3,4].map(v=><option key={v} value={v}>{v>0?'+'+v:v} пт</option>)}</select>
     <select aria-label={'Тембр: '+name} value={value.timbre||'neutral'} onChange={e=>change(name,{timbre:e.target.value})}>{TIMBRES.map(t=><option key={t} value={t}>{TIMBRE_LABELS[t]}</option>)}</select>
    </span></li>)}</ul>
   {!people.length&&<p className="fine">В этой главе нет реплик персонажей — читает рассказчик.</p>}
  </div>}
 </div>;
}
