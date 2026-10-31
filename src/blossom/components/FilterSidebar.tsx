import {RotateCcw,SlidersHorizontal} from 'lucide-react';
import type {ReactNode} from 'react';
// Supplied FilterSidebar anatomy, with existing controlled MediaVault fields.
export function FilterSidebar({children,onReset,open=false}:{children:ReactNode;onReset?:()=>void;open?:boolean}){
 return <aside className={'filter-sidebar blossom-catalog-sidebar '+(open?'is-open':'')} aria-label="Фильтры каталога"><div className="filter-heading"><SlidersHorizontal size={19}/><h2>Уточнить поиск</h2>{onReset&&<button className="icon-button" aria-label="Сбросить фильтры каталога" onClick={onReset}><RotateCcw size={15}/></button>}</div>{children}</aside>;
}
