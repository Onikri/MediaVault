import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';
import { AlertTriangle, ArrowLeft, ArrowRight, RefreshCw } from 'lucide-react';

export function Button({variant='primary',children,className='',...props}:ButtonHTMLAttributes<HTMLButtonElement> & {variant?:'primary'|'secondary'|'ghost'}) {
  return <button {...props} className={`ui-button ui-button-${variant} ${className}`}>{children}</button>;
}
export function Badge({variant='accent',children}: {variant?:'accent'|'outline'|'muted';children:ReactNode}) {
  return <span className={`ui-badge ui-badge-${variant}`}>{children}</span>;
}
export function Card({children,className='',...props}: HTMLAttributes<HTMLElement>) {
  return <article {...props} className={`ui-card ${className}`}>{children}</article>;
}
export function PageHeader({title,description,kicker}:{title:string;description?:string;kicker?:string}) {
  return <div className="page-heading"><span className="eyebrow">{kicker||'ANIVIEW BLOSSOM'}</span><h1>{title}<em>.</em></h1>{description&&<p>{description}</p>}</div>;
}
export function EmptyState({title='Nothing here yet',description='Try another search or adjust your filters.'}:{title?:string;description?:string}) {
  return <div className="empty-state"><span aria-hidden="true">✳</span><h3>{title}</h3><p>{description}</p></div>;
}
export function ErrorState({onRetry,description='Unable to load this content.'}:{onRetry?:()=>void;description?:string}) {
  return <div className="empty-state"><AlertTriangle size={26} color="var(--color-blossom)"/><h3>Something went wrong</h3><p>{description}</p>{onRetry&&<Button onClick={onRetry}><RefreshCw size={16}/> Try again</Button>}</div>;
}
export function Pagination({page,pages,onChange}:{page:number;pages:number;onChange:(page:number)=>void}) {
  const indices=Array.from({length:Math.min(pages,5)},(_,i)=>Math.max(1,Math.min(pages-4,page-2))+i);
  return <nav className="ui-pagination" aria-label="Pagination">
    <button disabled={page<=1} aria-label="Previous page" onClick={()=>onChange(page-1)}><ArrowLeft size={17}/></button>
    {indices.map(p=><button key={p} aria-current={p===page?'page':undefined} onClick={()=>onChange(p)}>{p}</button>)}
    <button disabled={page>=pages} aria-label="Next page" onClick={()=>onChange(page+1)}><ArrowRight size={17}/></button>
  </nav>;
}
export function SelectField({label,options,value,onChange}:{label:string;options:Array<{label:string;value:string}>;value:string;onChange:(value:string)=>void}) {
  return <label className="field">{label}<select value={value} onChange={event=>onChange(event.target.value)}>{options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
}
