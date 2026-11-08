import {useEffect,useState} from 'react';
import {Star} from 'lucide-react';
import {animeHome,youtubeTrailer} from '../media-metadata.js';
import {normalizeCatalog} from '../catalog.js';
import {normalizeProfile} from '../title-metadata.js';
import {Poster} from '../ImportParts.jsx';
import {blossomRecord} from './media-adapter.js';
import {HeroBanner} from './components/HeroBanner';
import {AnimeCarousel} from './components/AnimeCarousel';
import {AnimeCard} from './components/AnimeCard';
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
 const card=(value:any,i:number)=><AnimeCard key={value.id} index={i} anime={blossomRecord(value)} category="anime" onOpen={()=>onChoose(value)} artwork={<Poster item={value}/>} detail={[value.episodesAired!=null?`Вышло ${value.episodesAired}${value.episodes?' / '+value.episodes:''} сер.`:value.episodes?value.episodes+' сер.':null,value.startDate?new Date(value.startDate).toLocaleDateString(uiLocale()):value.year].filter(Boolean).join(' · ')}/>;
 return <div className="home-discover"><HeroBanner identity={item?.ids?.mal} server={server} title={detail?.title&&detail.title!=='Название уточняется'?detail.title:item?.title} description={detail?.description||item?.description} artwork={backdrop} trailer={trailer} poster={item?<Poster item={item}/>:undefined} onOpen={open} kicker={feed?.current?.length?feed.season.label:'Популярное'} metadata={<>{item?.score&&<span><Star size={12} fill="currentColor"/>{item.score.toFixed(2)}</span>}{item?.format&&<span>{item.format}</span>}{item?.year&&<span>{item.year}</span>}</>} count={featured.length} index={index%Math.max(1,featured.length)} onNext={()=>setIndex(n=>(n+1)%featured.length)} onPrevious={()=>setIndex(n=>(n-1+featured.length)%featured.length)}/>
  {error&&<p className="home-feed-error" role="status">{error} <button className="text-link" onClick={()=>setRetry(n=>n+1)}>Повторить</button></p>}
  {!feed&&!error&&<div className="home-feed-loading"><SkeletonGrid count={6}/></div>}
  {feed?.current?.length>0&&<AnimeCarousel title="Релизы сезона" kicker={feed.season.label} onMore={onCatalog} moreLabel="Каталог">{feed.current.map(card)}</AnimeCarousel>}
  {feed?.popular?.length>0&&<AnimeCarousel title="Популярное" onMore={onCatalog} moreLabel="Каталог">{feed.popular.map(card)}</AnimeCarousel>}
 </div>;
}
