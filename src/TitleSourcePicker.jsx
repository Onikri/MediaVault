import {useId,useState} from 'react';
import {mangaLanguageName} from './manga-import.js';

const plural=(n,forms)=>{const v=n%100;return forms[v>=11&&v<=14?2:n%10===1?0:n%10>=2&&n%10<=4?1:2];};
export default function TitleSourcePicker({sources,value,onChoose,info={},loading=false,requireVerified=false}){
 const [query,setQuery]=useState(''),id=useId();
 const normalized=query.normalize('NFKC').toLocaleLowerCase().trim();
 const matches=sources.filter(s=>[s.providerName,s.title].join(' ').normalize('NFKC').toLocaleLowerCase().includes(normalized));
 const unavailable=matches.filter(s=>info[s.url]?.state==='error'||info[s.url]?.readable===false||info[s.url]?.chapterCount===0);
 const visible=matches.filter(s=>!unavailable.includes(s)&&(!requireVerified||info[s.url]?.readable===true));
 const pending=matches.length-visible.length-unavailable.length;
 const counts=s=>{const data=info[s.url]||s;return Number.isInteger(data.chapterCount)?`${data.chapterCount} ${plural(data.chapterCount,['глава','главы','глав'])} · ${data.volumeCount??'—'} ${plural(data.volumeCount,['том','тома','томов'])}`:data.state==='error'?data.error:'Проверяем главы и тома…';};
 return <section className="title-source-picker" aria-label="Источники чтения">
  <div className="section-heading"><h4>Источники <span className="fine">{visible.length}</span></h4>{(loading||pending>0)&&<span className="fine" role="status">{pending>0?'Проверяем страницы · '+pending:'Поиск продолжается'}</span>}</div>
  <label className="input-label" htmlFor={id}>Поиск по источникам</label><input id={id} className="field-input" value={query} onChange={e=>setQuery(e.target.value)} type="search" placeholder="Название сайта или перевода…"/>
  <div className="title-source-options" role="group" aria-label="Выбрать источник чтения">{visible.map(s=><button type="button" className="title-source-option" aria-pressed={value===s.url} key={s.url} onClick={()=>onChoose(s.url)}><span><strong>{s.providerName}</strong><small>{mangaLanguageName(s.language)}</small></span><span className="title-source-counts" data-state={info[s.url]?.state}><span>{counts(s)}</span>{info[s.url]?.state==='error'&&<small>Выбрать и повторить проверку</small>}</span></button>)}</div>
  {!visible.length&&<p className="fine" role="status">{pending||loading?'Проверяем, отдают ли читалки страницы…':query?'Нет доступных источников с таким названием.':'Работающий источник для этого тайтла пока не найден.'}</p>}
  {unavailable.length>0&&<details className="title-source-tools"><summary>Недоступные источники · {unavailable.length}</summary>{unavailable.map(s=><div key={s.url}><p className="fine"><strong>{s.providerName}</strong> · {mangaLanguageName(s.language)}<br/>{info[s.url]?.error||info[s.url]?.readabilityError||'Нет открытых глав.'}</p><button type="button" className="text-link" onClick={()=>onChoose(s.url)}>Повторить проверку</button></div>)}</details>}
 </section>;
}
