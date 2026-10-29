import {useId,useState} from 'react';
import {mangaLanguageName} from './manga-import.js';

export default function TitleSourcePicker({sources,value,onChoose,info={},loading=false}){
 const [query,setQuery]=useState(''),id=useId();
 const normalized=query.normalize('NFKC').toLocaleLowerCase().trim();
 const visible=sources.filter(s=>[s.providerName,s.title].join(' ').normalize('NFKC').toLocaleLowerCase().includes(normalized));
 const counts=s=>{const data=info[s.url]||s;return Number.isInteger(data.chapterCount)?`${data.chapterCount} глав · ${data.volumeCount??'—'} томов`:data.state==='error'?data.error:'Проверяем главы и тома…';};
 return <section className="title-source-picker" aria-label="Источники чтения">
  <div className="section-heading"><h4>Источники <span className="fine">{sources.length}</span></h4>{loading&&<span className="fine" role="status">Поиск продолжается</span>}</div>
  <label className="input-label" htmlFor={id}>Поиск по источникам</label><input id={id} className="field-input" value={query} onChange={e=>setQuery(e.target.value)} type="search" placeholder="Название сайта или перевода…"/>
  <div className="title-source-options" role="group" aria-label="Выбрать источник чтения">{visible.map(s=><button type="button" className="title-source-option" aria-pressed={value===s.url} key={s.url} onClick={()=>onChoose(s.url)}><span><strong>{s.providerName}</strong><small>{mangaLanguageName(s.language)}</small></span><span className="title-source-counts" data-state={info[s.url]?.state}><span>{counts(s)}</span>{info[s.url]?.state==='error'&&<small>Выбрать и повторить проверку</small>}</span></button>)}</div>
  {!visible.length&&<p className="fine" role="status">{query?'Нет источников с таким названием. Измени поиск.':loading?'Проверяем подключённые источники…':'По выбранным фильтрам источников пока нет.'}</p>}
 </section>;
}
