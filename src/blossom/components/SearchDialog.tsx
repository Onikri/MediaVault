import {useMemo,useState} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {ArrowUpRight,Search,X} from 'lucide-react';
import {useCatalog} from '../../use-catalog.js';
import useSourceTitles from '../../use-source-titles.js';
import {worldResults} from '../../world-search.js';
import {Poster} from '../../ImportParts.jsx';

/** Supplied SearchDialog anatomy, backed by MediaVault's existing live catalog. */
export function SearchDialog({service,onClose,onChoose,onBrowse}:{service:any;onClose:()=>void;onChoose:(item:any)=>void;onBrowse:(query:string,kind:string)=>void}){
 const [query,setQuery]=useState(''),[kind,setKind]=useState('anime'),[active,setActive]=useState(0),[composing,setComposing]=useState(false);
 const paused=composing||!query.trim(),catalog=useCatalog(query,kind,'',service.server,1,paused),sources=useSourceTitles(query,kind,service,paused);
 const items=useMemo(()=>worldResults(catalog.items,sources.results,query).slice(0,8),[catalog.items,sources.results,query]);
 const loading=!paused&&(catalog.loading||sources.loading),index=Math.min(active,Math.max(0,items.length-1));
 return <Dialog.Root open onOpenChange={open=>{if(!open)onClose();}}><Dialog.Portal><Dialog.Overlay className="dialog-backdrop blossom-search-backdrop"/><Dialog.Content className="search-dialog blossom-search-dialog" aria-describedby="blossomSearchHelp">
  <Dialog.Title className="sr-only">Поиск в библиотеке</Dialog.Title>
  <div className="search-input-row"><Search size={20}/><input autoComplete="off" autoFocus role="combobox" aria-expanded={!paused&&items.length>0} aria-controls="blossomSearchHits" aria-activedescendant={!paused&&items.length?'blossom-hit-'+index:undefined} value={query} aria-label="Поиск произведения" placeholder="Название истории…" onCompositionStart={()=>setComposing(true)} onCompositionEnd={()=>setComposing(false)} onChange={e=>{setQuery(e.target.value);setActive(0);}} onKeyDown={e=>{if(e.nativeEvent.isComposing||composing)return;if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setActive(Math.max(0,Math.min(items.length-1,index+(e.key==='ArrowDown'?1:-1))));}if(e.key==='Enter'&&query.trim()){e.preventDefault();if(items[index])onChoose(items[index]);else onBrowse(query,kind);}}}/><Dialog.Close className="icon-button" aria-label="Закрыть поиск"><X size={18}/></Dialog.Close></div>
  <div className="search-kind-row" role="group" aria-label="Где искать">{[['anime','Аниме и видео'],['manga','Манга'],['ranobe','Ранобэ']].map(([id,label])=><button key={id} className="chip" aria-pressed={kind===id} onClick={()=>{setKind(id);setActive(0);}}>{label}</button>)}</div>
  <div className="search-body" id="blossomSearchHits" role="listbox" aria-label="Результаты поиска" aria-busy={loading}>
   {paused?<p className="search-empty">Найди историю по названию. ↑ ↓ — выбрать, Enter — открыть.</p>:<>{items.map((item,i)=><button type="button" role="option" aria-selected={index===i} id={'blossom-hit-'+i} onMouseEnter={()=>setActive(i)} onClick={()=>onChoose(item)} className={'search-hit'+(index===i?' is-active':'')} key={item.id}><span className="search-poster"><Poster item={item}/></span><span><strong>{item.title}</strong><small>{[item.year,item.format,...(item.genres||[]).slice(0,1)].filter(Boolean).join(' · ')}</small></span><ArrowUpRight size={17}/></button>)}{loading&&<p className="search-empty" role="status">Ищем в каталогах…</p>}{!loading&&!items.length&&<p className="search-empty" role="status">Пока ничего не нашлось. Попробуй другое название или открой полный поиск.</p>}</>}
  </div><footer className="search-footer" id="blossomSearchHelp"><span><kbd>ESC</kbd> Закрыть</span>{query.trim()&&<button className="text-link search-powered" onClick={()=>onBrowse(query,kind)}>Все результаты <ArrowUpRight size={14}/></button>}</footer>
 </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
