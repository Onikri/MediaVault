let current=null,sequence=0;
const listeners=new Set();
export const musicSnapshot=()=>current;
export function subscribeMusic(fn){listeners.add(fn);return()=>listeners.delete(fn);}
export function playMusic(track){if(!track?.id||!track?.title)return;current={track,request:++sequence};listeners.forEach(fn=>fn());}
export function closeMusic(){current=null;listeners.forEach(fn=>fn());}
globalThis.addEventListener?.('mediavault-locked',closeMusic);
