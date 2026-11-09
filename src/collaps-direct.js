// Collaps in MediaVault's own player, straight from the viewer's browser.
//
// Measured 2026-11-09: Collaps' CDN answers HTTP 410 to every media segment
// requested from the Oracle VM (a data-centre address) and binds stream links
// to the address that opened the embed page, so a server relay cannot play it.
// From a home connection the same embed plays, and both the embed page and the
// stream allow this site's origin (CORS). The browser therefore opens the
// public embed itself, takes the published HLS and hands it to hls.js. No
// server traffic, no address substitution: the viewer's own connection plays.
const HOSTS=/^api\.(?:nextembed\.ws|delivembd\.ws|namy\.ws|bhcesh\.me)$/i;

export function collapsSelection(value){
 try{
  const url=new URL(value);
  if(url.protocol!=='https:'||url.username||url.password||!HOSTS.test(url.hostname)||!/^\/embed\/[a-z]+\/\d{1,10}$/.test(url.pathname))return null;
  const number=key=>/^\d{1,4}$/.test(url.searchParams.get(key)||'')?Number(url.searchParams.get(key)):null;
  return {embed:url.origin+url.pathname,audio:number('mv_audio'),season:number('mv_season'),episode:number('mv_episode')};
 }catch{return null;}
}

// The JSON array/object that follows `key:` in the embed script.
function jsValue(text,key,opener){
 const match=new RegExp('\\b'+key+'\\s*:\\s*\\'+opener).exec(text);if(!match)return null;
 const closer=opener==='['?']':'}',start=match.index+match[0].length-1;let depth=0,quote=false,escape=false;
 for(let i=start;i<text.length;i++){
  const c=text[i];
  if(quote){if(escape)escape=false;else if(c==='\\')escape=true;else if(c==='"')quote=false;continue;}
  if(c==='"')quote=true;else if(c===opener)depth++;else if(c===closer&&--depth===0){try{return JSON.parse(text.slice(start,i+1));}catch{return null;}}
 }
 return null;
}
const numberOf=value=>{const m=/\d+/.exec(String(value??''));return m?Number(m[0]):null;};

export function collapsStream(text,{season=null,episode=null}={}){
 const seasons=jsValue(text,'seasons','[');
 if(Array.isArray(seasons)&&seasons.length){
  for(const row of seasons){
   if(!row||row.blocked||season!=null&&numberOf(row.season)!==season)continue;
   for(const item of row.episodes||[])if(String(item?.hls||'').startsWith('https://')&&(episode==null||numberOf(item.episode)===episode))return item.hls;
  }
  return null;
 }
 return /\bhls\s*:\s*"(https:\/\/[^"]+)"/.exec(text)?.[1]||null;
}

// The embed appends its page token to the stream address, as its own player does.
export function pageToken(text){return /var\s+lok\s*=\s*1\s*,\s*\w+\s*=\s*"(\w{4,64})"/.exec(text)?.[1]||'';}

// One HLS carries every dub: the chosen one becomes the default audio.
export function preferAudio(manifest,index){
 if(index==null||!manifest.includes('#EXT-X-MEDIA'))return manifest;
 const names=[];for(const line of manifest.split(/\r?\n/))if(line.startsWith('#EXT-X-MEDIA')&&line.includes('TYPE=AUDIO')){const n=/NAME="([^"]*)"/.exec(line)?.[1];if(n!=null&&!names.includes(n))names.push(n);}
 if(!(index>=0&&index<names.length))return manifest;
 return manifest.split(/\r?\n/).map(line=>{
  if(!(line.startsWith('#EXT-X-MEDIA')&&line.includes('TYPE=AUDIO')))return line;
  const yes=/NAME="([^"]*)"/.exec(line)?.[1]===names[index]?'YES':'NO';
  return line.replace(/DEFAULT=(YES|NO)/,'DEFAULT='+yes).replace(/AUTOSELECT=(YES|NO)/,'AUTOSELECT='+yes);
 }).join('\n');
}

// Absolute addresses (the master becomes a blob) and an optional height cap.
export function directMaster(manifest,base,maxHeight=null){
 if(!manifest.trimStart().startsWith('#EXTM3U'))throw Error('Collaps не отдал плейлист HLS.');
 if(/#EXT-X-(?:SESSION-)?KEY:(?![^\n]*METHOD=NONE)/.test(manifest))throw Error('Зашифрованные потоки Collaps не поддерживаются.');
 let lines=manifest.split(/\r?\n/);
 if(maxHeight){
  const keep=[];let dropped=0,kept=0;
  for(let i=0;i<lines.length;i++){
   const height=Number(/RESOLUTION=\d+x(\d+)/.exec(lines[i])?.[1]);
   if(lines[i].startsWith('#EXT-X-STREAM-INF')&&height>maxHeight){dropped++;i++;continue;}
   if(lines[i].startsWith('#EXT-X-STREAM-INF'))kept++;
   keep.push(lines[i]);
  }
  if(kept)lines=keep;else if(dropped)throw Error('В этом потоке нет качества в выбранных пределах.');
 }
 return lines.map(line=>line.startsWith('#')?line.replace(/URI="([^"]+)"/g,(_,uri)=>'URI="'+new URL(uri,base).href+'"'):line.trim()?new URL(line.trim(),base).href:line).join('\n')+'\n';
}

export const collapsRequest=(fetcher,signal)=>url=>fetcher(url,{signal,credentials:'omit',referrerPolicy:'strict-origin-when-cross-origin'});

// The embed page → the episode's master playlist, exactly as Collaps' own player reads it.
export async function collapsMaster(value,{signal,fetcher=fetch}={}){
 const selection=collapsSelection(value);if(!selection)throw Error('Это не плеер Collaps.');
 const request=collapsRequest(fetcher,signal);
 const page=await request(selection.embed);
 if(!page.ok)throw Object.assign(Error('Collaps не открыл плеер (HTTP '+page.status+').'),{status:page.status});
 const text=await page.text(),stream=collapsStream(text,selection);
 if(!stream)throw Error('Collaps не опубликовал эту серию.');
 const token=pageToken(text),address=token&&!stream.includes('&'+token)?stream+'&'+token:stream;
 const master=await request(address);
 if(!master.ok)throw Object.assign(Error('Collaps не отдал поток (HTTP '+master.status+').'),{status:master.status});
 return {selection,raw:await master.text(),base:master.url||address};
}

export async function prepareCollaps(value,{quality='best',signal,fetcher=fetch}={}){
 const {selection,raw,base}=await collapsMaster(value,{signal,fetcher}),maxHeight=quality==='best'?null:Number(quality);
 const playlist=directMaster(preferAudio(raw,selection.audio),base,maxHeight);
 const qualities=[...new Set([...raw.matchAll(/RESOLUTION=\d+x(\d+)/g)].map(m=>Number(m[1])))].sort((a,b)=>b-a);
 const url=URL.createObjectURL(new Blob([playlist],{type:'application/vnd.apple.mpegurl'}));
 return {id:'direct:'+crypto.randomUUID(),kind:'video',url,type:'hls',direct:true,qualities,subtitles:[],sourceIntervals:[]};
}

// Shared by the viewer, the separate audio track and episode previews.
export function prepareOnline(service,body,{signal}={}){
 if(body.kind==='video'&&collapsSelection(body.url))return prepareCollaps(body.url,{quality:body.quality||'best',signal});
 return service.request('/online/prepare',{method:'POST',body,signal});
}
export function releaseOnline(service,data){
 if(!data)return;
 if(data.direct){URL.revokeObjectURL(data.url);return;}
 service.request('/online/'+data.id,{method:'DELETE',keepalive:true}).catch(()=>{});
}
export const onlineMediaUrl=(service,data,url=data.url)=>data.direct?url:service.server.replace(/\/$/,'')+url;
