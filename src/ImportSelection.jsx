import React,{useEffect,useRef,useState} from 'react';
import Icon from './Icons.jsx';
import VoicePicker from './VoicePicker.jsx';
import useSourceDiscovery from './use-source-discovery.js';
import ImportReadiness,{canImport} from './ImportReadiness.jsx';
import {kinds,ReleaseCalendar} from './ImportParts.jsx';
import MangaImport from './MangaImport.jsx';
import OnlineViewer from './OnlineViewer.jsx';
import {exportLocally} from './local-export.js';
import {selectedVideoEntries} from './import-selection-model.js';
import TitleEpisodeCard from './TitleEpisodeCard.jsx';

export default function ImportSelection({state,service,item,manual=false,onSubmitted,onOpenLibrary,destination='drive',compact=false}){
  const localAbort=useRef(null);
 useEffect(()=>()=>localAbort.current?.abort(),[]);
 const [online,setOnline]=useState(false),[playingEntry,setPlayingEntry]=useState(null),[localProgress,setLocalProgress]=useState(''),[episodeCount,setEpisodeCount]=useState(24);
  const [url,setUrl]=useState(''),[collection,setCollection]=useState(item?.title||''),[season,setSeason]=useState('1'),[manualKind,setManualKind]=useState('anime');
  const [found,setFound]=useState([]),[providers,setProviders]=useState([]),[inspection,setInspection]=useState(null),[dub,setDub]=useState('');
  const [mode,setMode]=useState('all'),[one,setOne]=useState(''),[first,setFirst]=useState('1'),[last,setLast]=useState('12'),[list,setList]=useState('');
  const [quality,setQuality]=useState('best'),[busy,setBusy]=useState(''),[searching,setSearching]=useState(false),[error,setError]=useState('');
  const [qualityData,setQualityData]=useState(null),[qualityLoading,setQualityLoading]=useState(false),[qualityError,setQualityError]=useState(''),[qualityRevision,setQualityRevision]=useState(0);
  const generation=useRef(0),kind=item?.kind||manualKind,ready=canImport(state,service);
  const discovery=useSourceDiscovery(item,service),[variant,setVariant]=useState(null);
  useEffect(()=>{
    generation.current++;setFound([]);setProviders([]);setInspection(null);setDub('');setUrl('');setCollection(item?.title||'');setBusy('');setError('');setVariant(null);
  },[item?.id]);
  useEffect(()=>{
    let closed=false;
    if(!item||['anime','manga'].includes(item.kind)||service.status!=='connected')return;
    setSearching(true);
    service.request('/sources/search?q='+encodeURIComponent(item.title)+'&kind='+item.kind).then(data=>{if(!closed){setFound(data.results||[]);setProviders(data.providers||[]);}}).catch(cause=>{if(!closed)setError(cause.message);}).finally(()=>{if(!closed)setSearching(false);});
    return()=>{closed=true;setSearching(false);};
  },[item?.id,service.status]);
  async function inspect(value,voice='',selectedSeason=season){
    const version=++generation.current;setOnline(false);setPlayingEntry(null);setEpisodeCount(24);setUrl(value);setBusy('inspect');setError('');setDub(voice);
    try{
      let data,continuation,previousProgress=-1,stalled=0;
      do{
        data=await service.request('/sources/inspect',{method:'POST',body:{url:value,...(voice?{dub_url:voice}:{}),season:Number(selectedSeason),kind,...(continuation?{continuation}:{})}});
        if(version!==generation.current)return;
        continuation=data.continuation;
        stalled=continuation&&data.scannedPages===previousProgress?stalled+1:0;previousProgress=data.scannedPages;
        if(stalled>=3)throw Error('Источник перестал отвечать во время проверки. Повтори позднее; другой перевод не подставлялся.');
      }while(continuation);
      if(version===generation.current){setInspection(data);if(data.seasons?.length&&!data.seasons.some(value=>value.number===Number(selectedSeason)))setSeason('');if(data.episodes?.length){setOne(String(data.episodes[0].number));setFirst(String(data.episodes[0].number));setLast(String(data.episodes.at(-1).number));}}
    }catch(cause){if(version===generation.current){setInspection(null);setError(cause.message);}}finally{if(version===generation.current)setBusy('');}
  }
  const published=(inspection?.episodes||[]).filter(e=>!e.season||Number(e.season)===Number(season));
  const episodeText=mode==='all'?'all':mode==='single'?one:mode==='range'?first+'-'+last:list;
  const qualityEpisode=(mode==='single'?published.find(e=>e.number===Number(one)):mode==='range'?published.find(e=>e.number>=Number(first)&&e.number<=Number(last)):published[0])?.url;
  useEffect(()=>{
    const controller=new AbortController();setQuality('best');setQualityData(null);setQualityError('');setQualityLoading(false);
    if(!qualityEpisode||!['anime','movie','tv'].includes(kind)||service.status!=='connected')return()=>controller.abort();
    if(service.session?.serverVersion&&service.session.serverVersion<7){setQualityError('Для полного списка качеств обнови сервер импорта.');return()=>controller.abort();}
    setQualityLoading(true);
    service.request('/sources/qualities',{method:'POST',body:{url:qualityEpisode,...(url&&service.session?.serverVersion>=34?{referer:url}:{})},signal:controller.signal})
      .then(data=>{if(!controller.signal.aborted)setQualityData(data);})
      .catch(cause=>{if(!controller.signal.aborted)setQualityError(cause.message);})
      .finally(()=>{if(!controller.signal.aborted)setQualityLoading(false);});
    return()=>controller.abort();
  },[qualityEpisode,url,kind,service.status,service.session?.serverVersion,qualityRevision]);
  let onlineEntries=[],selectionError='';try{onlineEntries=selectedVideoEntries(published,episodeText);}catch(e){selectionError=e.message;}
  function startOnline(){if(!inspection||!onlineEntries.length||selectionError){setError(selectionError||'Выбери опубликованные серии для просмотра.');return;}if(inspection.dubs?.length&&!dub){setError('Выбери озвучку.');return;}setOnline(true);}
  async function submit(event){
    event.preventDefault();setError('');
    if(destination==='online'){startOnline();return;}if(destination==='local'){if(!onlineEntries.length||selectionError){setError(selectionError||'Выбери серии.');return;}setBusy('local');const controller=new AbortController();localAbort.current=controller;try{await exportLocally({signal:controller.signal,entries:onlineEntries,kind:'video',referer:url,quality,service,onProgress:setLocalProgress});setLocalProgress('Файлы переданы браузеру для сохранения.');}catch(e){setError(e.message);}finally{setBusy('');}return;}
    if(!ready){setError('Открой библиотеку владельца и подключи сервер к Google Drive.');return;}
    if(service.session?.serverVersion&&service.session.serverVersion<7){setError('Обнови сервер импорта для полного выбора озвучек и качеств.');return;}
    if(!url||!collection.trim()){setError('Выбери источник и название тайтла.');return;}
    if(!inspection){setError('Сначала проверь ссылку: нужны опубликованные серии или главы.');return;}
    if(inspection.dubs?.length&&!dub){setError('Выбери озвучку из плеера.');return;}
    if(!published.length){setError('В этом источнике не найдены опубликованные файлы выбранного сезона.');return;}
    if(mode==='range'&&(!Number(first)||Number(last)<Number(first))){setError('Проверь начало и конец диапазона.');return;}
    const metadata=item?Object.fromEntries(['title','titles','aliases','description','cover','year','format','genres','tags','age','ageLabel','episodes','chapters','volumes','status','startDate','endDate','releases','ids','links','kind'].map(key=>[key,item[key]])):{};
    const selectedTranslation=variant||inspection.dubs?.find(d=>d.url===dub);
    const job={version:3,library_id:state.libraryId,sources:[url],collection:collection.trim(),season:Number(season),episodes:episodeText||'all',quality,resume:true,
      section:kind==='manga'?'manga':kind==='ranobe'?'ranobe':['movie','tv'].includes(kind)?'video':'anime',metadata,
      entries:published.map(entry=>({number:entry.number,url:entry.url,title:entry.title||'',...(entry.description?{description:entry.description}:{}),season:Number(entry.season||season)})),
      dub:variant?.name||inspection.dubs?.find(d=>d.url===dub)?.name||'',provider:inspection.provider,
      ...(selectedTranslation?.kind?{translation:{name:selectedTranslation.name,kind:selectedTranslation.kind,language:selectedTranslation.language||'und',player:selectedTranslation.player||'',variantId:selectedTranslation.id}}:{})};
    setBusy('submit');try{await service.submit(job);onSubmitted();}catch(cause){setError(cause.message);}finally{setBusy('');}
  }
  if(kind==='manga')return <MangaImport compact={compact} destination={destination} state={state} service={service} item={item} manual={manual} onKindChange={setManualKind} onSubmitted={onSubmitted} onOpenLibrary={onOpenLibrary}/>;
  const player=online&&<OnlineViewer sourceUrl={url} inline={compact} onEntryChange={e=>{setPlayingEntry(e);setOne(String(e.number));}} quality={quality} kind="video" entries={(compact?published:onlineEntries).map(e=>({...e,season:Number(e.season||season)}))} initial={playingEntry||onlineEntries[0]} title={collection} service={service} userId={state.user?.sub} dub={variant?.name||inspection?.dubs?.find(d=>d.url===dub)?.name||''} metadata={item} onClose={()=>setOnline(false)}/>;
  if(compact&&destination==='online')return <div className="title-playback-controls video-playback-controls">
   {item?.kind==='anime'&&<VoicePicker discovery={discovery} selected={variant} onChoose={value=>{setVariant(value);setInspection(null);setDub('');setOnline(false);generation.current++;if(value)inspect(value.sourceUrl,value.url);}}/>}
   {item?.kind!=='anime'&&found.length>0&&<label className="form-field input-label">Источник<select aria-label="Источник просмотра" className="field-input" value={url} onChange={e=>inspect(e.target.value)}><option value="">Выбери источник</option>{found.map(s=><option key={s.url} value={s.url}>{s.providerName}</option>)}</select></label>}
   {busy==='inspect'&&<p className="fine" role="status">Загружаем опубликованные серии…</p>}
   {!variant&&inspection?.dubs?.length>0&&<label className="form-field input-label">Перевод<select aria-label="Озвучка" className="field-input" value={dub} onChange={e=>inspect(url,e.target.value)}><option value="">Выбери озвучку</option>{inspection.dubs.map(d=><option key={d.url} value={d.url}>{d.name}</option>)}</select></label>}
   {inspection&&<div className="title-playback-selectors">{inspection.seasons?.length>1&&<label className="form-field input-label">Сезон<select aria-label="Сезон просмотра" className="field-input" value={season} onChange={e=>{const s=inspection.seasons.find(s=>s.number===Number(e.target.value));setSeason(e.target.value);setOnline(false);if(s?.url)inspect(s.url,'',e.target.value);}}>{inspection.seasons.map(s=><option key={s.number} value={s.number}>{s.name||s.number}</option>)}</select></label>}<label className="form-field input-label">Качество<select aria-label="Качество просмотра" className="field-input" value={quality} onChange={e=>setQuality(e.target.value)}><option value="best">Лучшее доступное{qualityData?.best?' · '+qualityData.best+'p':''}</option>{(qualityData?.qualities||[]).map(h=><option key={h} value={String(h)}>До {h}p</option>)}</select></label></div>}
   {error&&<p className="inline-error" role="alert">{error}</p>}{player}
   {published.length>0?<><div className="section-heading"><h3>Серии</h3><span className="fine">{published.length}</span></div><div className="title-episode-grid">{published.slice(0,episodeCount).map(e=><TitleEpisodeCard key={e.url} number={e.number} title={e.title||'Серия '+e.number} detail={variant?.name||inspection?.dubs?.find(d=>d.url===dub)?.name||'Смотреть онлайн'} selected={playingEntry?.url===e.url} onClick={()=>{setPlayingEntry(e);setOne(String(e.number));setMode('single');setOnline(true);}} artwork={<div className="episode-preview-pending"><span>{String(e.number).padStart(2,'0')}</span></div>}/>)}</div>{published.length>episodeCount&&<button type="button" className="text-link" onClick={()=>setEpisodeCount(n=>n+24)}>Ещё серии</button>}{!online&&<button type="button" className="btn btn-primary title-start-playback" onClick={startOnline} disabled={!!busy||inspection.dubs?.length>0&&!dub}><Icon name="video" size={16}/>Смотреть сейчас</button>}</>:<div className="title-playback-empty"><Icon name="video" size={28}/><p>{discovery.loading?'Проверяем переводы и источники…':'Выбери перевод и источник, затем серию.'}</p></div>}
   <details className="title-source-tools"><summary>Своя ссылка на источник</summary><div className="form-actions"><input className="field-input" aria-label="Своя ссылка на источник" type="url" value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://…"/><button type="button" className="btn btn-secondary" onClick={()=>inspect(url)} disabled={!url||!!busy}>Проверить</button></div></details>
  </div>;
  return <>{player}<form className="import-selection import-compact" onSubmit={submit}>
    <div className="import-form-heading"><span className="eyebrow">{destination==='online'?'Без ожидания импорта':'Настрой свою коллекцию'}</span><h3>{destination==='online'?'Открыть сейчас':'Что сохраним?'}</h3></div><ol className="import-step-rail" aria-label="Этапы выбора"><li data-active={!inspection}>Источник</li><li data-active={!!inspection}>Серии и перевод</li><li>{destination==='online'?'Просмотр':'Google Диск'}</li></ol>

    {manual&&<div className="form-field"><label className="input-label" htmlFor="manualKind">Тип произведения</label><select id="manualKind" className="field-input" value={manualKind} onChange={e=>{setManualKind(e.target.value);setInspection(null);}}>{kinds.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></div>}
    {item?.kind==='anime'&&<VoicePicker discovery={discovery} selected={variant} onChoose={value=>{setVariant(value);setInspection(null);setDub('');generation.current++;if(value)inspect(value.sourceUrl,value.url);}}/>}
    {item&&item.kind!=='anime'&&<><label className="input-label">Источники с публичными плеерами</label>{searching?<div className="source-loading"><span className="loading-ring"/>Ищем доступные страницы…</div>:found.length?<div className="source-results">{found.map(source=><button type="button" key={source.provider+source.url} className={'source-result'+(url===source.url?' selected':'')} onClick={()=>inspect(source.url)}><span><b>{source.providerName}</b><small>{source.title}</small></span><Icon name={url===source.url?'check':'chevron'} size={17}/></button>)}</div>:<p className="fine">{service.status==='connected'?'Подходящую страницу пока не нашли. Можно указать публичную ссылку ниже.':'Поиск доступных серий включится после подключения сервера.'}</p>}{providers.some(s=>s.status!=='ok')&&<details className="provider-diagnostics"><summary>Доступность сайтов</summary>{providers.map(s=><p key={s.provider}><b>{s.name}</b> — {s.status==='ok'?'проверен':s.message||'временно недоступен'}</p>)}</details>}</>}
    {item?<details className="manual-source"><summary>Проверить свою ссылку</summary><div className="form-field"><label className="input-label" htmlFor="streamUrl">{manual?'Ссылка на сезон, главу или видео':'Своя ссылка на источник'}</label><div className="form-actions"><input id="streamUrl" className="field-input" type="url" value={url} onChange={e=>{setUrl(e.target.value);setInspection(null);}} placeholder="https://…" required/><button type="button" className="btn btn-secondary btn-small" disabled={!url||!!busy||service.status!=='connected'} onClick={()=>inspect(url)}>{busy==='inspect'?'Проверяем…':'Проверить'}</button></div></div></details>:<div className="form-field"><label className="input-label" htmlFor="streamUrl">{manual?'Ссылка на сезон, главу или видео':'Своя ссылка на источник'}</label><div className="form-actions"><input id="streamUrl" className="field-input" type="url" value={url} onChange={e=>{setUrl(e.target.value);setInspection(null);}} placeholder="https://…" required/><button type="button" className="btn btn-secondary btn-small" disabled={!url||!!busy||service.status!=='connected'} onClick={()=>inspect(url)}>{busy==='inspect'?'Проверяем…':'Проверить'}</button></div></div>}
    {!variant&&inspection?.dubs?.length>0&&<div className="form-field"><label className="input-label" htmlFor="importDub">Озвучка</label><select id="importDub" className="field-input" value={dub} onChange={e=>inspect(url,e.target.value)}><option value="">Выбрать озвучку</option>{inspection.dubs.map(d=><option key={d.id+d.url} value={d.url}>{d.name}</option>)}</select></div>}
    {inspection&&!inspection.dubs?.length&&['anime','movie','tv'].includes(kind)&&<p className="fine">Источник не указал названия озвучек. Будет использована дорожка доступного плеера.</p>}
    <div className="import-field-grid"><div className="form-field"><label className="input-label" htmlFor="serverCollection">Название в коллекции</label><input id="serverCollection" className="field-input" value={collection} onChange={e=>setCollection(e.target.value)} required placeholder="Название тайтла"/></div><div className="form-field"><label className="input-label" htmlFor="serverSeason">{['manga','ranobe'].includes(kind)?'Том':'Сезон'}</label>{inspection?.seasons?.length?<select id="serverSeason" className="field-input" required value={season} onChange={e=>{const selected=inspection.seasons.find(s=>s.number===Number(e.target.value));setSeason(e.target.value);if(selected?.url)inspect(selected.url,'',e.target.value);}}><option value="">Выбери опубликованный сезон</option>{inspection.seasons.map(s=><option key={s.number} value={s.number}>{s.name||s.number}</option>)}</select>:<input id="serverSeason" className="field-input" type="number" min="1" max="1000" value={season} onChange={e=>setSeason(e.target.value)} required/>}</div></div>
    <div className="episode-selection" role="group" aria-labelledby="episodeSelectionLabel"><p id="episodeSelectionLabel" className="episode-selection-legend">{kind==='manga'?'Какие главы добавить':'Какие серии добавить'}</p><div className="chip-row">{[['all','Весь сезон'],['single','Одна'],['range','Диапазон'],['list','Свой список']].map(([id,label])=><button type="button" key={id} className={'chip'+(mode===id?' chip-active':'')} onClick={()=>setMode(id)}>{id==='all'&&kind==='manga'?'Все главы':label}</button>)}</div>{mode==='single'&&<select className="field-input" value={one} onChange={e=>setOne(e.target.value)} aria-label="Номер серии">{published.map(e=><option key={e.url} value={e.number}>{e.title||'Серия '+e.number}</option>)}</select>}{mode==='range'&&<div className="import-field-grid"><input className="field-input" type="number" min="1" value={first} onChange={e=>setFirst(e.target.value)} aria-label="Первая серия"/><input className="field-input" type="number" min="1" value={last} onChange={e=>setLast(e.target.value)} aria-label="Последняя серия"/></div>}{mode==='list'&&<input id="serverEpisodes" className="field-input" value={list} onChange={e=>setList(e.target.value)} placeholder="1, 3, 5-8" aria-label="Список серий"/>}<p className="fine">{inspection?`Найдено опубликованных файлов: ${published.length}. `:''}Добавляются только доступные файлы. Завершённые повторно не скачиваются.</p></div>
    {['anime','movie','tv'].includes(kind)&&<><label className="input-label" htmlFor="serverQuality">Качество</label><select id="serverQuality" className="field-input" value={quality} onChange={e=>setQuality(e.target.value)}><option value="best">Лучшее доступное{qualityData?.best?' · '+qualityData.best+'p':''}</option>{(qualityData?.qualities||[]).map(height=><option key={height} value={String(height)}>До {height}p</option>)}</select>{qualityLoading&&<p className="fine" role="status">Проверяем все качества выбранного плеера…</p>}{qualityError&&<p className="fine">{qualityError} <button type="button" className="text-link" onClick={()=>setQualityRevision(v=>v+1)}>Повторить проверку качеств</button></p>}{qualityData&&<p className="fine">Показаны качества выбранной серии и озвучки. «Лучшее доступное» выбирает максимум отдельно для каждой серии.</p>}</>}
    {destination!=='online'&&Number(service.session?.serverVersion)>=11&&published.length>0&&['anime','movie','tv'].includes(kind)&&<button type="button" className="btn btn-secondary online-launch" disabled={!!busy||service.status!=='connected'} onClick={startOnline}><Icon name="video" size={17}/>Смотреть сейчас · без импорта</button>}
    {state.busy&&<p className="fine" role="status">Библиотека обновляется. Импорт будет доступен через несколько секунд.</p>}{destination==='drive'&&<ImportReadiness state={state} service={service} onOpenLibrary={onOpenLibrary}/>}
    {localProgress&&<p className="world-local-progress" role="status">{localProgress}{busy==='local'&&<button type="button" className="text-link" onClick={()=>localAbort.current?.abort(new DOMException('Скачивание остановлено','AbortError'))}>Остановить</button>}</p>}{error&&<p className="inline-error" role="alert">{error}</p>}<button id="importVideoBtn" className="btn btn-primary import-submit" disabled={(destination==='drive'?!ready||!!state.busy:service.status!=='connected')||!!busy||!inspection||!published.length} type="submit"><Icon name="cloud" size={18}/>{busy==='submit'?'Отправляем на сервер…':destination==='online'?'Смотреть сейчас':destination==='local'?(busy==='local'?'Подготавливаем файлы…':'Сохранить на устройство'):'Сохранить в Google Диск'}<Icon name="arrow" size={17}/></button><p className="fine">{destination==='online'?'Видео открывается из источника в нашем плеере. Файл не добавляется в Drive.':'После принятия задания сервером можно закрыть вкладку. Файлы появятся в коллекции.'}</p>
    {inspection&&<details className="source-calendar"><summary>Даты публикаций этого источника</summary><ReleaseCalendar dubReleases={inspection.releases||[]}/></details>}
  </form></>;
}
