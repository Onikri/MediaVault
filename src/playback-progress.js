import {notePlace} from './place-sync.js';
// Per-account, per-library positions. Decrypted video and access credentials are never stored.
const key=(user,library,id)=>'mediavault_progress_v2:'+encodeURIComponent(user||'anonymous')+':'+encodeURIComponent(library||'local')+':'+encodeURIComponent(id);
export function readProgress(user,library,id,storage){
  try{storage=storage||globalThis.localStorage;const value=JSON.parse(storage.getItem(key(user,library,id))||'null');return value&&Number.isFinite(value.time)&&value.time>=1?value:null;}catch{return null;}
}
export function writeProgress(user,library,item,time,duration,storage){
  if(!item?.id||!Number.isFinite(time))return;
  try{
    storage=storage||globalThis.localStorage;
    const itemKey=key(user,library,item.id);
    const groupId=item.collectionId?'collection:'+item.collectionId:'';
    const groupKey=groupId?key(user,library,groupId):'';
    const previous=readProgress(user,library,item.id,storage);
    const previousGroup=groupId?readProgress(user,library,groupId,storage):null;
    const done=Number.isFinite(duration)&&duration>0&&duration-time<10;
    const remove=time<1||done;
    const changeGroup=groupKey&&(!remove||previousGroup?.itemId===item.id);
    // The server rejects equal timestamps. A removal must win even if a
    // device receives the saved place and finishes playback in the same tick.
    const at=Math.max(Date.now(),(Number(previous?.updatedAt)||0)+1,
      changeGroup?(Number(previousGroup?.updatedAt)||0)+1:0);
    const value={itemId:item.id,time:Math.max(0,Math.floor(time)),duration:Number.isFinite(duration)?duration:null,updatedAt:at,done,episode:item.episode,season:item.season,voiceId:item.voiceId,dub:item.dub};
    if(remove)storage.removeItem(itemKey);else storage.setItem(itemKey,JSON.stringify(value));
    if(changeGroup){
      if(remove)storage.removeItem(groupKey);else storage.setItem(groupKey,JSON.stringify(value));
    }
    if(library==='online'){
      notePlace(user,itemKey,storage,at);
      if(changeGroup)notePlace(user,groupKey,storage,at);
    }
  }catch{}
}

export function progressClock(seconds){const n=Math.max(0,Math.floor(seconds||0));return (n>=3600?Math.floor(n/3600)+":":"")+String(Math.floor(n%3600/60)).padStart(2,"0")+":"+String(n%60).padStart(2,"0");}
