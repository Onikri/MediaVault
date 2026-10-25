import {useEffect,useState} from 'react';
export default function WatchOrder({identity,server}){
  const [value,setValue]=useState(null),[error,setError]=useState('');
  useEffect(()=>{
    const controller=new AbortController();setValue(null);setError('');
    if(!identity||!server)return()=>controller.abort();
    fetch(server+'/metadata/watch-order?identity='+encodeURIComponent(identity),{signal:controller.signal}).then(async response=>{if(!response.ok)throw Error('Порядок просмотра временно недоступен.');return response.json();}).then(value=>{if(!Array.isArray(value.items))throw Error('Каталог не предоставил порядок выхода.');setValue(value);}).catch(cause=>{if(!controller.signal.aborted)setError(cause.message);});
    return()=>controller.abort();
  },[identity,server]);
  if(!identity||!server)return null;
  return <section className="watch-order"><h2>Порядок просмотра</h2>{error?<p>{error}</p>:!value?<p>Получаем связи франшизы…</p>:<><p className="fine">{value.message}</p><ol>{value.items.map(item=><li key={item.id} aria-current={item.current?'step':undefined}><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>{item.current&&<strong> · Ты здесь</strong>}{item.year&&<small> · {item.year}</small>}</li>)}</ol></>}</section>;
}
