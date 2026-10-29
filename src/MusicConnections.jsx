import {useEffect,useState} from 'react';
import {connectSpotify,connectYouTube,musicConnectionInfo,subscribeMusicConnections,disconnectMusicProvider,configuredSpotifyClient,spotifyRedirect,playlists,playlistTracks,createPlaylist,findTracks,addToPlaylist} from './music-connectors.js';
import {playMusic} from './music-player.js';
import './music-dock.css';

export default function MusicConnections({track,compact=false}){
 const [provider,setProvider]=useState('youtube'),[version,update]=useState(0),[client,setClient]=useState(configuredSpotifyClient),[lists,setLists]=useState([]),[playlist,setPlaylist]=useState(''),[name,setName]=useState(''),[values,setValues]=useState([]),[candidates,setCandidates]=useState([]),[recording,setRecording]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
 const info=musicConnectionInfo(provider);
 useEffect(()=>subscribeMusicConnections(()=>update(v=>v+1)),[]);
 useEffect(()=>{setLists([]);setValues([]);setCandidates([]);setPlaylist('');setMessage('');setError('');},[provider,track?.id]);
 async function run(action){setBusy(true);setError('');setMessage('');try{await action();}catch(e){setError(e.message);}finally{setBusy(false);}}
 async function load(){const rows=await playlists(provider);setLists(rows);setPlaylist(rows[0]?.id||'');if(track){const songs=await findTracks(provider,track);setCandidates(songs);setRecording(songs[0]?.id||'');}}
 return <section className={'music-connections'+(compact?' is-compact':'')} aria-label="Музыкальные аккаунты">
  <div className="music-connection-heading"><h2>{track?'Плейлист платформы':'Музыкальные аккаунты'}</h2><span>{info.connected?'Подключено в этой вкладке':'Отдельное подключение'}</span></div>
  <label>Платформа<select aria-label="Музыкальная платформа" value={provider} onChange={e=>setProvider(e.target.value)}><option value="youtube">YouTube / YouTube Music</option><option value="spotify">Spotify</option></select></label>
  {provider==='spotify'&&<details><summary>Приложение Spotify</summary><p>Для доступа к плейлистам нужен публичный Client ID зарегистрированного приложения. Воспроизведение идёт через Oracle. Доступ зависит от режима приложения и разрешённых пользователей.</p><label>Публичный Client ID<input aria-label="Spotify Client ID" value={client} onChange={e=>setClient(e.target.value)} autoComplete="off"/></label><p>Redirect URI: <code>{spotifyRedirect()}</code></p><a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener noreferrer">Настроить приложение Spotify</a></details>}
  <div className="music-connection-actions"><button disabled={busy} onClick={()=>run(async()=>{if(provider==='spotify')await connectSpotify(client||undefined);else await connectYouTube();await load();})}>{busy?'Подключаем…':info.connected?'Обновить подключение':'Подключить '+(provider==='spotify'?'Spotify':'YouTube')}</button>{info.connected&&<><button disabled={busy} onClick={()=>run(load)}>Загрузить плейлисты</button><button onClick={()=>{disconnectMusicProvider(provider);setLists([]);setValues([]);}}>Отключить</button></>}</div>
  {info.connected&&<><label>Новый плейлист<input aria-label="Название нового музыкального плейлиста" maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label><button disabled={busy||!name.trim()} onClick={()=>run(async()=>{const row=await createPlaylist(provider,name);setLists(old=>[row,...old]);setPlaylist(row.id);setName('');setMessage('Плейлист создан на платформе.');})}>Создать плейлист</button></>}
  {lists.length>0&&<label>Плейлист<select aria-label="Плейлист музыкальной платформы" value={playlist} onChange={e=>{setPlaylist(e.target.value);setValues([]);}}>{lists.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
  {track&&candidates.length>0&&<><label>Запись<select aria-label="Запись для плейлиста" value={recording} onChange={e=>setRecording(e.target.value)}>{candidates.map(v=><option key={v.id} value={v.id}>{v.title}</option>)}</select></label><button disabled={busy||!playlist||!recording} onClick={()=>run(async()=>{await addToPlaylist(provider,playlist,recording);setMessage('Запись добавлена в выбранный плейлист.');})}>Добавить запись в плейлист</button></>}
  {!track&&playlist&&<button disabled={busy} onClick={()=>run(async()=>setValues(await playlistTracks(provider,playlist)))}>Открыть песни плейлиста</button>}
  {values.length>0&&<div className="music-account-tracks">{values.map(v=><button key={v.id} onClick={()=>playMusic(v,values)}>{v.title}</button>)}<small>Первые 50 записей плейлиста.</small></div>}
  {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  <p className="music-connection-note">Google-вход в MediaVault не подключает YouTube автоматически. Подключение даёт доступ к плейлистам; Premium YouTube не определяется этим API и отсутствие рекламы не гарантируется. Токены находятся только в памяти вкладки.</p>
 </section>;
}
