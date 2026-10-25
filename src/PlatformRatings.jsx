import {useEffect,useRef,useState} from 'react';
import {Star,ArrowUpRight,RefreshCw} from 'lucide-react';
const colors={shikimori:'136 190 154',mal:'105 151 235',anilist:'106 194 240',kitsu:'239 151 115'};
const valid=(v,id,kind)=>v?.identity===String(id)&&v.kind===kind&&Array.isArray(v.items);
const number=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
const count=new Intl.NumberFormat('ru-RU',{notation:'compact',maximumFractionDigits:1});
export default function PlatformRatings({identity,kind='anime',cached,score,server,onLoaded,compact=false}){
  kind=['manga','ranobe'].includes(kind)?'manga':'anime';identity=String(identity||'');
  const [value,setValue]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0),callback=useRef(onLoaded);callback.current=onLoaded;
  useEffect(()=>{
    const abort=new AbortController(),saved=valid(cached,identity,kind)?cached:null;setValue(saved);setError('');
    if(!/^[1-9]\d{0,11}$/.test(identity)||!server)return;
    const dates=(saved?.items||[]).map(v=>Date.parse(v.checkedAt)).filter(Number.isFinite);
    const expires=saved?.providers?.some(v=>v.status==='unavailable')?saved.retryAfter:(dates.length?Math.min(...dates):Date.parse(saved?.checkedAt))+6*3600000;
    if(!revision&&saved?.items?.length&&Date.now()<expires)return;
    setLoading(true);
    fetch(server+'/metadata/ratings?'+new URLSearchParams({identity,kind}),{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(20000)])}).then(async response=>{if(!response.ok)throw Error('Платформы временно не ответили. Сохранённые оценки остаются доступными.');return response.json();}).then(data=>{
      if(!valid(data,identity,kind))throw Error('Каталоги не подтвердили выбранное произведение.');
      if(abort.signal.aborted)return;
      const items=[...new Map([...(saved?.items||[]),...data.items].map(item=>[item.provider,item])).values()];
      const next={...data,items};setValue(next);if(items.length)callback.current?.(next);
    }).catch(cause=>{if(!abort.signal.aborted)setError(cause.message);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[identity,kind,server,revision]);
  if(!/^[1-9]\d{0,11}$/.test(identity))return null;
  const fallback=Number(score)>0?{provider:'shikimori',name:'Шикимори',value:Number(score),scale:10,normalized:Number(score),url:'https://shikimori.io/'+kind+'s/'+identity}:null;
  const current=valid(value,identity,kind)?value:null;
  const items=current?.items?.length?current.items:fallback?[fallback]:[],unavailable=current?.providers?.filter(v=>v.status==='unavailable').length||0;
  return <section id={compact?undefined:'titleRatings'} className={'platform-ratings'+(compact?' ratings-compact':'')} aria-label="Оценки на платформах"><div className="section-heading"><h2><Star size={17}/>Оценки зрителей{kind==='manga'?' и читателей':''}</h2>{!compact&&<button className={'text-link ratings-refresh'+(loading?' is-loading':'')} onClick={()=>setRevision(n=>n+1)} disabled={loading} aria-label="Обновить оценки"><RefreshCw size={13}/></button>}</div>
    <div className="ratings-grid">{items.map(item=><a key={item.provider} className="rating-card" href={item.url} target="_blank" rel="noopener noreferrer" style={{'--rating-rgb':colors[item.provider]||colors.shikimori}} title={'Исходная оценка: '+number.format(item.value)+' / '+item.scale+(item.checkedAt?' · Проверено '+new Date(item.checkedAt).toLocaleDateString('ru-RU'):'')}><span className="rating-brand"><i/>{item.name}<ArrowUpRight size={12}/></span><span className="rating-value">{number.format(item.normalized)}<small>/ 10</small></span><span className="rating-meter" aria-hidden="true"><i style={{width:Math.min(100,item.normalized*10)+'%'}}/></span><small className="rating-votes">{item.votes?count.format(item.votes)+' оценок':'Публичная оценка'}</small></a>)}</div>
    {loading&&<p className="ratings-status" role="status">Сверяем оценки по ID произведения…</p>}{!loading&&!items.length&&<p className="fine">Оценки ещё не опубликованы или платформы временно недоступны.</p>}{!compact&&<p className="ratings-note">Шкалы приведены к 10 баллам. Оригинальная оценка — при наведении.{unavailable?' Часть платформ сейчас недоступна.':''}</p>}{error&&!value&&<p className="ratings-status">{error}</p>}
  </section>;
}
