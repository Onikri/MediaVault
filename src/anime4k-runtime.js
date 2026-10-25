import {ImageUpscaler,ANIME4KJS_SIMPLE_S_2X,ANIME4KJS_SIMPLE_M_2X} from 'anime4k.js';

// Anime4K 4.0.1 shaders, not a CSS sharpening effect. One render per decoded frame.
export async function startAnime4K(video,canvas,{mode='balanced',onStats=()=>{},onFailure=()=>{}}={}){
  if(typeof OffscreenCanvas==='undefined'||!ImageUpscaler.isSupported())throw Error('Этот браузер не поддерживает нужные расширения WebGL для Anime4K.');
  if(video.readyState<2)await new Promise((resolve,reject)=>{const finish=error=>{clearTimeout(timer);video.removeEventListener('loadeddata',ready);video.removeEventListener('error',failed);error?reject(error):resolve();};const ready=()=>finish(),failed=()=>finish(Error('Не удалось получить кадр для Anime4K.')),timer=setTimeout(failed,10000);video.addEventListener('loadeddata',ready);video.addEventListener('error',failed);});
  const input=document.createElement('canvas'),ctx=input.getContext('2d',{alpha:false});
  const coarse=matchMedia('(any-pointer: coarse)').matches;
  const limit=mode==='performance'?640:mode==='quality'?(coarse?960:1920):(coarse?800:1280);
  const width=Math.max(2,Math.min(video.videoWidth||640,limit));
  input.width=width;input.height=Math.max(2,Math.round(width*(video.videoHeight||360)/(video.videoWidth||640)));
  canvas.getContext('webgl',{powerPreference:'high-performance',alpha:false});
  const upscaler=new ImageUpscaler(mode==='quality'?ANIME4KJS_SIMPLE_M_2X:ANIME4KJS_SIMPLE_S_2X);
  let stopped=false,frame=0,raf=0,count=0,slow=0,started=performance.now(),lastMediaTime=-1,lastRenderAt=0,nativeBase=null,windowStart=performance.now(),windowFrames=0,slowWindows=0;
  function stop(){
    if(stopped)return;stopped=true;
    video.cancelVideoFrameCallback?.(frame);cancelAnimationFrame(raf);
    video.removeEventListener('play',wake);video.removeEventListener('pause',render);video.removeEventListener('seeked',render);video.removeEventListener('loadeddata',render);canvas.removeEventListener('webglcontextlost',lost);
    upscaler.detachSource();canvas.style.opacity='0';
  }
  function lost(event){event.preventDefault();stop();onFailure(Error('GPU освободил контекст Anime4K. Продолжаем исходное видео.'));}
  function render(){
    if(stopped||video.readyState<2||document.hidden)return;
    if(lastMediaTime===video.currentTime)return;
    if(!video.requestVideoFrameCallback&&!video.paused&&performance.now()-lastRenderAt<1000/30)return;
    lastMediaTime=video.currentTime;lastRenderAt=performance.now();
    try{
      const start=performance.now();ctx.drawImage(video,0,0,input.width,input.height);upscaler.upscale();
      const gl=canvas.getContext('webgl');
      if(!gl||gl.isContextLost()||gl.getError()!==gl.NO_ERROR)throw Error('Ошибка WebGL при обработке Anime4K.');
      canvas.style.opacity='1';count++;windowFrames++;
      const elapsed=performance.now()-start;slow=elapsed>65?slow+1:Math.max(0,slow-1);
      if(slow>18)throw Error('Anime4K не успевает за видео на этом устройстве. Продолжаем исходное видео.');
      if(performance.now()-started>1000){onStats({engine:'Anime4K',width:canvas.width,height:canvas.height,fps:Math.round(count*1000/(performance.now()-started)),latency:Math.round(elapsed)});count=0;started=performance.now();}
    }catch(error){stop();onFailure(error);}
  }
  function tick(now,metadata){
    frame=0;raf=0;if(stopped)return;render();
    if(metadata&&Number.isFinite(metadata.presentedFrames)){
      if(nativeBase===null){nativeBase=metadata.presentedFrames;windowStart=performance.now();windowFrames=0;}
      if(!video.paused&&performance.now()-windowStart>1800){
        const expected=metadata.presentedFrames-nativeBase;
        slowWindows=expected>20&&windowFrames/expected<.65?slowWindows+1:0;
        nativeBase=metadata.presentedFrames;windowFrames=0;windowStart=performance.now();
        if(slowWindows>=2){stop();onFailure(Error('GPU не успевает обрабатывать кадры Anime4K. Продолжаем исходное видео.'));return;}
      }
    }
    if(stopped)return;
    if(video.requestVideoFrameCallback)frame=video.requestVideoFrameCallback(tick);else if(!video.paused)raf=requestAnimationFrame(tick);
  }
  function wake(){if(!stopped&&!frame&&!raf)tick();}
  try{upscaler.attachSource(input,canvas);canvas.addEventListener('webglcontextlost',lost);video.addEventListener('play',wake);video.addEventListener('pause',render);video.addEventListener('seeked',render);video.addEventListener('loadeddata',render);tick();}
  catch(error){stop();throw error;}
  return stop;
}
