import {useId,useState} from 'react';
import {Heart} from 'lucide-react';
import {mangaLanguageName} from './manga-import.js';

const plural=(n,forms)=>{const v=n%100;return forms[v>=11&&v<=14?2:n%10===1?0:n%10>=2&&n%10<=4?1:2];};
// Sources keep the order they are given (favourites first, the most complete
// translation next). A heart marks a favourite site; the thin bar under a
// source shows how much of the work's total it has translated.
export default function TitleSourcePicker({sources,value,onChoose,info={},loading=false,requireVerified=false,favorites=null,expected=0}){
 const [query,setQuery]=useState(''),id=useId();
 const normalized=query.normalize('NFKC').toLocaleLowerCase().trim();
 const matches=sources.filter(s=>[s.providerName,s.title].join(' ').normalize('NFKC').toLocaleLowerCase().includes(normalized));
 const unavailable=matches.filter(s=>info[s.url]?.state==='error'||info[s.url]?.readable===false||info[s.url]?.chapterCount===0);
 const visible=matches.filter(s=>!unavailable.includes(s)&&(!requireVerified||info[s.url]?.readable===true||info[s.url]?.inspection?.episodes?.length));
 const pending=matches.filter(s=>!unavailable.includes(s)&&(requireVerified?info[s.url]?.readable!==true:!info[s.url]||['loading','verifying','pending'].includes(info[s.url]?.state))).length;
 const counts=s=>{const data=info[s.url]||s;return Number.isInteger(data.chapterCount)?`${data.chapterCount} ${plural(data.chapterCount,['глава','главы','глав'])} · ${data.volumeCount??'—'} ${plural(data.volumeCount,['том','тома','томов'])}${requireVerified&&data.readable!==true?' · проверяем страницы':''}`:data.state==='error'?data.error:'Проверяем главы и тома…';};
 return <section className="title-source-picker" aria-label="Источники чтения">
  <div className="section-heading"><h4>Источники <span className="fine">{visible.length}</span></h4>{(loading||pending>0)&&<span className="fine" role="status">{pending>0?'Проверяем страницы · '+pending:'Поиск продолжается'}</span>}</div>
  <label className="input-label" htmlFor={id}>Поиск по источникам</label><input id={id} className="field-input" value={query} onChange={e=>setQuery(e.target.value)} type="search" placeholder="Сайт или перевод…"/>
  <div className="title-source-options" role="group" aria-label="Выбрать источник чтения">{visible.map(s=>{const chapters=Number(info[s.url]?.chapterCount),favorite=!!favorites?.has(s);
   return <div className="title-source-row" key={s.url} data-selected={value===s.url||undefined}>
    <button type="button" className="title-source-option" aria-pressed={value===s.url} onClick={()=>onChoose(s.url)}><span><strong>{s.providerName}</strong><small>{mangaLanguageName(s.language)}</small></span><span className="title-source-counts" data-state={info[s.url]?.state}><span>{counts(s)}</span>{info[s.url]?.state==='error'&&<small>Выбрать и повторить проверку</small>}</span>
     {expected>0&&Number.isFinite(chapters)&&chapters>0&&<i className="reader-source-fill" style={{'--fill':Math.min(1,chapters/expected)}} aria-hidden="true"/>}</button>
    {favorites&&<button type="button" className="reader-source-favorite" aria-pressed={favorite} aria-label={(favorite?'Убрать из любимых: ':'В любимые источники: ')+s.providerName} title={favorite?'Любимый источник — проверяется и открывается первым':'Сделать любимым: проверять и открывать первым'} onClick={()=>favorites.toggle(s)}><Heart size={14} fill={favorite?'currentColor':'none'}/></button>}
   </div>;})}</div>
  {!visible.length&&<p className="fine" role="status">{pending||loading?'Проверяем, отдают ли читалки страницы…':query?'Нет доступных источников с таким названием.':'Работающий источник для этого тайтла пока не найден.'}</p>}
  {unavailable.length>0&&<details className="title-source-tools"><summary>Недоступные источники · {unavailable.length}</summary>{unavailable.map(s=><div key={s.url}><p className="fine"><strong>{s.providerName}</strong> · {mangaLanguageName(s.language)}<br/>{info[s.url]?.error||info[s.url]?.readabilityError||'Нет открытых глав.'}</p><button type="button" className="text-link" onClick={()=>onChoose(s.url)}>Повторить проверку</button></div>)}</details>}
 </section>;
}
