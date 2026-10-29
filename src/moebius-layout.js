// Pure geometry shared by the worker and native benchmark. No browser globals.
export function moebiusRuntimeUrl(moduleUrl){return new URL('../lmt/moebius-ort/',moduleUrl).href;}
export function moebiusLayout(width,height,size=512){
 if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1)throw Error('Некорректный размер страницы Moebius');
 const scale=Math.min(size/width,size/height),w=Math.max(1,Math.round(width*scale)),h=Math.max(1,Math.round(height*scale));
 return {x:Math.floor((size-w)/2),y:Math.floor((size-h)/2),w,h,size,scaleX:w/width,scaleY:h/height};
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
