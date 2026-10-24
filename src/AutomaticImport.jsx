import React,{useEffect,useRef,useState} from 'react';
import Icon from './Icons.jsx';
import {importRequest} from './import-api.js';
import {buildServerJob} from './server-job.js';

const phases={planned:'Подготовка',downloading:'Скачивание на сервер',assembling:'Сборка видео',uploading:'Шифрование и загрузка',saved:'Серия сохранена',skipped:'Серия уже есть',source_error:'Источник серии недоступен'};
const statuses={queued:'В очереди',running:'Выполняется',completed:'Готово',partial:'Завершено с пропусками',failed:'Остановлено из-за ошибки',cancelled:'Отменено'};

export default function AutomaticImport({state,onConnect,onRefresh}){
  const [query,setQuery]=useState(''),[results,setResults]=useState(null),[searching,setSearching]=useState(false);
  const [anime,setAnime]=useState(null),[source,setSource]=useState(null),[collection,setCollection]=useState('');
  const [season,setSeason]=useState('1'),[episodes,setEpisodes]=useState('all'),[quality,setQuality]=useState('720');
  const [status,setStatus]=useState(null),[jobs,setJobs]=useState([]),[phrase,setPhrase]=useState('');
  const [error,setError]=useState(''),[searchError,setSearchError]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const requestRef=useRef(null),refreshRef=useRef(onRefresh),lastSaved=useRef(new Map()),selectionEpoch=useRef(0);
  refreshRef.current=onRefresh;
  const ready=!!state.catalog&&state.admin&&!!state.token;
  const active=jobs.some(job=>['queued','running'].includes(job.status));
  const api=(path,options)=>importRequest(state.token,path,options);

  useEffect(()=>{
    setStatus(null);setJobs([]);lastSaved.current.clear();setPhrase('');
    if(!ready)return;
    const controller=new AbortController();let timer;
    async function poll(){
      try{
        const suffix='?library='+encodeURIComponent(state.libraryId);
        const [nextStatus,next]=await Promise.all([
          importRequest(state.token,'/status'+suffix,{signal:controller.signal}),
          importRequest(state.token,'/jobs'+suffix,{signal:controller.signal})]);
        if(controller.signal.aborted)return;
        setStatus(nextStatus);setJobs(next.jobs);
        if(next.jobs.some(job=>job.id===requestRef.current?.jobId&&!['queued','running'].includes(job.status)))requestRef.current=null;
        let changed=false;
        for(const job of next.jobs){
          const saved=Number(job.progress?.completed||0);
          const previous=lastSaved.current.get(job.id);
          if(previous!==undefined&&saved>previous&&['saved','skipped'].includes(job.progress?.phase))changed=true;
          if(previous!==undefined&&['completed','partial'].includes(job.status)&&previous!==-1){changed=true;lastSaved.current.set(job.id,-1);}
          else if(previous!==-1)lastSaved.current.set(job.id,saved);
        }
        if(changed)await refreshRef.current?.();
      }catch(cause){if(!controller.signal.aborted){setStatus(null);setError(cause.message);}}
      finally{if(!controller.signal.aborted)timer=setTimeout(poll,5000);}
    }
    poll();return()=>{controller.abort();clearTimeout(timer);};
  },[ready,state.token,state.libraryId]);

  useEffect(()=>{
    const controller=new AbortController();setSearchError('');
    if(!ready||query.trim().length<2){setResults(null);setSearching(false);return()=>controller.abort();}
    setSearching(true);
    const timer=setTimeout(async()=>{
      try{
        const data=await importRequest(state.token,'/search?q='+encodeURIComponent(query.trim()),{signal:controller.signal});
        if(!controller.signal.aborted)setResults(data);
      }catch(cause){if(!controller.signal.aborted){setResults(null);setSearchError(cause.message);}}
      finally{if(!controller.signal.aborted)setSearching(false);}
    },650);
    return()=>{clearTimeout(timer);controller.abort();};
  },[query,ready,state.token]);

  function changeQuery(value){selectionEpoch.current++;setQuery(value);setAnime(null);setSource(null);setResults(null);}
  async function selectAnime(card){
    const epoch=++selectionEpoch.current;
    setAnime(card);setCollection(card.title);setSource(null);
    const nextQuery=card.original_title||card.title;
    if(nextQuery!==query)setResults(null);
    setQuery(nextQuery);
    try{const detail=await api('/anime/'+card.id);if(epoch===selectionEpoch.current)setAnime(detail);}
    catch(cause){if(epoch===selectionEpoch.current)setError(cause.message);}
  }
  async function connect(event){
    event.preventDefault();setBusy(true);setError('');
    try{
      await api('/libraries/unlock',{method:'POST',body:{library_id:state.libraryId,passphrase:phrase}});
      setStatus(current=>({...current,library_connected:true}));setMessage('Библиотека подключена. Повторно вводить фразу для импорта не нужно.');
    }catch(cause){setError(cause.message);}finally{setPhrase('');setBusy(false);}
  }
  async function submit(event){
    event.preventDefault();setBusy(true);setError('');setMessage('');
    try{
      if(!source)throw Error('Выбери найденный источник.');
      const job=buildServerJob({libraryId:state.libraryId,urls:source.url,collection,season,episodes,quality});
      const fingerprint=JSON.stringify(job);
      if(requestRef.current?.fingerprint!==fingerprint)requestRef.current={fingerprint,id:crypto.randomUUID()};
      const result=await api('/jobs',{method:'POST',body:{job,request_id:requestRef.current.id}});
      requestRef.current.jobId=result.id;
      setMessage('Импорт поставлен в очередь. Можно закрыть страницу.');
      setJobs(current=>current.some(item=>item.id===result.id)?current:[{id:result.id,status:'queued',progress:{}},...current]);
    }catch(cause){setError(cause.message);}finally{setBusy(false);}
  }
  async function cancel(id){
    try{await api('/jobs/'+id+'/cancel',{method:'POST'});setJobs(current=>current.map(job=>job.id===id?{...job,cancel:1}:job));}
    catch(cause){setError(cause.message);}
  }
  async function disconnect(){
    setBusy(true);setError('');
    try{await api('/libraries/'+encodeURIComponent(state.libraryId),{method:'DELETE'});setStatus(current=>({...current,library_connected:false}));}
    catch(cause){setError(cause.message);}finally{setBusy(false);}
  }
  return <>
    <div className="page-title-row"><div><p className="eyebrow">Твоя следующая история</p><h1 className="page-title">Добавить аниме</h1><p className="page-subtitle">Найди историю. Остальное сделает сервер.</p></div><Icon name="cloud" size={32}/></div>
    <div className="server-route auto-route"><span>Источник</span><Icon name="arrow" size={16}/><span>Сервер · шифрование</span><Icon name="arrow" size={16}/><span>Твой Drive</span></div>
    {!ready?<section className="settings-card"><h2>Открой библиотеку владельца</h2><p>После входа можно искать аниме и управлять импортом.</p><button className="btn btn-primary" onClick={onConnect}>Подключить библиотеку</button></section>:<>
      <section className="settings-card runtime-status">
        <h2 className="section-title">Сервер импорта</h2>
        {!status?<p role="status">Проверяем подключение…</p>:<>
          <p>{status.worker_online?'Обработчик на связи':'Обработчик недоступен'} · {status.drive_connected?'Drive подключён':'Drive ещё не подключён'}</p>
          {!status.drive_connected&&<p className="fine">Нужна первоначальная настройка доступа Google на сервере. <a href="https://github.com/Onikri/MediaVault/blob/main/docs/automatic-import.md" target="_blank" rel="noreferrer">Открыть инструкцию настройки</a>.</p>}
          {status.drive_connected&&!status.library_connected&&<form onSubmit={connect}>
            <p>Один раз разреши серверу открывать эту библиотеку. Он сохранит ключ в зашифрованном виде и сможет импортировать, когда сайт закрыт. Доверяй только своему серверу.</p>
            <label className="input-label" htmlFor="serverPhrase">Секретная фраза библиотеки</label>
            <input id="serverPhrase" className="field-input" type="password" autoComplete="off" value={phrase} onChange={event=>setPhrase(event.target.value)} required minLength={12} maxLength={1024}/>
            <button className="btn btn-secondary" disabled={busy} type="submit">Подключить автоматический импорт</button>
          </form>}
          {status.library_connected&&<button className="text-link" disabled={busy||active} onClick={disconnect}>Удалить ключ библиотеки с сервера</button>}
        </>}
      </section>
      <section className="settings-card anime-search">
        <label className="input-label" htmlFor="animeSearch">Название аниме</label>
        <input id="animeSearch" type="search" className="field-input" placeholder="Например, Наруто" value={query} onChange={event=>changeQuery(event.target.value)} maxLength={120} autoComplete="off"/>
        <p className="fine">Карточки и оценки — Shikimori. Источники ищутся параллельно; выбери нужную версию по названию.</p>
        <div aria-live="polite">{searching&&<p>Ищем аниме и источники…</p>}{searchError&&<p className="inline-error">{searchError}</p>}{results?.metadata_error&&<p>{results.metadata_error}</p>}</div>
        {!anime&&results&&<div className="anime-results">{results.items.map(card=><button key={card.id} className="anime-result" onClick={()=>selectAnime(card)} aria-label={'Выбрать '+card.title}>
          {card.image?<img src={card.image} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<span className="anime-poster-empty"><Icon name="video"/></span>}
          <span><strong>{card.title}</strong><small>{card.year} {card.kind} · ★ {card.score||'—'}</small></span>
        </button>)}</div>}
        {anime&&<article className="anime-selected">{anime.image&&<img src={anime.image} alt="" referrerPolicy="no-referrer"/>}<div><h2>{anime.title}</h2><p>{anime.year} · ★ {anime.score||'—'} · {anime.episodes||'?'} серий</p><p className="anime-description">{anime.description||'Описание пока не загружено.'}</p><a href={anime.url} target="_blank" rel="noreferrer">Карточка Shikimori</a></div></article>}
        {results&&!searching&&!results.items.length&&!results.providers.some(provider=>provider.items.length)&&<p>Совпадений нет. Попробуй оригинальное название или другое написание.</p>}
      </section>
      {results&&<section className="settings-card"><h2 className="section-title">Доступные источники</h2><p className="fine">Совпадения по названию могут относиться к разным сезонам. Наличие страницы ещё не гарантирует доступность видео.</p>
        {results.providers.map(provider=><div key={provider.id} className="source-provider"><h3>{provider.name}</h3>
          {provider.error&&<p>{provider.error}</p>}{provider.status==='empty'&&<p className="fine">Совпадений нет либо разметка сайта изменилась.</p>}
          {provider.items.map(item=><button key={item.url} className={'source-choice '+(source?.url===item.url?'source-selected':'')} aria-pressed={source?.url===item.url} onClick={()=>{setSource(item);if(!anime)setCollection(item.title);requestRef.current=null;}}><Icon name={source?.url===item.url?'check':'video'} size={18}/><span>{item.title}</span></button>)}
        </div>)}
      </section>}
      {source&&<form className="settings-card" onSubmit={submit}><h2 className="section-title">Добавить в библиотеку</h2><p>{source.provider_name}: {source.title}</p>
        <label className="input-label" htmlFor="autoCollection">Название тайтла в библиотеке</label><input id="autoCollection" className="field-input" value={collection} onChange={event=>setCollection(event.target.value)} required/>
        <div className="import-field-grid"><div><label className="input-label" htmlFor="autoSeason">Сезон</label><input id="autoSeason" type="number" min="1" max="1000" className="field-input" value={season} onChange={event=>setSeason(event.target.value)} required/></div>
        <div><label className="input-label" htmlFor="autoEpisodes">Серии</label><input id="autoEpisodes" className="field-input" value={episodes} onChange={event=>setEpisodes(event.target.value)} placeholder="all или 1-12"/></div></div>
        <label className="input-label" htmlFor="autoQuality">Качество</label><select id="autoQuality" className="field-input" value={quality} onChange={event=>setQuality(event.target.value)}><option value="720">До 720p</option><option value="1080">До 1080p</option><option value="480">До 480p</option><option value="360">До 360p</option><option value="best">Лучшее доступное</option></select>
        <p className="fine">Аниме → {collection} → Сезон {season}. Видео скачивается на сервер, шифруется и сохраняется в Drive.</p>
        <button id="importVideoBtn" className="btn btn-primary" disabled={busy||!!state.busy||!status?.library_connected||!status?.worker_online}>Добавить в библиотеку<Icon name="arrow" size={18}/></button>
      </form>}
      <section className="settings-card"><h2 className="section-title">Очередь импорта</h2>{!jobs.length&&<p className="fine">Здесь появятся задания и их прогресс.</p>}
        {active&&<p className="fine">Пока идёт импорт, не изменяй эту библиотеку с другого устройства.</p>}
        {jobs.map(job=><article className="import-queue-item" key={job.id}><div>{job.title&&<h3>{job.title} · Сезон {job.season}</h3>}<strong>{statuses[job.status]||job.status}</strong><small>Задание {job.id.slice(0,8)}</small><p>{phases[job.progress?.phase]||''} {job.progress?.total?`${job.progress.completed||0} / ${job.progress.total}`:''}</p>
          {!!job.progress?.total&&<progress max={job.progress.total} value={job.progress.completed||0}/>}
          {job.result?.message&&<p>{job.result.message}</p>}{job.result?.saved!==undefined&&<p>Сохранено: {job.result.saved}; уже были: {job.result.skipped}; недоступны: {job.result.failed}.</p>}
        </div>{['queued','running'].includes(job.status)&&<button className="text-link" disabled={!!job.cancel} onClick={()=>cancel(job.id)}>{job.cancel?'Останавливается…':'Остановить'}</button>}</article>)}
        <button className="btn btn-secondary" disabled={!!state.busy} onClick={onRefresh}><Icon name="refresh" size={16}/>Обновить библиотеку</button>
      </section>
    </>}
    {error&&<p className="inline-error" role="alert">{error}</p>}{message&&<p className="import-success" role="status">{message}</p>}
  </>;
}
