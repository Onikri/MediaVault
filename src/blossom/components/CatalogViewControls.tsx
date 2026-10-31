import {LayoutGrid,Grid2X2,List,Table2} from 'lucide-react';
export function CatalogViewControls({value,onChange,collection=false}:{value:string;onChange:(value:string)=>void;collection?:boolean}){
 return <div className={'catalog-views'+(collection?' library-layouts':'')} role="group" aria-label={collection?'Вид библиотеки':'Вид каталога'}>{[['grid',collection?'Плитки':'Крупные карточки',LayoutGrid],['compact',collection?'Маленькие плитки':'Небольшие карточки',Grid2X2],['list','Список',List],['table','Таблица',Table2]].map(([id,label,Icon]:any)=><button key={id} title={label} aria-label={label} aria-pressed={value===id} onClick={()=>onChange(id)}><Icon size={17}/></button>)}</div>;
}
