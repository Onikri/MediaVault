// English lettering on light comic backgrounds. Connected components + line
// grouping, no OCR/model/runtime download. A selectable RT-DETR path remains
// available for difficult artwork; this deliberately favours reading latency.
export function englishTextBoxes({data,width:w,height:h}){
 const ink=new Uint8Array(w*h),seen=new Uint8Array(w*h),queue=new Int32Array(w*h),glyphs=[];
 for(let n=0;n<ink.length;n++)ink[n]=(data[n*4]+data[n*4+1]+data[n*4+2]<420)?1:0;
 for(let seed=0;seed<ink.length;seed++)if(ink[seed]&&!seen[seed]){
  let a=0,z=1,x1=w,y1=h,x2=0,y2=0;seen[seed]=1;queue[0]=seed;
  while(a<z){const n=queue[a++],x=n%w,y=(n/w)|0;x1=Math.min(x1,x);y1=Math.min(y1,y);x2=Math.max(x2,x);y2=Math.max(y2,y);
   for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const xx=x+dx,yy=y+dy,i=yy*w+xx;if(xx>=0&&xx<w&&yy>=0&&yy<h&&ink[i]&&!seen[i]){seen[i]=1;queue[z++]=i;}}
  }
  const bw=x2-x1+1,bh=y2-y1+1;
  if(z<6||bh<5||bh>Math.min(90,h*.09)||bw<2||bw>Math.min(100,bh*4)||z>2500||z/(bw*bh)<.08)continue;
  let light=0,total=0;
  for(let y=Math.max(0,y1-2);y<=Math.min(h-1,y2+2);y++)for(let x=Math.max(0,x1-2);x<=Math.min(w-1,x2+2);x++)if(x<x1||x>x2||y<y1||y>y2){light+=!ink[y*w+x];total++;}
  if(light/Math.max(1,total)<.65)continue;
  glyphs.push({x1,y1,x2:x2+1,y2:y2+1,count:1});if(glyphs.length>6000)throw Error('Слишком сложный фон для лёгкого поиска. Выбери RT-DETR в настройках.');
 }
 const lines=[];
 for(const g of glyphs.sort((a,b)=>(a.y1+a.y2)-(b.y1+b.y2)||a.x1-b.x1)){
  const gh=g.y2-g.y1;
  let match=lines.find(l=>{const lh=l.y2-l.y1,overlap=Math.min(l.y2,g.y2)-Math.max(l.y1,g.y1),gap=Math.max(0,l.x1-g.x2,g.x1-l.x2);return overlap>Math.min(lh,gh)*.5&&Math.abs((g.y1+g.y2-l.y1-l.y2)/2)<Math.max(lh,gh)*.55&&gap<Math.max(lh,gh)*1.5;});
  if(match){match.x1=Math.min(match.x1,g.x1);match.y1=Math.min(match.y1,g.y1);match.x2=Math.max(match.x2,g.x2);match.y2=Math.max(match.y2,g.y2);match.count++;}else lines.push({...g});
 }
 // Components may have reached the same line from opposite ends. Join those
 // fragments before combining consecutive lines into a paragraph.
 for(let i=0;i<lines.length;i++)for(let j=i+1;j<lines.length;j++){
  const a=lines[i],b=lines[j],height=Math.max(a.y2-a.y1,b.y2-b.y1),overlap=Math.min(a.y2,b.y2)-Math.max(a.y1,b.y1),gap=Math.max(0,a.x1-b.x2,b.x1-a.x2);
  if(overlap>height*.5&&gap<height*1.5){a.x1=Math.min(a.x1,b.x1);a.x2=Math.max(a.x2,b.x2);a.y1=Math.min(a.y1,b.y1);a.y2=Math.max(a.y2,b.y2);a.count+=b.count;lines.splice(j--,1);}
 }
 const candidates=lines.filter(l=>l.count>=2&&l.x2-l.x1>=(l.y2-l.y1)*.65),parent=candidates.map((_,i)=>i),find=i=>parent[i]===i?i:(parent[i]=find(parent[i]));
 for(let i=0;i<candidates.length;i++)for(let j=i+1;j<candidates.length;j++){
  const a=candidates[i],b=candidates[j],ah=a.y2-a.y1,bh=b.y2-b.y1,gap=Math.max(a.y1,b.y1)-Math.min(a.y2,b.y2),overlap=Math.min(a.x2,b.x2)-Math.max(a.x1,b.x1);
  if(gap>=-Math.min(ah,bh)*.25&&gap<Math.max(ah,bh)*1.5&&overlap>Math.min(a.x2-a.x1,b.x2-b.x1)*.3)parent[find(j)]=find(i);
 }
 const blocks=new Map();candidates.forEach((l,i)=>{const key=find(i),b=blocks.get(key);if(b){b.x1=Math.min(b.x1,l.x1);b.y1=Math.min(b.y1,l.y1);b.x2=Math.max(b.x2,l.x2);b.y2=Math.max(b.y2,l.y2);b.count+=l.count;}else blocks.set(key,{...l});});
 return [...blocks.values()].filter(b=>b.count>=3&&(b.x2-b.x1)*(b.y2-b.y1)<w*h*.16).map(b=>({x1:Math.max(0,b.x1-3),y1:Math.max(0,b.y1-3),x2:Math.min(w,b.x2+3),y2:Math.min(h,b.y2+3)}));
}
export async function prepareEnglishPage(blob,index,direction='rtl'){
 const start=performance.now(),bitmap=await createImageBitmap(blob);
 try{
  const decodeMs=performance.now()-start;
  if(bitmap.width*bitmap.height>24_000_000)throw Error('Страница превышает 24 Мп.');
  const scale=Math.min(1,1280/Math.max(bitmap.width,bitmap.height)),canvas=new OffscreenCanvas(Math.round(bitmap.width*scale),Math.round(bitmap.height*scale)),ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
  const detectStart=performance.now();
  const boxes=englishTextBoxes(ctx.getImageData(0,0,canvas.width,canvas.height)).map(b=>Object.fromEntries(Object.entries(b).map(([k,v])=>[k,v/scale]))).sort((a,b)=>Math.abs(a.y1-b.y1)<Math.min(a.y2-a.y1,b.y2-b.y1)*.4?(direction==='ltr'?a.x1-b.x1:b.x1-a.x1):a.y1-b.y1);
  const detectMs=performance.now()-detectStart;
  if(boxes.length>60)throw Error('Фон слишком сложный для лёгкого поиска. Выбери RT-DETR.');
  const id='P'+(index+1),regions=boxes.map((b,i)=>({id:id+'_B'+(i+1),bbox:[b.x1,b.y1,b.x2,b.y2].map(Math.round)}));
  const markStart=performance.now();
  for(const r of regions){const[x,y,x2,y2]=r.bbox.map(n=>n*scale);ctx.strokeStyle='#ff0033';ctx.lineWidth=2;ctx.strokeRect(x,y,x2-x,y2-y);ctx.font='bold 12px sans-serif';const width=ctx.measureText(r.id).width+6,top=Math.max(0,y-16);ctx.fillStyle='#ff0033';ctx.fillRect(x,top,width,15);ctx.fillStyle='white';ctx.textBaseline='top';ctx.fillText(r.id,x+3,top+1);}
  const markMs=performance.now()-markStart,encodeStart=performance.now();
  const image=await canvas.convertToBlob({type:'image/webp',quality:.8}),bytes=new Uint8Array(await image.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return {id,page:index+1,width:bitmap.width,height:bitmap.height,image:btoa(binary),mime:image.type,regions,sentWidth:canvas.width,sentHeight:canvas.height,prepareTimings:{decodeMs,detectMs,markMs,encodeMs:performance.now()-encodeStart},detectionMs:Math.round(performance.now()-start)};
 }finally{bitmap.close();}
}
