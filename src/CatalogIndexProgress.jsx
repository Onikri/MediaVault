import {useEffect,useState} from 'react';
export default function CatalogIndexProgress({service}){
 const [value,setValue]=useState(null);
 useEffect(()=>{
  if(Number(service?.session?.serverVersion)<75)return;
  const abort=new AbortController();let busy=false;
  const read=async()=>{if(busy||document.hidden)return;busy=true;try{const next=await service.request('/catalog/status',{signal:abort.signal});if(!abort.signal.aborted)setValue(next);}catch{}finally{busy=false;}};
  read();const timer=setInterval(read,10000);return()=>{clearInterval(timer);abort.abort();};
 },[service?.server,service?.session?.serverVersion]);
 if(!value)return null;
 const active=(value.sources||[]).filter(row=>['queued','running'].includes(row.status)).length;
 return <p className="fine catalog-index-progress" role="status">В индексе источников: {Number(value.indexed).toLocaleString('ru')} карточек{active?' · собираем каталоги: '+active:value.pending?' · уточняем теги найденных карточек':''}</p>;
}
