// Real viewer state only. One request at a time; bursts collapse to the latest
// snapshot so a delayed Play cannot overwrite a later Pause or seek.
export function reportOnlinePlayback(service,token,player,onExpired=()=>{},intervalMs=10000){
 const media=player.media;if(!media)return()=>{};
 let closed=false,busy=false,dirty=false,expired=false,buffering=false;
 const abort=new AbortController();
 async function send(){
  if(closed||expired)return;
  if(busy){dirty=true;return;}
  if(media.readyState===0)return;
  const snapshot=player.getSnapshot();
  if(!Number.isFinite(snapshot.time)||snapshot.time<0)return;
  busy=true;dirty=false;
  try{
   await service.request('/online/'+token+'/playback',{method:'POST',body:{
    time:snapshot.time,paused:!snapshot.playing,rate:media.playbackRate||1,
    seeking:!!media.seeking,buffering,ended:!!media.ended
   },signal:AbortSignal.any([abort.signal,AbortSignal.timeout(10000)])});
  }catch(error){
   if(!closed&&[404,409,410].includes(error.status)&&!expired){expired=true;onExpired();}
  }finally{busy=false;if(dirty&&!closed&&!expired)send();}
 }
 const update=event=>{
  if(['waiting','stalled'].includes(event.type))buffering=true;
  if(['playing','seeked','pause','ended'].includes(event.type))buffering=false;
  send();
 };
 const events=['play','playing','pause','seeking','seeked','ratechange','waiting','stalled','ended'];
 for(const name of events)media.addEventListener(name,update);
 const timer=setInterval(send,intervalMs);send();
 return()=>{closed=true;clearInterval(timer);abort.abort();for(const name of events)media.removeEventListener(name,update);};
}
