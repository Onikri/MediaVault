import {useEffect,useMemo,useRef,useState} from 'react';
import OnlineViewer from './OnlineViewer.jsx';
import TitleEpisodeCard from './TitleEpisodeCard.jsx';
import OnlineEpisodePreviews from './OnlineEpisodePreviews.jsx';
import {readWatch,saveWatch,orderedVoices,variantsFor,onlineEpisodeId} from './watch-session.js';
import {readEpisodePreview,saveEpisodePreview} from './episode-preview-cache.js';
import './watch-page.css';
import EpisodeMotionPreview from './EpisodeMotionPreview.jsx';
import {voiceEpisodeCount} from './anime-navigation.js';
import useWatchQualities from './use-watch-qualities.js';
import {bestQualityRow,qualityHeights} from './watch-quality.js';

export default function OnlineWatch({item,profile=item,discovery,service,userId}){
 const identity=String(item.ids?.mal||item.id),saved=useRef(readWatch(userId,identity));
 const voices=useMemo(()=>orderedVoices(discovery.data?.voices||[],saved.current),[discovery.data]);
 const [voiceId,setVoiceId]=useState(saved.current.voiceId||''),[episode,setEpisode]=useState(saved.current.episode||1),[season,setSeason]=useState(saved.current.season||1);
 const [audioId,setAudioId]=useState(saved.current.audioId||''),[subtitleId,setSubtitleId]=useState(saved.current.subtitleId||'');
 const [entries,setEntries]=useState([]),[seasons,setSeasons]=useState([]),[variant,setVariant]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[playing,setPlaying]=useState(false),[count,setCount]=useState(24);
 const [hovering,setHovering]=useState(false);
 const [quality,setQuality]=useState(saved.current.quality||'best'),[bestVideo,setBestVideo]=useState(!!saved.current.bestVideo);
 const frozen=useRef(null);
 const [previews,setPreviews]=useState({}),[audio,setAudio]=useState(null),[captions,setCaptions]=useState([]),[trackError,setTrackError]=useState(''),[trackBusy,setTrackBusy]=useState(false);
 const trackClient=useRef('watch-'+crypto.randomUUID());
 const failed=useRef(new Set()),cache=useRef(new Map()),seasonUrls=useRef(new Map()),tracked=useRef('');
 const voice=voices.find(v=>v.id===voiceId)||voices[0];
 function persist(change){saved.current=saveWatch(userId,identity,change);}
 useEffect(()=>{if(voice&&voice.id!==voiceId)setVoiceId(voice.id);},[voice?.id,voiceId]);
 async function inspect(candidate,signal){
  const key=candidate.id+':'+season;if(cache.current.has(key))return cache.current.get(key);
  const seasonUrl=seasonUrls.current.get(key);
  let data,continuation,progress=-1,stalled=0;
  do{data=await service.request('/sources/inspect',{method:'POST',body:{url:seasonUrl||candidate.sourceUrl,...(!seasonUrl?{dub_url:candidate.url}:{}),season:Number(season),kind:'anime',...(continuation?{continuation}:{})},signal});
   continuation=data.continuation;stalled=continuation&&data.scannedPages===progress?stalled+1:0;progress=data.scannedPages;
   if(stalled>=3)throw Error('Источник не завершил проверку серий.');
  }while(continuation);
  signal.throwIfAborted();for(const s of data.seasons||[])if(s.url)seasonUrls.current.set(candidate.id+':'+s.number,s.url);
  const rows=(data.episodes||[]).filter(e=>!e.season||Number(e.season)===Number(season)).map(e=>({...e,season:e.season||Number(season)}));
  if(!rows.length)throw Error('У этой озвучки пока нет доступных серий.');
  const result={entries:rows,seasons:data.seasons||[],variant:candidate};cache.current.set(key,result);return result;
 }
 const qualityScan=useWatchQualities({voices,voiceId:voice?.id,episode,season,server:service.server,inspect,service,attempt});
 async function resolve(group,number,signal,excluded=failed.current){
  let last;for(const candidate of variantsFor(group,number,excluded)){
   try{const value=await inspect(candidate,signal);if(!value.entries.some(e=>Number(e.number)===Number(number))&&playing)continue;return value;}
   catch(e){signal.throwIfAborted();last=e;}
  }throw last||Error('Эта серия не ответила ни в одном источнике выбранной озвучки.');
 }
 useEffect(()=>{if(!voice)return;const abort=new AbortController();setBusy(true);setVariant(null);setError('');
  resolve(voice,episode,abort.signal).then(value=>{if(abort.signal.aborted)return;setEntries(value.entries);setSeasons(value.seasons);setVariant(value.variant);const selected=value.entries.find(e=>Number(e.number)===Number(episode))||value.entries[0];setEpisode(Number(selected.number));persist({voiceId:voice.id,episode:Number(selected.number),season});}).catch(e=>{if(!abort.signal.aborted){setVariant(null);setError(e.message);}}).finally(()=>!abort.signal.aborted&&setBusy(false));
  return()=>abort.abort();
 },[voice?.id,season,attempt,service.server]);
 useEffect(()=>{let closed=false;(async()=>{const values={};for(const e of entries.slice(0,count)){const id=onlineEpisodeId(identity,e.season||season,e.number),image=await readEpisodePreview(id+':'+(userId||'anonymous'));if(image)values[e.number]=image;}if(!closed)setPreviews(old=>({...old,...values}));})();return()=>{closed=true;};},[entries,count,identity,userId]);
 useEffect(()=>{if(!playing||!voice)return;const key=voice.id+':'+season+':'+episode;if(tracked.current===key)return;tracked.current=key;
  persist({voiceId:voice.id,episode,season,usage:{...saved.current.usage,[voice.id]:(saved.current.usage?.[voice.id]||0)+1}});
 },[playing,voice?.id,episode,season]);
 const preferred=bestQualityRow(qualityScan.rows,{voiceId:voice?.id,quality,anyVoice:bestVideo,failed:failed.current});
 const selectionKey=[voice?.id,season,episode,quality,bestVideo,attempt].join(':');
 const selectionReady=!qualityScan.busy||(!bestVideo&&qualityScan.done>=(voice?.variants.length||0));
 const base=voice?.variants.some(v=>v.id===variant?.id)&&!failed.current.has(variant?.id)?{variant,entries,voiceId:voice?.id}:null;
 if(!playing)frozen.current=null;
 if(playing&&(frozen.current?.key!==selectionKey||!frozen.current?.value))frozen.current={key:selectionKey,value:selectionReady?(preferred||base):null};
 const selectedVideo=playing?frozen.current?.value:preferred;
 const viewVariant=selectedVideo?.variant||(!playing?base?.variant:null),viewEntries=selectedVideo?.entries||base?.entries||entries,videoVoiceId=selectedVideo?.voiceId||voice?.id;
 const effectiveAudioId=audioId||(videoVoiceId!==voice?.id?voice?.id:'');
 // Independent audio/captions get their own lease; changing them never
 // replaces the video source or its HLS quality selection.
 useEffect(()=>{setAudio(null);setCaptions([]);setTrackError('');if(!playing||!effectiveAudioId&&!subtitleId)return;
  const abort=new AbortController(),leases=[];let closed=false;setTrackBusy(true);
  const prepare=async(id,mode)=>{
   if(!id)return;const group=voices.find(v=>v.id===id);if(!group)throw Error('Сохранённая дорожка пока недоступна.');
   const value=await resolve(group,episode,abort.signal,new Set()),entry=value.entries.find(e=>Number(e.number)===Number(episode));
   if(!entry)throw Error('Дорожка для этой серии не опубликована.');
   const data=await service.request('/online/prepare',{method:'POST',body:{url:entry.url,referer:value.variant.sourceUrl,kind:'video',quality:'best',clientId:trackClient.current+':'+mode},signal:abort.signal});
   if(closed){service.request('/online/'+data.id,{method:'DELETE',keepalive:true}).catch(()=>{});return;}
   leases.push(data.id);
   if(mode==='audio')setAudio({url:service.server.replace(/\/$/,'')+data.url,type:data.type,name:group.name});
   else if(data.subtitles?.length)setCaptions(data.subtitles.map(t=>({...t,url:service.server.replace(/\/$/,'')+t.url})));
   else {leases.splice(leases.indexOf(data.id),1);service.request('/online/'+data.id,{method:'DELETE',keepalive:true}).catch(()=>{});throw Error('У этой версии субтитры вшиты в изображение. Отдельная дорожка не опубликована; можно загрузить SRT/VTT.');}
  };
  Promise.allSettled([prepare(effectiveAudioId,'audio'),prepare(subtitleId,'captions')]).then(results=>{if(!closed){const rejected=results.find(v=>v.status==='rejected');if(rejected)setTrackError(rejected.reason.message);setTrackBusy(false);}});
  const timer=setInterval(()=>leases.forEach(id=>service.request('/online/'+id+'/heartbeat',{method:'POST'}).catch(()=>{})),35000);
  return()=>{closed=true;abort.abort();clearInterval(timer);leases.forEach(id=>service.request('/online/'+id,{method:'DELETE',keepalive:true}).catch(()=>{}));};
 },[effectiveAudioId,subtitleId,episode,season,playing,service.server]);
 const current=viewEntries.find(e=>Number(e.number)===Number(episode))||viewEntries[0];
 const visibleEntries=useMemo(()=>viewEntries.slice(0,count),[viewEntries,count]);
 const spoken=voices.filter(v=>v.kind!=='subtitles');
 function changeVoice(id,nextQuality=quality){failed.current.clear();setVoiceId(id);setAudioId('');setSubtitleId('');if(nextQuality!=='best'&&!bestVideo&&!qualityScan.rows.some(r=>r.voiceId===id&&r.qualities.includes(Number(nextQuality)))){setQuality('best');persist({quality:'best'});}persist({voiceId:id,audioId:'',subtitleId:''});}
 function fallback(){if(!viewVariant)return false;failed.current.add(viewVariant.id);if(!variantsFor(voice,episode,failed.current).length)return false;setAttempt(n=>n+1);return true;}
 function preview(number,image){setPreviews(old=>({...old,[number]:image}));saveEpisodePreview(onlineEpisodeId(identity,season,number)+':'+(userId||'anonymous'),image);}
 const heights=qualityHeights(qualityScan.rows);
 const offeredVoices=quality==='best'||bestVideo?voices:voices.filter(v=>v.id===voice?.id||qualityScan.rows.some(r=>r.voiceId===v.id&&r.qualities.includes(Number(quality)))||!qualityScan.rows.some(r=>r.voiceId===v.id));
 function changeQuality(value){setQuality(value);persist({quality:value});if(value!=='best'&&!bestVideo&&!qualityScan.rows.some(r=>r.voiceId===voice?.id&&r.qualities.includes(Number(value)))){const row=bestQualityRow(qualityScan.rows,{quality:value,anyVoice:true});if(row)changeVoice(row.voiceId,value);}}
 const controls={voices:spoken.map(v=>({id:v.id,name:v.name})),voiceId:audioId||voice?.id,
  onVoice:id=>{const value=id===voice?.id?'':id;setAudioId(value);persist({audioId:value});},
  captionVoices:voices.filter(v=>v.kind==='subtitles').map(v=>({id:v.id,name:v.name})),subtitleId,
  onCaptionVoice:id=>{setSubtitleId(id);persist({subtitleId:id});},audio,externalCaptions:captions,trackBusy,trackError};
 return <div className="online-watch">
  <OnlineEpisodePreviews entries={visibleEntries} active={!playing&&!busy&&!hovering} service={service} sourceUrl={viewVariant?.sourceUrl} identity={identity} season={season} userId={userId} onPreview={preview}/>
  <div className="watch-selection"><label>Озвучка<select aria-label="Озвучка для просмотра" value={voice?.id||''} onChange={e=>changeVoice(e.target.value)} disabled={!voices.length}><option value="" disabled>{discovery.loading?'Ищем озвучки…':'Выбери озвучку'}</option>{offeredVoices.map(v=><option key={v.id} value={v.id}>{v.name}{qualityHeights(qualityScan.rows.filter(r=>r.voiceId===v.id))[0]?' · до '+qualityHeights(qualityScan.rows.filter(r=>r.voiceId===v.id))[0]+'p':''}{voiceEpisodeCount(v,season)?' · '+voiceEpisodeCount(v,season)+' сер.':''}{v.kind==='subtitles'?' · субтитры':''}{saved.current.usage?.[v.id]?' · твой выбор':''}</option>)}</select></label>
   <label>Качество<select aria-label="Качество просмотра" value={quality} onChange={e=>changeQuality(e.target.value)}><option value="best">Лучшее · авто</option>{heights.map(q=><option key={q} value={String(q)}>{q}p{!bestVideo&&!qualityScan.rows.some(r=>r.voiceId===voice?.id&&r.qualities.includes(q))?' · другая озвучка':''}</option>)}{quality!=='best'&&!heights.includes(Number(quality))&&<option value={quality}>{quality}p · проверяем</option>}</select></label>
  </div>
  <div className="watch-quality-note"><label><input type="checkbox" checked={bestVideo} onChange={e=>{setBestVideo(e.target.checked);persist({bestVideo:e.target.checked});}}/>Лучшее видео из всех озвучек · звук отдельно</label><span role="status">{qualityScan.busy?'Проверяем качества: '+qualityScan.done+' / '+qualityScan.total:heights.length?'Доступно до '+heights[0]+'p':'Качества будут доступны в плеере'}{bestVideo&&videoVoiceId!==voice?.id?' · видео: '+(voices.find(v=>v.id===videoVoiceId)?.name||'другая версия'):''}</span></div>
  {playing&&current&&viewVariant?<OnlineViewer quality={quality} entries={viewEntries} initial={current} kind="video" title={item.title} service={service} userId={userId} inline sourceUrl={viewVariant.sourceUrl} dub={voice?.name} metadata={{...profile,ids:item.ids}} identity={identity} voiceId={voice?.id} controls={controls} onPreview={preview} previews={previews} onUnavailable={fallback} onClose={()=>setPlaying(false)} onEntryChange={e=>{setEpisode(Number(e.number));persist({episode:Number(e.number),season:e.season||season});}}/>
   :<div className="watch-idle" style={profile.cover?{'--watch-poster':`url("${profile.cover.replace(/["\\]/g,'')}")`}:undefined}>
    {busy||playing&&!selectionReady||discovery.loading&&!voices.length?<div className="watch-skeleton" role="status"><span/>Подбираем озвучки, качества и серии…</div>:<button className="watch-play" disabled={!current||!viewVariant} onClick={()=>setPlaying(true)}><span aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M8 4v16l13-8z"/></svg></span>{current?'Смотреть · серия '+current.number:'Выбери озвучку'}</button>}
   </div>}
  {error&&<div className="inline-error" role="alert">{error}<button className="text-link" onClick={()=>{failed.current.clear();setAttempt(n=>n+1);}}>Повторить</button></div>}
  {discovery.error&&<p className="fine">{discovery.error}<button className="text-link" onClick={discovery.retry}>Повторить поиск</button></p>}
  <div className="watch-episodes-heading"><h3>Серии</h3><span>{viewEntries.length||''}</span>{seasons.length>1&&<select aria-label="Сезон просмотра" value={season} onChange={e=>{setPlaying(false);setSeason(Number(e.target.value));setEpisode(1);setPreviews({});failed.current.clear();persist({season:Number(e.target.value),episode:1});}}>{seasons.map(s=><option key={s.number} value={s.number}>{s.name||'Сезон '+s.number}</option>)}</select>}</div>
  <div className="watch-episode-grid">{viewEntries.slice(0,count).map(e=>{const art=previews[e.number]||profile.episodeImages?.[String(e.number)]||profile.cover;return <TitleEpisodeCard key={e.number} number={e.number} title={'Серия '+e.number} detail={e.title&&e.title!=='Серия '+e.number?e.title:undefined} selected={playing&&Number(e.number)===episode} onClick={()=>{setEpisode(Number(e.number));persist({episode:Number(e.number),season:e.season||season});setPlaying(true);}} artwork={<EpisodeMotionPreview cacheKey={onlineEpisodeId(identity,e.season||season,e.number)+':'+(userId||'anonymous')} onActive={setHovering} prepare={async signal=>{const d=await service.request('/online/prepare',{method:'POST',body:{url:e.url,referer:viewVariant.sourceUrl,kind:'video',quality:'best',clientId:'motion-'+crypto.randomUUID()},signal});return {url:service.server.replace(/\/$/,'')+d.url,type:d.type,close:()=>service.request('/online/'+d.id,{method:'DELETE',keepalive:true}).catch(()=>{})};}}>{art?<img src={art} alt={previews[e.number]?'Кадр серии '+e.number:'Обложка тайтла'} loading='lazy' referrerPolicy='no-referrer'/>:null}</EpisodeMotionPreview>}/>;})}</div>
  {viewEntries.length>count&&<button className="text-link" onClick={()=>setCount(n=>n+24)}>Ещё серии</button>}
  {!!saved.current.usage&&<p className="watch-personal-note">«Твой выбор» — история просмотров на этом устройстве.</p>}
 </div>;
}
