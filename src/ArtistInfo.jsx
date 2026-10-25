import {useEffect,useState} from 'react';
export default function ArtistInfo({name}){
 const [data,setData]=useState(null),[error,setError]=useState('');
 useEffect(()=>{setData(null);setError('');const a=new AbortController(),server=window.MEDIA_VAULT_CONFIG?.importServerUrl;if(!name||!server)return;fetch(server+'/music/artist?'+new URLSearchParams({name}),{signal:AbortSignal.any([a.signal,AbortSignal.timeout(30000)])}).then(async r=>{if(!r.ok)throw Error('Сведения об исполнителе недоступны.');return r.json();}).then(d=>!a.signal.aborted&&setData(d)).catch(e=>!a.signal.aborted&&setError(e.message));return()=>a.abort();},[name]);
 return <div className="song-artist-info" aria-live="polite"><h3>{name}</h3>{!data?<p className="fine">{error||'Загружаем сведения об исполнителе…'}</p>:<><small>{[data.type,data.description,data.begin&&'С '+data.begin].filter(Boolean).join(' · ')}</small><p>{data.biography||'Русское описание этого исполнителя пока не найдено.'}</p><div>{data.links?.map(l=><a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer">{l.name}</a>)}</div></>}</div>;
}
