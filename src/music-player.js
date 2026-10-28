let current=null,sequence=0;
const listeners=new Set();
const emit=()=>listeners.forEach(fn=>fn());
export const musicSnapshot=()=>current;
export function subscribeMusic(fn){listeners.add(fn);return()=>listeners.delete(fn);}
export function playMusic(track,queue){
 if(!track?.id||!track?.title)return;
 if(globalThis.document?.fullscreenElement)document.exitFullscreen?.().catch(()=>{});
 const values=(Array.isArray(queue)&&queue.length?queue:[track]).filter(t=>t?.id&&t?.title),index=Math.max(0,values.findIndex(t=>t.id===track.id));
 current={track,queue:values,index,request:++sequence};emit();
}
export function stepMusic(delta){if(!current)return;const next=current.index+delta;if(next<0||next>=current.queue.length)return;const {queue}=current;current={track:queue[next],queue,index:next,request:++sequence};emit();}
export function closeMusic(){current=null;emit();}
globalThis.addEventListener?.('mediavault-locked',closeMusic);
