import {ArrowUpRight} from 'lucide-react';
import {plural} from './title-context.js';
import {ratingColors} from './PlatformRatings.jsx';
import {uiLocale} from './i18n/index.js';
import './title-passport.css';

import {passportVolume,whole} from './title-passport-model.js';
export {runtime} from './title-passport-model.js';
const format=value=>new Intl.NumberFormat(uiLocale(),{maximumFractionDigits:1}).format(value);
const compact=value=>new Intl.NumberFormat(uiLocale(),{notation:'compact',maximumFractionDigits:1}).format(value);

// A phrase made of figures: [[112,chapter forms],[14,volume forms]] → «112 глав, 14 томов».
function Figures({parts,joiner}){
 const shown=parts.filter(([n])=>whole(n));if(!shown.length)return null;
 return <p className="passport-figures">{shown.map(([n,forms],i)=><span key={i}>{i>0&&<span className="passport-joiner">{joiner||' · '}</span>}<strong>{format(whole(n))}</strong> {plural(whole(n),forms)}</span>)}</p>;
}
// The work's structure as a ruler: one mark per volume, season or episode
// (bucketed past 48), filled up to what is released or translated.
function Ruler({units,filled,label}){
 const count=Math.min(48,whole(units));if(count<2)return null;
 const share=Math.max(0,Math.min(1,filled));
 return <div className="passport-ruler" role="img" aria-label={label} data-dense={count>12||undefined} style={{'--marks':count}}>
  {Array.from({length:count},(_,i)=><i key={i} data-state={(i+1)/count<=share+1e-9?'done':i/count<share?'part':undefined}/>)}
 </div>;
}

export default function TitlePassport({kind,profile:p,stats,ratings,extraScores=[],facts=[],factValue=(l,v)=>v,heading,ownRating=0,onRate,rateDisabled=false,rateNote}){
 const volume=passportVolume(kind,p,stats);
 const scores=[...(ratings?.items||[]).map(item=>({key:item.provider,name:item.name,value:item.normalized,votes:item.votes,url:item.url,rgb:ratingColors[item.provider]})),...extraScores].filter(s=>Number(s.value)>0);
 const rows=facts.filter(([,value])=>value!=null&&value!==''&&!(Array.isArray(value)&&!value.length));
 return <section className="title-facts title-passport" aria-label={heading||'Сведения о тайтле'}>
  {(volume.figures.length>0||volume.lead)&&<div className="passport-volume">
   {volume.lead&&<p className="passport-figures"><strong>{volume.lead}</strong></p>}
   <Figures parts={volume.figures} joiner={volume.joiner}/>
   {volume.ruler&&<Ruler {...volume.ruler}/>}
   {volume.note&&<p className="passport-note">{volume.note}</p>}
  </div>}
  {scores.length>0&&<ul className="passport-scores" aria-label="Оценки на платформах">{scores.map(s=><li key={s.key} style={s.rgb?{'--score-rgb':s.rgb}:undefined}>
   {s.url?<a href={s.url} target="_blank" rel="noopener noreferrer"><b>{format(s.value)}</b><span>{s.name}{s.votes?<small>{compact(s.votes)}</small>:null}</span><ArrowUpRight size={12} aria-hidden="true"/></a>
    :<span className="passport-score-static"><b>{format(s.value)}</b><span>{s.name}{s.votes?<small>{compact(s.votes)}</small>:null}</span></span>}
  </li>)}</ul>}
  {ratings?.loading&&!scores.length&&<p className="passport-note" role="status">Сверяем оценки платформ…</p>}
  {rows.length>0&&<dl className="passport-facts">{rows.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{factValue(label,value)}</dd></div>)}</dl>}
  {onRate&&<div className="passport-rate"><p>Твоя оценка{ownRating?<> <b>{ownRating} из 10</b></>:null}</p>
   <div role="group" aria-label="Оценить произведение">{Array.from({length:10},(_,i)=><button type="button" key={i} aria-label={'Оценка '+(i+1)} aria-pressed={ownRating===i+1} data-filled={ownRating>i||undefined} disabled={rateDisabled} onClick={()=>onRate(i+1)}/>)}</div>
   {rateNote&&<small>{rateNote}</small>}</div>}
 </section>;
}
