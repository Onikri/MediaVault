import {useEffect,useRef,useState} from 'react';
// Automatic captions for our own player, from the playing element's audio.
// 1. Chrome's on-device recognizer (SODA via Web Speech, processLocally) fed
//    with the media track, plus Chrome's on-device Translator.
// 2. Fallback: Whisper base in a worker (WebGPU, else WASM).
// No audio leaves the device in either path.

export const AUTO_LANGUAGES={ja:'Японский',ru:'Русский',en:'Английский'};
const BCP47={ja:'ja-JP',ru:'ru-RU',en:'en-US'};

function Recognition(){return globalThis.SpeechRecognition||globalThis.webkitSpeechRecognition;}
export function autoCaptionSupport(){
 const SR=Recognition();
 return {native:!!SR&&typeof SR.available==='function'&&typeof SR.install==='function',translator:'Translator' in globalThis,whisper:typeof Worker!=='undefined'};
}

// captureStream() has no audio track until the element actually plays; wait
// for it instead of failing when captions are switched on before playback.
let captured=new WeakMap();
function audioTrack(media,signal){
 if(!media?.captureStream&&!media?.mozCaptureStream)return Promise.resolve(null);
 let stream=captured.get(media);if(!stream){stream=media.captureStream?.()||media.mozCaptureStream();captured.set(media,stream);}
 const now=stream.getAudioTracks()[0];if(now&&now.readyState==='live')return Promise.resolve(now);
 return new Promise(resolve=>{const done=()=>{const t=stream.getAudioTracks().find(v=>v.readyState==='live');if(t){stream.removeEventListener('addtrack',done);media.removeEventListener('playing',done);resolve(t);}};stream.addEventListener('addtrack',done);media.addEventListener('playing',done);signal?.addEventListener('abort',()=>resolve(null),{once:true});});
}

async function translatorFor(source,target,onStatus){
 if(!target||target===source||!('Translator' in globalThis))return null;
 const options={sourceLanguage:source,targetLanguage:target};
 const state=await globalThis.Translator.availability(options).catch(()=>'unavailable');
 if(state==='unavailable')return null;
 if(state!=='available')onStatus?.('Скачиваем переводчик Chrome…');
 return globalThis.Translator.create({...options,monitor(m){m.addEventListener?.('downloadprogress',e=>onStatus?.('Переводчик Chrome · '+Math.round((e.loaded||0)*100)+'%'));}});
}

async function startNative({media,language,translator,show,onStatus,signal,onFail}){
 const SR=Recognition();
 if(!SR||typeof SR.available!=='function')throw Error('native-unavailable');
 const options={langs:[BCP47[language]],processLocally:true};
 const state=await SR.available(options);
 if(state==='unavailable')throw Error('native-unavailable');
 if(state!=='available'){onStatus('Скачиваем языковой пакет Chrome…');if(!await SR.install(options))throw Error('native-unavailable');}
 onStatus('Ждём звук видео…');const track=await audioTrack(media,signal);if(!track)throw Error('Браузер не отдаёт звук видео для распознавания.');
 let active=true;const recognition=new SR();
 recognition.lang=BCP47[language];recognition.continuous=true;recognition.interimResults=true;recognition.processLocally=true;
 // Chrome may accept a media track yet never transcribe it (the track input
 // is still behind a flag in some builds): hearing speech without any result
 // for 12 s means this path does not work here, so the caller falls back.
 let heard=0,results=0;const watchdog=setInterval(()=>{if(active&&heard&&!results&&performance.now()-heard>12000){clearInterval(watchdog);onFail?.();}},1000);
 recognition.onspeechstart=()=>{if(!heard)heard=performance.now();};
 recognition.onresult=async event=>{results++;
  let final='',interim='';
  for(let i=event.resultIndex;i<event.results.length;i++){const r=event.results[i];if(r.isFinal)final+=r[0].transcript;else interim+=r[0].transcript;}
  if(final.trim()){const text=final.trim();show(translator?await translator.translate(text).catch(()=>text):text,true);}
  else if(interim.trim()&&!translator)show(interim.trim(),false);
 };
 recognition.onerror=event=>{if(['no-speech','aborted'].includes(event.error))return;onStatus('Распознавание Chrome: '+event.error);};
 // Continuous sessions still end on long silence: resume while active.
 recognition.onend=()=>{if(active)try{recognition.start(track);}catch{}};
 recognition.start(track);
 onStatus('');
 return {engine:'native',stop(){active=false;clearInterval(watchdog);try{recognition.abort();}catch{}}};
}

// Chrome downloads speech and translation packs only with user activation:
// call this synchronously from the settings change (a click) so the packs
// start downloading while that activation is still valid.
export function prepareAutoCaptions(language,translateTo){
 if(!AUTO_LANGUAGES[language])return;
 const SR=Recognition();
 if(SR&&typeof SR.install==='function')SR.install({langs:[BCP47[language]],processLocally:true}).catch(()=>{});
 if(translateTo&&translateTo!==language&&'Translator' in globalThis)globalThis.Translator.create({sourceLanguage:language,targetLanguage:translateTo}).catch(()=>{});
}

// Whisper's well-known silence hallucinations (credits/outro lines from its
// training subtitles); never shown as captions.
const HALLUCINATIONS=/(редактор субтитров|корректор|субтитры (сделал|создавал|подготовил)|продолжение следует|спасибо за (просмотр|внимание)|подписывайтесь|thanks? for watching|subtitles by|please subscribe|ご視聴ありがとうございました|字幕)/i;

// Google: gemini-3.5-transcribe-live over the Live API WebSocket, text only.
// Our server mints a one-use token (the API key stays on Oracle), or the
// viewer's personal translator key is used. Sessions are renewed every 9 min
// (Google closes audio sessions at 15 min) with a short overlap.
const LIVE_URL='wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';
async function personalKey(userId){
 try{const config=JSON.parse(localStorage.getItem('mv_lmt_settings:'+userId)||'{}');if(config.engine!=='direct')return null;}catch{return null;}
 const {restoreDirectKeys}=await import('./manga-direct-key.js');const keys=await restoreDirectKeys(String(userId||'anonymous'));
 return keys.length?keys[Math.floor(Math.random()*keys.length)]:null;
}
async function liveUrl(service,userId){
 const key=await personalKey(userId).catch(()=>null);
 if(!service?.request)throw Error('Подключи сервер Oracle в профиле для субтитров Google.');
 const data=await service.request('/reader/google/live-token',{method:'POST',body:key?{key}:{}});
 return LIVE_URL+'Constrained?access_token='+encodeURIComponent(data.token);
}
// Fallback translation when Chrome's on-device Translator is not available.
async function geminiTranslate(text,from,to,{service,userId},previous){
 const key=await personalKey(userId).catch(()=>null);
 const names={ja:'японского',ru:'русского',en:'английского'},target={ru:'русский',en:'английский'}[to];
 const request={systemInstruction:{parts:[{text:'Ты переводишь субтитры аниме с '+names[from]+' на '+target+'. Верни только перевод одной реплики, живым разговорным языком, без кавычек и пояснений. Предыдущие реплики даны для контекста, их не переводи.'}]},contents:[{role:'user',parts:[{text:(previous.length?'Контекст: '+previous.join(' / ')+'\n':'')+'Реплика: '+text}]}],generationConfig:{temperature:.2,maxOutputTokens:200}};
 const result=await service.request('/reader/google/generate',{method:'POST',body:{...(key?{key}:{}),model:'gemini-3.5-flash-lite',request}});
 return (result?.candidates?.[0]?.content?.parts||[]).map(p=>p.text||'').join('').trim()||text;
}
async function startGoogle({media,language,translateTo,translator,show,onStatus,signal,service,userId}){
 const track=await audioTrack(media,signal);if(!track)throw Error('Браузер не отдаёт звук видео для распознавания.');
 const ctx=new AudioContext(),source=ctx.createMediaStreamSource(new MediaStream([track])),node=ctx.createScriptProcessor(4096,1,1),mute=ctx.createGain();mute.gain.value=0;
 const ratio=ctx.sampleRate/16000;let carry=new Int16Array(0),active=true,sockets=[],renew=0;
 const recent=[],needsTranslation=translateTo&&translateTo!==language;
 const deliver=async text=>{
  text=text.trim();if(!text||!active)return;
  let shown=text;
  if(needsTranslation){shown=translator?await translator.translate(text).catch(()=>null):null;if(!shown)shown=await geminiTranslate(text,language,translateTo,{service,userId},recent.slice(-2)).catch(()=>text);}
  recent.push(text);if(recent.length>4)recent.shift();
  // A whole utterance can be several sentences: show them as a sequence of
  // short captions (≤ ~70 chars), each for a time proportional to its length.
  const parts=shown.match(/[^。！？!?.…]+[。！？!?.…]*\s*/g)||[shown],lines=[];
  for(const part of parts){const last=lines.at(-1);if(last&&(last+part).length<=70)lines[lines.length-1]=last+part;else lines.push(part);}
  queue=queue.then(async()=>{for(const line of lines){if(!active)return;show(line.trim(),true);await new Promise(r=>setTimeout(r,Math.max(1800,Math.min(5000,line.length*70))));}});
 };
 let queue=Promise.resolve();
 const open=async()=>{
  const ws=new WebSocket(await liveUrl(service,userId));let pending='';
  ws.onopen=()=>ws.send(JSON.stringify({setup:{model:'models/gemini-3.5-transcribe-live',generationConfig:{responseModalities:['TEXT']},inputAudioTranscription:{}}}));
  ws.onmessage=async event=>{
   let message;try{message=JSON.parse(typeof event.data==='string'?event.data:await event.data.text());}catch{return;}
   const piece=message.serverContent?.inputTranscription?.text;
   if(piece){pending+=piece;if(/[。！？!?.…]\s*$/.test(pending)||pending.length>80){const line=pending;pending='';deliver(line);}}
   if(message.serverContent?.turnComplete&&pending){const line=pending;pending='';deliver(line);}
  };
  ws.onclose=event=>{sockets=sockets.filter(s=>s!==ws);if(active&&!sockets.length)onStatus(event.code===1000?'':'Субтитры Google переподключаются…');if(active&&!sockets.length)setTimeout(()=>{if(active&&!sockets.length)open().then(s=>sockets.push(s)).catch(e=>onStatus(e.message));},1500);};
  return ws;
 };
 sockets.push(await open());onStatus('');
 renew=setInterval(async()=>{if(!active)return;try{const next=await open();sockets.push(next);const old=sockets.filter(s=>s!==next);setTimeout(()=>old.forEach(s=>{try{s.close(1000);}catch{}}),5000);}catch(e){onStatus(e.message);}},9*60*1000);
 node.onaudioprocess=event=>{
  if(!active||media.paused)return;
  const input=event.inputBuffer.getChannelData(0),length=Math.floor(input.length/ratio),samples=new Int16Array(carry.length+length);samples.set(carry);
  for(let i=0;i<length;i++){const v=input[Math.min(input.length-1,Math.floor(i*ratio))];samples[carry.length+i]=Math.max(-32768,Math.min(32767,Math.round(v*32767)));}
  let offset=0;
  while(samples.length-offset>=1600){const chunk=samples.subarray(offset,offset+1600);offset+=1600;const bytes=new Uint8Array(chunk.buffer,chunk.byteOffset,chunk.byteLength);let binary='';for(let i=0;i<bytes.length;i++)binary+=String.fromCharCode(bytes[i]);const data=btoa(binary);
   for(const ws of sockets)if(ws.readyState===1)ws.send(JSON.stringify({realtimeInput:{audio:{data,mimeType:'audio/pcm;rate=16000'}}}));}
  carry=samples.slice(offset);
 };
 source.connect(node);node.connect(mute).connect(ctx.destination);
 return {engine:'google',stop(){active=false;clearInterval(renew);for(const ws of sockets)try{ws.close(1000);}catch{}try{source.disconnect();node.disconnect();}catch{}ctx.close().catch(()=>{});}};
}

let worker=null;
function whisperWorker(){if(!worker)worker=new Worker(new URL('./auto-captions.worker.js',import.meta.url),{type:'module'});return worker;}

async function startWhisper({media,language,translateTo,translator,show,onStatus,signal}){
 const track=await audioTrack(media,signal);if(!track)throw Error('Браузер не отдаёт звук видео для распознавания.');
 const w=whisperWorker();let active=true,sequence=0;
 // Whisper translates only into English; other targets use Chrome's Translator.
 const task=translateTo==='en'&&language!=='en'?'translate':'transcribe';
 const pending=new Map();
 w.onmessage=async({data})=>{
  if(data.type==='status'&&data.phase==='download')onStatus('Whisper · загрузка модели '+(data.total?Math.round(data.loaded/data.total*100)+'%':'…'));
  if(data.type==='ready')onStatus('');
  if(data.type==='error'){onStatus('Whisper: '+data.message);pending.delete(data.id);}
  if(data.type==='text'){pending.delete(data.id);if(!active||!data.text||/^\[.*\]$|^\(.*\)$/.test(data.text)||HALLUCINATIONS.test(data.text))return;const text=translator&&task==='transcribe'?await translator.translate(data.text).catch(()=>data.text):data.text;show(text,true);}
 };
 w.postMessage({type:'load'});
 const ctx=new AudioContext(),source=ctx.createMediaStreamSource(new MediaStream([track])),node=ctx.createScriptProcessor(4096,1,1),mute=ctx.createGain();mute.gain.value=0;
 const rate=ctx.sampleRate,windowSamples=Math.round(rate*5);let buffer=new Float32Array(windowSamples),filled=0;
 const reset=()=>{filled=0;};media.addEventListener('seeking',reset);
 node.onaudioprocess=event=>{
  if(!active||media.paused)return;
  const input=event.inputBuffer.getChannelData(0);
  for(let i=0;i<input.length;i++){buffer[filled++]=input[i];if(filled===windowSamples){flush();filled=0;}}
 };
 function flush(){
  // Skip silence and avoid a backlog when the device is slower than playback.
  let energy=0;for(let i=0;i<windowSamples;i+=8)energy+=buffer[i]*buffer[i];if(Math.sqrt(energy/(windowSamples/8))<.012||pending.size>1)return;
  const length=Math.floor(windowSamples*16000/rate),audio=new Float32Array(length),step=rate/16000;
  for(let i=0;i<length;i++){const a=Math.floor(i*step),b=Math.min(windowSamples,Math.floor((i+1)*step));let sum=0;for(let j=a;j<b;j++)sum+=buffer[j];audio[i]=sum/Math.max(1,b-a);}
  const id=++sequence;pending.set(id,true);w.postMessage({type:'chunk',id,audio:audio.buffer,language,task},[audio.buffer]);
 }
 source.connect(node);node.connect(mute).connect(ctx.destination);
 return {engine:'whisper',stop(){active=false;media.removeEventListener('seeking',reset);try{source.disconnect();node.disconnect();}catch{}ctx.close().catch(()=>{});}};
}

// language: 'off'|'ja'|'ru'|'en'; translateTo: ''|'ru'|'en'; engine: 'auto'|'native'|'whisper'
export function useAutoCaptions(mediaRef,{language='off',translateTo='',engine='auto',service=null,userId=''},active){
 const [text,setText]=useState(''),[status,setStatus]=useState(''),[running,setRunning]=useState('');
 const clear=useRef(0);
 useEffect(()=>{
  setText('');setRunning('');
  const media=mediaRef.current;if(!active||language==='off'||!media){setStatus('');return;}
  let session=null,closed=false;const abort=new AbortController(),signal=abort.signal;
  const show=(value,final)=>{if(closed)return;setText(value);clearTimeout(clear.current);clear.current=setTimeout(()=>setText(''),final?4500:2500);};
  (async()=>{
   setStatus('Подключаем автосубтитры…');
   const translator=await translatorFor(language,translateTo,setStatus).catch(()=>null);
   if(closed)return;
   const fallback=async()=>{if(closed||engine==='native')return;session?.stop();setStatus('Chrome не распознаёт звук видео — переключились на Whisper.');session=await startWhisper({media,language,translateTo,translator,show,onStatus:v=>setStatus(v||''),signal}).catch(e=>{setStatus(e.message);return null;});if(session)setRunning(session.engine);};
   // Google first (most accurate), then Chrome on-device, then Whisper.
   if((engine==='auto'||engine==='google')&&service?.request){try{session=await startGoogle({media,language,translateTo,translator,show,onStatus:setStatus,signal,service,userId});}catch(error){if(engine==='google'){setStatus(error.message);return;}}}
   if(!session&&engine!=='whisper'&&engine!=='google'){try{session=await startNative({media,language,translator,show,onStatus:setStatus,signal,onFail:fallback});}catch(error){if(engine==='native'){setStatus(error.message==='native-unavailable'?'Распознавание Chrome на устройстве недоступно для этого языка.':error.message);return;}}}
   if(!session&&!closed)session=await startWhisper({media,language,translateTo,translator,show,onStatus:setStatus,signal});
   if(closed){session?.stop();return;}
   setRunning(session.engine);
  })().catch(error=>{if(!closed)setStatus(error.message||'Автосубтитры недоступны.');});
  return()=>{closed=true;abort.abort();clearTimeout(clear.current);session?.stop();};
 },[mediaRef,language,translateTo,engine,active,service,userId]);
 return {text,status,engine:running};
}
