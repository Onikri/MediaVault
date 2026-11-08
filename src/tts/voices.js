// Casting and delivery. Supertonic has ten preset voices (F1–F5, M1–M5) and
// no emotion embedding, so a character gets a preset or a blend of two, and an
// emotion becomes what the model really controls: pace, loudness, pauses and
// the <laugh>/<sigh>/<breath> expression tags.
const FEMALE=['F1','F2','F3','F4','F5'],MALE=['M1','M2','M3','M4','M5'];
const KEY='mediavault_tts_cast_v1:';

export const DELIVERY={
 neutral:{speed:1,gain:1,pause:.32},joy:{speed:1.06,gain:1.06,pause:.28},sad:{speed:.9,gain:.84,pause:.5},angry:{speed:1.08,gain:1.18,pause:.22},
 fear:{speed:1.1,gain:.9,pause:.25},surprise:{speed:1.05,gain:1.1,pause:.3},whisper:{speed:.92,gain:.55,pause:.4},shout:{speed:1.1,gain:1.28,pause:.22},
 tender:{speed:.95,gain:.88,pause:.4},sarcastic:{speed:.97,gain:1,pause:.35},tired:{speed:.88,gain:.82,pause:.5},excited:{speed:1.08,gain:1.12,pause:.25},
};

// Interpolate toward the emotion by its intensity, then apply the reader's pace.
export function delivery(segment,pace=1){
 const target=DELIVERY[segment.emotion]||DELIVERY.neutral,k=segment.kind==='narration'?.4:Math.max(0,Math.min(1,segment.intensity??.5));
 const mix=(a,b)=>a+(b-a)*k;
 return {speed:Math.max(.6,Math.min(1.6,mix(1,target.speed)*pace)),gain:mix(1,target.gain)*(segment.kind==='thought'?.85:1),pause:mix(.32,target.pause)};
}

function stableHash(text){let h=2166136261;for(const c of String(text))h=Math.imul(h^c.codePointAt(0),16777619)>>>0;return h;}

// Distinct voices: most frequent characters get pure presets of their gender,
// later ones a blend of two presets; the narrator keeps its own preset.
export function castVoices(segments,characters=[],{narrator='M2',saved={}}={}){
 const counts=new Map();
 for(const s of segments)if(s.kind!=='narration'&&s.speaker)counts.set(s.speaker,(counts.get(s.speaker)||0)+1);
 const info=new Map(characters.map(c=>[c.name,c]));
 for(const s of segments)if(s.speaker&&!info.has(s.speaker))info.set(s.speaker,{name:s.speaker,gender:s.gender||'u',age:'adult'});
 const cast={...saved},used=new Set(Object.values(cast).map(v=>JSON.stringify(v.voice)));used.add(JSON.stringify({[narrator]:1}));
 const pick=(pool,seed)=>{
  for(const p of pool){const v={[p]:1};if(!used.has(JSON.stringify(v)))return v;}
  for(let i=0;i<pool.length*pool.length;i++){const a=pool[(seed+i)%pool.length],b=pool[(seed+i*3+1)%pool.length];if(a===b)continue;const v={[a]:.6,[b]:.4};if(!used.has(JSON.stringify(v)))return v;}
  return {[pool[seed%pool.length]]:1};
 };
 for(const [name] of [...counts].sort((a,b)=>b[1]-a[1])){
  if(cast[name])continue;
  const c=info.get(name)||{gender:'u',age:'adult'},seed=stableHash(name);
  const voice=c.gender==='f'?pick(FEMALE,seed):c.gender==='m'?pick(MALE,seed):pick(seed%2?FEMALE:MALE,seed);
  used.add(JSON.stringify(voice));
  cast[name]={voice,gender:c.gender,age:c.age||'adult',pace:c.age==='child'?1.08:c.age==='old'?.92:1};
 }
 return cast;
}

export function voiceFor(segment,cast,narrator='M2'){
 if(segment.kind==='narration'||!segment.speaker||!cast[segment.speaker]){
  if(segment.kind!=='narration'&&segment.gender==='f')return {voice:{F2:1},pace:1};
  if(segment.kind!=='narration'&&segment.gender==='m')return {voice:{M4:1},pace:1};
  return {voice:{[narrator]:1},pace:1};
 }
 return cast[segment.speaker];
}

export function savedCast(book){try{return JSON.parse(localStorage.getItem(KEY+book)||'{}')||{};}catch{return {};}}
export function saveCast(book,cast){try{localStorage.setItem(KEY+book,JSON.stringify(cast));}catch{}}
export const voiceLabel=voice=>Object.entries(voice||{}).map(([name,w])=>w===1?name:name+' '+Math.round(w*100)+'%').join(' + ');
