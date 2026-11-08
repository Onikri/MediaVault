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
 return {input:low,rate};
}

let previewContext=null;
export async function playClip(result,options={}){
 previewContext||=new (globalThis.AudioContext||globalThis.webkitAudioContext)();if(previewContext.state==='suspended')await previewContext.resume();
 const buffer=previewContext.createBuffer(1,result.audio.length,result.sampleRate);buffer.copyToChannel(result.audio,0);
 const source=previewContext.createBufferSource();source.buffer=buffer;source.playbackRate.value=options.rate||1;
 source.connect(voiceChain(previewContext,options).input);
 return new Promise(resolve=>{source.onended=resolve;source.start();});
}

export function createNarrator({language='ru',steps=5,lookahead=4,onSegment=()=>{},onState=()=>{},onEnd=()=>{},onError=()=>{}}={}){
 let queue=[],index=0,playing=false,generation=0,source=null,title='';
 const ready=new Map();
 const state=extra=>onState({playing,index,total:queue.length,...extra});

 function prefetch(){
  const version=generation;
  for(let i=index;i<Math.min(queue.length,index+lookahead);i++){
   if(ready.has(i))continue;
   const row=queue[i];
   ready.set(i,synthesize({text:row.text,lang:language,voice:row.voice,steps,speed:row.speed/(row.rate||1),tags:row.tags,seed:7+i%5}).then(result=>{
    if(version!==generation)return null;
    const buffer=audioContext().createBuffer(1,result.audio.length,result.sampleRate);buffer.copyToChannel(result.audio,0);
    return {buffer,ms:result.ms,provider:result.provider};
   }));
  }
  for(const key of ready.keys())if(key<index-1)ready.delete(key);
 }

 async function playNext(){
  if(!playing)return;
  if(index>=queue.length){playing=false;state();onEnd();return;}
  const version=generation,row=queue[index];
  onSegment(row);
  prefetch();
  let item;
  try{state({buffering:true});item=await ready.get(index);}catch(error){if(version===generation){playing=false;state();onError(error);}return;}
  if(version!==generation||!playing||!item)return;
  const ctx=audioContext();if(ctx.state==='suspended')await ctx.resume();
  source=ctx.createBufferSource();source.buffer=item.buffer;source.playbackRate.value=row.rate||1;
  source.connect(voiceChain(ctx,row).input);
  state({buffering:false,provider:item.provider});
  source.onended=()=>{if(version!==generation||!playing)return;source=null;setTimeout(()=>{if(version!==generation)return;index++;playNext();},row.pause*1000);};
  source.start();
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
  load(rows,{start=0,label=''}={}){generation++;source?.stop?.();source=null;ready.clear();queue=rows;index=Math.max(0,Math.min(start,rows.length));title=label;state();},
  async play(){
   if(playing||!queue.length)return;
   playing=true;dispatchEvent(new CustomEvent(TTS_EVENT));claimMedia();
   const ctx=audioContext();if(ctx.state==='suspended')await ctx.resume();
   generation++;ready.clear();playNext();
  },
  pause(){if(!playing)return;playing=false;generation++;try{source?.stop();}catch{}source=null;state();},
  skip(step){const was=playing;api.pause();index=Math.max(0,Math.min(queue.length-1,index+step));state();if(was)api.play();},
  seekSegment(segmentId){const at=queue.findIndex(r=>r.segment===segmentId);if(at>=0){const was=playing;api.pause();index=at;state();if(was)api.play();}},
  get playing(){return playing;},get index(){return index;},get queue(){return queue;},
  destroy(){api.pause();removeEventListener('mediavault-music-playing',yieldToOthers);document.removeEventListener('play',onVideo,true);try{if(navigator.mediaSession?.metadata?.artist==='MediaVault · озвучка')navigator.mediaSession.metadata=null;}catch{}},
 };
 return api;
}
