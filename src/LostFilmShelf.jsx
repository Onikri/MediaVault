import {useEffect,useState} from 'react';
import {AnimeCard} from './blossom/components/AnimeCard.tsx';
import {AnimeGrid} from './blossom/components/AnimeGrid.tsx';
import {blossomRecord} from './blossom/media-adapter.js';
import {rememberVoiceHint} from './content-language.js';

// LostFilm's own catalogue; watching uses the LostFilm dub from public players.
export default function LostFilmShelf({service,onSearch}){
 const [state,setState]=useState({items:[],error:'',loading:true}),[sort,setSort]=useState('new');
 useEffect(()=>{
  if(service?.status!=='connected'){setState({items:[],error:'',loading:false});return;}
  const abort=new AbortController();setState(old=>({...old,loading:true,error:''}));
  service.request('/catalog/lostfilm?sort='+sort,{signal:abort.signal}).then(data=>setState({items:data.items||[],error:'',loading:false})).catch(e=>{if(e.name!=='AbortError')setState({items:[],error:e.message||'Каталог LostFilm временно недоступен.',loading:false});});
  return()=>abort.abort();
 },[service?.status,sort]);
 if(service?.status!=='connected'||(!state.loading&&!state.items.length&&!state.error))return null;
 function open(item){rememberVoiceHint('LostFilm',[item.title,item.original]);onSearch(item.original||item.title);}
 return <section className="lostfilm-shelf" aria-label="Сериалы в озвучке LostFilm">
  <header><div><h2>Озвучка LostFilm</h2><p>Каталог студии. Серии открываются в озвучке LostFilm из публичных плееров.</p></div>
   <div className="lostfilm-sort" role="group" aria-label="Порядок каталога LostFilm">{[['new','Новые'],['rating','Рейтинг'],['alpha','А–Я']].map(([id,label])=><button key={id} type="button" aria-pressed={sort===id} onClick={()=>setSort(id)}>{label}</button>)}</div></header>
  {state.error&&<p className="inline-error" role="alert">{state.error}</p>}
  <AnimeGrid className="media-grid catalog-grid lostfilm-grid">{state.items.slice(0,12).map((item,i)=><AnimeCard key={item.id} index={i} anime={blossomRecord({id:item.id,title:item.title,cover:item.cover,year:item.year,genres:item.genres,kind:'tv'})} className="title-card catalog-card" titleName={item.title} category="tv" onOpen={()=>open(item)} openLabel={'Найти '+item.title} detail={[item.year,item.original!==item.title?item.original:'',item.upcoming?'Скоро':''].filter(Boolean).join(' · ')}/>)}</AnimeGrid>
 </section>;
}
