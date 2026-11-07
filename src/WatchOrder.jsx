import {useEffect,useState} from 'react';
import {AnimatePresence,motion,useReducedMotion} from 'motion/react';
import {loadWatchOrder} from './franchise-seasons.js';
import {ListOrdered,Check,ExternalLink,ChevronDown,ArrowUpRight} from 'lucide-react';
import './watch-order.css';

const formats={tv:'Сериал',tv_13:'Сериал',tv_24:'Сериал',movie:'Фильм',ova:'OVA',ona:'ONA',special:'Спецвыпуск',music:'Клип'};
export default function WatchOrder({identity,server,onRelated,cached,onLoaded}){
 const [value,setValue]=useState(null),[error,setError]=useState(''),[expanded,setExpanded]=useState(false),[mode,setMode]=useState('main'),[retry,setRetry]=useState(0),reduce=useReducedMotion();
 useEffect(()=>{
  const controller=new AbortController();setValue(null);setError('');setExpanded(false);setMode('main');
  if(cached?.version>=2&&cached?.items&&!retry){setValue(cached);return()=>controller.abort();}
  if(!identity||!server)return()=>controller.abort();
  loadWatchOrder(identity,server,{signal:controller.signal}).then(data=>{
   if(controller.signal.aborted)return;
   if(!Array.isArray(data?.items))throw Error('Каталог не предоставил связи произведений.');
   setValue(data);onLoaded?.(data);
  }).catch(e=>{if(!controller.signal.aborted)setError(e.message);});return()=>controller.abort();
 },[identity,server,!!cached,retry]);
 if(!identity||!server)return null;
 const all=value?.items||[],main=value?.seasons||[],hasMain=main.length>1;
 const items=mode==='main'&&hasMain?main:all,current=items.findIndex(i=>String(i.id)===String(identity));
 const start=expanded?0:Math.max(0,Math.min(current-2,items.length-6)),visible=expanded?items:items.slice(start,start+6);
 return <section id="titleWatchOrder" className="watch-order watch-route">
  <div className="section-heading"><h2><ListOrdered size={17}/>Порядок просмотра</h2></div>
  {hasMain&&<div className="watch-route-modes" role="group" aria-label="Порядок просмотра">{[['main','Основные сезоны'],['release','Все произведения']].map(([id,label])=><button key={id} type="button" aria-pressed={mode===id} onClick={()=>{setMode(id);setExpanded(false);}}>{mode===id&&<motion.span className="watch-route-mode-active" layoutId="watch-route-mode" transition={reduce?{duration:0}:{type:'spring',stiffness:420,damping:36}}/>}<span>{label}</span></button>)}</div>}
  {error?<p className="fine" role="status">{error} <button className="text-link" onClick={()=>setRetry(v=>v+1)}>Повторить</button></p>:!value?<p className="fine" role="status">Получаем связи франшизы…</p>:<>
   <p className="watch-order-note">{mode==='main'&&hasMain?'Продолжения основной истории по связям каталога.':'Все адаптации и ответвления по дате выхода.'} Для разных сюжетных веток единого порядка может не быть.</p>
   {!items.length?<p className="fine">Связанные произведения пока не указаны.</p>:<motion.ol className={!expanded&&items.length>visible.length?'is-clipped':''} layout={!reduce} aria-label={mode==='main'&&hasMain?'Основная история':'Порядок выхода'}>
    <AnimatePresence initial={false}>{visible.map((item,index)=>{
     const active=String(item.id)===String(identity);
     return <motion.li layout={!reduce} key={item.id} aria-current={active?'step':undefined} initial={reduce?false:{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.18}}>
      <span className="watch-step">{active?<Check size={13}/>:String(start+index+1).padStart(2,'0')}</span>
      <button disabled={active} onClick={()=>onRelated?.({...item,kind:'anime',relation:'Порядок просмотра',format:item.kind==='movie'?'Фильм':'Аниме'})}>
       <span><strong>{item.title||'Название уточняется'}</strong><small>{[item.name,formats[item.kind]||item.kind,item.year].filter(Boolean).join(' · ')}</small></span>
       {active?<span className="watch-route-current">Сейчас</span>:<ArrowUpRight className="watch-route-arrow" size={14}/>}</button>
     </motion.li>;
    })}</AnimatePresence>
   </motion.ol>}
   {items.length>6&&<button type="button" className="watch-route-expand" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}><span>{expanded?'Свернуть список':'Показать весь порядок'}</span>{!expanded&&<small>{items.length}</small>}<ChevronDown size={16} style={{transform:expanded?'rotate(180deg)':undefined}}/></button>}
   <footer>
    <a className="watch-order-source" href={'https://shikimori.io/animes/'+identity+'/franchise'} target="_blank" rel="noopener noreferrer">Карта связей<ExternalLink size={12}/></a></footer>
  </>}
 </section>;
}
