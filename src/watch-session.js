// Stable account/title identities; expiring source URLs never enter storage.
export const watchKey=(user,title)=>'mv_watch_v1:'+encodeURIComponent(user||'anonymous')+':'+encodeURIComponent(title);
export function readWatch(user,title,storage=globalThis.localStorage){try{return JSON.parse(storage.getItem(watchKey(user,title))||'{}')||{};}catch{return {};}}
export function saveWatch(user,title,change,storage=globalThis.localStorage){try{const value={...readWatch(user,title,storage),...change,updatedAt:Date.now()};storage.setItem(watchKey(user,title),JSON.stringify(value));return value;}catch{return change;}}
export function onlineEpisodeId(identity,season,episode){return 'online:'+identity+':s'+(season||1)+':e'+episode;}
export function orderedVoices(voices,saved={}){
 return [...voices].filter(v=>v.language!=='en'&&v.language!=='uk'&&!/^(?:неизвестн|unknown|название перевода не указано|озвучка не указана|(?:серия|episode)\s*\d)/i.test(v.name)).sort((a,b)=>
  Number(!!(b.id===saved.voiceId||b.aliases?.includes(saved.voiceId)))-Number(!!(a.id===saved.voiceId||a.aliases?.includes(saved.voiceId)))||(saved.usage?.[b.id]||0)-(saved.usage?.[a.id]||0)||
  Number(a.kind==='subtitles')-Number(b.kind==='subtitles')||a.name.localeCompare(b.name,'ru'));
}
export function variantsFor(voice,episode,failed=new Set()){
 const rank=v=>{const known=v.episodes?.length,found=v.episodes?.some(e=>Number(e.number)===Number(episode));return (known&&!found?10:0)+(v.player==='Kodik'?0:v.player==='Alloha'?2:1);};
 return [...(voice?.variants||[])].filter(v=>!failed.has(v.id)).sort((a,b)=>rank(a)-rank(b));
}

// A catalogue sequel can be season 1 at one publisher and season 2 in a
// bundled player. Scope only bundled sources; keep standalone numbering intact.
export function voicesForCatalogue(voices,sources,season){
 if(!season)return voices;
 const bundled=new Set((sources||[]).filter(source=>source.seasons?.length>1).map(source=>source.url));
 for(const voice of voices)for(const variant of voice.variants){
  if(new Set(variant.episodes?.map(e=>Number(e.season||1))).size>1)bundled.add(variant.sourceUrl);
 }
 return voices.map(voice=>({...voice,variants:voice.variants.flatMap(variant=>{
  if(!bundled.has(variant.sourceUrl)||!variant.episodes?.length)return [variant];
  const episodes=variant.episodes.filter(e=>Number(e.season||1)===Number(season));
  return episodes.length?[{...variant,episodes,url:episodes[0].url}]:[];
 })})).filter(voice=>voice.variants.length);
}

// Public source identity (not a media URL) isolates thumbnails from different mirrors.
export function episodePreviewKey(identity,season,episode,source,user){return 'v2:'+onlineEpisodeId(identity,season,episode)+':source:'+encodeURIComponent(source||'default')+':'+encodeURIComponent(user||'anonymous');}

export function isShortEpisodeClip(duration,minimum){return minimum>0&&Number.isFinite(duration)&&duration>0&&duration<minimum;}

export function minimumEpisodeDuration(profile){
 const minutes=Number(profile?.duration);
 return minutes>=5?Math.min(60,minutes*15):0;
}
