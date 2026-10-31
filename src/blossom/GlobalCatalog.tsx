import {useState} from 'react';
import {Search} from 'lucide-react';
import {useGlobalSearch} from '../use-global-search.js';
import {Poster} from '../ImportParts.jsx';
import {blossomRecord} from './media-adapter.js';
import {AnimeGrid} from './components/AnimeGrid';
import {AnimeCard} from './components/AnimeCard';
import {CatalogViewControls} from './components/CatalogViewControls';
import {CatalogResultsTable} from './components/CatalogResultsTable';
export function GlobalCatalog({initialQuery='',kind='all',service,onChoose}:{initialQuery?:string;kind?:string;service:any;onChoose:(item:any)=>void}){
 const [query,setQuery]=useState(initialQuery),state=useGlobalSearch(query,kind,service),[view,setView]=useState(()=>{try{return localStorage.getItem('mediavault_catalog_view_v2')||'grid';}catch{return 'grid';}});
 const changeView=(value:string)=>{setView(value);try{localStorage.setItem('mediavault_catalog_view_v2',value);}catch{}};
 const label=(kind:string)=>({anime:'Аниме',manga:'Манга',ranobe:'Ранобэ',book:'Книга',music:'Музыка',movie:'Фильм',tv:'Сериал'})[kind]||kind;
 return <section className="global-catalog blossom-catalog-content"><div className="catalog-search"><Search size={19}/><input className="search-input" aria-label={kind==='book'?'Поиск книг':'Поиск во всех онлайн-каталогах'} value={query} onChange={e=>setQuery(e.target.value)} placeholder={kind==='book'?'Название книги или автор':'Аниме, манга, книги, музыка…'}/></div><div className="section-heading"><h2>{kind==='book'?'Книги':'Результаты поиска'}</h2><span className="fine" role="status">{state.loading?'Дополняем результаты…':state.items.length+' найдено'}</span><CatalogViewControls value={view} onChange={changeView}/></div>{view==='table'?<CatalogResultsTable items={state.items} onChoose={onChoose}/>:<AnimeGrid className={"catalog-grid media-grid global-results catalog-layout-"+view}>{state.items.map(item=><AnimeCard key={item.id} category={item.kind} anime={blossomRecord(item)} onOpen={()=>onChoose(item)} artwork={<Poster item={item}/>} detail={[label(item.kind),item.year,item.authors?.join(', ')||item.artists?.join(', ')].filter(Boolean).join(' · ')}/>)}</AnimeGrid>}{query.trim().length<2&&<p className="fine">Введи название, чтобы начать поиск.</p>}{query.trim().length>=2&&!state.loading&&!state.items.length&&<p className="fine">Совпадений не найдено.</p>}</section>;
}
