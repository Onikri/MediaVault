// Adding a title from the owner's computer: files go through the ordinary
// encrypted upload into the Drive collection; a chosen catalogue card gives the
// collection its identity, so covers, descriptions, sources and enrichment
// follow the same path as an imported title. Manga page folders are packed
// into one CBZ per chapter (stored, not recompressed) in the browser.
export const LOCAL_KINDS=[
 ['book','Книга','book','book','.epub,.pdf,.fb2,.txt'],
 ['ranobe','Ранобэ','ranobe','ranobe','.epub,.pdf,.fb2,.txt'],
 ['manga','Манга, манхва','manga','manga','.cbz,.zip,.jpg,.jpeg,.png,.webp,.avif,.gif'],
 ['anime','Аниме','anime','anime','.mp4,.webm,.m4v,.mov,.mkv'],
 ['movie','Фильм','video','movie','.mp4,.webm,.m4v,.mov,.mkv'],
 ['tv','Сериал','video','tv','.mp4,.webm,.m4v,.mov,.mkv'],
 ['music','Музыка','music','','.mp3,.m4a,.aac,.ogg,.opus,.flac,.wav'],
];
export const localKind=id=>LOCAL_KINDS.find(k=>k[0]===id)||LOCAL_KINDS[0];
const IMAGE=/\.(jpe?g|png|webp|avif|gif)$/i;
const extension=name=>String(name).toLowerCase().split('.').pop();

// The title name a selection suggests: the chosen folder, else the file name
// without volume/chapter/episode numbering.
export function suggestedTitle(files){
 const list=[...files||[]];if(!list.length)return '';
 const path=String(list[0].webkitRelativePath||'');
 if(path.includes('/'))return path.split('/')[0].replace(/[_]+/g,' ').trim();
 const name=list[0].name.replace(/\.[^.]+$/,'').replace(/[_.]+/g,' ');
 return name.replace(/\s*[\[(].*?[\])]\s*/g,' ').replace(/\b(?:vol(?:ume)?|том|t|ch(?:apter)?|глава|гл|ep(?:isode)?|серия|s\d+e)\s*\.?\s*\d+.*$/i,'').replace(/\s*[-–—]?\s*\d{1,4}\s*$/,'').replace(/\s+/g,' ').trim()||name.trim();
}

// Accepts what this kind can open; returns {files,rejected}.
export function acceptedFiles(kind,files){
 const allowed=new Set(localKind(kind)[4].split(',').map(v=>v.slice(1)));
 const ok=[],rejected=[];for(const f of files||[])(allowed.has(extension(f.name))?ok:rejected).push(f);
 return {files:ok,rejected};
}

// Manga pages chosen as images: one chapter per folder (or one chapter when
// all pages lie together). Pages keep natural order (2 before 10).
export function mangaChapters(files){
 const pages=[...files].filter(f=>IMAGE.test(f.name)),groups=new Map();
 for(const f of pages){const parts=String(f.webkitRelativePath||f.name).split('/');const key=parts.length>2?parts.slice(1,-1).join(' · '):parts.length===2?parts[0]:'Глава 1';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(f);}
 const order=(a,b)=>a.localeCompare(b,'ru',{numeric:true,sensitivity:'base'});
 return [...groups].sort(([a],[b])=>order(a,b)).map(([name,list])=>({name,pages:list.sort((a,b)=>order(a.name,b.name))}));
}

const TABLE=(()=>{const t=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;t[n]=c>>>0;}return t;})();
export function crc32(bytes){let c=0xffffffff;for(let i=0;i<bytes.length;i++)c=TABLE[(c^bytes[i])&0xff]^(c>>>8);return (c^0xffffffff)>>>0;}

// A stored ZIP (method 0): pages are already compressed images. ZIP64 is not
// needed — one chapter stays far below 4 GiB, which is checked.
export async function packCbz(name,pages){
 if(!pages.length||pages.length>1500)throw Error('В главе «'+name+'» должно быть от 1 до 1500 страниц.');
 const encoder=new TextEncoder(),local=[],central=[];let offset=0;
 for(const [index,page] of pages.entries()){
  const bytes=new Uint8Array(await page.arrayBuffer()),file=encoder.encode(String(index+1).padStart(4,'0')+'.'+extension(page.name)),crc=crc32(bytes);
  const head=new DataView(new ArrayBuffer(30));
  head.setUint32(0,0x04034b50,true);head.setUint16(4,20,true);head.setUint16(6,0x0800,true);head.setUint32(14,crc,true);head.setUint32(18,bytes.length,true);head.setUint32(22,bytes.length,true);head.setUint16(26,file.length,true);
  const entry=new DataView(new ArrayBuffer(46));
  entry.setUint32(0,0x02014b50,true);entry.setUint16(4,20,true);entry.setUint16(6,20,true);entry.setUint16(8,0x0800,true);entry.setUint32(16,crc,true);entry.setUint32(20,bytes.length,true);entry.setUint32(24,bytes.length,true);entry.setUint16(28,file.length,true);entry.setUint32(42,offset,true);
  local.push(head.buffer,file,bytes);central.push(entry.buffer,file);offset+=30+file.length+bytes.length;
  if(offset>0xfffffff0)throw Error('Глава «'+name+'» больше 4 ГБ. Раздели её на части.');
 }
 const size=central.reduce((sum,part)=>sum+(part.byteLength??part.length),0),end=new DataView(new ArrayBuffer(22));
 end.setUint32(0,0x06054b50,true);end.setUint16(8,pages.length,true);end.setUint16(10,pages.length,true);end.setUint32(12,size,true);end.setUint32(16,offset,true);
 const safe=String(name).replace(/[\\/:*?"<>|]+/g,' ').replace(/\s+/g,' ').trim().slice(0,120)||'Глава';
 return new File([...local,...central,end.buffer],safe+'.cbz',{type:'application/vnd.comicbook+zip'});
}

// The stored title profile for a chosen catalogue card. Shikimori cards also
// give the collection its MAL id, which the regular enrichment completes.
export function cardProfile(card){
 if(!card)return null;
 const link=(card.links||[])[0]?.url||'';
 return {version:4,partial:true,language:'ru',title:card.title,aliases:(card.aliases||[]).slice(0,12),authors:(card.authors||[]).slice(0,4),
  description:card.description||'',cover:card.cover||'',year:card.year||null,format:card.format||'',genres:card.genres||[],themes:card.tags||[],
  source:card.provider,sourceId:card.ids?.mal?String(card.ids.mal):'',sourceURL:link,ids:card.ids||{},characters:[],related:[],screenshots:[]};
}
export const malIdentity=card=>/^[1-9]\d{0,11}$/.test(String(card?.ids?.mal||''))?Number(card.ids.mal):undefined;
