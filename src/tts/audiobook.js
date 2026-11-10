// A narrated chapter saved as one audiobook file. Phrases the reader has
// already voiced are kept on the page (16-bit, per chapter) and reused, so the
// file costs only the phrases nobody has listened to yet; those are made by
// the same engine and voices, at most two at a time.

// What a phrase sounds like is decided by these fields; EQ, gain and pitch
// are applied when it is played (or rendered into the file).
export function clipKey(row,language){
 return JSON.stringify([language||'',row.text,row.voice,row.style||'',row.speed||1,row.rate||1,row.tags||[]]);
}
export const usableClip=clip=>!!clip&&clip.done&&!clip.error&&!clip.aborted&&clip.chunks.length>0;
const settled=clip=>clip.ready?Promise.resolve(clip.ready).catch(()=>{}):new Promise(resolve=>{const check=()=>clip.done?resolve():setTimeout(check,40);check();});

function toInt16(chunks){
 const out=new Int16Array(chunks.reduce((n,c)=>n+c.length,0));let at=0;
 for(const chunk of chunks)for(let i=0;i<chunk.length;i++){const v=Math.max(-1,Math.min(1,chunk[i]));out[at++]=v<0?v*32768:v*32767;}
 return out;
}
function toFloat(pcm){const out=new Float32Array(pcm.length);for(let i=0;i<pcm.length;i++)out[i]=pcm[i]/32768;return out;}

// Clips of one chapter. get() gives a finished clip (rebuilt from the stored
// samples) or the one still streaming; track() registers a new clip.
export function createClipStore(){
 const entries=new Map();
 const store={
  has(row,language){return !!entries.get(clipKey(row,language))?.pcm;},
  get(row,language){
   const key=clipKey(row,language),entry=entries.get(key);
   if(!entry)return null;
   if(entry.pcm)return {chunks:[toFloat(entry.pcm)],done:true,error:null,aborted:false,sampleRate:entry.sampleRate,provider:entry.provider,wake:null,ready:Promise.resolve(),stored:true};
   if(entry.clip.done&&!usableClip(entry.clip)){entries.delete(key);return null;}
   return entry.clip;
  },
  track(row,language,clip){
   const key=clipKey(row,language);entries.set(key,{clip});
   settled(clip).then(()=>{
    if(entries.get(key)?.clip!==clip)return;
    if(usableClip(clip))entries.set(key,{pcm:toInt16(clip.chunks),sampleRate:clip.sampleRate,provider:clip.provider});
    else entries.delete(key);
   });
   return clip;
  },
  // make(row) is called only when no clip for the row exists.
  obtain(row,language,make){return store.get(row,language)||store.track(row,language,make());},
  get size(){return entries.size;},
 };
 return store;
}

// How many phrases of the chapter are ready.
export function chapterReadiness(rows,store,language){
 const ready=rows.filter(row=>store.has(row,language)).length;
 return {ready,total:rows.length,missing:rows.length-ready};
}

const abortError=()=>Object.assign(Error('Сохранение остановлено.'),{name:'AbortError'});
function joined(chunks){if(chunks.length===1)return chunks[0];const out=new Float32Array(chunks.reduce((n,c)=>n+c.length,0));let at=0;for(const c of chunks){out.set(c,at);at+=c.length;}return out;}

// Phrases in reading order as {row, audio:Float32Array, sampleRate}. A phrase
// that fails (quota, a dropped stream) is asked again after a pause, three
// tries in all; then the file stops (a book with a missing phrase is worse
// than none) and the voiced phrases stay for the next attempt.
const pause=(ms,signal)=>new Promise((resolve,reject)=>{const t=setTimeout(resolve,ms);signal?.addEventListener('abort',()=>{clearTimeout(t);reject(abortError());},{once:true});});
export async function* chapterAudio({rows,language,store,make,signal,ahead=2,attempts=3,retryDelay=1500,onProgress=()=>{}}){
 const pending=new Map();let made=0,done=0;
 const start=i=>{
  if(i>=rows.length||pending.has(i))return;
  const row=rows[i];
  const job=(async()=>{
   for(let attempt=0;;attempt++){
    if(signal?.aborted)throw abortError();
    const clip=store.obtain(row,language,()=>{made++;return make(row,i,signal,language);});
    await settled(clip);
    if(signal?.aborted)throw abortError();
    if(usableClip(clip))return clip;
    if(attempt<attempts-1){await pause(retryDelay*(attempt+1),signal);continue;}
    throw Object.assign(Error('Фраза '+(i+1)+' не озвучилась: '+(clip.error?.message||'нет звука')+'. Готовые фразы сохранены, повтори позже.'),{phrase:i});
   }
  })();
  job.catch(()=>{});pending.set(i,job);
 };
 for(let i=0;i<rows.length;i++){
  for(let j=i;j<i+Math.max(1,ahead);j++)start(j);
  const clip=await pending.get(i);pending.delete(i);done++;
  onProgress({done,total:rows.length,made});
  yield {row:rows[i],audio:joined(clip.chunks),sampleRate:clip.sampleRate};
 }
}

// One phrase as the listener hears it: pitch by playback rate, the voice EQ
// and gain (chain(ctx,row) from the player), at the file's sample rate.
export async function renderPhrase({audio,sampleRate},row,rate,chain,Offline=globalThis.OfflineAudioContext){
 const speed=row.rate||1,eq=row.eq||{};
 const plain=speed===1&&(row.gain??1)===1&&!eq.low&&!eq.mid&&!eq.high&&sampleRate===rate;
 if(plain||!audio.length)return audio;
 const length=Math.max(1,Math.ceil(audio.length/speed*rate/sampleRate));
 const ctx=new Offline(1,length,rate);
 const buffer=ctx.createBuffer(1,audio.length,sampleRate);buffer.copyToChannel(audio,0);
 const source=ctx.createBufferSource();source.buffer=buffer;source.playbackRate.value=speed;
 const voice=chain(ctx,row);source.connect(voice.input);source.start(0);
 const rendered=await ctx.startRendering();voice.dispose();
 return rendered.getChannelData(0).slice();
}

// ---- Files ----

const text=new TextEncoder();
function tagList(tags){return Object.entries(tags).filter(([,v])=>v!=null&&String(v).trim()).map(([k,v])=>[k,String(v).trim()]);}

// RIFF/WAVE 16-bit mono with a LIST/INFO block (title, album, artist, genre).
const WAV_TAGS={title:'INAM',album:'IPRD',artist:'IART',genre:'IGNR',comment:'ICMT',date:'ICRD'};
export function wavFile(chunks,sampleRate,tags={}){
 const info=[];
 for(const [key,value] of tagList(tags)){
  const id=WAV_TAGS[key];if(!id)continue;
  const bytes=text.encode(value+'\0'),body=new Uint8Array(8+bytes.length+(bytes.length&1)),view=new DataView(body.buffer);
  body.set(text.encode(id),0);view.setUint32(4,bytes.length,true);body.set(bytes,8);info.push(body);
 }
 const infoSize=info.reduce((n,b)=>n+b.length,0),list=infoSize?12+infoSize:0;
 const samples=chunks.reduce((n,c)=>n+c.length,0),data=samples*2;
 const ascii=(view,at,value)=>[...value].forEach((c,i)=>view.setUint8(at+i,c.charCodeAt(0)));
 const head=new DataView(new ArrayBuffer(36));
 ascii(head,0,'RIFF');head.setUint32(4,36+list+data,true);ascii(head,8,'WAVE');ascii(head,12,'fmt ');head.setUint32(16,16,true);
 head.setUint16(20,1,true);head.setUint16(22,1,true);head.setUint32(24,sampleRate,true);head.setUint32(28,sampleRate*2,true);head.setUint16(32,2,true);head.setUint16(34,16,true);
 const parts=[head.buffer];
 if(list){const l=new DataView(new ArrayBuffer(12));ascii(l,0,'LIST');l.setUint32(4,4+infoSize,true);ascii(l,8,'INFO');parts.push(l.buffer,...info);}
 const dataHead=new DataView(new ArrayBuffer(8));ascii(dataHead,0,'data');dataHead.setUint32(4,data,true);
 parts.push(dataHead.buffer,...chunks.map(c=>c instanceof Int16Array?c:toInt16([c])));
 return new Blob(parts,{type:'audio/wav'});
}

// Ogg pages (RFC 3533) carrying Opus (RFC 7845).
const CRC=new Uint32Array(256);
for(let i=0;i<256;i++){let r=i<<24;for(let j=0;j<8;j++)r=r&0x80000000?(r<<1)^0x04c11db7:r<<1;CRC[i]=r>>>0;}
export function oggCrc(bytes){let crc=0;for(let i=0;i<bytes.length;i++)crc=((crc<<8)^CRC[((crc>>>24)^bytes[i])&255])>>>0;return crc;}
export function oggPage(packets,{granule,serial,sequence,first=false,last=false}){
 const lacing=[];
 for(const p of packets){let n=p.length;while(n>=255){lacing.push(255);n-=255;}lacing.push(n);}
 if(lacing.length>255)throw Error('Ogg page holds at most 255 segments.');
 const size=27+lacing.length+packets.reduce((n,p)=>n+p.length,0),page=new Uint8Array(size),view=new DataView(page.buffer);
 page.set(text.encode('OggS'),0);page[4]=0;page[5]=(first?2:0)|(last?4:0);
 view.setBigUint64(6,BigInt(granule),true);view.setUint32(14,serial,true);view.setUint32(18,sequence,true);view.setUint32(22,0,true);
 page[26]=lacing.length;page.set(lacing,27);let at=27+lacing.length;for(const p of packets){page.set(p,at);at+=p.length;}
 view.setUint32(22,oggCrc(page),true);
 return page;
}
export function opusHead({channels=1,preSkip=312,inputRate=48000}={}){
 const head=new Uint8Array(19),view=new DataView(head.buffer);
 head.set(text.encode('OpusHead'),0);head[8]=1;head[9]=channels;view.setUint16(10,preSkip,true);view.setUint32(12,inputRate,true);view.setInt16(16,0,true);head[18]=0;
 return head;
}
const VORBIS_TAGS={title:'TITLE',album:'ALBUM',artist:'ARTIST',genre:'GENRE',comment:'COMMENT',date:'DATE',language:'LANGUAGE'};
export function opusTags(tags={},vendor='MediaVault'){
 const comments=tagList(tags).filter(([k])=>VORBIS_TAGS[k]).map(([k,v])=>text.encode(VORBIS_TAGS[k]+'='+v));
 const vendorBytes=text.encode(vendor),size=8+4+vendorBytes.length+4+comments.reduce((n,c)=>n+4+c.length,0);
 const out=new Uint8Array(size),view=new DataView(out.buffer);let at=0;
 out.set(text.encode('OpusTags'),0);at=8;view.setUint32(at,vendorBytes.length,true);at+=4;out.set(vendorBytes,at);at+=vendorBytes.length;
 view.setUint32(at,comments.length,true);at+=4;for(const c of comments){view.setUint32(at,c.length,true);at+=4;out.set(c,at);at+=c.length;}
 return out;
}
// packets: [{data:Uint8Array, samples}] with samples at 48 kHz.
export function oggOpusFile(packets,{preSkip=312,inputRate=48000,totalSamples48,tags={},serial=0x4d566175}={}){
 const pages=[oggPage([opusHead({preSkip,inputRate})],{granule:0,serial,sequence:0,first:true}),oggPage([opusTags(tags)],{granule:0,serial,sequence:1})];
 let granule=0,sequence=2,group=[],lacing=0;
 const end=preSkip+(totalSamples48??packets.reduce((n,p)=>n+p.samples,0)-preSkip);
 const flush=last=>{if(!group.length&&!last)return;pages.push(oggPage(group.map(p=>p.data),{granule:last?Math.min(granule,end):granule,serial,sequence:sequence++,last}));group=[];lacing=0;};
 packets.forEach((packet,i)=>{
  const segments=Math.floor(packet.data.length/255)+1;
  if(lacing+segments>255||group.length>=50)flush(false);
  group.push(packet);lacing+=segments;granule+=packet.samples;
  if(i===packets.length-1)flush(true);
 });
 if(!packets.length)flush(true);
 return new Blob(pages,{type:'audio/ogg; codecs=opus'});
}

const OPUS_RATES=[8000,12000,16000,24000,48000];
// The file writer: Opus in Ogg through WebCodecs where the browser has it,
// 16-bit WAV otherwise. write(Float32Array) in order, then finish() → Blob.
export async function audiobookWriter(sourceRate,{tags={},bitrate=48000,Encoder=globalThis.AudioEncoder,Data=globalThis.AudioData}={}){
 const opusRate=OPUS_RATES.includes(sourceRate)?sourceRate:48000;
 const config={codec:'opus',sampleRate:opusRate,numberOfChannels:1,bitrate};
 let opus=false;
 try{opus=!!Encoder&&!!Data&&!!(await Encoder.isConfigSupported(config)).supported;}catch{opus=false;}
 if(!opus){
  const chunks=[];let samples=0;
  return {format:'wav',ext:'wav',rate:sourceRate,get seconds(){return samples/sourceRate;},
   async write(audio){chunks.push(toInt16([audio]));samples+=audio.length;},
   async finish(){return wavFile(chunks,sourceRate,tags);},close(){}};
 }
 const packets=[];let failure=null,preSkip=312,timestamp=0,samples=0;
 const encoder=new Encoder({
  output(chunk,meta){
   const description=meta?.decoderConfig?.description;
   if(description){const bytes=new Uint8Array(description.buffer||description,description.byteOffset||0,description.byteLength);if(bytes.length>=12&&new TextDecoder().decode(bytes.slice(0,8))==='OpusHead')preSkip=bytes[10]|bytes[11]<<8;}
   const data=new Uint8Array(chunk.byteLength);chunk.copyTo(data);
   packets.push({data,samples:Math.round((chunk.duration||20000)*48/1000)});
  },
  error(e){failure=e;},
 });
 encoder.configure(config);
 return {format:'opus',ext:'opus',rate:opusRate,get seconds(){return samples/opusRate;},
  async write(audio){
   if(failure)throw failure;
   for(let at=0;at<audio.length;at+=opusRate){
    const part=audio.subarray(at,Math.min(audio.length,at+opusRate));
    const frame=new Data({format:'f32-planar',sampleRate:opusRate,numberOfFrames:part.length,numberOfChannels:1,timestamp,data:part.slice()});
    encoder.encode(frame);frame.close();timestamp+=Math.round(part.length/opusRate*1e6);samples+=part.length;
    while(encoder.encodeQueueSize>8)await new Promise(r=>setTimeout(r,4));
   }
  },
  async finish(){
   await encoder.flush();encoder.close();if(failure)throw failure;
   return oggOpusFile(packets,{preSkip,inputRate:opusRate,totalSamples48:Math.round(samples*48000/opusRate),tags});
  },
  close(){try{if(encoder.state!=='closed')encoder.close();}catch{}},
 };
}

// "Book — Chapter 3.opus", safe on Windows, macOS and phones.
export function audiobookFileName(book,chapter,ext){
 const clean=value=>String(value||'').replace(/[\\/:*?"<>|\u0000-\u001f]+/g,' ').replace(/\s+/g,' ').trim();
 const b=clean(book),c=clean(chapter);
 const name=(b&&c&&!c.startsWith(b)?b+' — '+c:c||b||'Аудиокнига').slice(0,150).replace(/[. ]+$/,'');
 return name+'.'+ext;
}
