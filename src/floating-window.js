// "Above every window": Chromium's Document Picture-in-Picture gets the very
// <video> element of our player (nothing restarts), with a few plain controls.
// Elsewhere the browser's own video picture-in-picture is used instead.
const ICON={
 play:'<path d="M7 4.5v15l12-7.5z" fill="currentColor"/>',
 pause:'<path d="M7 4h4v16H7zM13 4h4v16h-4z" fill="currentColor"/>',
 back:'<path d="M15 3h6v6M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
};
const svg=name=>'<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">'+ICON[name]+'</svg>';
const CSS=[
 'html,body{margin:0;height:100%;background:#000;color:#fff;font:600 12px system-ui,sans-serif;overflow:hidden}',
 '.pip{position:relative;height:100%;display:grid}',
 '.pip video{width:100%;height:100%;object-fit:contain;background:#000}',
 '.pip-bar{position:absolute;inset:auto 0 0;display:flex;align-items:center;gap:10px;padding:28px 12px 10px;background:linear-gradient(transparent,rgb(0 0 0/.78));opacity:0;transition:opacity .2s}',
 '.pip:hover .pip-bar,.pip.is-paused .pip-bar,.pip:focus-within .pip-bar{opacity:1}',
 '.pip button{display:grid;place-items:center;width:34px;height:34px;padding:0;border:0;border-radius:50%;background:rgb(255 255 255/.14);color:#fff;cursor:pointer;flex:none}',
 '.pip button:hover{background:rgb(255 255 255/.26)}',
 '.pip input{flex:1;min-width:0;accent-color:#e23c4b}',
 '.pip time{font-variant-numeric:tabular-nums;opacity:.85}',
].join('\n');
const clock=v=>{v=Math.max(0,Math.floor(v||0));const h=Math.floor(v/3600),m=Math.floor(v%3600/60),s=String(v%60).padStart(2,'0');return h?h+':'+String(m).padStart(2,'0')+':'+s:m+':'+s;};

export const floatingWindowSupported=()=>typeof window!=='undefined'&&('documentPictureInPicture' in window||!!document.pictureInPictureEnabled);

export async function openFloatingWindow(host,{title='MediaVault',onReturn}={}){
 const video=host?.querySelector('video.mv-player-media');
 if(!video)throw Error('Видео ещё не загрузилось.');
 if(!('documentPictureInPicture' in window)){await video.requestPictureInPicture();return null;}
 const ratio=(video.videoWidth||16)/(video.videoHeight||9),width=Math.min(560,Math.round(screen.availWidth*.36)),height=Math.round(width/ratio);
 const pip=await window.documentPictureInPicture.requestWindow({width,height});
 const doc=pip.document,parent=video.parentNode,next=video.nextSibling,playing=!video.paused;
 doc.title=title;
 const style=doc.createElement('style');style.textContent=CSS;doc.head.append(style);
 const shell=doc.createElement('div');shell.className='pip';
 const bar=doc.createElement('div');bar.className='pip-bar';
 bar.innerHTML='<button type="button" aria-label="Пауза">'+svg('pause')+'</button><time>0:00</time><input type="range" min="0" max="1000" value="0" aria-label="Перемотка"><time>0:00</time><button type="button" aria-label="Вернуть во вкладку" title="Вернуть во вкладку">'+svg('back')+'</button>';
 const [toggle,back]=bar.querySelectorAll('button'),[now,total]=bar.querySelectorAll('time'),seek=bar.querySelector('input');
 shell.append(video,bar);doc.body.append(shell);
 const sync=()=>{const paused=video.paused;shell.classList.toggle('is-paused',paused);toggle.innerHTML=svg(paused?'play':'pause');toggle.setAttribute('aria-label',paused?'Продолжить':'Пауза');now.textContent=clock(video.currentTime);total.textContent=clock(video.duration);if(video.duration&&doc.activeElement!==seek)seek.value=String(Math.round(video.currentTime/video.duration*1000));};
 const events=['play','pause','timeupdate','durationchange'];events.forEach(name=>video.addEventListener(name,sync));sync();
 toggle.onclick=()=>video.paused?video.play().catch(()=>{}):video.pause();
 seek.oninput=()=>{if(video.duration)video.currentTime=Number(seek.value)/1000*video.duration;};
 back.onclick=()=>pip.close();
 doc.addEventListener('keydown',event=>{if(event.key===' '){event.preventDefault();toggle.click();}if(event.key==='ArrowRight')video.currentTime+=10;if(event.key==='ArrowLeft')video.currentTime-=10;});
 if(playing)video.play().catch(()=>{});
 pip.addEventListener('pagehide',()=>{
  events.forEach(name=>video.removeEventListener(name,sync));
  const wasPlaying=!video.paused;
  if(parent?.isConnected)parent.insertBefore(video,next&&next.parentNode===parent?next:null);
  if(wasPlaying)video.play().catch(()=>{});
  onReturn?.();
 },{once:true});
 return pip;
}
