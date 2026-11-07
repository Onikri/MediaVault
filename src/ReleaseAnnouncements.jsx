import {useEffect,useState} from 'react';
export default function ReleaseAnnouncements({service}){
  const [data,setData]=useState(null),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();setData(null);setError('');
    if(service.status!=='connected')return()=>controller.abort();
    service.request('/sources/calendar',{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(90000)])}).then(value=>{if(!controller.signal.aborted)setData(value);}).catch(cause=>{if(!controller.signal.aborted)setError(cause.message);});
    return()=>controller.abort();
  },[service.status,service.server,revision]);
  return <section className="settings-card dub-announcements"><div className="section-heading"><div><h3>Свежие озвучки</h3><p className="fine">Что опубликовали русские студии и сайты. Это даты выхода перевода, не японского эфира.</p></div><button className="text-link" onClick={()=>setRevision(r=>r+1)}>Обновить</button></div>
    {service.status!=='connected'?<p>Подключи сервер, чтобы проверить публикации студий.</p>:error?<p role="alert">{error}</p>:!data?<p role="status">Проверяем опубликованные даты источников…</p>:<>
    {!data.events.length&&<p>Источники пока не вернули дат публикаций. Даты японского эфира сюда не подставляются.</p>}
    <ul className="dub-list">{data.events.slice(0,40).map((event,index)=><li key={event.url+event.date+index}><a href={event.url} target="_blank" rel="noreferrer"><strong>{event.title}</strong><small>{event.provider}{event.episode?' · серия '+event.episode:''}</small></a><time dateTime={event.date}>{new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',...(event.datePrecision==='time'?{hour:'2-digit',minute:'2-digit'}:{})}).format(new Date(event.date))}</time></li>)}</ul>
    <details><summary>Доступность источников</summary>{data.providers.map(p=><p key={p.name}>{p.name} — {p.status==='ok'?'даты получены':p.status==='no_dates'?'дат в публичной странице нет':'недоступен'}</p>)}</details></>}
  </section>;
}
