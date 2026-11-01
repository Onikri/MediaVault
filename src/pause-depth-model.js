// DepthFX Studio adaptation: actual relative depth, not luminance segmentation.
export const DEPTH_MODEL={name:'Depth Anything V2 Small',revision:'4472b7362082ad9968fee890ca0f1e5aca36b93d',url:'https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/4472b7362082ad9968fee890ca0f1e5aca36b93d/onnx/model_quantized.onnx',bytes:27258801,sha256:'fcf51f1b230362b28690bb9d1809bf0431f29cad20534e3f589bd7285547f20d'};
export function depthSize(width,height,max=392){
 const scale=max/Math.max(width,height);
 return {width:Math.max(14,Math.round(width*scale/14)*14),height:Math.max(14,Math.round(height*scale/14)*14)};
}
export function depthInput(rgba,width,height){
 if(rgba.length!==width*height*4)throw Error('Некорректный стоп-кадр.');
 const n=width*height,result=new Float32Array(n*3),mean=[.485,.456,.406],std=[.229,.224,.225];
 for(let c=0;c<3;c++)for(let i=0;i<n;i++)result[c*n+i]=(rgba[i*4+c]/255-mean[c])/std[c];
 return result;
}
export function normalizeDepth(values){
 const sample=[];for(let i=0;i<values.length;i+=Math.max(1,Math.floor(values.length/4096)))if(Number.isFinite(values[i]))sample.push(values[i]);
 if(!sample.length)throw Error('Модель не вернула карту глубины.');
 sample.sort((a,b)=>a-b);const low=sample[Math.floor(sample.length*.02)],high=sample[Math.min(sample.length-1,Math.floor(sample.length*.98))],span=high-low;
 if(span<1e-7)throw Error('В стоп-кадре недостаточно различимой глубины.');
 return Uint8Array.from(values,v=>Math.round(Math.max(0,Math.min(1,(v-low)/span))*255));
}
export const shadowCutoff=seconds=>.48+.16*Math.sin(seconds*Math.PI*2/12-Math.PI/2);
export function videoRect(width,height,videoWidth,videoHeight){
 const scale=Math.min(width/videoWidth,height/videoHeight),w=videoWidth*scale,h=videoHeight*scale;
 return {left:(width-w)/2,top:(height-h)/2,width:w,height:h};
}
// A depth-connected surface seeded inside a returned character box. This is a
// relative-depth highlight, not a claim of semantic/full-body segmentation.
export function depthSurface(depth,width,height,box){
 const [x1,y1,x2,y2]=box,sx=Math.min(width-1,Math.max(0,Math.floor((x1+x2)*.5*width))),sy=Math.min(height-1,Math.max(0,Math.floor((y1+y2)*.5*height))),seed=depth[sy*width+sx];
 const mask=new Uint8Array(depth.length),seen=new Uint8Array(depth.length),queue=new Int32Array(depth.length);let head=0,tail=1;queue[0]=sy*width+sx;seen[queue[0]]=1;
 const minX=Math.max(0,Math.floor((x1-(x2-x1)*.9)*width)),maxX=Math.min(width-1,Math.ceil((x2+(x2-x1)*.9)*width));
 const minY=Math.max(0,Math.floor((y1-(y2-y1)*.8)*height)),maxY=Math.min(height-1,Math.ceil((y2+(y2-y1)*6)*height));
 while(head<tail){const n=queue[head++],x=n%width,y=Math.floor(n/width);if(x<minX||x>maxX||y<minY||y>maxY||Math.abs(depth[n]-seed)>38)continue;const feather=Math.max(3,(x2-x1)*width*.2),fade=Math.min(1,(x-minX)/feather,(maxX-x)/feather,(y-minY)/feather,(maxY-y)/feather);mask[n]=Math.round(Math.max(0,fade)*255);
  for(const k of [x>0?n-1:-1,x+1<width?n+1:-1,y>0?n-width:-1,y+1<height?n+width:-1])if(k>=0&&!seen[k]){seen[k]=1;queue[tail++]=k;}
 }
 return mask;
}
