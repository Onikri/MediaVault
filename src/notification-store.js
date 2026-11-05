const stores=new Map();
export function notificationStore(userId='guest'){
 const key='mv_notifications_v1:'+encodeURIComponent(userId||'guest');if(stores.has(key))return stores.get(key);
 let items=[];const listeners=new Set();
 function load(){try{const value=JSON.parse(globalThis.localStorage?.getItem(key)||'[]');items=Array.isArray(value)?value.filter(v=>v&&typeof v.id==='string'&&typeof v.message==='string'&&Number.isFinite(v.at)&&v.at>0).slice(0,100):[];}catch{items=[];}}
 function change(next){items=next;try{globalThis.localStorage?.setItem(key,JSON.stringify(items));}catch{}for(const listener of listeners)listener();}
 load();const store={getSnapshot:()=>items,subscribe(listener){listeners.add(listener);return()=>listeners.delete(listener);},
  push(notice){if(!notice?.id||!notice.message||items.some(v=>v.id===notice.id))return;const same=items.find(v=>v.message===notice.message&&!!v.bad===!!notice.bad&&Date.now()-v.at<60000);const value={id:same?.id||notice.id,message:String(notice.message).slice(0,1600),bad:!!notice.bad,at:Date.now(),read:false,count:(same?.count||0)+1,...(/^[\w:-]{1,100}$/.test(notice.taskId||'')?{taskId:notice.taskId}:{})};change([value,...items.filter(v=>v.id!==value.id)].slice(0,100));},
  read(id){change(items.map(v=>!id||v.id===id?{...v,read:true}:v));},clear(){change([]);}};
 globalThis.addEventListener?.('storage',event=>{if(event.key===key){load();for(const listener of listeners)listener();}});
 stores.set(key,store);return store;
}
