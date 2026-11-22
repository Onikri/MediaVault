// Collaps in MediaVault's own player, straight from the viewer's browser.
//
// Measured 2026-11-09: Collaps' CDN answers HTTP 410 to every media segment
// requested from the Oracle VM (a data-centre address) and binds stream links
// to the address that opened the embed page, so a server relay cannot play it.
// From a home connection the same embed plays, and both the embed page and the
// stream allow this site's origin (CORS). The browser therefore opens the
// public embed itself, takes the published HLS and hands it to hls.js. No
// server traffic, no address substitution: the viewer's own connection plays.
const HOSTS=/^api\.(?:nextembed\.ws|delivembd\.ws|namy\.ws|bhcesh\.me|embf\.net)$/i;

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

function collapsEpisode(text,{season=null,episode=null}={}){
 const seasons=jsValue(text,'seasons','[');
 if(Array.isArray(seasons)&&seasons.length){
  for(const row of seasons){
   if(!row||row.blocked||season!=null&&numberOf(row.season)!==season)continue;
   for(const item of row.episodes||[])if(String(item?.hls||'').startsWith('https://')&&(episode==null||numberOf(item.episode)===episode))return item;
  }
  return null;
 }
 const hls=/\bhls\s*:\s*"(https:\/\/[^"]+)"/.exec(text)?.[1];
 return hls?{hls,cc:jsValue(text,'cc','[')}:null;
}

export function collapsStream(text,selection){
 return collapsEpisode(text,selection)?.hls||null;
}

function captionsOf(episode){
 if(!Array.isArray(episode.cc))return [];
 return episode.cc.slice(0,32).flatMap((track,index)=>{
  const name=typeof track?.name==='string'?track.name.trim().replace(/\s+-\s+\d+$/,'').slice(0,100):'';
  let url;
  try{url=new URL(track?.url);}catch{return [];}
  if(!name||url.protocol!=='https:'||url.username||url.password||!url.pathname.toLowerCase().endsWith('.vtt'))return [];
  const language=/^(?:eng|english|англ)/i.test(name)?'en':/^(?:рус|rus|russian)/i.test(name)?'ru':/^(?:укр|ukr|ukrainian)/i.test(name)?'uk':'und';
  return [{id:'collaps-cc-'+index,name,language,url:url.href}];
 });
}

// The embed appends its page token to the stream address, as its own player does.
export function pageToken(text){return /var\s+lok\s*=\s*1\s*,\s*\w+\s*=\s*"(\w{4,64})"/.exec(text)?.[1]||'';}

// Unique audio rendition names in manifest order: the order Collaps numbers its dubs.
export function audioNames(manifest){
 const names=[];
 for(const line of String(manifest||'').split(/\r?\n/))if(line.startsWith('#EXT-X-MEDIA')&&line.includes('TYPE=AUDIO')){const name=/NAME="([^"]*)"/.exec(line)?.[1];if(name!=null&&!names.includes(name))names.push(name);}
 return names;
}

// One HLS carries every dub: the chosen one becomes the default audio.
export function preferAudio(manifest,index){
 if(index==null||!manifest.includes('#EXT-X-MEDIA'))return manifest;
 const names=audioNames(manifest);
 if(!(index>=0&&index<names.length))return manifest;
 return manifest.split(/\r?\n/).map(line=>{
  if(!(line.startsWith('#EXT-X-MEDIA')&&line.includes('TYPE=AUDIO')))return line;
  const yes=/NAME="([^"]*)"/.exec(line)?.[1]===names[index]?'YES':'NO';
  return line.replace(/DEFAULT=(YES|NO)/,'DEFAULT='+yes).replace(/AUTOSELECT=(YES|NO)/,'AUTOSELECT='+yes);
 }).join('\n');
}

const variantHeight=line=>Number(/RESOLUTION=\d+x(\d+)/.exec(line)?.[1]);
const variantGroup=line=>/\bAUDIO="([^"]+)"/.exec(line)?.[1]||'';
const audioGroup=line=>/\bGROUP-ID="([^"]+)"/.exec(line)?.[1]||'';
const isAudioRendition=line=>line.startsWith('#EXT-X-MEDIA:')&&line.includes('TYPE=AUDIO');

function videoRenditions(manifest,base,selectedName){
 const lines=manifest.split(/\r?\n/);
 const matchingGroups=new Set(lines.filter(line=>isAudioRendition(line)&&/NAME="([^"]*)"/.exec(line)?.[1]===selectedName).map(audioGroup));
 return lines.flatMap((line,index)=>{
  if(!line.startsWith('#EXT-X-STREAM-INF:'))return [];
  const height=variantHeight(line),group=variantGroup(line),uri=lines[index+1]?.trim();
  if(!height||!group||!uri||uri.startsWith('#')||(selectedName&&!matchingGroups.has(group)))return [];
  return [{height,group,host:new URL(uri,base).host}];
 });
}

// Collaps publishes parallel video variants with separate audio groups. A
// different CDN can carry the same resolution and the same chosen dub.
export function nextCollapsRendition(media,height,group,tried){
 if(!tried&&group){
  const variants=media.renditions.filter(row=>row.height===height);
  const playing=variants.find(row=>row.group===group);
  const mirror=playing&&variants.find(row=>row.group!==group&&row.host!==playing.host);
  if(mirror)return {quality:String(height),group:mirror.group};
 }
 if(!tried||tried.group){
  const lower=media.qualities.find(quality=>quality<height);
  if(lower)return {quality:String(lower),group:''};
 }
 return null;
}

// Absolute addresses (the master becomes a blob), optional height cap and
// audio group for a retry on a specific provider-published variant.
export function directMaster(manifest,base,maxHeight=null,group=''){
 if(!manifest.trimStart().startsWith('#EXTM3U'))throw Error('Collaps не отдал плейлист HLS.');
 if(/#EXT-X-(?:SESSION-)?KEY:(?![^\n]*METHOD=NONE)/.test(manifest))throw Error('Зашифрованные потоки Collaps не поддерживаются.');
 let lines=manifest.split(/\r?\n/);
 if(maxHeight||group){
  const keep=[];let dropped=0,kept=0;
  for(let i=0;i<lines.length;i++){
   if(group&&isAudioRendition(lines[i])&&audioGroup(lines[i])!==group)continue;
   if(lines[i].startsWith('#EXT-X-STREAM-INF:')){
    if((maxHeight&&variantHeight(lines[i])>maxHeight)||(group&&variantGroup(lines[i])!==group)){dropped++;i++;continue;}
    kept++;
   }
   keep.push(lines[i]);
  }
  if(kept)lines=keep;else if(dropped)throw Error(group?'Резервный поток Collaps больше недоступен.':'В этом потоке нет качества в выбранных пределах.');
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
 const text=await page.text(),episode=collapsEpisode(text,selection),stream=episode?.hls;
 if(!stream)throw Error('Collaps не опубликовал эту серию.');
 const token=pageToken(text),address=token&&!stream.includes('&'+token)?stream+'&'+token:stream;
 const master=await request(address);
 if(!master.ok)throw Object.assign(Error('Collaps не отдал поток (HTTP '+master.status+').'),{status:master.status});
 return {selection,raw:await master.text(),base:master.url||address,subtitles:captionsOf(episode)};
}

export async function prepareCollaps(value,{quality='best',group='',signal,fetcher=fetch}={}){
 const {selection,raw,base,subtitles}=await collapsMaster(value,{signal,fetcher}),maxHeight=quality==='best'?null:Number(quality);
 const names=audioNames(raw),renditions=videoRenditions(raw,base,names[selection.audio]);
 if(group&&!renditions.some(row=>row.group===group))throw Error('Резервный поток Collaps больше недоступен с выбранной озвучкой.');
 const playlist=directMaster(preferAudio(raw,selection.audio),base,maxHeight,group);
 const qualities=[...new Set([...raw.matchAll(/RESOLUTION=\d+x(\d+)/g)].map(m=>Number(m[1])))].sort((a,b)=>b-a);
 const url=URL.createObjectURL(new Blob([playlist],{type:'application/vnd.apple.mpegurl'}));
 return {id:'direct:'+crypto.randomUUID(),kind:'video',url,type:'hls',direct:true,qualities,renditions,
  audioNames:names,subtitles,sourceIntervals:[],guardSlate:true};
}

// Shared by the viewer, the separate audio track and episode previews.
export function prepareOnline(service,body,{signal}={}){
 if(body.kind==='video'&&collapsSelection(body.url))return prepareCollaps(body.url,{quality:body.quality||'best',group:body.collapsGroup,signal});
 return service.request('/online/prepare',{method:'POST',body,signal});
}
export function releaseOnline(service,data){
 if(!data)return;
 if(data.direct){URL.revokeObjectURL(data.url);return;}
 service.request('/online/'+data.id,{method:'DELETE',keepalive:true}).catch(()=>{});
}
export const onlineMediaUrl=(service,data,url=data.url)=>data.direct?url:service.server.replace(/\/$/,'')+url;
