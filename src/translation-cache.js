import {resultConfig,bytesBase64,fromBase64,hasRenderedPage} from './manga-translation.js';
const DB='mv-translated-pages-v1',LIMIT=256*1024*1024,MAX=1000;
const request=r=>new Promise((resolve,reject)=>{r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
const done=tx=>new Promise((resolve,reject)=>{tx.oncomplete=resolve;tx.onerror=tx.onabort=()=>reject(tx.error);});
let opening;
function database(){if(!opening)opening=new Promise((resolve,reject)=>{const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>{r.result.createObjectStore('pages',{keyPath:'id'});r.result.createObjectStore('keys');};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});return opening;}
async function key(db,scope){let tx=db.transaction('keys','readonly'),k=await request(tx.objectStore('keys').get(scope));if(k)return k;k=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);tx=db.transaction('keys','readwrite');const store=tx.objectStore('keys'),existing=await request(store.get(scope));if(existing)return existing;store.put(k,scope);await done(tx);return k;}
export async function translationCacheKey(blob,config,scope){const digest=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());return scope+':'+bytesBase64(digest)+':'+JSON.stringify(resultConfig(config));}
export async function getTranslation(id,scope){try{const db=await database(),row=await request(db.transaction('pages').objectStore('pages').get(id));if(!row||row.scope!==scope)return null;const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:row.iv,additionalData:new TextEncoder().encode(id)},await key(db,scope),row.data instanceof Blob?await row.data.arrayBuffer():row.data),value=JSON.parse(new TextDecoder().decode(plain));if(value.renderedImage)value.renderedImage=fromBase64(value.renderedImage);else if(value.kind!=='manga-json')return null;return {...value,cacheHit:true};}catch{return null;}}
export async function putTranslation(id,scope,result,metadata){if((!hasRenderedPage(result)&&result.kind!=='manga-json')||result.inpaint?.unpainted||result.warnings?.length)return;try{const {debug,...persistent}=result;result=persistent;const db=await database(),iv=crypto.getRandomValues(new Uint8Array(12)),plain=new TextEncoder().encode(JSON.stringify({...result,...(result.renderedImage?{renderedImage:bytesBase64(result.renderedImage)}:{})})),data=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode(id)},await key(db,scope),plain);let tx=db.transaction('pages','readwrite');tx.objectStore('pages').put({id,scope,metadata,iv,data:new Blob([data]),size:data.byteLength,time:Date.now()});await done(tx);const rows=await request(db.transaction('pages').objectStore('pages').getAll());let size=rows.reduce((n,r)=>n+r.size,0),count=rows.length;tx=db.transaction('pages','readwrite');for(const row of rows.sort((a,b)=>a.time-b.time)){if(size<=LIMIT&&count<=MAX)break;tx.objectStore('pages').delete(row.id);size-=row.size;count--;}await done(tx);}catch{/* Private browsing/quota: the memory cache still works. */}}
// Old reader rows are discoverable too; never treat an incomplete cache as a chapter.
export async function cachedChapterPages({scope,chapter,url,total}){
 const db=await database(),rows=await request(db.transaction('pages').objectStore('pages').getAll()),marker=':chapter='+encodeURIComponent(chapter||'online:'+url)+':page=';
 const candidates=rows.filter(row=>row.scope===scope&&(row.id.includes(':render-v')||row.metadata)&&(row.metadata?.chapter===chapter||url&&row.metadata?.url===url||row.id.includes(marker))).sort((a,b)=>b.time-a.time);
 if(!candidates.length)return {pages:[],total:total||0,complete:false};
 const variant=row=>row.metadata?.variant||row.id.slice(scope.length+1).slice(row.id.slice(scope.length+1).indexOf(':')+1).replace(/:page=\d+/,'');
 const newest=variant(candidates[0]),pages=[],seen=new Set();let expected=total||candidates[0].metadata?.total||0;
 for(const row of candidates){
  if(variant(row)!==newest)continue;
  const page=row.metadata?.index??Number(row.id.match(/:page=(\d+)/)?.[1]);if(!Number.isInteger(page)||seen.has(page))continue;
  const value=await getTranslation(row.id,scope);if(!value?.renderedImage)continue;
  const digest=fromBase64(row.id.slice(scope.length+1).split(':')[0]);
  pages.push({page,blob:new Blob([value.renderedImage],{type:value.renderedMime||'image/webp'}),sourceHash:Array.from(new Uint8Array(digest),n=>n.toString(16).padStart(2,'0')).join('')});seen.add(page);
 }
 pages.sort((a,b)=>a.page-b.page);
 return {pages,total:expected,complete:!!expected&&pages.length===expected&&pages.every((p,i)=>p.page===i)};
}
export async function clearTranslations(scope){const db=await database(),rows=await request(db.transaction('pages').objectStore('pages').getAll()),tx=db.transaction(['pages','keys'],'readwrite');for(const row of rows)if(row.scope===scope)tx.objectStore('pages').delete(row.id);tx.objectStore('keys').delete(scope);await done(tx);}
