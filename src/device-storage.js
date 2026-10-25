const DATABASE='mediavault-trusted-device-v1';
export async function deviceStore(operation,key,value){
  if(!globalThis.indexedDB)throw Error('Браузер не разрешил сохранять настройки устройства.');
  const db=await new Promise((resolve,reject)=>{const r=indexedDB.open(DATABASE,1);r.onupgradeneeded=()=>r.result.createObjectStore('records');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
  try{return await new Promise((resolve,reject)=>{
    const tx=db.transaction('records',operation==='get'?'readonly':'readwrite',operation==='get'?undefined:{durability:'strict'}),store=tx.objectStore('records');let result;
    if(operation==='getOrPut'){
      // A readwrite transaction serializes this decision across tabs as well.
      const request=store.get(key);request.onsuccess=()=>{result=request.result;if(result===undefined){result=value;store.add(value,key);}};
    }else{
      const request=operation==='get'?store.get(key):operation==='clear'?store.clear():operation==='delete'?store.delete(key):store.put(value,key);
      request.onsuccess=()=>{result=request.result;};
    }
    tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('Хранилище устройства недоступно.'));
  });}finally{db.close();}
}
