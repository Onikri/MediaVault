// Shows who speaks in the text itself: the speaker's name before their line,
// a colour per character (the same colour in the cast panel and the caption),
// the emotion the narration will use, and the phrase being spoken right now.
// The paragraph text is never rewritten: segments are located in it in order.
import {uiLanguage} from '../i18n/index.js';
export const ROLE_COLORS=['#d9485f','#2f7fe0','#1f9d6c','#c27a00','#8a58d6','#d1457f','#0f97ab','#6f8f12'];
export const EMOTION_LABELS={joy:'радостно',sad:'грустно',angry:'сердито',fear:'испуганно',surprise:'удивлённо',whisper:'шёпотом',shout:'громко',
 tender:'мягко',sarcastic:'с иронией',tired:'устало',excited:'взволнованно',calm:'спокойно',cold:'холодно',pleading:'умоляюще',nervous:'нервно',
 determined:'решительно',proud:'гордо',menacing:'угрожающе',crying:'сквозь слёзы',embarrassed:'смущённо',disgust:'с отвращением',confused:'растерянно',dreamy:'мечтательно'};
// Chips sit inside translate="no" prose, so they are localised here.
const EMOTION_LABELS_UK={joy:'радісно',sad:'сумно',angry:'сердито',fear:'налякано',surprise:'здивовано',whisper:'пошепки',shout:'голосно',
 tender:'лагідно',sarcastic:'з іронією',tired:'втомлено',excited:'схвильовано',calm:'спокійно',cold:'холодно',pleading:'благально',nervous:'нервово',
 determined:'рішуче',proud:'гордо',menacing:'загрозливо',crying:'крізь сльози',embarrassed:'збентежено',disgust:'з огидою',confused:'розгублено',dreamy:'мрійливо'};

// Colours follow the cast order (most frequent speakers first), so the first
// eight characters of a chapter never share a colour.
export function roleColors(cast){
 return Object.fromEntries(Object.keys(cast||{}).map((name,i)=>[name,ROLE_COLORS[i%ROLE_COLORS.length]]));
}

export function segmentsByParagraph(segments){
 const map=new Map();
 for(const s of segments||[]){if(!map.has(s.p))map.set(s.p,[]);map.get(s.p).push(s);}
 return map;
}

export function emotionLabel(segment){
 return segment&&segment.kind!=='narration'&&segment.emotion&&segment.emotion!=='neutral'&&(segment.intensity??.5)>=.45?(uiLanguage()==='uk'?EMOTION_LABELS_UK:EMOTION_LABELS)[segment.emotion]||'':'';
}

export default function RoleText({text,segments,colors,speaking,show=true}){
 if(!show||!segments?.length||!segments.some(s=>s.kind!=='narration'))return text;
 const out=[];let cursor=0,last=null;
 segments.forEach((segment,i)=>{
  const at=segment.text?text.indexOf(segment.text,cursor):-1;
  if(at<0)return;
  const speech=segment.kind!=='narration',named=speech&&segment.speaker,color=named?colors?.[segment.speaker]:null;
  const mood=emotionLabel(segment),label=named&&(segment.speaker!==last||mood);
  const chip=label&&<b key={'n'+i} className="role-name" style={color?{'--role':color}:undefined} aria-label={(uiLanguage()==='uk'?'Говорить ':'Говорит ')+segment.speaker+(mood?', '+mood:'')}>{segment.speaker}{mood&&<i>{mood}</i>}</b>;
  const before=at>cursor?text.slice(cursor,at):'';
  // "— Line": the name goes before the dialogue dash, like a script.
  const dash=chip&&/^\s*[—–―-]\s*$/.test(before);
  if(dash)out.push(chip);
  if(before)out.push(before);
  out.push(<span key={i} data-segment={segment.id} className={'role-segment'+(speech?' role-speech':'')+(segment.kind==='thought'?' role-thought':'')+(segment.id===speaking?' is-speaking':'')} style={color?{'--role':color}:undefined}>
   {chip&&!dash&&chip}{segment.text}</span>);
  cursor=at+segment.text.length;if(named)last=segment.speaker;
 });
 if(cursor<text.length)out.push(text.slice(cursor));
 return out;
}
