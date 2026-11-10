// Saving the subtitle track picked in the player. A track that already is a
// file (a server VTT, the viewer's own SRT/VTT/ASS) is saved as it is; a
// track that exists only inside the stream (HLS segments, cues added by the
// browser) is assembled into one WebVTT file.

// 'vtt' | 'srt' | 'ass' | '' for text that is not a subtitle file.
export function subtitleFormat(text){
 const value=String(text||'').replace(/^\uFEFF/,'').trimStart();
 if(/^WEBVTT(?:[ \t]|\r?\n|$)/.test(value))return 'vtt';
 if(/^\[Script Info\]/i.test(value)||/^\[V4\+? Styles\]/im.test(value)&&/^\[Events\]/im.test(value))return 'ass';
 if(/\d{1,2}:\d\d:\d\d[,.]\d{1,3}\s*-->\s*\d{1,2}:\d\d:\d\d[,.]\d{1,3}/.test(value))return 'srt';
 return '';
}

const pad=(n,size=2)=>String(n).padStart(size,'0');
export function vttTime(seconds){
 const ms=Math.max(0,Math.round(Number(seconds||0)*1000));
 return pad(Math.floor(ms/3600000))+':'+pad(Math.floor(ms/60000)%60)+':'+pad(Math.floor(ms/1000)%60)+'.'+pad(ms%1000,3);
}
// "01:02:03.456", "02:03.456", "01:02:03,456" → seconds.
export function parseTime(value){
 const match=/^(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})$/.exec(String(value).trim());
 if(!match)return NaN;
 return Number(match[1]||0)*3600+Number(match[2])*60+Number(match[3])+Number(match[4].padEnd(3,'0'))/1000;
}

// WebVTT text → cues {start,end,text,settings}. HLS segments carry
// X-TIMESTAMP-MAP=MPEGTS:…,LOCAL:…; that mapping is returned as well.
export function parseVtt(text){
 const lines=String(text||'').replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').split('\n');
 const cues=[];let map=null;
 for(const line of lines.slice(0,8)){
  const header=/X-TIMESTAMP-MAP=(.*)$/.exec(line);if(!header)continue;
  const mpegts=/MPEGTS:(\d+)/.exec(header[1]),local=/LOCAL:([\d:.]+)/.exec(header[1]);
  map={mpegts:mpegts?Number(mpegts[1]):0,local:local?parseTime(local[1]):0};
 }
 for(let i=0;i<lines.length;i++){
  const timing=/^\s*([\d:.,]+)\s+-->\s+([\d:.,]+)(.*)$/.exec(lines[i]);if(!timing)continue;
  const start=parseTime(timing[1]),end=parseTime(timing[2]);if(!Number.isFinite(start)||!Number.isFinite(end))continue;
  const body=[];for(i++;i<lines.length&&lines[i].trim();i++)body.push(lines[i]);
  cues.push({start,end,text:body.join('\n'),settings:timing[3].trim()});
 }
 return {cues,map};
}

// Same cue from two overlapping segments is kept once; order is by time.
export function mergeCues(cues){
 const seen=new Set(),out=[];
 for(const cue of [...cues].sort((a,b)=>a.start-b.start||a.end-b.end)){
  const key=Math.round(cue.start*1000)+'|'+Math.round(cue.end*1000)+'|'+cue.text;
  if(seen.has(key)||!String(cue.text).trim())continue;seen.add(key);out.push(cue);
 }
 return out;
}

export function cuesToVtt(cues){
 return 'WEBVTT\n\n'+mergeCues(cues).map(c=>vttTime(c.start)+' --> '+vttTime(c.end)+(c.settings?' '+c.settings:'')+'\n'+String(c.text).replace(/\n{2,}/g,'\n')).join('\n\n')+'\n';
}

// Media playlist → its segment URLs (resolved against the playlist).
export function playlistSegments(text,base){
 return String(text||'').split(/\r?\n/).map(l=>l.trim()).filter(l=>l&&!l.startsWith('#')).map(l=>new URL(l,base).href);
}

// Every segment of an HLS subtitle playlist joined into one WebVTT file.
// Segment times are moved onto the video timeline the way players do it:
// MPEGTS of the first segment is the start of the stream.
export async function hlsSubtitleText(playlistUrl,{fetch:get=globalThis.fetch,signal,onProgress}={}){
 const response=await get(playlistUrl,{signal});
 if(!response.ok)throw Error('Источник не отдал список субтитров (HTTP '+response.status+').');
 const playlist=await response.text();
 // Some sources publish one VTT file as the "playlist".
 if(subtitleFormat(playlist)==='vtt')return {text:playlist.replace(/^\uFEFF/,''),format:'vtt'};
 const segments=playlistSegments(playlist,response.url||playlistUrl);
 if(!segments.length)throw Error('В списке субтитров нет файлов.');
 const cues=[];let base=null;
 for(let i=0;i<segments.length;i++){
  const part=await get(segments[i],{signal});
  if(!part.ok)throw Error('Источник не отдал часть субтитров (HTTP '+part.status+').');
  const parsed=parseVtt(await part.text());
  let shift=0;
  if(parsed.map){base??=parsed.map.mpegts;shift=(parsed.map.mpegts-base)/90000-parsed.map.local;}
  for(const cue of parsed.cues)cues.push({...cue,start:cue.start+shift,end:cue.end+shift});
  onProgress?.(i+1,segments.length);
 }
 return {text:cuesToVtt(cues),format:'vtt'};
}

// Cues the browser holds for a TextTrack (a track added by the stream, or a
// file the page has no URL for). Cues of a disabled track load only while it
// is hidden, so the mode is switched for a moment and restored.
export async function textTrackText(track,{wait=ms=>new Promise(r=>setTimeout(r,ms))}={}){
 const mode=track.mode;
 try{
  if(mode==='disabled'){track.mode='hidden';for(let i=0;i<20&&!track.cues?.length;i++)await wait(50);}
  const cues=Array.from(track.cues||[]).map(c=>({start:c.startTime,end:c.endTime,text:c.text??''}));
  if(!cues.length)throw Error('У этой дорожки пока нет загруженных субтитров.');
  return {text:cuesToVtt(cues),format:'vtt'};
 }finally{if(track.mode!==mode)track.mode=mode;}
}

// A file the page knows the URL of (server VTT, <track src>).
export async function fileText(url,{fetch:get=globalThis.fetch,signal}={}){
 const response=await get(url,{signal});
 if(!response.ok)throw Error('Источник не отдал субтитры (HTTP '+response.status+').');
 const text=(await response.text()).replace(/^\uFEFF/,'');
 const format=subtitleFormat(text);
 if(!format)throw Error('Источник отдал не субтитры.');
 return {text,format};
}

const MIME={vtt:'text/vtt',srt:'application/x-subrip',ass:'text/x-ssa'};
export const subtitleMime=format=>(MIME[format]||'text/plain')+';charset=utf-8';

// "Title · Episode 3 · Русские.vtt", safe on Windows, macOS and phones.
export function subtitleFileName(parts,format){
 const name=parts.map(p=>String(p||'').trim()).filter(Boolean).join(' · ').replace(/[\\/:*?"<>|\u0000-\u001f]+/g,' ').replace(/\s+/g,' ').trim().slice(0,150)||'Субтитры';
 return name.replace(/[. ]+$/,'')+'.'+(format||'vtt');
}

// value: the menu value of the track ('hls:N', 'native:N', 'local').
// Returns {text, format}; the caller saves it.
export async function readSubtitleTrack(value,{video,hlsUrl,localFile,fetch:get=globalThis.fetch,signal}={}){
 if(value==='local'&&localFile?.text){
  const format=subtitleFormat(localFile.text)||(/\.ass$|\.ssa$/i.test(localFile.name)?'ass':/\.srt$/i.test(localFile.name)?'srt':'vtt');
  return {text:localFile.text.replace(/^\uFEFF/,''),format};
 }
 if(value.startsWith('hls:')){
  const url=hlsUrl?.(Number(value.slice(4)));
  if(!url)throw Error('Поток не сообщил адрес этих субтитров.');
  return hlsSubtitleText(url,{fetch:get,signal});
 }
 const tracks=Array.from(video?.textTracks||[]);
 const track=value==='local'?tracks.find(t=>t.label==='Загруженные субтитры'):tracks[Number(value.slice(7))];
 if(!track)throw Error('Дорожка субтитров больше недоступна.');
 const element=Array.from(video.querySelectorAll?.('track')||[]).find(t=>t.track===track);
 if(element?.src){
  try{return await fileText(element.src,{fetch:get,signal});}
  catch(error){if(signal?.aborted)throw error;}
 }
 return textTrackText(track);
}
