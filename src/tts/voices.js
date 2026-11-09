// Casting and delivery. Supertonic has ten preset voices (F1–F5, M1–M5) and
// no emotion embedding. A character's voice is built from what really works:
// the preset whose MEASURED pitch and brightness fit the character, a pitch
// shift in semitones (played faster/slower with tempo compensated in
// synthesis) and a three-band equaliser for timbre. Emotions change pace,
// loudness, pauses, expression tags and add their own EQ tint.

// Measured on 3 Russian sentences each (median F0 in Hz, spectral centroid in
// Hz, share of energy above 4 kHz), Supertonic 3, 5 steps, 2026-11-08.
export const PRESET_TRAITS={
 F1:{f0:186,centroid:485,air:.011},F2:{f0:212,centroid:692,air:.010},F3:{f0:169,centroid:1247,air:.110},F4:{f0:200,centroid:635,air:.011},F5:{f0:165,centroid:410,air:.016},
 M1:{f0:127,centroid:612,air:.004},M2:{f0:89,centroid:487,air:.004},M3:{f0:102,centroid:559,air:.024},M4:{f0:122,centroid:359,air:.004},M5:{f0:90,centroid:325,air:.010},
};
const FEMALE=['F1','F2','F3','F4','F5'],MALE=['M1','M2','M3','M4','M5'];
const KEY='mediavault_tts_cast_v2:';
// Typical speaking pitch by gender and age (Hz) the casting aims for.
const TARGET={f:{child:270,teen:228,young:210,adult:192,old:170},m:{child:250,teen:150,young:128,adult:112,old:94}};
export const TIMBRE_EQ={neutral:{low:0,mid:0,high:0},warm:{low:3,mid:-1,high:-2},bright:{low:-1,mid:2,high:3},dark:{low:2,mid:-1,high:-4},
 breathy:{low:-2,mid:-1,high:4},rough:{low:1,mid:3,high:-1},nasal:{low:-2,mid:4,high:-1,midFreq:1100},soft:{low:1,mid:-2,high:-1}};

export const DELIVERY={
 neutral:{speed:1,gain:1,pause:.32},joy:{speed:1.06,gain:1.06,pause:.28,eq:{high:1}},sad:{speed:.9,gain:.84,pause:.5,eq:{high:-2}},angry:{speed:1.08,gain:1.18,pause:.22,eq:{mid:2}},
 fear:{speed:1.1,gain:.9,pause:.25,eq:{low:-1}},surprise:{speed:1.05,gain:1.1,pause:.3},whisper:{speed:.92,gain:.55,pause:.4,eq:{low:-6,high:4}},shout:{speed:1.1,gain:1.28,pause:.22,eq:{mid:3}},
 tender:{speed:.95,gain:.88,pause:.4,eq:{low:1,high:-1}},sarcastic:{speed:.97,gain:1,pause:.35},tired:{speed:.88,gain:.82,pause:.5,eq:{high:-2}},excited:{speed:1.08,gain:1.12,pause:.25,eq:{high:1}},
 calm:{speed:.96,gain:.95,pause:.38},cold:{speed:.97,gain:.95,pause:.36,eq:{low:-2,mid:1}},pleading:{speed:.95,gain:.92,pause:.36},nervous:{speed:1.07,gain:.94,pause:.24},
 determined:{speed:1.02,gain:1.1,pause:.3,eq:{mid:1}},proud:{speed:.97,gain:1.08,pause:.34,eq:{low:1}},menacing:{speed:.9,gain:1,pause:.45,eq:{low:3,high:-2}},
 crying:{speed:.88,gain:.85,pause:.5,eq:{high:-1}},embarrassed:{speed:1.02,gain:.85,pause:.3},disgust:{speed:.96,gain:1,pause:.34,eq:{mid:1}},
 confused:{speed:.98,gain:.95,pause:.36},dreamy:{speed:.92,gain:.9,pause:.42,eq:{high:1}},
};

// Interpolate toward the emotion by its intensity, then apply the reader's pace.
export function delivery(segment,pace=1){
 const target=DELIVERY[segment.emotion]||DELIVERY.neutral,k=segment.kind==='narration'?Math.min(.5,(segment.intensity??.3)*.6):Math.max(0,Math.min(1,segment.intensity??.5));
 const mix=(a,b)=>a+(b-a)*k,eq=Object.fromEntries(['low','mid','high'].map(band=>[band,(target.eq?.[band]||0)*k]));
 return {speed:Math.max(.6,Math.min(1.6,mix(1,target.speed)*pace)),gain:mix(1,target.gain)*(segment.kind==='thought'?.85:1),pause:mix(.32,target.pause),eq};
}

function stableHash(text){let h=2166136261;for(const c of String(text))h=Math.imul(h^c.codePointAt(0),16777619)>>>0;return h;}
const semitones=(from,to)=>12*Math.log2(to/from);

// The preset closest to the wanted pitch and timbre that nobody else uses
// yet; then a pitch shift (±4 semitones at most) closes the remaining gap.
export function designVoice(design={},used=new Set()){
 const gender=design.gender==='f'?'f':design.gender==='m'?'m':'m';
 const age=TARGET[gender][design.age]?design.age:'adult';
 const target=TARGET[gender][age]*Math.pow(2,(Number(design.pitch)||0)*.75/12);
 const pool=gender==='f'||(gender==='m'&&age==='child')?FEMALE:MALE;
 const timbre=TIMBRE_EQ[design.timbre]?design.timbre:'neutral';
 const score=p=>{const t=PRESET_TRAITS[p];
  let s=Math.abs(semitones(t.f0,target));
  if(timbre==='bright')s-=t.centroid/400;if(timbre==='dark'||timbre==='warm')s+=t.centroid/500;if(timbre==='breathy'||timbre==='soft')s-=t.air*30;
  return s+(used.has(p)?4:0);};
 const preset=[...pool].sort((a,b)=>score(a)-score(b))[0];
 const shift=Math.max(-4,Math.min(4,semitones(PRESET_TRAITS[preset].f0,target)));
 const eq={...TIMBRE_EQ[timbre]};
 const energy=Number(design.energy)||0;
 return {voice:{[preset]:1},rate:Math.pow(2,Math.round(shift*2)/2/12),pitch:Math.round(shift*2)/2,eq,
  gain:1+energy*.05,pace:Math.max(.85,Math.min(1.15,Number(design.pace)||(age==='child'?1.06:age==='old'?.93:1))),timbre,gender,age};
}

// Distinct voices: bible characters first (by importance), then speakers the
// chapter pass found. Saved choices of the listener always win.
export function castVoices(segments,characters=[],{narrator='auto',saved={},bible=null}={}){
 const counts=new Map();
 for(const s of segments)if(s.kind!=='narration'&&s.speaker)counts.set(s.speaker,(counts.get(s.speaker)||0)+1);
 const info=new Map([...characters,...(bible?.characters||[])].map(c=>[c.name,c]));
 for(const s of segments)if(s.speaker&&!info.has(s.speaker))info.set(s.speaker,{name:s.speaker,gender:s.gender||'u',age:'adult'});
 const narratorVoice=narratorCast(bible,narrator);
 const cast={},used=new Set([Object.keys(narratorVoice.voice)[0]]);
 const rank={main:0,secondary:1,minor:2};
 const order=[...counts.keys()].sort((a,b)=>(rank[info.get(a)?.importance]??3)-(rank[info.get(b)?.importance]??3)||counts.get(b)-counts.get(a));
 for(const name of order){
  const c=info.get(name)||{gender:'u',age:'adult'};
  if(saved[name]?.voice){cast[name]={...designVoice(c,used),...saved[name],saved:true};used.add(Object.keys(cast[name].voice)[0]);continue;}
  const design={...c,gender:c.gender==='u'?(stableHash(name)%2?'f':'m'):c.gender};
  const value=designVoice(design,used);
  // Same preset twice: separate the two by pitch and timbre.
  if(used.has(Object.keys(value.voice)[0])){value.pitch=Math.max(-4,Math.min(4,value.pitch+(stableHash(name)%2?1.5:-1.5)));value.rate=Math.pow(2,value.pitch/12);value.eq={...value.eq,high:(value.eq.high||0)+(stableHash(name)%2?2:-2)};}
  used.add(Object.keys(value.voice)[0]);
  // description and geminiVoice: the director's words for this voice and its Gemini pick.
  cast[name]={...value,traits:c.traits||'',speech:c.speech||'',importance:c.importance||'',description:c.voice||'',geminiVoice:c.geminiVoice||''};
 }
 return cast;
}

// 'auto': the narrator voice the title bible describes; otherwise a preset.
export function narratorCast(bible,choice='auto'){
 if(choice==='auto'&&bible?.narrator)return designVoice(bible.narrator);
 return {voice:{[PRESET_TRAITS[choice]?choice:'M2']:1},rate:1,pitch:0,eq:{low:0,mid:0,high:0},gain:1,pace:1,timbre:'neutral'};
}

export function voiceFor(segment,cast,narrator){
 if(segment.kind==='narration'||!segment.speaker||!cast[segment.speaker]){
  if(segment.kind!=='narration'&&segment.gender==='f')return {voice:{F2:1},pace:1,rate:1,eq:{low:0,mid:0,high:1},gain:1};
  if(segment.kind!=='narration'&&segment.gender==='m')return {voice:{M4:1},pace:1,rate:1,eq:{low:0,mid:0,high:0},gain:1};
  return narrator;
 }
 return cast[segment.speaker];
}

export function savedCast(book){try{return JSON.parse(localStorage.getItem(KEY+book)||'{}')||{};}catch{return {};}}
// Only what the listener changed is stored: preset, pitch and timbre.
export function saveCast(book,cast){try{localStorage.setItem(KEY+book,JSON.stringify(Object.fromEntries(Object.entries(cast).filter(([,v])=>v.saved).map(([k,v])=>[k,{voice:v.voice,pitch:v.pitch,rate:v.rate,eq:v.eq,timbre:v.timbre,saved:true}]))));}catch{}}
export const voiceLabel=voice=>Object.entries(voice||{}).map(([name,w])=>w===1?name:name+' '+Math.round(w*100)+'%').join(' + ');
