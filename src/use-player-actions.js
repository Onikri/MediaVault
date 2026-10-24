import {useEffect,useRef,useState} from 'react';
export function saveBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);}
export default function usePlayerActions({videoRef,canvasRef,item,gpuActive}){
  const [notice,setNotice]=useState(''),[recording,setRecording]=useState(false),[clipSeconds,setClipSeconds]=useState(0);
  const recorder=useRef(null),timer=useRef(null),alive=useRef(true),noticeTimer=useRef(null);
  function inform(text){setNotice(text);clearTimeout(noticeTimer.current);noticeTimer.current=setTimeout(()=>setNotice(''),3500);}
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;clearInterval(timer.current);clearTimeout(noticeTimer.current);const r=recorder.current;if(r){r.discard=true;if(r.state!=='inactive')r.stop();r.stream.getTracks().forEach(t=>t.stop());}};},[]);
  useEffect(()=>{const v=videoRef.current;const stop=()=>{const r=recorder.current;if(r?.state==='recording')r.stop();};v?.addEventListener('ended',stop);return()=>v?.removeEventListener('ended',stop);},[videoRef]);
  async function screenshot(){
    try{const v=videoRef.current;if(!v||v.readyState<2)throw Error('Дождись загрузки кадра.');const c=document.createElement('canvas');c.width=gpuActive?canvasRef.current.width:v.videoWidth;c.height=gpuActive?canvasRef.current.height:v.videoHeight;c.getContext('2d').drawImage(gpuActive?canvasRef.current:v,0,0,c.width,c.height);const blob=await new Promise(resolve=>c.toBlob(resolve,'image/png'));if(!blob)throw Error('Кадр недоступен.');saveBlob(blob,'MediaVault-кадр-'+Math.floor(v.currentTime)+'.png');inform('Кадр сохранён');}catch{inform('Этот источник не разрешает сохранить кадр.');}
  }
  async function share(){
    const url=new URL(location.href);url.hash=new URLSearchParams({episode:item.id,t:String(Math.floor(videoRef.current?.currentTime||0))}).toString();
    try{if(navigator.share)await navigator.share({title:item.name,url:url.href});else{await navigator.clipboard.writeText(url.href);inform('Ссылка скопирована');}}catch(e){if(e.name!=='AbortError')inform('Не удалось поделиться ссылкой.');}
  }
  function clip(){
    const previous=recorder.current;if(previous?.state==='recording'){previous.stop();return;}
    let stream;
    try{
      const v=videoRef.current;if(!v||v.paused)throw Error('Для записи клипа запусти видео.');
      const capture=v.captureStream||v.mozCaptureStream;if(!capture||!window.MediaRecorder)throw Error('Запись клипов недоступна в этом браузере.');
      stream=capture.call(v);if(!stream.getVideoTracks().length)throw Error('Источник не разрешает запись.');
      const mime=['video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm','video/mp4'].find(t=>MediaRecorder.isTypeSupported(t));if(!mime)throw Error('Формат записи не поддерживается.');
      const r=new MediaRecorder(stream,{mimeType:mime}),chunks=[];recorder.current=r;r.discard=false;
      r.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      r.onstop=()=>{clearInterval(timer.current);stream.getTracks().forEach(t=>t.stop());if(!alive.current||r.discard)return;setRecording(false);if(chunks.length){saveBlob(new Blob(chunks,{type:r.mimeType}),'MediaVault-клип.'+(r.mimeType.includes('mp4')?'mp4':'webm'));inform('Клип сохранён');}recorder.current=null;};
      r.onerror=()=>{r.discard=true;clearInterval(timer.current);stream.getTracks().forEach(t=>t.stop());if(alive.current){setRecording(false);inform('Не удалось записать клип.');}};
      r.start(200);setRecording(true);setClipSeconds(0);const start=performance.now();timer.current=setInterval(()=>{const seconds=Math.floor((performance.now()-start)/1000);setClipSeconds(seconds);if(seconds>=30&&r.state==='recording')r.stop();},250);
    }catch(e){stream?.getTracks().forEach(t=>t.stop());inform(e.message);}
  }
  return {notice,recording,clipSeconds,share,screenshot,clip};
}
