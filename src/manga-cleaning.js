// A region owns only its glyph mask. All masks are derived from the immutable
// original; one region can never erase Russian text inserted into another.
export function dilateInk(mask,w,h,radius=1){
 const out=new Uint8Array(mask.length);
 for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(mask[y*w+x])for(let dy=-radius;dy<=radius;dy++)for(let dx=-radius;dx<=radius;dx++){
  const xx=x+dx,yy=y+dy;if(xx>=0&&xx<w&&yy>=0&&yy<h)out[yy*w+xx]=1;
 }return out;
}
export function prepareInkPatch(original,box){
 const {width:pw,height:ph}=original;
 if(!Array.isArray(box)||box.length!==4||!box.every(Number.isFinite))return {declined:'Некорректные координаты текста'};
 const [x1,y1,x2,y2]=box.map(Math.round);if(x1<0||y1<0||x2>pw||y2>ph||x2-x1<2||y2-y1<2)return {declined:'Область текста выходит за границы'};
 const pad=24,left=Math.max(0,x1-pad),top=Math.max(0,y1-pad),w=Math.min(pw,x2+pad)-left,h=Math.min(ph,y2+pad)-top;
 const local=[x1-left,y1-top,x2-left,y2-top],data=new Uint8ClampedArray(w*h*4),border=[[],[],[]];
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  const dst=(y*w+x)*4,src=((top+y)*pw+left+x)*4;data.set(original.data.subarray(src,src+4),dst);
  if(x>=local[0]-4&&x<local[2]+4&&y>=local[1]-4&&y<local[3]+4&&(x<local[0]||x>=local[2]||y<local[1]||y>=local[3])&&data[dst+3]>127)for(let c=0;c<3;c++)border[c].push(data[dst+c]);
 }
 const background=border.map(a=>a.sort((a,b)=>a-b)[a.length>>1]??255),paper=background.reduce((a,b)=>a+b)/3;
 const deviation=border.reduce((s,a,c)=>s+a.reduce((n,v)=>n+Math.abs(v-background[c]),0)/Math.max(1,a.length),0)/3;
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
  if(z<3||z>area*.6)for(let n=0;n<z;n++)ink[queue[n]]=0;
 }
 const mask=dilateInk(ink,w,h,1),masked=mask.reduce((n,v)=>n+v,0),coverage=masked/(w*h);
 if(masked<3)return {declined:'Не выделена безопасная маска букв'};
 if(coverage>.6)return {declined:'Маска захватывает рисунок: область оставлена в оригинале',coverage};
 return {left,top,width:w,height:h,data,mask,background,coverage,flat:deviation<15,masked};
}
export function compositeInkPatch(target,patch,modified,writeMask=patch.mask){
 for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++)if(writeMask[y*patch.width+x]){
  const src=(y*patch.width+x)*4,dst=((patch.top+y)*target.width+patch.left+x)*4;
  target.data.set(modified.subarray(src,src+4),dst);
 }
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
