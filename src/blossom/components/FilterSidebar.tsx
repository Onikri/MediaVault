import {RotateCcw,SlidersHorizontal} from 'lucide-react';
import type {ReactNode} from 'react';
import {createPortal} from 'react-dom';
// Supplied FilterSidebar anatomy, with existing controlled MediaVault fields.
// `active` counts the filters in use; reset is offered only when there is something to reset.
export function FilterSidebar({children,onReset,open=false,portal,active}:{children:ReactNode;onReset?:()=>void;open?:boolean;portal?:HTMLElement|null;active?:number}){
 const count=active&&active>0?<span className="filter-count" aria-label={'Выбрано фильтров: '+active}>{active}</span>:null;
 const reset=onReset&&(active===undefined||active>0)?<button type="button" className="filter-reset" aria-label="Сбросить фильтры каталога" onClick={onReset}><RotateCcw size={13}/>{active!==undefined&&<span>Сбросить</span>}</button>:null;
 if(portal!==undefined)return portal?createPortal(<div className={'library-sidebar-filters'+(open?' is-open':'')}><div className="filter-heading"><SlidersHorizontal size={16}/><h3>Фильтры</h3>{count}{reset}</div>{children}</div>,portal):null;
 return <aside className={'filter-sidebar blossom-catalog-sidebar '+(open?'is-open':'')} aria-label="Фильтры каталога"><div className="filter-heading"><SlidersHorizontal size={19}/><h2>Уточнить поиск</h2>{count}{reset}</div>{children}</aside>;
}
