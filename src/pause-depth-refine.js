// Edge-aware refinement of the low-resolution depth model output.
// Depth Anything returns ~392 px maps; drawn at 1280 px their edges are
// stair-stepped. A guided filter (He et al.) driven by the frame's own
// luminance snaps depth and character masks to the drawn contours.

function boxFilter(src,width,height,radius,out=new Float32Array(src.length)){
 // Separable running sums: O(N) regardless of radius.
 const tmp=new Float32Array(src.length);
 for(let y=0;y<height;y++){
  const row=y*width;let sum=0;
  for(let x=-radius;x<=radius;x++)sum+=src[row+Math.min(width-1,Math.max(0,x))];
  for(let x=0;x<width;x++){
   tmp[row+x]=sum/(2*radius+1);
   sum+=src[row+Math.min(width-1,x+radius+1)]-src[row+Math.max(0,x-radius)];
  }
 }
 for(let x=0;x<width;x++){
  let sum=0;
  for(let y=-radius;y<=radius;y++)sum+=tmp[Math.min(height-1,Math.max(0,y))*width+x];
  for(let y=0;y<height;y++){
   out[y*width+x]=sum/(2*radius+1);
   sum+=tmp[Math.min(height-1,y+radius+1)*width+x]-tmp[Math.max(0,y-radius)*width+x];
  }
 }
 return out;
}

export function upsample(data,width,height,targetWidth,targetHeight){
 const out=new Float32Array(targetWidth*targetHeight),sx=width/targetWidth,sy=height/targetHeight;
 for(let y=0;y<targetHeight;y++){
  const fy=Math.max(0,Math.min(height-1,(y+.5)*sy-.5)),y0=Math.floor(fy),y1=Math.min(height-1,y0+1),wy=fy-y0;
  for(let x=0;x<targetWidth;x++){
   const fx=Math.max(0,Math.min(width-1,(x+.5)*sx-.5)),x0=Math.floor(fx),x1=Math.min(width-1,x0+1),wx=fx-x0;
   const a=data[y0*width+x0],b=data[y0*width+x1],c=data[y1*width+x0],d=data[y1*width+x1];
   out[y*targetWidth+x]=((a*(1-wx)+b*wx)*(1-wy)+(c*(1-wx)+d*wx)*wy)/255;
  }
 }
 return out;
}

export function luminance(rgba,width,height){
 const out=new Float32Array(width*height);
 for(let i=0,j=0;i<out.length;i++,j+=4)out[i]=(rgba[j]*.299+rgba[j+1]*.587+rgba[j+2]*.114)/255;
 return out;
}

// Guided filter: q = mean(a)*I + mean(b), a = cov(I,p)/(var(I)+eps).
// Small eps keeps edges sharp where the guide has contours.
export function guidedRefine(data,width,height,guide,targetWidth,targetHeight,{radius=5,eps=.0012}={}){
 const p=upsample(data,width,height,targetWidth,targetHeight),n=p.length,I=guide;
 const meanI=boxFilter(I,targetWidth,targetHeight,radius),meanP=boxFilter(p,targetWidth,targetHeight,radius);
 const ip=new Float32Array(n),ii=new Float32Array(n);for(let i=0;i<n;i++){ip[i]=I[i]*p[i];ii[i]=I[i]*I[i];}
 const corrIP=boxFilter(ip,targetWidth,targetHeight,radius),corrII=boxFilter(ii,targetWidth,targetHeight,radius);
 const a=ip,b=ii;
 for(let i=0;i<n;i++){const varI=corrII[i]-meanI[i]*meanI[i],cov=corrIP[i]-meanI[i]*meanP[i];a[i]=cov/(varI+eps);b[i]=meanP[i]-a[i]*meanI[i];}
 const meanA=boxFilter(a,targetWidth,targetHeight,radius),meanB=boxFilter(b,targetWidth,targetHeight,radius);
 const out=new Uint8Array(n);
 for(let i=0;i<n;i++)out[i]=Math.max(0,Math.min(255,Math.round((meanA[i]*I[i]+meanB[i])*255)));
 return out;
}

// Soft background for depth of field: downscale twice, scale back with
// smoothing. Works everywhere (no ctx.filter), no ring/ghost artifacts.
export function blurredCopy(image,factor=10){
 const w=image.width,h=image.height,steps=[[Math.max(2,Math.round(w/3)),Math.max(2,Math.round(h/3))],[Math.max(2,Math.round(w/factor)),Math.max(2,Math.round(h/factor))]];
 let source=image;
 for(const [sw,sh] of steps){const c=document.createElement('canvas');c.width=sw;c.height=sh;const x=c.getContext('2d');x.imageSmoothingQuality='high';x.drawImage(source,0,0,sw,sh);source=c;}
 const out=document.createElement('canvas');out.width=w;out.height=h;const x=out.getContext('2d');x.imageSmoothingQuality='high';x.drawImage(source,0,0,w,h);
 return out;
}

// Focus masks are low-frequency on purpose: two wide box passes (≈ Gaussian)
// mean a fill that stops at an inner line or leaks into flat background can
// never draw a hard edge across a face or a box-shaped glow.
export function softMask(mask,width,height,radius=Math.max(6,Math.round(Math.max(width,height)/90))){
 const f=new Float32Array(mask.length);for(let i=0;i<f.length;i++)f[i]=mask[i]/255;
 const once=boxFilter(f,width,height,radius),twice=boxFilter(once,width,height,radius);
 const out=new Uint8Array(mask.length);for(let i=0;i<out.length;i++)out[i]=Math.round(Math.min(1,twice[i]*1.2)*255);
 return out;
}
