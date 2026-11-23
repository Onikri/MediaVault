import {useId} from 'react';
import {LayoutGroup,motion} from 'motion/react';

// Solid glyphs drawn for these four views; the lit pill slides between them.
const GLYPHS:Record<string,JSX.Element>={
 grid:<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1.6"/><rect x="9" y="1.5" width="5.5" height="5.5" rx="1.6"/><rect x="1.5" y="9" width="5.5" height="5.5" rx="1.6"/><rect x="9" y="9" width="5.5" height="5.5" rx="1.6"/></svg>,
 compact:<svg viewBox="0 0 16 16" aria-hidden="true">{[1.5,6.2,10.9].flatMap(x=>[1.5,6.2,10.9].map(y=><rect key={x+'-'+y} x={x} y={y} width="3.6" height="3.6" rx="1"/>))}</svg>,
 list:<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2" width="3.6" height="3.6" rx="1"/><rect x="6.6" y="2.8" width="7.9" height="2" rx="1"/><rect x="1.5" y="6.2" width="3.6" height="3.6" rx="1"/><rect x="6.6" y="7" width="7.9" height="2" rx="1"/><rect x="1.5" y="10.4" width="3.6" height="3.6" rx="1"/><rect x="6.6" y="11.2" width="7.9" height="2" rx="1"/></svg>,
 table:<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2" width="13" height="2.6" rx="1.1"/><rect x="1.5" y="6.7" width="13" height="2.6" rx="1.1"/><rect x="1.5" y="11.4" width="13" height="2.6" rx="1.1"/></svg>
};
export function CatalogViewControls({value,onChange,collection=false}:{value:string;onChange:(value:string)=>void;collection?:boolean}){
 const id=useId();
 return <LayoutGroup id={'views'+id}><div className={'catalog-views'+(collection?' library-layouts':'')} role="group" aria-label={collection?'Вид библиотеки':'Вид каталога'}>
  {[['grid',collection?'Плитки':'Крупные карточки'],['compact',collection?'Маленькие плитки':'Небольшие карточки'],['list','Список'],['table','Таблица']].map(([key,label])=><button key={key} type="button" title={label} aria-label={label} aria-pressed={value===key} onClick={()=>onChange(key)}>
   {value===key&&<motion.span layoutId="lit" className="catalog-views-lit" transition={{type:'spring',stiffness:520,damping:40,mass:.8}}/>}
   <span className="catalog-views-glyph">{GLYPHS[key]}</span>
  </button>)}
 </div></LayoutGroup>;
}
