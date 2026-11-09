// Narration player: segments → utterances (≤ one sentence) → synthesized ahead
// in the worker → played gaplessly through Web Audio. Emits the current
// segment for highlighting. Pauses for music and video, and they pause for it.
import {synthesize} from './engine.js';
import {sentences} from './text.js';
import {delivery,voiceFor} from './voices.js';

export const TTS_EVENT='mediavault-tts-playing';
let context=null;
function audioContext(){context||=new (globalThis.AudioContext||globalThis.webkitAudioContext)();return context;}

// narrator: the narrator's voice object (narratorCast). Each row carries the
// stressed text to speak, its voice, pitch rate, EQ and delivery.
export function utterancesOf(segments,{cast,narrator,pace=1}){
 const rows=[];
 for(const segment of segments){
  const voice=voiceFor(segment,cast,narrator),how=delivery(segment,pace*(voice.pace||1));
  const parts=sentences(segment.spoken||segment.text);
  const eq={low:(voice.eq?.low||0)+how.eq.low,mid:(voice.eq?.mid||0)+how.eq.mid,high:(voice.eq?.high||0)+how.eq.high,midFreq:voice.eq?.midFreq||2500};
  parts.forEach((text,i)=>rows.push({segment:segment.id,p:segment.p,text,voice:voice.voice,rate:voice.rate||1,eq,speed:how.speed,gain:how.gain*(voice.gain||1),
   pause:i===parts.length-1?how.pause:.12,tags:i===0?segment.tags||[]:[],kind:segment.kind}));
 }
 return rows;
}

// Pitch by playback rate (tempo compensated at synthesis), then a three-band
// equaliser: low shelf 220 Hz, presence peak, high shelf 6.5 kHz.
export function voiceChain(ctx,{rate=1,eq={},gain=1}={}){
 const low=ctx.createBiquadFilter();low.type='lowshelf';low.frequency.value=220;low.gain.value=Math.max(-12,Math.min(12,eq.low||0));
 const mid=ctx.createBiquadFilter();mid.type='peaking';mid.frequency.value=eq.midFreq||2500;mid.Q.value=1;mid.gain.value=Math.max(-12,Math.min(12,eq.mid||0));
 const high=ctx.createBiquadFilter();high.type='highshelf';high.frequency.value=6500;high.gain.value=Math.max(-12,Math.min(12,eq.high||0));
 const level=ctx.createGain();level.gain.value=Math.min(1.6,gain);
 low.connect(mid).connect(high).connect(level).connect(ctx.destination);
 return {input:low,rate,dispose(){for(const node of [low,mid,high,level])try{node.disconnect();}catch{}}};
}

let previewContext=null;
export async function playClip(result,options={}){
 previewContext||=new (globalThis.AudioContext||globalThis.webkitAudioContext)();if(previewContext.state==='suspended')await previewContext.resume();
 const buffer=previewContext.createBuffer(1,result.audio.length,result.sampleRate);buffer.copyToChannel(result.audio,0);
 const source=previewContext.createBufferSource();source.buffer=buffer;source.playbackRate.value=options.rate||1;
 source.connect(voiceChain(previewContext,options).input);
 return new Promise(resolve=>{source.onended=resolve;source.start();});
}

// synth(row, index, signal, language) → clip {chunks:Float32Array[], done,
// error, sampleRate, provider, wake}. Without it the Supertonic worker is used.
// Chunks are scheduled as they arrive, so a streamed voice starts at once.
export function localClip(row,i,{language,steps}){
 const clip={chunks:[],done:false,error:null,sampleRate:44100,provider:'',wake:null};
 synthesize({text:row.text,lang:language,voice:row.voice,steps,speed:row.speed/(row.rate||1),tags:row.tags,seed:7+i%5})
  .then(result=>{clip.sampleRate=result.sampleRate;clip.provider=result.provider;clip.chunks.push(result.audio);},error=>{clip.error=error;})
  .finally(()=>{clip.done=true;clip.wake?.();});
 return clip;
}

export function createNarrator({language='ru',steps=5,lookahead=4,synth=null,onSegment=()=>{},onState=()=>{},onEnd=()=>{},onError=()=>{}}={}){
 let queue=[],index=0,playing=false,generation=0,title='',abort=new AbortController(),current=null;
 const ready=new Map(),retried=new Set();let failures=0;
 const state=extra=>onState({playing,index,total:queue.length,...extra});
 const make=synth||((row,i)=>localClip(row,i,{language,steps}));
 function reset(){generation++;abort.abort();abort=new AbortController();ready.clear();retried.clear();failures=0;current?.cancel();current=null;}

 function prefetch(){
  for(let i=index;i<Math.min(queue.length,index+lookahead);i++)if(!ready.has(i))ready.set(i,make(queue[i],i,abort.signal,language));
  for(const key of ready.keys())if(key<index)ready.delete(key);
 }

 // Plays one clip through the row's voice chain; resolves when its audio ends.
 function playRow(clip,row,version){
  const ctx=audioContext(),chain=voiceChain(ctx,row),sources=[];
  let at=ctx.currentTime+.05,scheduled=0,timer=null,finished=false;
  return new Promise(resolve=>{
   const end=value=>{if(finished)return;finished=true;clearTimeout(timer);clip.wake=null;setTimeout(()=>chain.dispose(),200);resolve(value);};
   current={cancel(){for(const s of sources)try{s.stop();}catch{}end('cancelled');}};
   const pump=()=>{
    if(version!==generation||!playing)return end('cancelled');
    while(scheduled<clip.chunks.length){
     const data=clip.chunks[scheduled++],buffer=ctx.createBuffer(1,data.length,clip.sampleRate);buffer.copyToChannel(data,0);
     const source=ctx.createBufferSource();source.buffer=buffer;source.playbackRate.value=row.rate||1;source.connect(chain.input);
     at=Math.max(at,ctx.currentTime+.02);source.start(at);at+=buffer.duration/(row.rate||1);sources.push(source);
     if(scheduled===1)state({buffering:false,provider:clip.provider});
    }
    if(!clip.done)return;
    if(clip.error&&!scheduled)return end(clip.error);
    clearTimeout(timer);timer=setTimeout(()=>end('ended'),Math.max(0,(at-ctx.currentTime)*1000));
   };
   clip.wake=pump;pump();
  });
 }

 async function playNext(){
  if(!playing)return;
  if(index>=queue.length){playing=false;state();onEnd();return;}
  const version=generation,row=queue[index];
  onSegment(row);
  prefetch();
  const clip=ready.get(index);
  if(!clip.chunks.length)state({buffering:true});
  const ctx=audioContext();if(ctx.state==='suspended')await ctx.resume();
  if(version!==generation||!playing)return;
  const result=await playRow(clip,row,version);
  if(version!==generation||!playing||result==='cancelled')return;
  current=null;
  if(result instanceof Error||(result&&result!=='ended')){
   // One failed phrase must not stop the chapter: ask once more, then skip it.
   // Three failures in a row (no network, no quota) stop and report.
   if(!retried.has(index)){retried.add(index);ready.set(index,make(row,index,abort.signal,language));playNext();return;}
   if(++failures<3){index++;playNext();return;}
   failures=0;playing=false;state();onError(result);return;
  }
  failures=0;
  setTimeout(()=>{if(version!==generation)return;index++;playNext();},row.pause*1000);
 }

 function claimMedia(){
  try{
   if(!('mediaSession' in navigator))return;
   navigator.mediaSession.metadata=new MediaMetadata({title:title||'Озвучка',artist:'MediaVault · озвучка'});
   navigator.mediaSession.setActionHandler('play',()=>api.play());
   navigator.mediaSession.setActionHandler('pause',()=>api.pause());
   navigator.mediaSession.setActionHandler('nexttrack',()=>api.skip(1));
   navigator.mediaSession.setActionHandler('previoustrack',()=>api.skip(-1));
  }catch{}
 }
 const yieldToOthers=()=>{if(playing)api.pause();};
 const onVideo=event=>{if(event.target?.tagName==='VIDEO')yieldToOthers();};
 addEventListener('mediavault-music-playing',yieldToOthers);
 document.addEventListener('play',onVideo,true);

 const api={
  load(rows,{start=0,label=''}={}){reset();queue=rows;index=Math.max(0,Math.min(start,rows.length));title=label;state();},
  async play(){
   if(playing||!queue.length)return;
   playing=true;dispatchEvent(new CustomEvent(TTS_EVENT));claimMedia();
   const ctx=audioContext();if(ctx.state==='suspended')await ctx.resume();
   reset();playNext();
  },
  pause(){if(!playing)return;playing=false;reset();state();},
  skip(step){const was=playing;api.pause();index=Math.max(0,Math.min(queue.length-1,index+step));state();if(was)api.play();},
  seekSegment(segmentId){const at=queue.findIndex(r=>r.segment===segmentId);if(at>=0){const was=playing;api.pause();index=at;state();if(was)api.play();}},
  get playing(){return playing;},get index(){return index;},get queue(){return queue;},
  destroy(){api.pause();removeEventListener('mediavault-music-playing',yieldToOthers);document.removeEventListener('play',onVideo,true);try{if(navigator.mediaSession?.metadata?.artist==='MediaVault · озвучка')navigator.mediaSession.metadata=null;}catch{}},
 };
 return api;
}
