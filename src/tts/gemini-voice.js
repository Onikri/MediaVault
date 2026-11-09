// Narration with Gemini native audio (Live API) through the MediaVault server.
// The server streams 24 kHz mono 16-bit PCM for one utterance; the player
// schedules the chunks as they arrive. Voices are Google's prebuilt speakers,
// cast by the gender, age and timbre the title bible gives each character.
// Emotions are not imitated with EQ here: the model is told how to deliver.
import {personalKey} from './google.js';
import {sentences} from './text.js';
import {styleFor} from './gemini-direction.js';
export {styleFor,EMOTION_DIRECTION} from './gemini-direction.js';

export const GEMINI_VOICE_MODEL='gemini-2.5-flash-native-audio-latest';
export const GEMINI_RATE=24000;
// [name, gender, character] — Google's descriptions of the prebuilt voices.
export const GEMINI_VOICES=[
 ['Kore','f','firm'],['Sulafat','f','warm'],['Zephyr','f','bright'],['Leda','f','youthful'],['Aoede','f','breezy'],['Callirrhoe','f','easy'],
 ['Autonoe','f','bright'],['Despina','f','smooth'],['Erinome','f','clear'],['Laomedeia','f','upbeat'],['Achernar','f','soft'],['Gacrux','f','mature'],
 ['Pulcherrima','f','forward'],['Vindemiatrix','f','gentle'],
 ['Charon','m','informative'],['Orus','m','firm'],['Puck','m','upbeat'],['Fenrir','m','excitable'],['Enceladus','m','breathy'],['Iapetus','m','clear'],
 ['Umbriel','m','easy'],['Algieba','m','smooth'],['Algenib','m','gravelly'],['Rasalgethi','m','informative'],['Alnilam','m','firm'],['Schedar','m','even'],
 ['Achird','m','friendly'],['Zubenelgenubi','m','casual'],['Sadachbia','m','lively'],['Sadaltager','m','knowledgeable'],
];
export const GEMINI_CHARACTER={firm:'твёрдый',warm:'тёплый',bright:'яркий',youthful:'юный',breezy:'лёгкий',easy:'непринуждённый',smooth:'плавный',clear:'чистый',
 upbeat:'бодрый',soft:'мягкий',mature:'зрелый',forward:'напористый',gentle:'нежный',informative:'дикторский',excitable:'взволнованный',breathy:'с придыханием',
 gravelly:'хриплый',even:'ровный',friendly:'дружелюбный',casual:'простой',lively:'живой',knowledgeable:'вдумчивый'};
export const NARRATORS={m:'Charon',f:'Kore'};
const GENDER=Object.fromEntries(GEMINI_VOICES.map(([name,gender])=>[name,gender]));
// Inside the «Мужские / Женские голоса» groups the gender is already said.
export const geminiVoiceLabel=name=>name+' · '+GEMINI_CHARACTER[GEMINI_VOICES.find(v=>v[0]===name)?.[2]];

// Preferred voices by gender and age, then by the timbre the bible describes.
const BY_AGE={
 f:{child:['Leda','Laomedeia','Autonoe'],teen:['Leda','Laomedeia','Zephyr','Autonoe'],young:['Aoede','Despina','Erinome','Zephyr','Callirrhoe'],
  adult:['Kore','Sulafat','Pulcherrima','Despina','Vindemiatrix','Achernar'],old:['Gacrux','Vindemiatrix','Sulafat']},
 m:{child:['Leda','Laomedeia'],teen:['Puck','Sadachbia','Fenrir'],young:['Puck','Achird','Iapetus','Zubenelgenubi','Umbriel'],
  adult:['Orus','Alnilam','Iapetus','Algieba','Schedar','Rasalgethi'],old:['Algenib','Sadaltager','Schedar','Charon']},
};
const BY_TIMBRE={warm:['Sulafat','Algieba','Achird'],bright:['Zephyr','Autonoe','Puck'],dark:['Algenib','Alnilam','Gacrux'],breathy:['Enceladus','Achernar'],
 rough:['Algenib','Fenrir'],soft:['Achernar','Vindemiatrix','Umbriel'],nasal:[]};

export function pickGeminiVoice({gender='m',age='adult',timbre='neutral'}={},used=new Set()){
 const g=gender==='f'?'f':'m',a=BY_AGE[g][age]?age:'adult';
 const own=GEMINI_VOICES.filter(v=>v[1]===g).map(v=>v[0]);
 const byTimbre=(BY_TIMBRE[timbre]||[]).filter(v=>GENDER[v]===g||a==='child');
 const order=[...byTimbre,...BY_AGE[g][a],...own];
 return order.find(v=>!used.has(v))||order[0];
}

// narratorChoice: 'auto' (the bible's narrator), 'm', 'f' or a voice name.
export function geminiNarrator(bible,choice='auto'){
 if(GENDER[choice])return choice;
 if(choice==='m'||choice==='f')return NARRATORS[choice];
 const n=bible?.narrator;
 if(!n)return NARRATORS.m;
 return n.gender==='f'?(n.timbre==='warm'||n.timbre==='soft'?'Sulafat':'Kore'):(n.age==='old'||n.timbre==='dark'?'Schedar':'Charon');
}

// cast: the Supertonic casting (gender, age, timbre per character) reused for
// order and character facts; saved: the listener's own choices {name: voice}.
export function geminiCast(cast,{narrator,saved={}}={}){
 const used=new Set([narrator]),result={};
 for(const [name,value] of Object.entries(cast)){
  const voice=GENDER[saved[name]]?saved[name]:pickGeminiVoice(value,used);
  used.add(voice);result[name]=voice;
 }
 return result;
}
const SAVED='mediavault_tts_gemini_cast_v1:';
export function savedGeminiCast(book){try{return JSON.parse(localStorage.getItem(SAVED+book)||'{}')||{};}catch{return {};}}
export function saveGeminiCast(book,value){try{localStorage.setItem(SAVED+book,JSON.stringify(value));}catch{}}

// Sentences of one segment are joined up to ~300 characters: the model keeps
// intonation across them and fewer sessions are opened. Stress marks of the
// title lexicon are for Supertonic; Gemini reads names well without them.
function chunks(text,limit=300){
 const out=[];
 for(const part of sentences(String(text).replace(/́/g,''),limit)){if(out.length&&(out.at(-1)+' '+part).length<=limit)out[out.length-1]+=' '+part;else out.push(part);}
 return out.filter(Boolean);
}
export function geminiRows(segments,{cast,voices,narrator,bible,pace=1}){
 const rows=[];
 for(const segment of segments){
  const own=segment.kind!=='narration'&&segment.speaker&&voices[segment.speaker];
  const voice=own||(segment.kind!=='narration'&&segment.gender==='f'?pickGeminiVoice({gender:'f'},new Set([narrator])):segment.kind!=='narration'&&segment.gender==='m'?pickGeminiVoice({gender:'m'},new Set([narrator])):narrator);
  const style=styleFor(segment,own?cast[segment.speaker]:segment.gender?{gender:segment.gender}:null,{tone:bible?.tone,pace});
  const parts=chunks(segment.spoken||segment.text);
  parts.forEach((text,i)=>rows.push({segment:segment.id,p:segment.p,text,voice,style,rate:1,gain:1,eq:{low:0,mid:0,high:0},
   pause:i===parts.length-1?(segment.kind==='narration'?.3:.22):.08,kind:segment.kind}));
 }
 return rows;
}

// 16-bit little-endian PCM bytes → Float32 samples; an odd byte waits for the next chunk.
export function pcmDecoder(){
 let rest=null;
 return bytes=>{
  let data=bytes;
  if(rest){data=new Uint8Array(rest.length+bytes.length);data.set(rest);data.set(bytes,rest.length);rest=null;}
  const even=data.length&~1;if(even<data.length)rest=data.slice(even);
  const view=new DataView(data.buffer,data.byteOffset,even),out=new Float32Array(even/2);
  for(let i=0;i<out.length;i++)out[i]=view.getInt16(i*2,true)/32768;
  return out;
 };
}

// A clip fills while the server streams; the player listens through clip.wake.
export function geminiClip({service,userId,text,voice,style,language,signal}){
 const clip={chunks:[],done:false,error:null,sampleRate:GEMINI_RATE,provider:'gemini',wake:null};
 const update=()=>clip.wake?.();
 (async()=>{
  const key=await personalKey(userId).catch(()=>'');
  const response=await service.request('/reader/google/speak',{method:'POST',raw:true,signal:signal||AbortSignal.timeout(180000),
   body:{...(key?{key}:{}),text,voice,style,language:language==='uk'?'uk':'ru'}});
  const reader=response.body.getReader(),decode=pcmDecoder();
  for(;;){const {done,value}=await reader.read();if(done)break;const samples=decode(value);if(samples.length){clip.chunks.push(samples);update();}}
 })().catch(error=>{if(!signal?.aborted)clip.error=error;}).finally(()=>{clip.done=true;update();});
 return clip;
}

// The whole clip as one buffer, for voice samples in the cast panel.
export function wholeClip(clip){
 return new Promise((resolve,reject)=>{
  const check=()=>{if(!clip.done)return;clip.wake=null;
   if(clip.error&&!clip.chunks.length)return reject(clip.error);
   const audio=new Float32Array(clip.chunks.reduce((n,c)=>n+c.length,0));let at=0;for(const c of clip.chunks){audio.set(c,at);at+=c.length;}
   resolve({audio,sampleRate:clip.sampleRate});};
  clip.wake=check;check();
 });
}
