import {spotifyPlaybackToken,musicProviderRequest} from './music-connectors.js';
let sdk;
function loadSDK(){
 if(window.Spotify?.Player)return Promise.resolve(window.Spotify);
 if(!sdk)sdk=new Promise((resolve,reject)=>{
  const timeout=setTimeout(()=>{sdk=null;reject(Error('Spotify не загрузился. Проверь доступ к сервису.'));},20000);
  const previous=window.onSpotifyWebPlaybackSDKReady;
  window.onSpotifyWebPlaybackSDKReady=()=>{clearTimeout(timeout);previous?.();resolve(window.Spotify);};
  let script=document.querySelector('script[data-mv-spotify]');
  if(!script){script=document.createElement('script');script.src='https://sdk.scdn.co/spotify-player.js';script.dataset.mvSpotify='true';script.onerror=()=>{clearTimeout(timeout);sdk=null;script.remove();reject(Error('Не удалось загрузить Spotify.'));};document.head.append(script);}
 });return sdk;
}
export async function spotifyPlayer({onState,onError}){
 spotifyPlaybackToken();const Spotify=await loadSDK();let player,closed=false;
 const ready=new Promise((resolve,reject)=>{
  player=new Spotify.Player({name:'MediaVault',volume:.8,getOAuthToken:callback=>{try{callback(spotifyPlaybackToken());}catch(e){onError?.(e.message);}},enableMediaSession:false});
  player.addListener('ready',({device_id})=>resolve(device_id));
  player.addListener('player_state_changed',s=>{if(!closed&&s)onState?.({playing:!s.paused,time:s.position/1000,duration:s.duration/1000,track:s.track_window?.current_track});});
  for(const event of ['initialization_error','authentication_error','account_error','playback_error'])player.addListener(event,({message})=>{if(!closed)onError?.(event==='account_error'?'Для воспроизведения здесь требуется Spotify Premium.':message||'Ошибка Spotify.');reject(Error(event==='account_error'?'Требуется Spotify Premium.':message||'Ошибка Spotify.'));});
 });
 const timeout=new Promise((_,reject)=>{const id=setTimeout(()=>reject(Error('Spotify Connect не ответил. Повтори подключение.')),20000);ready.finally(()=>clearTimeout(id)).catch(()=>{});});
 try{
  await player.connect();const device=await Promise.race([ready,timeout]);
  return {play:async uri=>{if(!/^spotify:track:[A-Za-z0-9]+$/.test(uri))throw Error('Выбери запись Spotify.');await player.activateElement();await musicProviderRequest('spotify','me/player/play?device_id='+encodeURIComponent(device),{method:'PUT',body:{uris:[uri]}});},
   resume:()=>player.resume(),pause:()=>player.pause(),seek:seconds=>player.seek(Math.round(seconds*1000)),volume:value=>player.setVolume(value),
   close:()=>{closed=true;player.disconnect();}};
 }catch(e){closed=true;player?.disconnect();throw e;}
}
