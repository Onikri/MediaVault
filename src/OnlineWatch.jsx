import useSeasonSource from './use-season-source.js';
import {episodeDetail,useFranchiseSeasons,catalogueSeasonHint} from './franchise-seasons.js';
import PlayerSettings from './PlayerSettings.jsx';
import {Settings2} from 'lucide-react';
import PlaybackReveal from './PlaybackReveal.jsx';
import {useEffect,useMemo,useRef,useState} from 'react';
import OnlineViewer from './OnlineViewer.jsx';
import TitleEpisodeCard from './TitleEpisodeCard.jsx';
import OnlineEpisodePreviews from './OnlineEpisodePreviews.jsx';
import {readWatch,saveWatch,orderedVoices,variantsFor,episodePreviewKey} from './watch-session.js';
import {readEpisodePreview,saveEpisodePreview} from './episode-preview-cache.js';
import './watch-page.css';
import EpisodeMotionPreview from './EpisodeMotionPreview.jsx';
import {voiceEpisodeCount} from './anime-navigation.js';
import useVisibleCards from './use-visible-cards.js';
import useWatchQualities from './use-watch-qualities.js';
import {bestQualityRow,qualityHeights} from './watch-quality.js';

const noEntries=Object.freeze([]);
export default function OnlineWatch({item:basisItem,profile:basisProfile=basisItem,discovery:basisDiscovery,service,userId,onSeasonBrowse}){
 const [sourceContext,setSourceContext]=useState(null),activeVoiceName=useRef('');
 const item=sourceContext?.item||basisItem,profile=sourceContext?.profile||basisProfile;
 const basisId=String(basisItem.ids?.mal||''),activeWorkId=String(item.ids?.mal||'');
 const family=useFranchiseSeasons(basisId,service.server),[browseWorkId,setBrowseWorkId]=useState(basisId);
 const catalogSeasons=family.length>1,familySeason=family.find(s=>String(s.id)===browseWorkId),activeFamilySeason=family.find(s=>String(s.id)===activeWorkId);
 const browsingCatalog=catalogSeasons&&!!browseWorkId&&browseWorkId!==activeWorkId;
 const foreign=useSeasonSource({workId:browseWorkId,basisItem,basisProfile,basisDiscovery,descriptor:familySeason,service,userId,voiceName:activeVoiceName.current,enabled:browsingCatalog});
 const discovery=sourceContext?(foreign.item&&String(foreign.item.ids?.mal)===activeWorkId?foreign.discovery:sourceContext.discovery):basisDiscovery;
 const shelf=useRef(null);
 const identity=String(item.ids?.mal||item.id),saved=useRef(readWatch(userId,identity));
 const playbackMetadata=useMemo(()=>({...profile,ids:item.ids}),[profile,item.ids]);
 const voices=useMemo(()=>orderedVoices(discovery.data?.voices||[],saved.current),[discovery.data]);
 const initialSeason=catalogueSeasonHint(basisItem)||saved.current.season||1;
 const [voiceId,setVoiceId]=useState(saved.current.voiceId||''),[episode,setEpisode]=useState(saved.current.episode||1),[season,setSeason]=useState(initialSeason);
 const [browseSeason,setBrowseSeason]=useState(initialSeason),[browseData,setBrowseData]=useState(null),[browseBusy,setBrowseBusy]=useState(false),[browseError,setBrowseError]=useState(''),[browseAttempt,setBrowseAttempt]=useState(0);
 const [audioId,setAudioId]=useState(saved.current.audioId||''),[subtitleId,setSubtitleId]=useState(saved.current.subtitleId||'');
 const [entries,setEntries]=useState([]),[seasons,setSeasons]=useState([]),[variant,setVariant]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[playing,setPlaying]=useState(false),[count,setCount]=useState(24);
 const [hovering,setHovering]=useState(false),[sourceSettings,setSourceSettings]=useState(false),sourceButton=useRef(null);
 const [quality,setQuality]=useState(saved.current.quality||'best'),[bestVideo,setBestVideo]=useState(!!saved.current.bestVideo);
 const frozen=useRef(null);
 const [scanScope,setScanScope]=useState(''),[scanRun,setScanRun]=useState(0),[applyRevision,setApplyRevision]=useState(0),[preparedRows,setPreparedRows]=useState([]);
 const [previewStore,setPreviewStore]=useState({}),[audio,setAudio]=useState(null),[captions,setCaptions]=useState([]),[trackError,setTrackError]=useState(''),[trackBusy,setTrackBusy]=useState(false);
 const trackClient=useRef('watch-'+crypto.randomUUID());
 const failed=useRef(new Set()),cache=useRef(new Map()),seasonUrls=useRef(new Map()),tracked=useRef('');
 const voice=voices.find(v=>v.id===voiceId||v.aliases?.includes(voiceId))||voices[0];activeVoiceName.current=voice?.name||'';
 function persist(change){saved.current=saveWatch(userId,identity,change);}
 useEffect(()=>{if(voice&&voice.id!==voiceId)setVoiceId(voice.id);},[voice?.id,voiceId]);
 async function inspect(candidate,signal,selectedSeason=season){
  const key=identity+':'+candidate.id+':'+selectedSeason;if(cache.current.has(key))return cache.current.get(key);
  const seasonUrl=seasonUrls.current.get(key);
  let data,continuation,progress=-1,stalled=0;
  do{data=await service.request('/sources/inspect',{method:'POST',body:{url:seasonUrl||candidate.sourceUrl,...(!seasonUrl?{dub_url:candidate.url}:{}),season:Number(selectedSeason),kind:'anime',...(continuation?{continuation}:{})},signal});
   continuation=data.continuation;stalled=continuation&&data.scannedPages===progress?stalled+1:0;progress=data.scannedPages;
   if(stalled>=3)throw Error('Источник не завершил проверку серий.');
  }while(continuation);
  signal.throwIfAborted();for(const s of data.seasons||[])if(s.url)seasonUrls.current.set(identity+':'+candidate.id+':'+s.number,s.url);
  let rows=(data.episodes||[]).filter(e=>!e.season||Number(e.season)===Number(selectedSeason)).map(e=>({...e,season:e.season||Number(selectedSeason)}));
  const actualSeasons=[...new Set((data.episodes||[]).map(e=>Number(e.season)||1))];
  if(!rows.length&&actualSeasons.length===1&&(data.seasons||[]).length<=1)rows=data.episodes;
  if(!rows.length)throw Error('У этой озвучки пока нет доступных серий.');
  const actualSeason=Number(rows[0].season)||Number(selectedSeason);
  const result={entries:rows,seasons:data.seasons||[],variant:candidate,season:actualSeason};cache.current.set(key,result);cache.current.set(identity+':'+candidate.id+':'+actualSeason,result);return result;
 }
 const qualityScan=useWatchQualities({voices,voiceId:voice?.id,episode,season,server:service.server,inspect,service,attempt:attempt+scanRun,scope:scanScope,identity});
 async function resolve(group,number,signal,excluded=failed.current,selectedSeason=season,requireEpisode=playing){
  let last;for(const candidate of variantsFor(group,number,excluded)){
   try{const value=await inspect(candidate,signal,selectedSeason);if(!value.entries.some(e=>Number(e.number)===Number(number))&&requireEpisode)continue;return value;}
   catch(e){signal.throwIfAborted();last=e;}
  }throw last||Error('Эта серия не ответила ни в одном источнике выбранной озвучки.');
 }
 useEffect(()=>{if(!voice)return;const abort=new AbortController();setBusy(true);setVariant(null);setError('');
  resolve(voice,episode,abort.signal).then(value=>{if(abort.signal.aborted)return;setEntries(value.entries);setSeasons(value.seasons);setVariant(value.variant);if(value.season!==season){setSeason(value.season);setBrowseSeason(value.season);}const selected=value.entries.find(e=>Number(e.number)===Number(episode))||value.entries[0];setEpisode(Number(selected.number));persist({voiceId:voice.id,episode:Number(selected.number),season:value.season});}).catch(e=>{if(!abort.signal.aborted){setVariant(null);setError(e.message);}}).finally(()=>!abort.signal.aborted&&setBusy(false));
  return()=>abort.abort();
 },[voice?.id,season,attempt,service.server]);
 useEffect(()=>{if(!playing||!voice)return;const key=identity+':'+voice.id+':'+season+':'+episode;if(tracked.current===key)return;tracked.current=key;
  persist({voiceId:voice.id,episode,season,usage:{...saved.current.usage,[voice.id]:(saved.current.usage?.[voice.id]||0)+1}});
 },[playing,voice?.id,episode,season,identity]);
 const knownRows=[...preparedRows.filter(r=>r.identity===identity&&r.episode===episode&&r.season===season),...qualityScan.rows];
 const preferred=bestQualityRow(knownRows,{voiceId:voice?.id,quality,anyVoice:bestVideo,failed:failed.current});
 const selectionKey=[identity,voice?.id,season,episode,quality,bestVideo,attempt,applyRevision].join(':');
 const base=voice?.variants.some(v=>v.id===variant?.id)&&!failed.current.has(variant?.id)?{variant,entries,voiceId:voice?.id}:null;
 if(!playing)frozen.current=null;
 const candidate=preferred||base;
 if(playing&&candidate&&(frozen.current?.key!==selectionKey||!frozen.current?.value))frozen.current={key:selectionKey,value:candidate};
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
 // Browsing another season is metadata work; it never mutates the active session.
 useEffect(()=>{
  if(browseSeason===season||!voice){setBrowseBusy(false);return;}
  const abort=new AbortController();setBrowseData(null);setBrowseBusy(true);setBrowseError('');
  resolve(voice,1,abort.signal,new Set(),browseSeason,false).then(value=>{if(!abort.signal.aborted)setBrowseData({...value,season:browseSeason});}).catch(e=>{if(!abort.signal.aborted)setBrowseError(e.message);}).finally(()=>{if(!abort.signal.aborted)setBrowseBusy(false);});
  return()=>abort.abort();
 },[browseSeason,season,voice?.id,browseAttempt,service.server]);
 const browsingOther=browseSeason!==season;
 const foreignBusy=browsingCatalog&&(foreign.busy||foreign.loading),foreignError=browsingCatalog&&(foreign.error||foreign.discovery.error);
 const displayRows=browsingCatalog?foreign.row:browsingOther?(browseData?.season===browseSeason?browseData:null):{entries:viewEntries,variant:viewVariant,voiceId:videoVoiceId};
 const displayEntries=displayRows?.entries||noEntries,displayVariant=displayRows?.variant;
 const displayIdentity=browsingCatalog?browseWorkId:identity,displaySeason=browsingCatalog?(displayRows?.season||1):browseSeason,displayProfile=browsingCatalog?foreign.profile:profile;
 const visibleEntries=useMemo(()=>displayEntries.slice(0,count),[displayEntries,count]);
 const visibleKeys=useVisibleCards(shelf,visibleEntries.map(e=>e.url).join('\n')+':'+playing);
 const previewEntries=useMemo(()=>visibleEntries.filter(e=>visibleKeys.has(e.url)&&!e.thumbnail&&!e.image&&!displayProfile?.episodeImages?.[String(e.number)]),[visibleEntries,visibleKeys,displayProfile?.episodeImages]);
 const previews=useMemo(()=>Object.fromEntries(Object.entries(previewStore).filter(([k])=>k.startsWith(identity+':'+season+':'+viewVariant?.id+':')).map(([k,v])=>[k.slice(k.lastIndexOf(':')+1),v])),[previewStore,identity,season,viewVariant?.id]);
 const displayPreviews=useMemo(()=>Object.fromEntries(Object.entries(previewStore).filter(([k])=>k.startsWith(displayIdentity+':'+displaySeason+':'+displayVariant?.id+':')).map(([k,v])=>[k.slice(k.lastIndexOf(':')+1),v])),[previewStore,displayIdentity,displaySeason,displayVariant?.id]);
 useEffect(()=>{let closed=false;(async()=>{const values={};for(const e of visibleEntries){const s=e.season||displaySeason,id=episodePreviewKey(displayIdentity,s,e.number,displayVariant?.id,userId),image=await readEpisodePreview(id);if(image)values[displayIdentity+':'+s+':'+displayVariant?.id+':'+e.number]=image;}if(!closed)setPreviewStore(old=>({...old,...values}));})();return()=>{closed=true;};},[visibleEntries,displayIdentity,userId,displaySeason,displayVariant?.id]);
 useEffect(()=>{
  if(browsingCatalog){if(foreign.item)onSeasonBrowse?.({number:familySeason?.number||1,name:familySeason?.name||'Сезон',episodes:foreign.row?.entries.length||foreign.item.episodes,item:foreign.item});}
  else if(displayRows&&!browseBusy)onSeasonBrowse?.({number:activeFamilySeason?.number||browseSeason,name:activeFamilySeason?.name||seasons.find(s=>Number(s.number)===browseSeason)?.name||'Сезон '+browseSeason,episodes:displayEntries.length,item});
 },[browsingCatalog,browseWorkId,foreign.item,foreign.row?.entries.length,familySeason?.name,activeFamilySeason?.name,browseSeason,displayEntries.length,browseBusy,!!displayRows,item]);


 const spoken=voices.filter(v=>v.kind!=='subtitles');
 function changeVoice(id,nextQuality=quality){failed.current.clear();setVoiceId(id);setAudioId('');setSubtitleId('');if(nextQuality!=='best'&&!bestVideo&&!knownRows.some(r=>r.voiceId===id&&r.qualities.includes(Number(nextQuality)))){setQuality('best');persist({quality:'best'});}persist({voiceId:id,audioId:'',subtitleId:''});}
 function fallback(){if(!viewVariant)return false;failed.current.add(viewVariant.id);if(!variantsFor(voice,episode,failed.current).length)return false;setAttempt(n=>n+1);return true;}
 function preview(number,image,selectedSeason=season,sourceId=viewVariant?.id,workIdentity=identity){setPreviewStore(old=>({...old,[workIdentity+':'+selectedSeason+':'+sourceId+':'+number]:image}));saveEpisodePreview(episodePreviewKey(workIdentity,selectedSeason,number,sourceId,userId),image);}
 const heights=qualityHeights(knownRows);
 const offeredVoices=quality==='best'||bestVideo?voices:voices.filter(v=>v.id===voice?.id||knownRows.some(r=>r.voiceId===v.id&&r.qualities.includes(Number(quality)))||!knownRows.some(r=>r.voiceId===v.id));
 function changeQuality(value){setQuality(value);persist({quality:value});if(value!=='best'&&!bestVideo&&!knownRows.some(r=>r.voiceId===voice?.id&&r.qualities.includes(Number(value)))){const row=bestQualityRow(knownRows,{quality:value,anyVoice:true});if(row)changeVoice(row.voiceId,value);}}
 function changeVideoMode(checked){setBestVideo(checked);if(checked)startScan('all');persist({bestVideo:checked});if(!checked&&quality!=='best'&&!knownRows.some(r=>r.voiceId===voice?.id&&r.qualities.includes(Number(quality)))){setQuality('best');persist({quality:'best'});}}
 function startScan(scope='all'){setScanScope(scope);setScanRun(n=>n+1);}
 function startPlayback(number=episode,targetSeason=season,row){const recommended=row||(preferred?.entries.some(e=>Number(e.number)===Number(number))?preferred:base);if(!recommended)return;frozen.current={key:[identity,voice?.id,targetSeason,Number(number),quality,bestVideo,attempt,applyRevision].join(':'),value:recommended};setScanScope('');setSeason(targetSeason);setBrowseSeason(targetSeason);setEpisode(Number(number));setSourceSettings(false);if(row){setEntries(row.entries);setVariant(row.variant);}setPlaying(true);}
 function startCatalogPlayback(number){
  const value=foreign.row;if(!value||!foreign.item)return;
  const nextIdentity=String(foreign.item.ids?.mal||foreign.item.id),nextSeason=value.season;
  const context={item:foreign.item,profile:foreign.profile,discovery:foreign.discovery,voice:value.voice};
  saved.current=saveWatch(userId,nextIdentity,{...readWatch(userId,nextIdentity),voiceId:value.voice.id,episode:Number(number),season:nextSeason,audioId:'',subtitleId:''});
  failed.current.clear();cache.current.set(nextIdentity+':'+value.variant.id+':'+nextSeason,value);
  frozen.current={key:[nextIdentity,value.voice.id,nextSeason,Number(number),quality,bestVideo,attempt,applyRevision].join(':'),value};
  setSourceContext(context);setVoiceId(value.voice.id);setAudioId('');setSubtitleId('');setSeason(nextSeason);setBrowseSeason(nextSeason);setEntries(value.entries);setSeasons(value.seasons);setVariant(value.variant);setEpisode(Number(number));setPlaying(true);setScanScope('');setSourceSettings(false);setError('');
 }
 function prepared(data){if(!viewVariant)return;const row={identity,variant:viewVariant,entries:viewEntries,voiceId:videoVoiceId,episode,season,qualities:(data.qualities||[]).map(Number).sort((a,b)=>b-a)};setPreparedRows(old=>[...old.filter(r=>r.variant.id!==row.variant.id||r.episode!==episode||r.season!==season),row].slice(-100));}
 const configuration=<div className="watch-player-configuration">  <div className="watch-selection"><label>Озвучка<select aria-label="Озвучка для просмотра" value={voice?.id||''} onChange={e=>changeVoice(e.target.value)} disabled={!voices.length}><option value="" disabled>{discovery.loading?'Ищем озвучки…':'Выбери озвучку'}</option>{offeredVoices.map(v=><option key={v.id} value={v.id}>{v.name}{qualityHeights(knownRows.filter(r=>r.voiceId===v.id))[0]?' · до '+qualityHeights(knownRows.filter(r=>r.voiceId===v.id))[0]+'p':''}{voiceEpisodeCount(v,season)?' · '+voiceEpisodeCount(v,season)+' сер.':''}{v.kind==='subtitles'?' · субтитры':''}{saved.current.usage?.[v.id]?' · твой выбор':''}</option>)}</select></label>
   <label>Качество<select aria-label="Качество просмотра" value={quality} onChange={e=>changeQuality(e.target.value)}><option value="best">Лучшее · авто</option>{heights.map(q=><option key={q} value={String(q)}>{q}p{!bestVideo&&!knownRows.some(r=>r.voiceId===voice?.id&&r.qualities.includes(q))?' · другая озвучка':''}</option>)}{quality!=='best'&&!heights.includes(Number(quality))&&<option value={quality}>{quality}p · проверяем</option>}</select></label>
  </div>
  <div className="watch-quality-note"><label><input type="checkbox" checked={bestVideo} onChange={e=>changeVideoMode(e.target.checked)}/>Лучшее видео из всех озвучек · звук отдельно</label><button type="button" className="text-link" onClick={()=>startScan('all')} disabled={qualityScan.busy&&!!scanScope}>{qualityScan.busy&&scanScope?'Ищем варианты…':'Найти другие качества'}</button>{playing&&preferred&&preferred.variant.id!==viewVariant?.id&&<button type="button" className="text-link" onClick={()=>{setScanScope('');setApplyRevision(n=>n+1);}}>Применить найденное · {preferred.qualities[0]}p</button>}<span role="status">{qualityScan.busy&&scanScope?'Проверяем качества: '+qualityScan.done+' / '+qualityScan.total:heights.length?'Доступно до '+heights[0]+'p':'Качества будут доступны в плеере'}{bestVideo&&videoVoiceId!==voice?.id?' · видео: '+(voices.find(v=>v.id===videoVoiceId)?.name||'другая версия'):''}</span></div>
</div>;
 const episodeBrowser=<section ref={shelf} className="watch-episode-browser" aria-label="Сезоны и серии">  <div className="watch-episodes-heading"><h3>Серии</h3><span>{displayEntries.length||''}</span>{(catalogSeasons||seasons.length>1)&&<select aria-label="Сезон просмотра" value={catalogSeasons?'work:'+browseWorkId:browseSeason} onChange={e=>{if(e.target.value.startsWith('work:'))setBrowseWorkId(e.target.value.slice(5));else setBrowseSeason(Number(e.target.value));setCount(24);}}>{catalogSeasons?family.map(s=><option key={s.id} value={'work:'+s.id}>{s.name}</option>):seasons.map(s=><option key={s.number} value={s.number}>{s.name||'Сезон '+s.number}</option>)}</select>}</div>
  {(browsingCatalog?foreignBusy:browsingOther&&browseBusy)&&<p className="fine" role="status">Загружаем серии: {catalogSeasons?familySeason?.name:'сезон '+browseSeason}…{playing?' Текущая серия продолжает играть.':''}</p>}
  {(browsingCatalog?foreignError:browsingOther&&browseError)&&<p className="inline-error" role="alert">{browsingCatalog?foreignError:browseError}<button className="text-link" onClick={()=>browsingCatalog?foreign.retry():setBrowseAttempt(n=>n+1)}>Повторить список серий</button></p>}
  <div className="watch-episode-grid">{displayEntries.slice(0,count).map(e=>{const art=displayPreviews[e.number]||e.thumbnail||e.image||displayProfile?.episodeImages?.[String(e.number)]||displayProfile?.cover;return <TitleEpisodeCard key={e.number} data-preview-key={e.url} number={e.number} title={'Серия '+e.number} detail={episodeDetail(e.title,e.number)} selected={playing&&!browsingCatalog&&browseSeason===season&&Number(e.number)===episode} onClick={()=>{if(browsingCatalog){startCatalogPlayback(e.number);return;}persist({episode:Number(e.number),season:e.season||browseSeason});startPlayback(e.number,browseSeason,displayRows);}} artwork={<EpisodeMotionPreview cacheKey={episodePreviewKey(displayIdentity,e.season||displaySeason,e.number,displayVariant?.id,userId)} onActive={setHovering} prepare={async signal=>{const d=await service.request('/online/prepare',{method:'POST',body:{url:e.url,referer:displayVariant?.sourceUrl,kind:'video',quality:'360',clientId:'motion-'+crypto.randomUUID()},signal});return {url:service.server.replace(/\/$/,'')+d.url,type:d.type,close:()=>service.request('/online/'+d.id,{method:'DELETE',keepalive:true}).catch(()=>{})};}}>{art?<img src={art} alt={displayPreviews[e.number]?'Кадр серии '+e.number:'Обложка тайтла'} loading='lazy' referrerPolicy='no-referrer'/>:null}</EpisodeMotionPreview>}/>;})}</div>
  {displayEntries.length>count&&<button className="text-link" onClick={()=>setCount(n=>n+24)}>Ещё серии</button>}
</section>;
 const idleCurrent=browsingCatalog?foreign.row?.entries[0]:current,idleVariant=browsingCatalog?foreign.row?.variant:viewVariant,idleBusy=browsingCatalog?foreignBusy:busy||discovery.loading&&!voices.length;
 const controls={configuration,episodeBrowser,seasonName:activeFamilySeason?.name,voices:spoken.map(v=>({id:v.id,name:v.name})),voiceId:audioId||voice?.id,
  onVoice:id=>{const value=id===voice?.id?'':id;setAudioId(value);persist({audioId:value});},
  captionVoices:voices.filter(v=>v.kind==='subtitles').map(v=>({id:v.id,name:v.name})),subtitleId,
  onCaptionVoice:id=>{setSubtitleId(id);persist({subtitleId:id});},audio,externalCaptions:captions,trackBusy,trackError};
 return <div className="online-watch">
  <OnlineEpisodePreviews entries={previewEntries} active={!playing&&!busy&&!browseBusy&&!foreignBusy&&!hovering} service={service} sourceUrl={displayVariant?.sourceUrl} sourceId={displayVariant?.id} identity={displayIdentity} season={displaySeason} userId={userId} onPreview={(number,image)=>preview(number,image,displaySeason,displayVariant?.id,displayIdentity)}/>
  <PlaybackReveal active={playing}>{playing&&current&&viewVariant?<OnlineViewer quality={quality} entries={viewEntries} initial={current} kind="video" title={item.title} service={service} userId={userId} inline sourceUrl={viewVariant.sourceUrl} dub={voice?.name} metadata={playbackMetadata} identity={identity} voiceId={voice?.id} controls={controls} onPreview={preview} previews={previews} onUnavailable={fallback} onPrepared={prepared} onClose={()=>{setPlaying(false);setScanScope('');}} onEntryChange={e=>{setEpisode(Number(e.number));persist({episode:Number(e.number),season:e.season||season});}}/>
   :<div className="watch-idle mv-player watch-player-idle" style={profile.cover?{'--watch-poster':`url("${profile.cover.replace(/["\\]/g,'')}")`}:undefined}>
    {idleBusy?<div className="watch-skeleton" role="status"><span/>Подбираем озвучки, качества и серии…</div>:<button className="watch-play" disabled={!idleCurrent||!idleVariant} onClick={()=>browsingCatalog?startCatalogPlayback(idleCurrent.number):startPlayback()}><span aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M8 4v16l13-8z"/></svg></span>{idleCurrent?'Смотреть · серия '+idleCurrent.number:'Выбери озвучку'}</button>}
    <button ref={sourceButton} type="button" className="watch-idle-settings" aria-label="Настройки просмотра" onClick={()=>setSourceSettings(v=>!v)}><Settings2 size={20}/></button>{sourceSettings&&<PlayerSettings anchor={sourceButton} initialPage="watch" onClose={()=>setSourceSettings(false)}>{{watch:configuration}}</PlayerSettings>}
   </div>}</PlaybackReveal>
  {!playing&&episodeBrowser}
  {!browsingCatalog&&error&&<div className="inline-error" role="alert">{error}<button className="text-link" onClick={()=>{failed.current.clear();setAttempt(n=>n+1);}}>Повторить</button></div>}
  {!browsingCatalog&&discovery.error&&<p className="fine">{discovery.error}<button className="text-link" onClick={discovery.retry}>Повторить поиск</button></p>}
  {!!saved.current.usage&&<p className="watch-personal-note">«Твой выбор» — история просмотров на этом устройстве.</p>}
 </div>;
}
