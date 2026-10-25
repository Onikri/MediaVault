// Per-account, per-library positions. Decrypted video and access credentials are never stored.
const key=(user,library,id)=>'mediavault_progress_v2:'+encodeURIComponent(user||'anonymous')+':'+encodeURIComponent(library||'local')+':'+encodeURIComponent(id);
export function readProgress(user,library,id,storage=globalThis.localStorage){
  try{const value=JSON.parse(storage.getItem(key(user,library,id))||'null');return value&&Number.isFinite(value.time)&&value.time>=1?value:null;}catch{return null;}
}
export function writeProgress(user,library,item,time,duration,storage=globalThis.localStorage){
  if(!item?.id||!Number.isFinite(time))return;
  try{
    const done=Number.isFinite(duration)&&duration>0&&duration-time<10;
    const value={itemId:item.id,time:Math.max(0,Math.floor(time)),duration:Number.isFinite(duration)?duration:null,updatedAt:Date.now(),done};
    if(time<1||done)storage.removeItem(key(user,library,item.id));else storage.setItem(key(user,library,item.id),JSON.stringify(value));
    if(item.collectionId){const group=key(user,library,'collection:'+item.collectionId);if(done||time<1){if(readProgress(user,library,'collection:'+item.collectionId,storage)?.itemId===item.id)storage.removeItem(group);}else storage.setItem(group,JSON.stringify(value));}
  }catch{}
}
