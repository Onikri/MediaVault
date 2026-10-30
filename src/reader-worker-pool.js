// Reuse only an idle renderer. An in-flight page is terminated on close so
// decrypted page data and stale messages never cross reader instances.
export function rendererPool({create,delay=120000,schedule=setTimeout,cancel=clearTimeout}){
 let idle=null,timer=null;
 const clear=()=>{if(timer!==null)cancel(timer);timer=null;idle?.terminate();idle=null;};
 return {
  acquire(){if(timer!==null)cancel(timer);timer=null;const worker=idle||create();idle=null;return worker;},
  release(worker,busy=false){if(!worker)return;worker.onmessage=null;worker.onerror=null;if(busy){worker.terminate();return;}clear();idle=worker;timer=schedule(clear,delay);timer?.unref?.();},
  clear,
 };
}
const pool=rendererPool({create:()=>new Worker(new URL('./manga-canvas.worker.js',import.meta.url),{type:'module'})});
globalThis.addEventListener?.('pagehide',()=>pool.clear());
export const acquireRenderer=()=>pool.acquire();
export const releaseRenderer=(worker,busy)=>pool.release(worker,busy);
