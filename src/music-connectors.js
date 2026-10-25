const b64=bytes=>btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
let spotifySession=null,youtubeSession=null;
const clientId=()=>{try{return localStorage.getItem('mediavault_spotify_client')||window.MEDIA_VAULT_CONFIG?.spotifyClientId||'';}catch{return '';}};
export function spotifyRedirect(){return new URL('spotify-callback.html',new URL(import.meta.env.BASE_URL,location.href)).href;}
export async function connectSpotify(id=clientId()){
 if(!/^[a-f\d]{32}$/i.test(id))throw Error('Нужен публичный Client ID приложения Spotify. Секрет клиента не используется.');
 const popup=window.open('about:blank','mv-spotify','popup,width=500,height=720');if(!popup)throw Error('Разреши окно входа Spotify.');
 const verifier=b64(crypto.getRandomValues(new Uint8Array(48))),state=b64(crypto.getRandomValues(new Uint8Array(24))),challenge=b64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
 try{
  localStorage.setItem('mediavault_spotify_client',id);
  const code=await new Promise((resolve,reject)=>{const finish=(error,value)=>{removeEventListener('message',handler);clearInterval(interval);clearTimeout(timeout);error?reject(error):resolve(value);};const handler=e=>{if(e.origin!==location.origin||e.source!==popup||e.data?.type!=='mediavault-spotify'||e.data.state!==state)return;if(e.data.error)finish(Error('Spotify не разрешил подключение.'));else finish(null,e.data.code);};addEventListener('message',handler);const interval=setInterval(()=>{if(popup.closed)finish(Error('Вход Spotify отменён.'));},700),timeout=setTimeout(()=>finish(Error('Время входа Spotify истекло.')),180000);popup.location='https://accounts.spotify.com/authorize?'+new URLSearchParams({response_type:'code',client_id:id,redirect_uri:spotifyRedirect(),code_challenge_method:'S256',code_challenge:challenge,state,scope:'playlist-read-private playlist-modify-private playlist-modify-public'});});
  const r=await fetch('https://accounts.spotify.com/api/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',code,client_id:id,redirect_uri:spotifyRedirect(),code_verifier:verifier})});const d=await r.json();if(!r.ok||!d.access_token)throw Error('Spotify не выдал доступ. Проверь Client ID, URI и пользователей приложения.');spotifySession={token:d.access_token,expires:Date.now()+d.expires_in*1000};return true;
 }finally{popup.close();}
}
export async function connectYouTube(){
 const id=window.MEDIA_VAULT_CONFIG?.googleClientId;
 if(!id||!window.google?.accounts?.oauth2)throw Error('Вход Google ещё не готов.');
 youtubeSession=await new Promise((resolve,reject)=>window.google.accounts.oauth2.initTokenClient({client_id:id,scope:'https://www.googleapis.com/auth/youtube',callback:d=>d.error?reject(Error('YouTube не разрешил доступ к плейлистам.')):resolve({token:d.access_token,expires:Date.now()+Number(d.expires_in||3600)*1000}),error_callback:()=>reject(Error('Подключение YouTube отменено.'))}).requestAccessToken({prompt:''}));return true;
}
function session(provider){const s=provider==='spotify'?spotifySession:youtubeSession;if(!s||s.expires<=Date.now())throw Error('Подключи аккаунт '+(provider==='spotify'?'Spotify':'YouTube')+' заново.');return s;}
async function api(provider,path,{method='GET',body}={}){const s=session(provider),r=await fetch((provider==='spotify'?'https://api.spotify.com/v1/':'https://www.googleapis.com/youtube/v3/')+path,{method,headers:{Authorization:'Bearer '+s.token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(provider==='spotify'?'Spotify отклонил запрос. Проверь доступ приложения к своему аккаунту.':'YouTube отклонил запрос. Проверь включение YouTube Data API в бесплатной квоте проекта.');return d;}
export async function playlists(provider){const d=await api(provider,provider==='spotify'?'me/playlists?limit=50':'playlists?part=snippet&mine=true&maxResults=50');return (d.items||[]).map(v=>({id:v.id,name:v.name||v.snippet?.title||'Плейлист'}));}
export async function findTracks(provider,track){const q=[track.title,...track.artists||[]].join(' ');const d=await api(provider,provider==='spotify'?'search?type=track&limit=5&q='+encodeURIComponent(q):'search?part=snippet&type=video&maxResults=5&q='+encodeURIComponent(q+' official audio'));return (provider==='spotify'?d.tracks?.items||[]:d.items||[]).map(v=>({id:provider==='spotify'?v.uri:v.id.videoId,title:provider==='spotify'?v.name+' — '+v.artists.map(a=>a.name).join(', '):v.snippet.title}));}
export async function addToPlaylist(provider,playlist,recording){return api(provider,provider==='spotify'?'playlists/'+encodeURIComponent(playlist)+'/items':'playlistItems?part=snippet',{method:'POST',body:provider==='spotify'?{uris:[recording]}:{snippet:{playlistId:playlist,resourceId:{kind:'youtube#video',videoId:recording}}}});}
export function disconnectMusic(){spotifySession=null;youtubeSession=null;}
if(globalThis.addEventListener)globalThis.addEventListener('mediavault-locked',disconnectMusic);
