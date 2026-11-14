// Imported music library: playlists copied from YouTube (Music) or Spotify into
// this profile on this device, so they stay after the provider's token expires.
import {musicProviderRequest} from './music-connectors.js';
import {historyScope} from './history-scope.js';

const KEY='mv_music_library_v1:';
const listeners=new Set();
export const subscribeMusicLibrary=fn=>{listeners.add(fn);addEventListener('mediavault-history-scope',fn);return()=>{listeners.delete(fn);removeEventListener('mediavault-history-scope',fn);};};
export function importedPlaylists(){try{const value=JSON.parse(localStorage.getItem(KEY+historyScope())||'[]');return Array.isArray(value)?value:[];}catch{return [];}}
function store(value){try{localStorage.setItem(KEY+historyScope(),JSON.stringify(value));}catch{throw Error('В памяти браузера не хватило места для плейлистов.');}listeners.forEach(fn=>fn());}
export function forgetImportedPlaylist(id){store(importedPlaylists().filter(p=>p.id!==id));}

async function pages(provider,first,pick,limit){
 const rows=[];let path=first;
 while(path&&rows.length<limit){
  const data=await musicProviderRequest(provider,path);rows.push(...pick(data));
  if(provider==='spotify')path=data.next?data.next.replace('https://api.spotify.com/v1/',''):'';
  else path=data.nextPageToken?first.replace(/&pageToken=[^&]*/,'')+'&pageToken='+encodeURIComponent(data.nextPageToken):'';
 }
 return rows.slice(0,limit);
}
const youtubeTrack=item=>{const s=item.snippet,video=s?.resourceId?.videoId;if(!video||/^(Deleted|Private) video$/i.test(s.title||''))return null;return {id:'youtube:'+video,title:s.title,artists:s.videoOwnerChannelTitle?[s.videoOwnerChannelTitle.replace(/ - Topic$/,'')]:[],youtubeId:video,source:'youtube',cover:s.thumbnails?.medium?.url||s.thumbnails?.default?.url||''};};
const spotifyTrack=item=>{const t=item.item||item.track;return t?.uri&&t.type!=='episode'?{id:t.uri,title:t.name,artists:(t.artists||[]).map(a=>a.name),source:'spotify',spotifyUri:t.uri,cover:t.album?.images?.[1]?.url||t.album?.images?.[0]?.url||''}:null;};

// Every playlist with its songs (up to 500 each); YouTube also gets the
// account's liked videos, which is where YouTube Music keeps liked songs.
export async function importMusicLibrary(provider,onProgress=()=>{}){
 const lists=await pages(provider,provider==='spotify'?'me/playlists?limit=50':'playlists?part=snippet,contentDetails&mine=true&maxResults=50',data=>(data.items||[]).map(v=>({id:v.id,name:v.name||v.snippet?.title||'Плейлист',cover:v.images?.[0]?.url||v.snippet?.thumbnails?.medium?.url||''})),200);
 if(provider==='youtube')lists.unshift({id:'LL',name:'Понравившиеся',cover:''});
 const done=[];
 for(const [index,list] of lists.entries()){
  onProgress(index+1,lists.length,list.name);
  try{
   const tracks=await pages(provider,provider==='spotify'?'playlists/'+encodeURIComponent(list.id)+'/items?limit=100':'playlistItems?part=snippet&maxResults=50&playlistId='+encodeURIComponent(list.id),data=>(data.items||[]).map(provider==='spotify'?spotifyTrack:youtubeTrack).filter(Boolean),500);
   if(tracks.length)done.push({id:provider+':'+list.id,provider,name:list.name,cover:list.cover||tracks[0]?.cover||'',tracks,importedAt:Date.now()});
  }catch{/* a private or removed playlist is skipped */}
 }
 const keep=importedPlaylists().filter(p=>p.provider!==provider);
 store([...done,...keep]);
 return done.length;
}
