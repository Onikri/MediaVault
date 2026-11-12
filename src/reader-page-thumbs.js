// Small page previews for the page track. Decoded at preview size, kept in a
// bounded LRU of object URLs, revoked on eviction and when the chapter closes.
export function createPageThumbs(entries,{width=200,limit=48}={}){
 const cache=new Map();let closed=false;
 const release=task=>task.then(value=>{if(value?.url)URL.revokeObjectURL(value.url);}).catch(()=>{});
 async function make(index){
  const blob=await entries[index].async('blob');if(closed)return null;
  let bitmap;try{bitmap=await createImageBitmap(blob,{resizeWidth:width,resizeQuality:'medium'});}catch{bitmap=await createImageBitmap(blob);}
  try{
   const scale=Math.min(1,width/bitmap.width),w=Math.max(1,Math.round(bitmap.width*scale)),h=Math.max(1,Math.round(bitmap.height*scale));
   const canvas=typeof OffscreenCanvas==='function'?new OffscreenCanvas(w,h):Object.assign(document.createElement('canvas'),{width:w,height:h});
   canvas.getContext('2d').drawImage(bitmap,0,0,w,h);
   const out=canvas.convertToBlob?await canvas.convertToBlob({type:'image/webp',quality:.72}):await new Promise(r=>canvas.toBlob(r,'image/webp',.72));
   if(closed||!out)return null;
   return {url:URL.createObjectURL(out),ratio:h/w};
  }finally{bitmap.close?.();}
 }
 return {
  get(index){
   if(closed||!entries[index])return Promise.resolve(null);
   let task=cache.get(index);
   if(task)cache.delete(index);else task=make(index).catch(()=>null);
   cache.set(index,task);
   while(cache.size>limit){const [key,old]=cache.entries().next().value;cache.delete(key);release(old);}
   return task;
  },
  close(){closed=true;for(const task of cache.values())release(task);cache.clear();}
 };
}
