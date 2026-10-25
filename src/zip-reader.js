// Native imports use ZIP_STORED: the directory and visible pages can be read
// through authenticated encrypted chunks without downloading the whole chapter.
export async function openRangeArchive(item,readRange,signal){
 const size=Number(item.size);if(!Number.isSafeInteger(size)||size<22)throw Error('Неизвестный размер архива.');
 const take=async(start,end)=>new Uint8Array(await(await readRange(item,start,end,{signal})).arrayBuffer());
 const start=Math.max(0,size-65557),tail=await take(start,size),view=new DataView(tail.buffer,tail.byteOffset,tail.byteLength);let end=-1;
 for(let i=tail.length-22;i>=0;i--)if(view.getUint32(i,true)===0x06054b50&&i+22+view.getUint16(i+20,true)===tail.length){end=i;break;}
 if(end<0)throw Error('Не найден каталог CBZ.');
 const count=view.getUint16(end+10,true),length=view.getUint32(end+12,true),offset=view.getUint32(end+16,true);
 if(view.getUint16(end+4,true)||view.getUint16(end+6,true)||count>1500||length>2*1024*1024||offset+length>size)throw Error('Неподдерживаемый архив.');
 const directory=offset>=start?tail.slice(offset-start,offset-start+length):await take(offset,offset+length),dv=new DataView(directory.buffer),entries=[];let at=0;
 for(let n=0;n<count;n++){
  if(at+46>directory.length||dv.getUint32(at,true)!==0x02014b50)throw Error('Повреждён каталог CBZ.');
  const flags=dv.getUint16(at+8,true),method=dv.getUint16(at+10,true),bytes=dv.getUint32(at+20,true),raw=dv.getUint32(at+24,true),nameLength=dv.getUint16(at+28,true),extra=dv.getUint16(at+30,true),comment=dv.getUint16(at+32,true),local=dv.getUint32(at+42,true),name=new TextDecoder().decode(directory.slice(at+46,at+46+nameLength));
  if(flags&1||method!==0||raw!==bytes)throw Error('Для сжатого CBZ используется совместимый режим загрузки целиком.');
  if(/\.(jpe?g|png|webp|gif|avif)$/i.test(name)&&!name.endsWith('/')){
   if(raw>30*1024*1024||local+30+bytes>size)throw Error('Страница слишком велика или повреждена.');
   entries.push({name,async:async()=>{const header=await take(local,local+30),h=new DataView(header.buffer);if(h.getUint32(0,true)!==0x04034b50)throw Error('Повреждена страница CBZ.');const begin=local+30+h.getUint16(26,true)+h.getUint16(28,true);if(begin+bytes>offset)throw Error('Страница выходит за пределы CBZ.');return new Blob([await take(begin,begin+bytes)],{type:/png$/i.test(name)?'image/png':/webp$/i.test(name)?'image/webp':/gif$/i.test(name)?'image/gif':/avif$/i.test(name)?'image/avif':'image/jpeg'});}});
  }
  at+=46+nameLength+extra+comment;
 }
 if(!entries.length)throw Error('В архиве нет изображений.');
 return entries.sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
}
export async function openChapter(item,readWhole,readRange,signal){
 if(item.onlinePages?.length)return item.onlinePages.map((url,n)=>({name:String(n).padStart(4,'0')+'.jpg',async:async()=>{const r=await fetch(url,{signal,cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer'});if(!r.ok)throw Error('Не удалось загрузить страницу. Открой онлайн-главу снова.');const b=await r.blob();if(!b.type.startsWith('image/')||b.size>30*1024*1024)throw Error('Источник не предоставил страницу.');return b;}}));
 if(readRange&&item.chunks?.length&&item.size){try{return await openRangeArchive(item,readRange,signal);}catch(e){if(signal?.aborted)throw e;}}
 const blob=await readWhole(item,{silent:true,signal});const{default:JSZip}=await import('jszip');const zip=await JSZip.loadAsync(blob);
 const entries=Object.values(zip.files).filter(e=>!e.dir&&/\.(jpe?g|png|webp|gif|avif)$/i.test(e.name)).sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
 if(!entries.length||entries.length>1500||entries.some(e=>e._data?.uncompressedSize>30*1024*1024))throw Error('Некорректные изображения в CBZ.');return entries;
}
