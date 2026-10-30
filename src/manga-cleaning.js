// A region owns only its glyph mask. All masks are derived from the immutable
// original; one region can never erase Russian text inserted into another.
export function dilateInk(mask,w,h,radius=1){
 const out=new Uint8Array(mask.length);
 for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(mask[y*w+x])for(let dy=-radius;dy<=radius;dy++)for(let dx=-radius;dx<=radius;dx++){
  const xx=x+dx,yy=y+dy;if(xx>=0&&xx<w&&yy>=0&&yy<h)out[yy*w+xx]=1;
 }return out;
}
function contrastGlyphs(data,w,h,box){
 const ink=new Uint8Array(w*h),seen=new Uint8Array(w*h),queue=new Int32Array(w*h),area=(box[2]-box[0])*(box[3]-box[1]);
 const luma=(x,y)=>{const n=(y*w+x)*4;return (data[n]+data[n+1]+data[n+2])/3;};
 const stride=w+1,sums=new Float64Array((w+1)*(h+1));
 for(let y=0;y<h;y++){let row=0;for(let x=0;x<w;x++){row+=luma(x,y);sums[(y+1)*stride+x+1]=sums[y*stride+x+1]+row;}}
 for(let y=box[1];y<box[3];y++)for(let x=box[0];x<box[2];x++){
  const a=Math.max(0,x-3),b=Math.min(w,x+4),c=Math.max(0,y-3),d=Math.min(h,y+4),sum=sums[d*stride+b]-sums[c*stride+b]-sums[d*stride+a]+sums[c*stride+a],count=(b-a)*(d-c);
  const contrast=luma(x,y)-sum/count;if(Math.abs(contrast)>32)ink[y*w+x]=contrast<0?1:2;
 }
 for(let seed=0;seed<ink.length;seed++)if(ink[seed]&&!seen[seed]){
  let a=0,z=1,x1=w,y1=h,x2=0,y2=0;queue[0]=seed;seen[seed]=1;
  while(a<z){const n=queue[a++],x=n%w,y=(n/w)|0;x1=Math.min(x1,x);y1=Math.min(y1,y);x2=Math.max(x2,x);y2=Math.max(y2,y);
   for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const xx=x+dx,yy=y+dy,i=yy*w+xx;if(xx>=0&&xx<w&&yy>=0&&yy<h&&ink[i]===ink[seed]&&!seen[i]){seen[i]=1;queue[z++]=i;}}
  }
  const tall=y2-y1+1>=(box[3]-box[1])*.95,wide=x2-x1+1>=(box[2]-box[0])*.95;
  const rule=tall&&wide||(tall&&x2-x1+1<(box[2]-box[0])*.2)||(wide&&y2-y1+1<(box[3]-box[1])*.2);
  if(z<4||z>area*.4||rule)for(let k=0;k<z;k++)ink[queue[k]]=0;
 }
 return ink.map(value=>value?1:0);
}
function protectRules(mask,data,w,h,local,bounds){
  const luma=(x,y)=>{const n=(Math.max(0,Math.min(h-1,y))*w+Math.max(0,Math.min(w-1,x)))*4;return (data[n]+data[n+1]+data[n+2])/3;};
  for(let x=bounds[0];x<bounds[2];x++)if(x<local[0]||x>=local[2]){
   let count=0;for(let y=bounds[1];y<bounds[3];y++){const value=luma(x,y);if(value<80&&(x<2||luma(x-2,y)>value+35)&&(x>=w-2||luma(x+2,y)>value+35))count++;}
   if(count>=Math.max(32,(bounds[3]-bounds[1])*.85))for(let y=bounds[1];y<bounds[3];y++)for(let dx=-1;dx<=1;dx++)if(x+dx>=0&&x+dx<w)mask[y*w+x+dx]=0;
  }
  for(let y=bounds[1];y<bounds[3];y++)if(y<local[1]||y>=local[3]){
   let count=0;for(let x=bounds[0];x<bounds[2];x++){const value=luma(x,y);if(value<80&&(y<2||luma(x,y-2)>value+35)&&(y>=h-2||luma(x,y+2)>value+35))count++;}
   if(count>=Math.max(32,(bounds[2]-bounds[0])*.85))for(let x=bounds[0];x<bounds[2];x++)for(let dy=-1;dy<=1;dy++)if(y+dy>=0&&y+dy<h)mask[(y+dy)*w+x]=0;
  }
}
export function prepareInkPatch(original,box,{category='dialogue',neural=false,model}={}){
 const {width:pw,height:ph}=original;
 if(!Array.isArray(box)||box.length!==4||!box.every(Number.isFinite))return {declined:'Некорректные координаты текста'};
 const [x1,y1,x2,y2]=box.map(Math.round);if(x1<0||y1<0||x2>pw||y2>ph||x2-x1<2||y2-y1<2)return {declined:'Область текста выходит за границы'};
 const pad=neural?24:Math.max(24,Math.min(48,Math.round(Math.min(x2-x1,y2-y1)*.6))),left=Math.max(0,x1-pad),top=Math.max(0,y1-pad),w=Math.min(pw,x2+pad)-left,h=Math.min(ph,y2+pad)-top;
 const local=[x1-left,y1-top,x2-left,y2-top],data=new Uint8ClampedArray(w*h*4),border=[[],[],[]];
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  const dst=(y*w+x)*4,src=((top+y)*pw+left+x)*4;data.set(original.data.subarray(src,src+4),dst);
  if(x>=local[0]-4&&x<local[2]+4&&y>=local[1]-4&&y<local[3]+4&&(x<local[0]||x>=local[2]||y<local[1]||y>=local[3])&&data[dst+3]>127)for(let c=0;c<3;c++)border[c].push(data[dst+c]);
 }
 const background=border.map(a=>a.sort((a,b)=>a-b)[a.length>>1]??255),paper=background.reduce((a,b)=>a+b)/3;
 const deviation=border.reduce((s,a,c)=>s+a.reduce((n,v)=>n+Math.abs(v-background[c]),0)/Math.max(1,a.length),0)/3;
 // A narrow text strip on artwork (common vertical Japanese captions) cannot
 // be segmented reliably by ink polarity: white outlines join the background.
 // Telea can safely bridge this small complete hole from the surrounding art.
 const bw=x2-x1,bh=y2-y1;
 if(!neural&&deviation>18&&Math.max(bw/bh,bh/bw)>2.4&&bw*bh<pw*ph*.15){
  const mask=new Uint8Array(w*h),a=Math.max(0,local[0]-4),b=Math.min(w,local[2]+4),c=Math.max(0,local[1]-4),d=Math.min(h,local[3]+4);
  for(let y=c;y<d;y++)mask.fill(1,y*w+a,y*w+b);
  protectRules(mask,data,w,h,local,[a,c,b,d]);const masked=mask.reduce((n,v)=>n+v,0),coverage=masked/(w*h);
  if(coverage<.58)return {left,top,width:w,height:h,data,mask,background,coverage,flat:false,masked,maskKind:'text-band'};
 }
 // Contrast in both directions includes white outlines and dark letter cores.
 // Keep neural masks on the glyphs; a filled text rectangle destroys too much
 // drawing context on SFX over hair/halftones.
 if(model==='moebius'){
  const margin=Math.min(8,Math.max(3,Math.ceil(Math.max(pw,ph)/512*1.5))+(category==='sfx'||category==='sign'?2:0));
  const glyphs=contrastGlyphs(data,w,h,local),mask=dilateInk(glyphs,w,h,margin),bounds=[Math.max(0,local[0]-margin),Math.max(0,local[1]-margin-2),Math.min(w,local[2]+margin),Math.min(h,local[3]+margin)];
  // Extra top coverage catches upper diacritics and anti-aliased outlines.
  for(let y=2;y<h;y++)for(let x=0;x<w;x++)if(mask[y*w+x]){mask[(y-1)*w+x]=1;mask[(y-2)*w+x]=1;}
  // Do not extend the safety margin through a long panel/bubble rule outside
  // the detected text. In particular preserve nearby vertical panel frames.
  protectRules(mask,data,w,h,local,bounds);
  const masked=mask.reduce((n,v)=>n+v,0);
  if(masked<3)return {declined:'Не выделена маска исходных букв'};
  return {left,top,width:w,height:h,data,mask,background,coverage:masked/(w*h),flat:false,masked,maskKind:'outlined-glyphs',margin};
 }
 const ink=new Uint8Array(w*h),seen=new Uint8Array(w*h),queue=new Int32Array(w*h);
 const area=(x2-x1)*(y2-y1);
 for(let y=local[1];y<local[3];y++)for(let x=local[0];x<local[2];x++){
  const n=y*w+x,p=n*4,luma=(data[p]+data[p+1]+data[p+2])/3;
  if(data[p+3]>127&&(paper<128?luma>paper+35:luma<paper-35))ink[n]=1;
 }
 // A giant connected artwork component is not a set of letters. Remove it
 // before dilation rather than handing most of a crop to Telea.
 for(let seed=0;seed<ink.length;seed++)if(ink[seed]&&!seen[seed]){
  let a=0,z=1;queue[0]=seed;seen[seed]=1;
  while(a<z){const n=queue[a++],x=n%w,y=(n/w)|0;for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){
   const xx=x+dx,yy=y+dy,i=yy*w+xx;if(xx>=0&&xx<w&&yy>=0&&yy<h&&ink[i]&&!seen[i]){seen[i]=1;queue[z++]=i;}
  }}
  let crossesArtwork=false;
  for(let k=0;k<z&&!crossesArtwork;k++){
   const n=queue[k],x=n%w,y=(n/w)|0;
   if(x!==local[0]&&x!==local[2]-1&&y!==local[1]&&y!==local[3]-1)continue;
   for(const[dx,dy]of [[-1,0],[1,0],[0,-1],[0,1]]){
    const xx=x+dx,yy=y+dy;if(xx<0||yy<0||xx>=w||yy>=h||xx>=local[0]&&xx<local[2]&&yy>=local[1]&&yy<local[3])continue;
    const p=(yy*w+xx)*4,luma=(data[p]+data[p+1]+data[p+2])/3;
    if(paper<128?luma>paper+35:luma<paper-35)crossesArtwork=true;
   }
  }
  if(z<3||z>area*.4||crossesArtwork)for(let n=0;n<z;n++)ink[queue[n]]=0;
 }
 if(!neural&&(deviation>=12||['sfx','sign','whisper_aside'].includes(category)))ink.set(contrastGlyphs(data,w,h,local));
 const mask=dilateInk(ink,w,h,1),masked=mask.reduce((n,v)=>n+v,0),coverage=masked/(w*h);
 if(masked<3)return {declined:'Не выделена безопасная маска букв'};
 if(coverage>.6)return {declined:'Маска захватывает рисунок: область оставлена в оригинале',coverage};
 let interiorDeviation=0,known=0;
 for(let y=local[1];y<local[3];y++)for(let x=local[0];x<local[2];x++){const n=y*w+x;if(mask[n])continue;for(let c=0;c<3;c++)interiorDeviation+=Math.abs(data[n*4+c]-background[c]);known++;}
 const flat=deviation<12&&interiorDeviation/Math.max(1,known*3)<12;
 const ambiguous=!flat&&(category==='sfx'||category==='sign')&&masked/area>.28;
 if(ambiguous&&!neural)return {declined:'Спецэффект пересекает рисунок: для безопасного удаления выбери нейросетевое восстановление',coverage};
 return {left,top,width:w,height:h,data,mask,background,coverage,flat,masked};
}
export function compositeInkPatch(target,patch,modified,writeMask=patch.mask){
 for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++)if(writeMask[y*patch.width+x]){
  const src=(y*patch.width+x)*4,dst=((patch.top+y)*target.width+patch.left+x)*4;
  target.data.set(modified.subarray(src,src+4),dst);
 }
}
// One native-resolution union. Preparing geometry never runs neural inference.
export function preparePageInk(original,regions,options={}){
 const mask=new Uint8Array(original.width*original.height),patches=[];
 for(const region of regions){
  const patch=prepareInkPatch(original,region.text_bbox,{category:region.text_category,neural:true,...options});
  patches.push({region,patch});if(patch.declined)continue;
  for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++)if(patch.mask[y*patch.width+x])mask[(patch.top+y)*original.width+patch.left+x]=1;
 }
 return {mask,patches,maskedPixels:mask.reduce((sum,n)=>sum+n,0)};
}

// Native-resolution dynamic LaMa input: snap small ROIs rather than inflating
// every bubble to 512x512. Never resize glyphs or pass arbitrary tensor shapes.
export function lamaInputSize(width,height){
 if(!Number.isInteger(width)||!Number.isInteger(height)||width<2||height<2)throw Error('Некорректный размер LaMa');
 if(width>512||height>512)return null;
 return {width:Math.max(128,Math.ceil(width/64)*64),height:Math.max(128,Math.ceil(height/64)*64)};
}
export function lamaInputTensors(image,mask,crop){
 const plane=crop.w*crop.h,rgb=new Float32Array(3*plane),holes=new Float32Array(plane);
 for(let y=0;y<crop.h;y++)for(let x=0;x<crop.w;x++){
  const px=crop.x+x,py=crop.y+y,n=y*crop.w+x;
  if(px>=0&&px<image.width&&py>=0&&py<image.height&&mask[py*image.width+px]){holes[n]=1;continue;}
  const src=(Math.max(0,Math.min(image.height-1,py))*image.width+Math.max(0,Math.min(image.width-1,px)))*4;
  rgb[n]=image.data[src]/255;rgb[plane+n]=image.data[src+1]/255;rgb[plane*2+n]=image.data[src+2]/255;
 }
 return {rgb,holes};
}
export function applyLamaOutput(image,mask,values,tile,done){
 const {crop,commit}=tile,plane=crop.w*crop.h;
 if(values.length!==plane*3)throw Error('Некорректный ответ LaMa');
 // Preserve the original outside the glyph mask plus a two-pixel AA ring.
 const ring=dilateInk(mask,image.width,image.height,2);
 for(let y=Math.max(0,commit.y);y<Math.min(image.height,commit.y+commit.h);y++)for(let x=Math.max(0,commit.x);x<Math.min(image.width,commit.x+commit.w);x++){
  const n=y*image.width+x;if(done[n]||!ring[n])continue;
  const local=(y-crop.y)*crop.w+x-crop.x;if(local<0||local>=plane)continue;
  const alpha=mask[n]?1:2/3;
  for(let c=0;c<3;c++){const sample=values[c*plane+local];if(!Number.isFinite(sample))throw Error('LaMa вернула некорректные пиксели');image.data[n*4+c]=Math.round(alpha*Math.max(0,Math.min(255,sample*255))+(1-alpha)*image.data[n*4+c]);}
  done[n]=1;
 }
}
