/* Local per-device streaming proxy. OAuth tokens and CryptoKeys stay in worker RAM. */
const STORAGE_CACHE="mediavault-ciphertext-v1";
const SHELL_CACHE="mediavault-app-v5";
const CHUNK_SIZE=4*1024*1024;
const CHUNK_LIMIT=160;
// A worker may control several tabs with different libraries or accounts.
const sessions=new Map();
const cipherMemory=new Map(),cipherPending=new Map();
let sessionSequence=0;
const pendingSessions=new Map();
const encoder=new TextEncoder();
function b64(s){return Uint8Array.from(atob(s),c=>c.charCodeAt(0));}
self.addEventListener("install",event=>event.waitUntil(self.skipWaiting()));
self.addEventListener("activate",event=>{
  event.waitUntil((async()=>{
    for(const name of await caches.keys())
      if(name.startsWith("mediavault-app-")&&name!==SHELL_CACHE)await caches.delete(name);
    await self.clients.claim();
  })());
});
function readSession(data){
  if(data?.type!=="SESSION"||!data.key||typeof data.token!=="string"||!Array.isArray(data.items))return null;
  return {tag:++sessionSequence,token:data.token,key:data.key,items:new Map(data.items.map(item=>[item.id,item]))};
}
self.addEventListener("message",event=>{
  const clientId=event.source?.id;
  if(!clientId)return;
  if(event.data?.type==="SESSION"){
    const session=readSession(event.data);
    if(session){
      sessions.set(clientId,session);
      pendingSessions.get(clientId)?.finish(session);
    }
    event.ports?.[0]?.postMessage({ready:!!session});
  }
  if(event.data?.type==="CLEAR_SESSION"){
    sessions.delete(clientId);
    for(const key of cipherMemory.keys())if(key.startsWith(clientId+"|"))cipherMemory.delete(key);
    pendingSessions.get(clientId)?.finish(null);
  }
});
async function sessionFor(clientId){
  if(!clientId)return null;
  if(sessions.has(clientId))return sessions.get(clientId);
  if(pendingSessions.has(clientId))return pendingSessions.get(clientId).promise;
  const client=await self.clients.get(clientId);
  if(!client)return null;
  // Another request may have restored the session while clients.get was pending.
  if(sessions.has(clientId))return sessions.get(clientId);
  if(pendingSessions.has(clientId))return pendingSessions.get(clientId).promise;
  const channel=new MessageChannel();
  let finish,timer,finished=false;
  const promise=new Promise(resolve=>{
    finish=session=>{
      if(finished)return;
      finished=true;
      clearTimeout(timer);
      channel.port1.close();
      channel.port2.close();
      pendingSessions.delete(clientId);
      resolve(session);
    };
  });
  pendingSessions.set(clientId,{promise,finish});
  channel.port1.onmessage=event=>{
    if(finished)return;
    const session=readSession(event.data);
    if(session)sessions.set(clientId,session);
    finish(session);
  };
  timer=setTimeout(()=>finish(null),8000);
  try{client.postMessage({type:"SESSION_REQUIRED"},[channel.port2]);}
  catch{finish(null);}
  return promise;
}
self.addEventListener("fetch",event=>{
  const url=new URL(event.request.url);
  const prefix=new URL("./__media__/",self.registration.scope).pathname;
  if(url.origin===self.location.origin&&url.pathname.startsWith(prefix)){
    let id;
    try{id=decodeURIComponent(url.pathname.slice(prefix.length));}
    catch{event.respondWith(new Response("Некорректный адрес",{status:400}));return;}
    event.respondWith(serveRange(event.request,id,event.clientId,promise=>{try{event.waitUntil?.(promise);}catch{promise.catch(()=>{});}}));
    return;
  }
  const shell=offlineShell(event.request,url);
  if(shell)event.respondWith(shell);
});
// Offline start: the page itself is network-first with the last good copy as a
// fallback; built assets (hashed names) and the few runtime files are kept
// once fetched. Only this site's own static files, never API or media.
const SHELL_FILES=/\/(?:assets\/[^/]+|config\.js|crypto\.js|drive\.js|icon\.svg|manifest\.webmanifest)$/;
function offlineShell(request,url){
  if(request.method!=="GET"||url.origin!==self.location.origin)return null;
  const scope=new URL(self.registration.scope).pathname;
  if(!url.pathname.startsWith(scope))return null;
  if(request.mode==="navigate")return (async()=>{
    const cache=await caches.open(SHELL_CACHE).catch(()=>null);
    try{
      const response=await fetch(request);
      if(response.ok&&cache)cache.put(scope,response.clone()).catch(()=>{});
      return response;
    }catch(error){
      const saved=cache&&await cache.match(scope);
      if(saved)return saved;
      throw error;
    }
  })();
  if(!SHELL_FILES.test(url.pathname))return null;
  return (async()=>{
    const cache=await caches.open(SHELL_CACHE).catch(()=>null);
    const saved=cache&&await cache.match(request);
    const fresh=fetch(request).then(response=>{if(response.ok&&cache)cache.put(request,response.clone()).catch(()=>{});return response;});
    if(saved){fresh.catch(()=>{});return /\/assets\//.test(url.pathname)?saved:fresh.catch(()=>saved);}
    return fresh;
  })();
}
async function downloadEncrypted(session,fileId,signal,clientId,background){
  let cache=null;
  try{cache=await caches.open(STORAGE_CACHE);}catch{}
  const cacheKey="https://mediavault.invalid/cipher/"+encodeURIComponent(fileId);
  if(cache){
    try{const hit=await cache.match(cacheKey);if(hit)return hit.arrayBuffer();}catch{}
  }
  if(!session.token)throw Error("Авторизуйтесь заново — сеанс Drive истёк.");
  const url="https://www.googleapis.com/drive/v3/files/"+encodeURIComponent(fileId)+"?alt=media";
  let data=null;
  for(let attempt=0;attempt<5;attempt++){
    const resp=await fetch(url,{signal,headers:{Authorization:"Bearer "+session.token}});
    if(resp.ok){data=await resp.arrayBuffer();break;}
    if(resp.status===401){
      // The page must request a fresh token from a user gesture.
      const client=await self.clients.get(clientId);
      client?.postMessage({type:"DRIVE_AUTH_REQUIRED"});
      throw Error("Авторизуйтесь заново — сеанс Drive истёк.");
    }
    const errorBody=await resp.text();
    const transient=[429,500,502,503,504].includes(resp.status)||
      (resp.status===403&&/rateLimitExceeded|userRateLimitExceeded/i.test(errorBody));
    if(!transient||attempt===4)throw Error("Google Drive: HTTP "+resp.status);
    await new Promise(resolve=>setTimeout(resolve,400*2**attempt+Math.random()*300));
  }
  if(!data)throw Error("Google Drive не прислал данные");
  // Cache failures, including an exhausted iOS quota, must not break playback.
  if(cache){
    const store=(async()=>{try{
      await cache.put(cacheKey,new Response(data,{headers:{"Content-Type":"application/octet-stream"}}));
      const keys=await cache.keys();
      if(keys.length>CHUNK_LIMIT)for(const key of keys.slice(0,keys.length-CHUNK_LIMIT))await cache.delete(key);
    }catch{}})();
    background?.(store);
  }
  return data;
}
// Only ciphertext is shared/cached. Each Range independently authenticates and
// decrypts its bytes with the requesting tab's key; one cancelled Range cannot
// cancel another subscriber to the same Drive download.
async function encryptedBlock(session,fileId,signal,clientId,background){
  if(signal?.aborted)throw new DOMException("Запрос отменён","AbortError");
  const key=clientId+"|"+session.tag+"|"+fileId,hit=cipherMemory.get(key);
  if(hit&&hit.until>Date.now()){cipherMemory.delete(key);cipherMemory.set(key,hit);return hit.data;}
  cipherMemory.delete(key);
  let task=cipherPending.get(key);
  if(!task){
    task={controller:new AbortController(),users:0};
    task.promise=downloadEncrypted(session,fileId,task.controller.signal,clientId,background).then(data=>{
      if(sessions.get(clientId)===session){
        cipherMemory.set(key,{data,until:Date.now()+60000});
        while(cipherMemory.size>4)cipherMemory.delete(cipherMemory.keys().next().value);
      }
      return data;
    }).finally(()=>{if(cipherPending.get(key)===task)cipherPending.delete(key);});
    cipherPending.set(key,task);
  }
  task.users++;
  return new Promise((resolve,reject)=>{
    let done=false;
    function finish(error,data){if(done)return;done=true;signal?.removeEventListener('abort',abort);task.users--;if(task.users===0&&cipherPending.get(key)===task){cipherPending.delete(key);task.controller.abort();}error?reject(error):resolve(data);}
    const abort=()=>finish(new DOMException("Запрос отменён","AbortError"));
    signal?.addEventListener('abort',abort,{once:true});
    task.promise.then(data=>finish(null,data),error=>finish(error));
    if(signal?.aborted)abort();
  });
}
async function chunkPlain(session,item,n,signal,clientId,background){
  const chunk=item.chunks[n];
  if(!chunk)throw Error("Не найден зашифрованный блок");
  const encrypted=await encryptedBlock(session,chunk.fileId,signal,clientId,background);
  return crypto.subtle.decrypt({name:"AES-GCM",iv:b64(chunk.iv),
    additionalData:encoder.encode(item.id+":"+n)},session.key,encrypted);
}
function parseRange(header,size){
  // Unsupported units, malformed syntax and multipart ranges are ignored per HTTP.
  if(!header)return null;
  const match=/^bytes=(\d*)-(\d*)$/i.exec(header.trim());
  if(!match||(!match[1]&&!match[2]))return null;
  let start,end;
  if(!match[1]){
    const suffix=Number(match[2]);
    if(!Number.isSafeInteger(suffix)||suffix<=0)return false;
    start=Math.max(0,size-suffix);end=size-1;
  }else{
    start=Number(match[1]);
    end=match[2]?Number(match[2]):size-1;
    if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>=size||end<start)return false;
    end=Math.min(end,size-1);
  }
  return {start,end};
}
// Build a front seek index for streamed fMP4 from FFmpeg's trailing index.
// The virtual playback response leaves the encrypted archive bytes unchanged.
function frontMp4Index(head,tail,mediaEnd,duration){
  const view=bytes=>new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  function* boxes(data,start=0,end=data.byteLength){
    while(start+8<=end){
      const size=data.getUint32(start);
      if(size<8||start+size>end)return;
      yield {type:data.getUint32(start+4),start:start+8,end:start+size};
      start+=size;
    }
  }
  const header=view(head),index=view(tail);
  const moov=[...boxes(header)].find(box=>box.type===0x6d6f6f76);
  if(!moov||index.getUint32(4)!==0x6d667261)return null; // moov, mfra
  const tracks=[];
  for(const track of boxes(header,moov.start,moov.end)){
    if(track.type!==0x7472616b)continue;
    const children=[...boxes(header,track.start,track.end)];
    const tkhd=children.find(box=>box.type===0x746b6864);
    const mdia=children.find(box=>box.type===0x6d646961);
    if(!tkhd||!mdia)continue;
    const media=[...boxes(header,mdia.start,mdia.end)];
    const hdlr=media.find(box=>box.type===0x68646c72);
    const mdhd=media.find(box=>box.type===0x6d646864);
    if(!hdlr||!mdhd)continue;
    const handler=header.getUint32(hdlr.start+8);
    if(handler!==0x76696465&&handler!==0x736f756e)continue;
    const id=header.getUint32(tkhd.start+(header.getUint8(tkhd.start)?20:12));
    const scale=header.getUint32(mdhd.start+(header.getUint8(mdhd.start)?20:12));
    const tfra=[...boxes(index,8)].find(box=>box.type===0x74667261&&index.getUint32(box.start+4)===id);
    if(!tfra||!scale)return null;
    const wide=index.getUint8(tfra.start)===1;
    const lengths=index.getUint32(tfra.start+8);
    const stride=(wide?16:8)+3+(lengths&3)+(lengths>>2&3)+(lengths>>4&3);
    const count=index.getUint32(tfra.start+12);
    const records=tfra.start+16;
    if(!count||count>65535||records+stride*count>tfra.end)return null;
    const read=(n,offset)=>wide?Number(index.getBigUint64(records+n*stride+offset)):index.getUint32(records+n*stride+offset);
    const position=n=>read(n,wide?8:4),time=n=>read(n,0);
    const first=position(0);
    if(first!==moov.end||first+8>head.length||header.getUint32(first+4)!==0x6d6f6f66)return null;
    tracks.push({id,scale,count,first,position,time,length:40+count*12});
  }
  if(!tracks.length)return null;
  const first=tracks[0].first;
  if(tracks.some(track=>track.first!==first))return null;
  const shift=tracks.reduce((sum,track)=>sum+track.length,0);
  const prefix=new Uint8Array(first+shift);
  prefix.set(head.subarray(0,first));
  let cursor=first;
  for(const {id,scale,count,position,time,length} of tracks){
    const sidx=new DataView(prefix.buffer,cursor,length);
    sidx.setUint32(0,length);sidx.setUint32(4,0x73696478);sidx.setUint32(8,0x01000000);
    sidx.setUint32(12,id);sidx.setUint32(16,scale);
    sidx.setBigUint64(20,BigInt(time(0)));
    sidx.setBigUint64(28,BigInt(prefix.length-cursor-length));
    sidx.setUint16(38,count);
    for(let n=0;n<count;n++){
      const size=(n+1<count?position(n+1):mediaEnd)-position(n);
      const ticks=(n+1<count?time(n+1):Math.round(duration*scale))-time(n);
      if(!Number.isSafeInteger(size)||size<=0||size>0x7fffffff||!Number.isSafeInteger(ticks)||ticks<=0||ticks>0xffffffff)return null;
      sidx.setUint32(40+n*12,size);
      sidx.setUint32(44+n*12,ticks);
      sidx.setUint32(48+n*12,0x90000000);
    }
    cursor+=length;
  }
  return {prefix,shift,size:mediaEnd+shift};
}
async function indexedMp4(session,item,clientId,background){
  session.playbackIndexes??=new Map();
  const cache=session.playbackIndexes;
  if(!cache.has(item.id)){
    const pending=(async()=>{
      const last=item.chunks.length-1;
      const chunk=async n=>new Uint8Array(await chunkPlain(session,item,n,undefined,clientId,background));
      const [head,tail]=await Promise.all([chunk(0),chunk(last)]);
      if(tail.length<16)return null;
      const footer=new DataView(tail.buffer,tail.byteOffset+tail.length-16,16);
      if(footer.getUint32(0)!==16||footer.getUint32(4)!==0x6d66726f)return null;
      const length=footer.getUint32(12),start=item.size-length;
      if(length<24||length>8*1024*1024||start<0)return null;
      const index=new Uint8Array(length);
      for(let n=Math.floor(start/CHUNK_SIZE);n<=last;n++){
        const bytes=n===last?tail:await chunk(n);
        const left=Math.max(0,start-n*CHUNK_SIZE);
        index.set(bytes.subarray(left),Math.max(0,n*CHUNK_SIZE-start));
      }
      return frontMp4Index(head,index,start,item.mediaInfo.duration);
    })().catch(error=>{cache.delete(item.id);throw error;});
    cache.set(item.id,pending);
    while(cache.size>4)cache.delete(cache.keys().next().value);
  }
  return cache.get(item.id);
}
function decryptedStream(session,item,start,end,request,clientId,background,prefix){
  let n=Math.floor(start/CHUNK_SIZE),cancelled=false;
  const last=Math.floor(end/CHUNK_SIZE);
  const aborter=new AbortController();
  const abort=()=>aborter.abort();
  request.signal.addEventListener("abort",abort,{once:true});
  if(request.signal.aborted)abort();
  function cleanup(){request.signal.removeEventListener("abort",abort);}
  return new ReadableStream({
    async pull(controller){
      try{
        if(prefix){controller.enqueue(prefix);prefix=null;return;}
        const raw=new Uint8Array(await chunkPlain(session,item,n,aborter.signal,clientId,background));
        if(cancelled)return;
        if(aborter.signal.aborted)throw new DOMException("Запрос отменён","AbortError");
        const offset=n*CHUNK_SIZE;
        const left=Math.max(0,start-offset),right=Math.min(raw.length,end-offset+1);
        if(right<=left||raw.length!==Math.min(CHUNK_SIZE,item.size-offset))
          throw Error("Повреждённый размер блока");
        controller.enqueue(raw.subarray(left,right));
        if(n++===last){cleanup();controller.close();}
      }catch(error){cleanup();if(!cancelled)controller.error(error);}
    },
    cancel(){cancelled=true;abort();cleanup();}
  },{highWaterMark:0});
}
async function serveRange(request,id,clientId,background){
  try{
    if(request.method!=="GET"&&request.method!=="HEAD")
      return new Response(null,{status:405,headers:{Allow:"GET, HEAD"}});
    const session=await sessionFor(clientId);
    if(!session)return new Response("Сначала откройте библиотеку",{status:503});
    const item=session.items.get(id);
    if(!item)return new Response("Медиа не найдено",{status:404});
    if(!Number.isSafeInteger(item.size)||item.size<=0)return new Response("Пустой или повреждённый файл",{status:404});
    const playbackIndex=item.mime==="video/mp4"&&item.size>=CHUNK_SIZE&&item.mediaInfo?.duration>0
      ?await indexedMp4(session,item,clientId,background):null;
    const size=playbackIndex?.size??item.size;
    // Range applies to GET only; HEAD returns metadata without decrypting a block.
    const range=request.method==="GET"?parseRange(request.headers.get("Range"),size):null;
    if(range===false)return new Response(null,{status:416,headers:{"Content-Range":"bytes */"+size}});
    const start=range?range.start:0,end=range?range.end:size-1;
    const headers={"Content-Type":item.mime||"application/octet-stream",
      "Accept-Ranges":"bytes","Content-Length":String(end-start+1),"Cache-Control":"no-store"};
    if(range)headers["Content-Range"]="bytes "+start+"-"+end+"/"+size;
    let body=null;
    if(request.method==="GET"){
      const prefix=playbackIndex&&start<playbackIndex.prefix.length
        ?playbackIndex.prefix.subarray(start,end+1):null;
      body=prefix?.length===end-start+1?prefix:decryptedStream(session,item,
        Math.max(start,playbackIndex?.prefix.length??0)-(playbackIndex?.shift??0),
        end-(playbackIndex?.shift??0),request,clientId,background,prefix);
    }
    return new Response(body,{status:range?206:200,headers});
  }catch(error){
    return new Response("Ошибка расшифровки или Google Drive: "+error.message,{status:503,
      headers:{"Content-Type":"text/plain;charset=utf-8"}});
  }
}
