import {englishTextBoxes} from './manga-fast-detect.js';
import {readingOrder} from './manga-blocks.js';

// Work in overlapping width-scaled strips. Long webtoons retain the same
// glyph resolution as short pages; source crops always keep native pixels.
export async function prepareBlocksPage(blob,index,direction='rtl',language='English'){
 const start=performance.now(),bitmap=await createImageBitmap(blob);
 try{
  if(bitmap.width*bitmap.height>24_000_000)throw Error('Страница превышает 24 Мп.');
  const scale=Math.min(1,1280/bitmap.width),width=Math.max(1,Math.round(bitmap.width*scale)),height=Math.max(1,Math.round(bitmap.height*scale)),found=[];
  const add=(box,y,vertical=false)=>{const b=vertical?{x1:box.y1,y1:box.x1,x2:box.y2,y2:box.x2}:box;const bbox=[Math.max(0,Math.floor(b.x1/scale)),Math.max(0,Math.floor((b.y1+y)/scale)),Math.min(bitmap.width,Math.ceil(b.x2/scale)),Math.min(bitmap.height,Math.ceil((b.y2+y)/scale))];
   const duplicate=found.find(r=>{const a=r.bbox,shared=Math.max(0,Math.min(a[2],bbox[2])-Math.max(a[0],bbox[0]))*Math.max(0,Math.min(a[3],bbox[3])-Math.max(a[1],bbox[1]));return shared/Math.max(1,Math.min((a[2]-a[0])*(a[3]-a[1]),(bbox[2]-bbox[0])*(bbox[3]-bbox[1])))>.65;});
   if(duplicate)duplicate.bbox=[Math.min(duplicate.bbox[0],bbox[0]),Math.min(duplicate.bbox[1],bbox[1]),Math.max(duplicate.bbox[2],bbox[2]),Math.max(duplicate.bbox[3],bbox[3])];else found.push({bbox});
  };
  for(let y=0;y<height;y+=1560){const h=Math.min(1800,height-y),canvas=new OffscreenCanvas(width,h),ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(bitmap,0,y/scale,bitmap.width,h/scale,0,0,width,h);const pixels=ctx.getImageData(0,0,width,h);
   for(const box of englishTextBoxes(pixels))add(box,y);
   if(language!=='English'){const rotated={width:h,height:width,data:new Uint8ClampedArray(pixels.data.length)};for(let yy=0;yy<h;yy++)for(let x=0;x<width;x++){const from=(yy*width+x)*4,to=(x*h+yy)*4;rotated.data.set(pixels.data.subarray(from,from+4),to);}for(const box of englishTextBoxes(rotated))add(box,y,true);}
   if(y+h>=height)break;
  }
  if(found.length>300)throw Error('Слишком много кандидатов текста. Раздели страницу или выбери нейронный детектор.');
  const id='P'+(index+1),regions=readingOrder(found,direction).map((r,i)=>({...r,id:id+'_B'+(i+1)}));
  return {id,page:index+1,width:bitmap.width,height:bitmap.height,inputMode:'blocks',detector:'algorithmic-blocks',regions,detectionMs:Math.round(performance.now()-start)};
 }finally{bitmap.close();}
}
