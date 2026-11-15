// SPDX-License-Identifier: AGPL-3.0-or-later
// The owner's own licensed lettering typefaces (sound effects, side chatter,
// notes). They are not in the repository or the public bundle: the owner's
// server hands them to the authenticated owner, the bytes are kept in this
// browser's Cache Storage and passed to the page renderer workers.
let fonts=null,pending=null;
const sent=new WeakSet();
async function fetchFonts(service){
 const list=(await service.request('/reader/lmt/fonts')).fonts||[],store=await globalThis.caches?.open('mv-private-fonts-v1').catch(()=>null),out=[],keep=new Set();
 for(const [index,font]of list.entries()){
  if(typeof font?.name!=='string'||!/^[0-9a-f]{64}$/.test(font.sha256||''))continue;
  const key=location.origin+'/__private-font/'+font.sha256;keep.add(key);
  let data=await(await store?.match(key))?.arrayBuffer();
  if(!data){
   data=await(await service.request('/reader/lmt/fonts/'+index,{raw:true})).arrayBuffer();
   await store?.put(key,new Response(data.slice(0),{headers:{'Content-Type':'application/octet-stream'}})).catch(()=>{});
  }
  out.push({name:font.name,data});
 }
 for(const request of await store?.keys().catch(()=>[])||[])if(!keep.has(request.url))await store.delete(request);
 return out;
}
// Starts one download per session; a failure (no owner session, older server) leaves the open fonts in use.
export function preloadPrivateFonts(service){
 if(!service?.request)return Promise.resolve();
 return pending||=fetchFonts(service).then(value=>{fonts=value;}).catch(()=>{pending=null;});
}
// Rendering waits briefly for a download that has already started, never for one that has not.
export const privateFontsSettled=()=>pending&&!fonts?Promise.race([pending,new Promise(resolve=>setTimeout(resolve,4000))]):Promise.resolve();
export function sharePrivateFonts(worker){
 if(!worker||!fonts?.length||sent.has(worker))return;
 sent.add(worker);worker.postMessage({operation:'fonts',fonts});
}
