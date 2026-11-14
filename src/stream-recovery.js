import {contiguousBufferEnd} from './watch-quality.js';

// Keep an already decoded/buffered stream through a control-plane outage.
// Reconnect before its reserve runs out, or immediately on an uncached seek.
export function deferStreamRecovery(media,recover){
 let closed=false;
 const needed=()=>!media||!!media.error||media.readyState<2||
  ((!media.paused||media.seeking)&&contiguousBufferEnd(media.buffered,media.currentTime)-media.currentTime<8);
 const events=['timeupdate','waiting','seeking','playing','play'];
 const cleanup=()=>{closed=true;for(const name of events)media?.removeEventListener(name,check);};
 const check=()=>{if(!closed&&needed()){cleanup();recover();}};
 if(needed()){recover();return()=>{};}
 for(const name of events)media.addEventListener(name,check);
 return cleanup;
}
