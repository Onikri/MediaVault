const key=user=>'mediavault_music_v1:'+encodeURIComponent(user||'anonymous');
export function tracks(user,storage=globalThis.localStorage){try{const a=JSON.parse(storage.getItem(key(user))||'[]');return Array.isArray(a)?a.filter(v=>v&&typeof v.id==='string'&&typeof v.title==='string').slice(0,500):[];}catch{return [];}}
export function toggleTrack(user,track,storage=globalThis.localStorage){let all=tracks(user,storage);all=all.some(t=>t.id===track.id)?all.filter(t=>t.id!==track.id):[{...track,savedAt:Date.now()},...all].slice(0,500);try{storage.setItem(key(user),JSON.stringify(all));globalThis.dispatchEvent?.(new Event('mediavault-music'));}catch{}return all;}
export const spotifySearch=track=>'https://open.spotify.com/search/'+encodeURIComponent([track.title,...track.artists||[]].join(' '));
export const youtubeSearch=track=>'https://music.youtube.com/search?q='+encodeURIComponent([track.title,...track.artists||[]].join(' '));
