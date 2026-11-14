import {useEffect,useState} from 'react';
import {ChevronRight,Star} from 'lucide-react';
import './home-shelves.css';
import {animeHome,youtubeTrailer} from '../media-metadata.js';
import {normalizeCatalog} from '../catalog.js';
import {normalizeProfile} from '../title-metadata.js';
import {Poster} from '../ImportParts.jsx';
import {blossomRecord} from './media-adapter.js';
import {HeroBanner} from './components/HeroBanner';
import {SkeletonGrid} from './components/SkeletonCard';
import {uiLocale} from '../i18n/index.js';
export function HomeDiscover({server,onChoose,onCatalog}:{server:string;onChoose:(item:any)=>void;onCatalog:()=>void}){
 const [feed,setFeed]=useState<any>(null),[index,setIndex]=useState(0),[error,setError]=useState(''),[retry,setRetry]=useState(0),[detail,setDetail]=useState<any>(null);
 useEffect(()=>{const abort=new AbortController();setError('');animeHome({server,signal:abort.signal}).then(data=>{if(!abort.signal.aborted){setFeed({...data,current:normalizeCatalog('jikan',{data:data.current}),popular:normalizeCatalog('jikan',{data:data.popular})});if(!data.current.length&&!data.popular.length)setError('Каталоги временно недоступны.');}}).catch(()=>{if(!abort.signal.aborted)setError('Не удалось загрузить релизы.');});return()=>abort.abort();},[server,retry]);
 const featured=(feed?.current?.length?feed.current:feed?.popular||[]).slice(0,6),item=featured[index%Math.max(1,featured.length)];
 useEffect(()=>{if(featured.length<2||matchMedia('(prefers-reduced-motion: reduce)').matches)return;const timer=setInterval(()=>{if(!document.hidden)setIndex(n=>(n+1)%featured.length);},15000);return()=>clearInterval(timer);},[featured.length]);
 useEffect(()=>{setDetail(null);if(!item?.ids?.mal||!server)return;const abort=new AbortController();fetch(server+'/metadata/shikimori?'+new URLSearchParams({identity:item.ids.mal,kind:'anime'}),{signal:abort.signal}).then(r=>r.ok?r.json():null).then(data=>{if(!abort.signal.aborted&&String(data?.id)===String(item.ids.mal))setDetail(normalizeProfile(data));}).catch(()=>{});return()=>abort.abort();},[item?.id,server]);
 const trailer=youtubeTrailer(item?.trailer)||detail?.trailers?.find((v:any)=>/youtube/.test(v.url))?.url;
 const backdrop=item?.trailer?.images?.maximum_image_url||item?.trailer?.images?.large_image_url||detail?.background||item?.background||item?.cover;
 const open=()=>item?onChoose(item):onCatalog();
 return <div className="home-discover"><HeroBanner identity={item?.ids?.mal} server={server} title={detail?.title&&detail.title!=='Название уточняется'?detail.title:item?.title} description={detail?.description||item?.description} artwork={backdrop} trailer={trailer} poster={item?<Poster item={item}/>:undefined} onOpen={open} kicker={feed?.current?.length?feed.season.label:'Популярное'} metadata={<>{item?.score&&<span><Star size={12} fill="currentColor"/>{item.score.toFixed(2)}</span>}{item?.format&&<span>{item.format}</span>}{item?.year&&<span>{item.year}</span>}</>} count={featured.length} index={index%Math.max(1,featured.length)} onNext={()=>setIndex(n=>(n+1)%featured.length)} onPrevious={()=>setIndex(n=>(n-1+featured.length)%featured.length)}/>
  {error&&<p className="home-feed-error" role="status">{error} <button className="text-link" onClick={()=>setRetry(n=>n+1)}>Повторить</button></p>}
  {!feed&&!error&&<div className="home-feed-loading"><SkeletonGrid count={6}/></div>}
  {feed?.current?.length>0&&<section className="home-shelf home-airing" aria-labelledby="home-airing-title">
   <header className="home-shelf-head"><h2 id="home-airing-title">Релизы сезона</h2><span>{feed.season.label}</span><button type="button" className="text-link" onClick={onCatalog}>Каталог<ChevronRight size={15}/></button></header>
   <div className="home-airing-track">{feed.current.slice(0,12).map((value:any)=>{const still=value.trailer?.images?.maximum_image_url||value.trailer?.images?.large_image_url||value.background;return <button key={value.id} type="button" className="home-airing-card" onClick={()=>onChoose(value)}>
    <span className="home-airing-art">{still?<img src={still} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<span className="anime-cover"><Poster item={value}/></span>}</span>
    <span className="home-airing-copy"><strong>{value.title}</strong><small>{value.episodesAired!=null?'Серия '+value.episodesAired+(value.episodes?' из '+value.episodes:''):value.episodes?value.episodes+' серий':value.format||''}</small></span>
   </button>;})}</div>
  </section>}
  {feed?.popular?.length>0&&<section className="home-shelf home-top" aria-labelledby="home-top-title">
   <header className="home-shelf-head"><h2 id="home-top-title">Топ-10 популярного</h2><button type="button" className="text-link" onClick={onCatalog}>Весь рейтинг<ChevronRight size={15}/></button></header>
   <ol className="home-top-track">{feed.popular.slice(0,10).map((value:any,i:number)=><li key={value.id}><button type="button" aria-label={(i+1)+' место: '+value.title} onClick={()=>onChoose(value)}><span className="home-top-rank" aria-hidden="true">{i+1}</span><span className="anime-cover home-top-poster"><Poster item={value}/></span><span className="home-top-copy"><strong>{value.title}</strong>{value.score?<small><Star size={11} fill="currentColor"/>{Number(value.score).toFixed(2)}</small>:null}</span></button></li>)}</ol>
  </section>}
 </div>;
}
