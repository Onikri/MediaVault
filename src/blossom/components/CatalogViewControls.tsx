import {LayoutGrid,Grid2X2,List,Table2} from 'lucide-react';
export function CatalogViewControls({value,onChange}:{value:string;onChange:(value:string)=>void}){
 return <div className="catalog-views" role="group" aria-label="Вид каталога">{[['grid','Крупные карточки',LayoutGrid],['compact','Небольшие карточки',Grid2X2],['list','Список',List],['table','Таблица',Table2]].map(([id,label,Icon]:any)=><button key={id} title={label} aria-label={label} aria-pressed={value===id} onClick={()=>onChange(id)}><Icon size={17}/></button>)}</div>;
}
