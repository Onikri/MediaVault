import {RotateCcw,SlidersHorizontal} from 'lucide-react';
import type {ReactNode} from 'react';
import {createPortal} from 'react-dom';
// Supplied FilterSidebar anatomy, with existing controlled MediaVault fields.
export function FilterSidebar({children,onReset,open=false,portal}:{children:ReactNode;onReset?:()=>void;open?:boolean;portal?:HTMLElement|null}){
 if(portal!==undefined)return portal?createPortal(<div className={'library-sidebar-filters'+(open?' is-open':'')}><div className="filter-heading"><SlidersHorizontal size={16}/><h3>Фильтры</h3>{onReset&&<button className="icon-button" aria-label="Сбросить фильтры каталога" onClick={onReset}><RotateCcw size={15}/></button>}</div>{children}</div>,portal):null;
 return <aside className={'filter-sidebar blossom-catalog-sidebar '+(open?'is-open':'')} aria-label="Фильтры каталога"><div className="filter-heading"><SlidersHorizontal size={19}/><h2>Уточнить поиск</h2>{onReset&&<button className="icon-button" aria-label="Сбросить фильтры каталога" onClick={onReset}><RotateCcw size={15}/></button>}</div>{children}</aside>;
}
