// Device-side chapter files. Pages are appended as Blob parts, so the browser
// keeps them in its blob store instead of one growing ArrayBuffer.
const encoder=new TextEncoder();
let table;
export function crc32(bytes){
 if(!table){table=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;table[n]=c>>>0;}}
 let crc=0xffffffff;for(let i=0;i<bytes.length;i++)crc=table[(crc^bytes[i])&0xff]^(crc>>>8);return (crc^0xffffffff)>>>0;
}
export function imageExtension(bytes){
 const b=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);
 if(b[0]===0xff&&b[1]===0xd8)return 'jpg';
 if(b[0]===0x89&&b[1]===0x50&&b[2]===0x4e&&b[3]===0x47)return 'png';
 if(b[0]===0x52&&b[1]===0x49&&b[2]===0x46&&b[3]===0x46&&b[8]===0x57&&b[9]===0x45&&b[10]===0x42&&b[11]===0x50)return 'webp';
 if(b[0]===0x47&&b[1]===0x49&&b[2]===0x46)return 'gif';
 if(b[4]===0x66&&b[5]===0x74&&b[6]===0x79&&b[7]===0x70)return 'avif';
 return '';
}
// Uncompressed ZIP (CBZ readers expect stored images; they are already compressed).
export function createZip(){
 const parts=[],central=[];let offset=0;
 const stamp=(()=>{const d=new Date();return {time:(d.getHours()<<11)|(d.getMinutes()<<5)|(d.getSeconds()>>1),date:((d.getFullYear()-1980)<<9)|((d.getMonth()+1)<<5)|d.getDate()};})();
 return {
  // data: bytes, or a Blob with its precomputed CRC-32 (keeps pages out of the JS heap).
  add(name,bytes,checksum){
   const blob=bytes instanceof Blob,data=blob?bytes:bytes instanceof Uint8Array?bytes:new Uint8Array(bytes),file=encoder.encode(name),size=blob?data.size:data.length;
   if(blob&&!Number.isInteger(checksum))throw Error('Для страницы-Blob нужна контрольная сумма.');
   const crc=blob?checksum>>>0:crc32(data);
   if(offset+size>0xfffffff0)throw Error('Файл главы превышает 4 ГБ.');
   const head=new DataView(new ArrayBuffer(30));
   head.setUint32(0,0x04034b50,true);head.setUint16(4,20,true);head.setUint16(6,0x0800,true);head.setUint16(8,0,true);head.setUint16(10,stamp.time,true);head.setUint16(12,stamp.date,true);
   head.setUint32(14,crc,true);head.setUint32(18,size,true);head.setUint32(22,size,true);head.setUint16(26,file.length,true);head.setUint16(28,0,true);
   parts.push(new Blob([head.buffer,file,data]));
   central.push({file,crc,size,offset});offset+=30+file.length+size;
  },
  get count(){return central.length;},
  finish(type='application/zip'){
   const start=offset;let size=0;const rows=[];
   for(const row of central){
    const head=new DataView(new ArrayBuffer(46));
    head.setUint32(0,0x02014b50,true);head.setUint16(4,20,true);head.setUint16(6,20,true);head.setUint16(8,0x0800,true);head.setUint16(10,0,true);head.setUint16(12,stamp.time,true);head.setUint16(14,stamp.date,true);
    head.setUint32(16,row.crc,true);head.setUint32(20,row.size,true);head.setUint32(24,row.size,true);head.setUint16(28,row.file.length,true);head.setUint32(42,row.offset,true);
    rows.push(head.buffer,row.file);size+=46+row.file.length;
   }
   const end=new DataView(new ArrayBuffer(22));
   end.setUint32(0,0x06054b50,true);end.setUint16(8,central.length,true);end.setUint16(10,central.length,true);end.setUint32(12,size,true);end.setUint32(16,start,true);
   return new Blob([...parts,...rows,end.buffer],{type});
  }
 };
}
// Minimal PDF: one JPEG image per page, page size follows the image (1 px = 0.75 pt).
export function createPdf(){
 const parts=[],offsets=[],pages=[];let offset=0,next=3;
 const push=value=>{const part=typeof value==='string'?encoder.encode(value):value;parts.push(part);offset+=part.byteLength??part.size;};
 const object=(id,body,stream)=>{offsets[id]=offset;push(id+' 0 obj\n'+body);if(stream){push('\nstream\n');push(stream);push('\nendstream');}push('\nendobj\n');};
 push('%PDF-1.4\n%\xe2\xe3\xcf\xd3\n');
 return {
  add(jpeg,width,height){
   const data=jpeg instanceof Blob?jpeg:new Blob([jpeg]),w=+(width*.75).toFixed(2),h=+(height*.75).toFixed(2),page=next++,content=next++,image=next++;
   const draw=encoder.encode('q '+w+' 0 0 '+h+' 0 0 cm /Im0 Do Q');
   object(image,'<< /Type /XObject /Subtype /Image /Width '+width+' /Height '+height+' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length '+data.size+' >>',data);
   object(content,'<< /Length '+draw.length+' >>',draw);
   object(page,'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 '+w+' '+h+'] /Resources << /XObject << /Im0 '+image+' 0 R >> >> /Contents '+content+' 0 R >>');
   pages.push(page);
  },
  get count(){return pages.length;},
  finish(){
   object(1,'<< /Type /Catalog /Pages 2 0 R >>');
   object(2,'<< /Type /Pages /Kids ['+pages.map(p=>p+' 0 R').join(' ')+'] /Count '+pages.length+' >>');
   const xref=offset;let table='xref\n0 '+next+'\n0000000000 65535 f \n';
   for(let id=1;id<next;id++)table+=String(offsets[id]).padStart(10,'0')+' 00000 n \n';
   push(table+'trailer\n<< /Size '+next+' /Root 1 0 R >>\nstartxref\n'+xref+'\n%%EOF\n');
   return new Blob(parts,{type:'application/pdf'});
  }
 };
}
