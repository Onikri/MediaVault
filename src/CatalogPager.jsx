import {useEffect,useState} from 'react';
import {motion,useReducedMotion} from 'motion/react';
import {ChevronLeft,ChevronRight} from 'lucide-react';

const number=new Intl.NumberFormat('ru-RU');
// Page numbers around the current one, the first and the last, with gaps between.
export function pageWindow(page,pages,hasMore){
 const last=pages?Math.max(pages,page):page+(hasMore?1:0),set=new Set([1,last]);
 for(let n=page-2;n<=page+2;n++)if(n>=1&&n<=last)set.add(n);
 const list=[...set].sort((a,b)=>a-b),out=[];
 list.forEach((n,i)=>{if(i&&n-list[i-1]>1)out.push('gap-'+n);out.push(n);});
 if(!pages&&hasMore)out.push('more');
 return out;
}

export default function CatalogPager({page,pages,hasMore,onPage,label='Страницы каталога'}){
 const reduced=useReducedMotion(),[draft,setDraft]=useState(''),last=pages?Math.max(pages,page):null;
 useEffect(()=>setDraft(''),[page]);
 const canNext=last?page<last:hasMore,jump=()=>{const n=Math.round(Number(draft));if(n>=1&&(!last||n<=last)&&n!==page)onPage(n);setDraft('');};
 return <nav className="catalog-pager" aria-label={label}>
  <button type="button" className="pager-step" disabled={page<=1} onClick={()=>onPage(page-1)} aria-label="Предыдущая страница"><ChevronLeft size={17}/><span>Назад</span></button>
  <ol className="pager-pages">{pageWindow(page,pages,hasMore).map(item=>typeof item==='number'
   ?<li key={item}><button type="button" className={item===page?'is-current':undefined} aria-current={item===page?'page':undefined} aria-label={'Страница '+item} onClick={()=>item!==page&&onPage(item)}>
     {item===page&&<motion.span layoutId="pager-current" className="pager-current" transition={reduced?{duration:0}:{type:'spring',stiffness:500,damping:38}} aria-hidden="true"/>}
     <span>{number.format(item)}</span></button></li>
   :<li key={item} className="pager-gap" aria-hidden="true">…</li>)}</ol>
  <button type="button" className="pager-step" disabled={!canNext} onClick={()=>onPage(page+1)} aria-label="Следующая страница"><span>Дальше</span><ChevronRight size={17}/></button>
  {last>7&&<label className="pager-jump"><span>Страница</span><input type="number" inputMode="numeric" min="1" max={last} value={draft} placeholder={String(page)} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();jump();}}} onBlur={()=>draft&&jump()} aria-label={'Перейти на страницу, всего '+number.format(last)}/><span>из {number.format(last)}</span></label>}
 </nav>;
}
