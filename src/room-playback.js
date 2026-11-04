// One pending playback request per media element. Server snapshots can arrive
// faster than play() resolves, especially during seek/buffer transitions.
const requests=new WeakMap();
export function applyRoomState(media,state,{force=false,canPlay=true,onBlocked}={}){
 if(!media||!state||!Number.isFinite(state.position))return;
 const target=Math.max(0,Math.min(state.duration||1e9,state.position));
 if(Number.isFinite(media.duration)&&media.readyState>=1&&Math.abs(media.currentTime-target)>(force?.15:1.1))media.currentTime=target;
 const rate=Number.isFinite(state.rate)?Math.max(.25,Math.min(3,state.rate)):1,drift=target-media.currentTime;
 const corrected=Math.abs(drift)<.12?rate:Math.max(.25,Math.min(3,rate+(drift>0?.035:-.035)));
 if(Math.abs(media.playbackRate-corrected)>.001)media.playbackRate=corrected;
 if(!state.playing||state.held||!canPlay){if(!media.paused||requests.has(media))media.pause();return;}
 if(media.readyState<2||!media.paused||requests.has(media))return;
 const request={};requests.set(media,request);
 try{Promise.resolve(media.play()).catch(error=>{if(error.name!=='AbortError')onBlocked?.(error);}).finally(()=>{if(requests.get(media)===request)requests.delete(media);});}
 catch(error){requests.delete(media);if(error.name!=='AbortError')onBlocked?.(error);}
}
