// Pure geometry shared by the worker and native benchmark. No browser globals.
export function moebiusRuntimeUrl(moduleUrl){return new URL('../lmt/moebius-ort/',moduleUrl).href;}
export function moebiusLayout(width,height,size=512){
 if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1)throw Error('Некорректный размер страницы Moebius');
 const scale=Math.min(size/width,size/height),w=Math.max(1,Math.round(width*scale)),h=Math.max(1,Math.round(height*scale));
 return {x:Math.floor((size-w)/2),y:Math.floor((size-h)/2),w,h,size,scaleX:w/width,scaleY:h/height};
}
export function moebiusInferenceRect(mask,width,height){
 let x1=width,y1=height,x2=-1,y2=-1;for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(mask[y*width+x]){x1=Math.min(x1,x);y1=Math.min(y1,y);x2=Math.max(x2,x);y2=Math.max(y2,y);}
 if(x2<0)return {x:0,y:0,w:width,h:height};
 const pad=Math.max(48,Math.min(192,Math.round(Math.max(width,height)*.1))),x=Math.max(0,x1-pad),y=Math.max(0,y1-pad);
 return {x,y,w:Math.min(width,x2+pad+1)-x,h:Math.min(height,y2+pad+1)-y};
}
export function moebiusPageMask(mask,width,height,layout=moebiusLayout(width,height)){
 if(mask.length!==width*height)throw Error('Размер маски не совпадает со страницей');
 const {size,x:ox,y:oy,w,h,scaleX:sx,scaleY:sy}=layout,out=new Uint8Array(size*size);
 // Max/OR pooling, not bilinear alpha thresholding: thin Japanese strokes and
 // small captions must not disappear when the complete page is reduced.
 for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(mask[y*width+x]){
  const left=Math.max(0,Math.floor(x*sx)),right=Math.min(w,Math.ceil((x+1)*sx));
  const top=Math.max(0,Math.floor(y*sy)),bottom=Math.min(h,Math.ceil((y+1)*sy));
  for(let yy=top;yy<bottom;yy++)for(let xx=left;xx<right;xx++)out[(oy+yy)*size+ox+xx]=1;
 }
 return out;
}
