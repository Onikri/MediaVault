// Geometry is kept in original pixels. Packing never shrinks source lettering.
export const BLOCK_LIMITS={width:1600,height:2264,gap:20,label:26,regions:100,pixels:24_000_000,sourceBytes:24*1024*1024};
export function readingOrder(regions,direction='rtl'){
 const pending=[...regions].sort((a,b)=>a.bbox[1]-b.bbox[1]||a.bbox[0]-b.bbox[0]),ordered=[];
 while(pending.length){const first=pending.shift(),row=[first],mid=(first.bbox[1]+first.bbox[3])/2;
  for(let i=0;i<pending.length;i++){const b=pending[i].bbox;if(b[1]>first.bbox[3])break;if(mid>=b[1]&&mid<=b[3])row.push(...pending.splice(i--,1));}
  row.sort((a,b)=>direction==='ltr'?a.bbox[0]-b.bbox[0]:b.bbox[2]-a.bbox[2]);ordered.push(...row);
 }return ordered;
}
export function linkPageBlocks(pages,{direction='rtl',webtoon=false}={}){
 const groups=[],byId=new Map();
 for(const page of pages)for(const r of readingOrder(page.regions,direction)){
  const part={page:page.page,id:r.id,bbox:[...r.bbox],width:page.width,height:page.height,layout_bbox:r.layout_bbox||r.bbox,bubble_bbox:r.bubble_bbox};
  const group={id:r.id,parts:[part]};groups.push(group);byId.set(r.id,group);
 }
 if(webtoon)for(let n=0;n<pages.length-1;n++){
  const a=pages[n],b=pages[n+1];if(b.page!==a.page+1||Math.abs(a.width-b.width)>1)continue;
  const edge=Math.max(16,Math.round(a.width*.025));
  const bottom=a.regions.filter(r=>a.height-r.bbox[3]<=edge),top=b.regions.filter(r=>r.bbox[1]<=edge);
  const candidates=[];
  for(const left of bottom)for(const right of top){const x=left.bbox,y=right.bbox,overlap=Math.min(x[2],y[2])-Math.max(x[0],y[0]),wa=x[2]-x[0],wb=y[2]-y[0];
   if(overlap/Math.max(wa,wb)<.7||Math.min(wa,wb)/Math.max(wa,wb)<.7)continue;
   // Require mutually unique geometric matches; nearby independent bubbles
   // remain separate. These are seam candidates, not semantic certainty.
   candidates.push({left,right});
  }
  for(const pair of candidates){if(candidates.filter(v=>v.left===pair.left).length!==1||candidates.filter(v=>v.right===pair.right).length!==1)continue;
   const first=byId.get(pair.left.id),second=byId.get(pair.right.id);if(first===second||first.parts.length>1||second.parts.length>1)continue;
   first.parts.push(...second.parts);for(const p of second.parts)byId.set(p.id,first);groups.splice(groups.indexOf(second),1);
  }
 }
 for(const group of groups){const x1=Math.min(...group.parts.map(p=>p.bbox[0])),x2=Math.max(...group.parts.map(p=>p.bbox[2]));let offset=0;
  group.parts.forEach((p,i)=>{p.crop=group.parts.length>1?[x1,i?0:p.bbox[1],x2,i<group.parts.length-1?p.height:p.bbox[3]]:[...p.bbox];p.offsetY=offset;offset+=p.crop[3]-p.crop[1];});
  group.width=x2-x1;group.height=offset;
 }return groups;
}
export function packBlockSheets(groups,limits=BLOCK_LIMITS){
 const sheets=[];let sheet,free=[];
 const fresh=(w,h)=>{sheet={id:'S'+(sheets.length+1),page:sheets.length+1,width:Math.max(limits.width,w+2*limits.gap),height:Math.max(limits.height,h+2*limits.gap),inputMode:'blocks',regions:[],placements:[],usedY:limits.gap};sheets.push(sheet);free=[{x:limits.gap,y:limits.gap,w:sheet.width-2*limits.gap,h:sheet.height-2*limits.gap}];};
 for(const group of groups){
  const w=Math.ceil(group.width),h=Math.ceil(group.height)+limits.label;
  if(w+2*limits.gap>4096||h+2*limits.gap>8192||w*h>limits.pixels)throw Error('Текстовый блок слишком велик для читаемого листа. Раздели исходную страницу.');
  if(!sheet)fresh(w,h);
  let candidates=free.map((r,i)=>({...r,i})).filter(r=>r.w>=w&&r.h>=h).sort((a,b)=>a.y-b.y||a.w*a.h-b.w*b.h||a.x-b.x);
  if(sheet.regions.length>=limits.regions||!candidates.length){fresh(w,h);candidates=[{...free[0],i:0}];}
  const r=candidates[0];free.splice(r.i,1);
  const right=r.w-w-limits.gap,bottom=r.h-h-limits.gap;
  if(right>0)free.push({x:r.x+w+limits.gap,y:r.y,w:right,h:r.h});
  if(bottom>0)free.push({x:r.x,y:r.y+h+limits.gap,w,h:bottom});
  const box=[r.x,r.y+limits.label,r.x+w,r.y+h];sheet.regions.push({id:group.id,bbox:box});sheet.placements.push({group,box});sheet.usedY=Math.max(sheet.usedY,box[3]+limits.gap);
 }
 for(const s of sheets){s.height=s.usedY;delete s.usedY;}return sheets;
}
export function unpackBlockTranslations(translated,sheets,pages){
 const expected=new Map(sheets.flatMap(s=>s.placements.map(p=>[p.group.id,p.group]))),rows=new Map();
 for(const sheet of translated)for(const r of sheet.regions){if(!expected.has(r.uid)||rows.has(r.uid))throw Error('Ответ не совпадает с ID блоков. Оригинал сохранён.');rows.set(r.uid,r);}
 if(rows.size!==expected.size)throw Error('Переведены не все блоки. Оригинал сохранён.');
 const result=new Map(pages.map(p=>[p.page,{page:p.page,width:p.width,height:p.height,regions:[],detected:{width:p.width,height:p.height,regions:p.regions.map(r=>({id:r.id,bbox:r.bbox})),seams:[]},timings:{detectionMs:p.detectionMs,ocrMs:0}}]));
 for(const [id,group]of expected){const row=rows.get(id);for(const part of group.parts){const page=result.get(part.page);page.regions.push({...row,uid:part.id,text_bbox:part.bbox,layout_bbox:part.layout_bbox||part.bbox,...(part.bubble_bbox?{bubble_bbox:part.bubble_bbox}:{}),...(group.parts.length>1?{flow:{id,width:group.width,height:group.height,offsetY:part.offsetY}}:{})});if(group.parts.length>1)page.detected.seams.push({id,parts:group.parts.map(p=>({page:p.page,bbox:p.bbox}))});}}
 return [...result.values()];
}
export async function paintBlockSheets(sheets,pages){
 const bitmaps=new Map();try{
  for(const p of pages)bitmaps.set(p.page,await createImageBitmap(p.blob));
  for(const sheet of sheets){const canvas=new OffscreenCanvas(sheet.width,sheet.height),ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);
   for(const{group,box}of sheet.placements){let y=box[1];const scale=group.scale||1;for(const part of group.parts){const[x1,y1,x2,y2]=part.crop;ctx.drawImage(bitmaps.get(part.page),x1,y1,x2-x1,y2-y1,box[0],y,(x2-x1)*scale,(y2-y1)*scale);y+=(y2-y1)*scale;}
    ctx.fillStyle='#111';ctx.font='16px sans-serif';ctx.textBaseline='bottom';ctx.fillText(group.id+(group.parts.length>1?' · joined':''),box[0],box[1]-4);
    ctx.strokeStyle='#999';ctx.lineWidth=1;ctx.strokeRect(box[0]-1,box[1]-1,group.width+2,group.height+2);
   }
   const blob=await canvas.convertToBlob({type:'image/png'}),bytes=new Uint8Array(await blob.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));sheet.detector=pages[0]?.detector||'local';sheet.image=btoa(binary);sheet.mime=blob.type;sheet.sentWidth=sheet.width;sheet.sentHeight=sheet.height;
  }return sheets;
 }finally{for(const bitmap of bitmaps.values())bitmap.close();}
}
