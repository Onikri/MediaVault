// Stable account/title identities; expiring source URLs never enter storage.
export const watchKey=(user,title)=>'mv_watch_v1:'+encodeURIComponent(user||'anonymous')+':'+encodeURIComponent(title);
export function readWatch(user,title,storage=globalThis.localStorage){try{return JSON.parse(storage.getItem(watchKey(user,title))||'{}')||{};}catch{return {};}}
export function saveWatch(user,title,change,storage=globalThis.localStorage){try{const value={...readWatch(user,title,storage),...change,updatedAt:Date.now()};storage.setItem(watchKey(user,title),JSON.stringify(value));return value;}catch{return change;}}
export function onlineEpisodeId(identity,season,episode){return 'online:'+identity+':s'+(season||1)+':e'+episode;}
export function orderedVoices(voices,saved={}){
 return [...voices].filter(v=>v.language!=='en'&&v.language!=='uk').sort((a,b)=>
  Number(!!(b.id===saved.voiceId||b.aliases?.includes(saved.voiceId)))-Number(!!(a.id===saved.voiceId||a.aliases?.includes(saved.voiceId)))||(saved.usage?.[b.id]||0)-(saved.usage?.[a.id]||0)||
  Number(a.kind==='subtitles')-Number(b.kind==='subtitles')||a.name.localeCompare(b.name,'ru'));
}
export function variantsFor(voice,episode,failed=new Set()){
 const rank=v=>{const known=v.episodes?.length,found=v.episodes?.some(e=>Number(e.number)===Number(episode));return (known&&!found?10:0)+(v.player==='Kodik'?0:v.player==='Alloha'?2:1);};
 return [...(voice?.variants||[])].filter(v=>!failed.has(v.id)).sort((a,b)=>rank(a)-rank(b));
}
