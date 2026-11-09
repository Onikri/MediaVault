// Saving a Collaps episode (to the device or to Google Drive) with the usual
// server remux. Collaps' CDN refuses data-centre addresses (HTTP 410), so the
// viewer's browser downloads the published HLS segments itself and uploads
// them to MediaVault's server; the server checks them, remuxes one MP4 with
// ffmpeg and then saves it exactly like any other export or Drive import.
import {collapsMaster,collapsRequest,collapsSelection} from './collaps-direct.js';

export const isCollaps=url=>!!collapsSelection(url);

function attributes(line){
 const value={},pattern=/([A-Z0-9-]+)=("[^"]*"|[^,]*)/g;let match;
 while((match=pattern.exec(line.slice(line.indexOf(':')+1))))value[match[1]]=match[2].replace(/^"|"$/g,'');
 return value;
}

// One video variant (≤ the chosen height) plus the chosen dub's audio playlist.
export function collapsTracks(raw,base,{quality='best',audio=null}={}){
 const lines=raw.split(/\r?\n/).map(line=>line.trim());
 if(!lines[0]?.startsWith('#EXTM3U'))throw Error('Collaps не отдал плейлист HLS.');
 const variants=[],media=[];
 lines.forEach((line,index)=>{
  if(line.startsWith('#EXT-X-STREAM-INF')){
   const info=attributes(line),uri=lines.slice(index+1).find(next=>next&&!next.startsWith('#'));
   if(uri)variants.push({uri,height:Number(/\d+x(\d+)/.exec(info.RESOLUTION||'')?.[1])||0,bandwidth:Number(info.BANDWIDTH)||0,audio:info.AUDIO||''});
  }else if(line.startsWith('#EXT-X-MEDIA')&&line.includes('TYPE=AUDIO'))media.push(attributes(line));
 });
 if(!variants.length)return {video:base,audio:null,height:null};
 const limit=quality==='best'?Infinity:Number(quality),allowed=variants.filter(v=>!v.height||v.height<=limit);
 if(!allowed.length)throw Error('В этом потоке нет качества в выбранных пределах.');
 const pick=allowed.sort((a,b)=>b.height-a.height||b.bandwidth-a.bandwidth)[0];
 // Dub indexes count distinct names in playlist order, as preferAudio does for playback.
 const names=[...new Set(media.map(m=>m.NAME).filter(name=>name!=null))],wanted=audio!=null?names[audio]:null;
 const group=media.filter(m=>m.URI&&(!pick.audio||m['GROUP-ID']===pick.audio));
 const rendition=group.find(m=>wanted!=null&&m.NAME===wanted)||group.find(m=>m.DEFAULT==='YES')||group[0];
 return {video:new URL(pick.uri,base).href,audio:rendition?new URL(rendition.URI,base).href:null,height:pick.height||null};
}

const pause=(ms,signal)=>new Promise((resolve,reject)=>{const stop=()=>{clearTimeout(timer);reject(signal.reason);};const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},ms);signal?.addEventListener('abort',stop,{once:true});});
const megabytes=bytes=>(bytes/1048576).toFixed(bytes<10485760?1:0).replace('.',',')+' МБ';

async function segment(request,url,signal){
 for(let attempt=0;;attempt++){
  signal?.throwIfAborted();
  try{
   const response=await request(url);
   if(response.ok)return await response.arrayBuffer();
   if(response.status===403||response.status===404||response.status===410)throw Object.assign(Error('Collaps перестал отдавать серию (HTTP '+response.status+'). Открой её заново и повтори.'),{final:true});
   throw Error('Collaps ответил HTTP '+response.status+'.');
  }catch(error){
   if(error.final||error.name==='AbortError'||signal?.aborted||attempt>=3)throw error;
   await pause(800*2**attempt,signal);
  }
 }
}

// Browser → server: returns the finished export snapshot (state "done").
export async function stageCollaps(service,url,{quality='best',name='',signal,onProgress=()=>{},fetcher=fetch,workers=4}={}){
 if(Number(service.session?.serverVersion)<63)throw Error('Для сохранения Collaps обнови сервер до версии 63.');
 onProgress('Открываем серию в Collaps…');
 const {selection,raw,base}=await collapsMaster(url,{signal,fetcher}),request=collapsRequest(fetcher,signal);
 const tracks=collapsTracks(raw,base,{quality,audio:selection.audio});
 const read=async address=>{const response=await request(address);if(!response.ok)throw Error('Collaps не отдал плейлист серии (HTTP '+response.status+').');return {url:response.url||address,text:await response.text()};};
 const stream={video:await read(tracks.video),...(tracks.audio?{audio:await read(tracks.audio)}:{})};
 let job=await service.request('/online/exports',{method:'POST',body:{url,kind:'video',quality:String(quality),stream,name:String(name||'').slice(0,120)},signal});
 try{
  const resources=job.resources||[];let next=0,done=0,bytes=0;
  const worker=async()=>{
   while(next<resources.length){
    const index=next++,data=await segment(request,resources[index],signal);
    await service.request('/online/exports/'+job.id+'/segments/'+index,{method:'PUT',body:data,signal:AbortSignal.any([signal||new AbortController().signal,AbortSignal.timeout(180000)])});
    done++;bytes+=data.byteLength;
    onProgress('Браузер передаёт серию серверу · '+done+' / '+resources.length+' · '+megabytes(bytes));
   }
  };
  await Promise.all(Array.from({length:Math.max(1,Math.min(workers,resources.length))},worker));
  job=await service.request('/online/exports/'+job.id+'/start',{method:'POST',signal});
  while(['queued','running'].includes(job.state)){
   onProgress(job.state==='queued'?'Серия в очереди на сборку…':'Сервер собирает MP4 без перекодирования…');
   await pause(1000,signal);
   job=await service.request('/online/exports/'+job.id,{signal});
  }
  if(job.state!=='done')throw Error(job.error||'Сервер не собрал серию.');
  return job;
 }catch(error){
  if(job?.id&&['staging','queued','running'].includes(job.state))service.request('/online/exports/'+job.id,{method:'DELETE'}).catch(()=>{});
  throw error;
 }
}

export function downloadExport(service,job){
 const url=new URL(job.downloadUrl,service.server);
 if(url.origin!==new URL(service.server).origin||!url.pathname.startsWith('/online/exports/file/'))throw Error('Сервер вернул некорректную ссылку сохранения.');
 const anchor=document.createElement('a');anchor.href=url.href;anchor.download=job.filename||'';anchor.rel='noreferrer';document.body.append(anchor);anchor.click();anchor.remove();
 return {url:url.href,name:job.filename};
}

// "На устройство": one file per selected episode.
export async function saveCollapsLocally({service,entries,quality='best',name='',signal,onProgress=()=>{}}){
 const files=[];
 for(const [index,entry] of entries.entries()){
  const label=entries.length>1?'Серия '+(index+1)+' / '+entries.length+' · ':'';
  const job=await stageCollaps(service,entry.url,{quality,signal,name:[name,entry.number!=null&&entries.length>1?'серия '+entry.number:''].filter(Boolean).join(' · '),onProgress:text=>onProgress(label+text)});
  files.push(downloadExport(service,job));
 }
 return files;
}

// "На Google Диск": each episode becomes a normal Drive import job that takes
// the server-assembled file (encryption, previews, catalogue entry as usual).
// The next episode is staged only after the server picked up the previous one,
// so the VM never holds more than one browser-delivered episode.
export async function saveCollapsToDrive({service,job,entries,signal,onProgress=()=>{},onSubmitted=()=>{}}){
 for(const [index,entry] of entries.entries()){
  const label='Серия '+(entry.number??index+1)+(entries.length>1?' ('+(index+1)+' / '+entries.length+')':'')+' · ';
  const staged=await stageCollaps(service,entry.url,{quality:job.quality,signal,onProgress:text=>onProgress(label+text)});
  const task=await service.submit({...job,episodes:String(entry.number),entries:[{...entry,export:staged.id}]});
  onSubmitted();
  for(let waited=0;;waited++){
   const value=await service.request('/online/exports/'+staged.id,{signal}).catch(error=>error.status===404?{state:'taken'}:Promise.reject(error));
   if(value.state==='taken'||value.state==='cancelled')break;
   // Already in Drive (skipped) or the task stopped: release the file on the server.
   const status=task?.id?(await service.request('/jobs/'+task.id,{signal}).catch(()=>({})))?.status:'';
   if(['completed','failed','cancelled'].includes(status)){service.request('/online/exports/'+staged.id,{method:'DELETE'}).catch(()=>{});break;}
   if(waited>=1800)throw Error('Сервер импорта долго не забирает серию. Она останется в задании; следующие серии сохрани позже.');
   onProgress(label+'передано в импорт на Google Диск, ждём очередь…');
   await pause(2000,signal);
  }
 }
}
