import {useEffect,useMemo,useState} from 'react';
import {fetchCatalog} from './catalog.js';
import useSourceDiscovery from './use-source-discovery.js';
import {useContentLanguage,preferredVoiceLanguage} from './content-language.js';
import {orderedVoices,variantsFor,readWatch,voicesForCatalogue} from './watch-session.js';
import {catalogueSeasonHint} from './franchise-seasons.js';

export function profileForSeason(item){return {title:item?.title,sourceId:item?.ids?.mal,source:'shikimori',cover:item?.cover,description:item?.description,year:item?.year,format:item?.format,status:item?.status,genres:item?.genres||[],themes:item?.tags||[],characters:[],staff:[],related:[],screenshots:[],releases:item?.releases||[]};}
const studio=value=>String(value||'').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
export async function inspectSeasonSource(service,candidate,number,signal){
 async function load(season,url){let data,continuation,previous=-1,stalled=0;
  do{data=await service.request('/sources/inspect',{method:'POST',body:{url:url||candidate.sourceUrl,...(!url?{dub_url:candidate.url}:{}),kind:'anime',...(season?{season}:{}),...(continuation?{continuation}:{})},signal});signal.throwIfAborted();continuation=data.continuation;stalled=continuation&&previous===data.scannedPages?stalled+1:0;previous=data.scannedPages;if(stalled>=3)throw Error('Источник не завершил список серий.');}while(continuation);return data;
 }
 let data=await load();const offered=[...new Set((data.seasons||[]).map(s=>Number(s.number)).filter(Boolean))];
 if(offered.length>1&&!offered.includes(number))throw Error('Этот источник не предоставляет выбранный сезон.');
 const actual=(data.episodes||[]).filter(e=>e.url),numbers=[...new Set(actual.map(e=>Number(e.season)||1))];
 const selected=offered.includes(number)?number:numbers.length===1?numbers[0]:number;
 if(offered.includes(number)&&!actual.some(e=>(Number(e.season)||1)===selected))data=await load(selected,data.seasons?.find(s=>Number(s.number)===selected)?.url);
 const rows=(data.episodes||[]).filter(e=>e.url&&(Number(e.season)||1)===selected).map(e=>({...e,season:selected}));
 if(!rows.length)throw Error('У этого источника пока нет опубликованных серий сезона.');
 const unique=[...new Map(rows.map(e=>[Number(e.number),e])).values()].sort((a,b)=>Number(a.number)-Number(b.number));
 return {entries:unique,seasons:data.seasons||[],season:selected,variant:candidate};
}
export default function useSeasonSource({workId,basisItem,basisProfile,basisDiscovery,descriptor,service,userId,voiceName,enabled}){
 const basisId=String(basisItem.ids?.mal||''),isBasis=workId===basisId;
 const [loaded,setLoaded]=useState(null),[metadataError,setMetadataError]=useState(''),[row,setRow]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 useEffect(()=>{setLoaded(null);setMetadataError('');if(!workId||isBasis)return;const abort=new AbortController();fetchCatalog('shikimori',{identity:workId,kind:'anime',server:service.server,signal:abort.signal}).then(values=>{if(abort.signal.aborted)return;const found=values.find(v=>String(v.ids?.mal)===workId);if(!found)throw Error('Каталог не подтвердил выбранный сезон.');setLoaded(found);}).catch(e=>{if(!abort.signal.aborted)setMetadataError(e.message);});return()=>abort.abort();},[workId,isBasis,service.server]);
 const item=isBasis?basisItem:loaded&&String(loaded.ids?.mal)===workId?loaded:null;
 const remoteDiscovery=useSourceDiscovery(isBasis?null:item,service),discovery=isBasis?basisDiscovery:remoteDiscovery;
 const profile=useMemo(()=>isBasis?basisProfile:profileForSeason(item),[isBasis,basisProfile,item]);
 const languageFilter=useContentLanguage();
 const voices=useMemo(()=>orderedVoices(voicesForCatalogue(discovery.data?.voices||[],discovery.data?.sources,catalogueSeasonHint(item)),readWatch(userId,String(item?.ids?.mal||item?.id||'')),{filter:languageFilter,prefer:preferredVoiceLanguage(languageFilter)}),[discovery.data,item,userId,languageFilter]);
 const voice=voices.find(v=>studio(v.name)===studio(voiceName))||voices[0];
 useEffect(()=>{setRow(null);setError('');if(!enabled||!item||!voice){setBusy(false);return;}const abort=new AbortController();setBusy(true);
  (async()=>{let last;for(const candidate of variantsFor(voice,1)){try{return await inspectSeasonSource(service,candidate,descriptor?.number||1,abort.signal);}catch(e){abort.signal.throwIfAborted();last=e;}}throw last||Error('Для выбранного сезона источник пока не найден.');})().then(value=>{if(!abort.signal.aborted)setRow({...value,voiceId:voice.id,voice,workId,item,profile,discovery});}).catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
 },[enabled,workId,item?.id,voice?.id,attempt,descriptor?.number,service.server]);
 return {item,profile,discovery,voices,voice,row:row?.workId===workId?row:null,busy,error:metadataError||error,retry:()=>{setAttempt(n=>n+1);if(discovery.error)discovery.retry();},loading:!!workId&&!item||discovery.loading&&!voices.length};
}
