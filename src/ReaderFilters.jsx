import {useId} from 'react';
import {Heart} from 'lucide-react';
import {contentLanguage} from './content-language.js';
import {counted} from './title-context.js';

// The reader's first language: Ukrainian for a Ukrainian profile, else Russian.
export const defaultReadingLanguage=()=>contentLanguage()==='uk'?'uk':'ru';

// A shop-style filter group: one choice, every option visible at once.
export function FilterGroup({legend,value,options,onChange,disabled=false}){
 const id=useId();
 return <fieldset className="reader-filter-group" disabled={disabled}>
  <legend id={id}>{legend}</legend>
  <div role="radiogroup" aria-labelledby={id}>{options.map(([key,label,hint])=><button type="button" role="radio" key={key} aria-checked={String(value)===String(key)} onClick={()=>String(value)!==String(key)&&onChange(key)}>
   <span>{label}</span>{hint!=null&&<small>{hint}</small>}
  </button>)}</div>
 </fieldset>;
}

// Sources of the chosen language, best first, with a heart for favourite sites.
export function SourceList({sources,value,onChoose,favorites,info=()=>({}),loading=false,pending=0,expected=0,noun=['глава','главы','глав']}){
 return <fieldset className="reader-filter-group reader-source-list">
  <legend>Источники{sources.length?<small> · {sources.length}</small>:null}</legend>
  {sources.length>0&&<ul>{sources.map(source=>{const data=info(source)||{},selected=value===source.url,favorite=favorites.has(source),chapters=Number(data.chapters);
   return <li key={source.url} data-selected={selected||undefined}>
    <button type="button" className="reader-source-pick" aria-pressed={selected} onClick={()=>onChoose(source)}>
     <strong>{source.providerName}</strong>
     <small>{Number.isFinite(chapters)&&chapters>0?counted(chapters,noun)+(expected?' из '+expected:''):data.error?'Не открылся':'Проверяем главы…'}{data.translator?' · '+data.translator:''}</small>
     {Number.isFinite(chapters)&&expected>0&&<i className="reader-source-fill" style={{'--fill':Math.min(1,chapters/expected)}} aria-hidden="true"/>}
    </button>
    <button type="button" className="reader-source-favorite" aria-pressed={favorite} aria-label={(favorite?'Убрать из любимых: ':'В любимые источники: ')+source.providerName} title={favorite?'Любимый источник — проверяется первым':'Сделать любимым: проверять и открывать первым'} onClick={()=>favorites.toggle(source)}><Heart size={14} fill={favorite?'currentColor':'none'}/></button>
   </li>;})}</ul>}
  {(loading||pending>0)&&<p className="reader-filter-note" role="status"><span className="loading-ring"/>{pending>0?'Проверяем источники · '+pending:'Ищем источники…'}</p>}
 </fieldset>;
}
