// Expand lettering only inside an enclosed light bubble. An open white page or
// gutter reaches the search boundary and is never accepted as a speech bubble.
export function paperBubble(image,box){
 const {width:pw,height:ph,data}=image,[x1,y1,x2,y2]=box.map(Math.round),bw=x2-x1,bh=y2-y1;
 const px=Math.min(pw*.5,Math.max(180,bw*3)),py=Math.min(ph*.5,Math.max(260,bh*1.2));
 const left=Math.max(0,Math.floor(x1-px)),top=Math.max(0,Math.floor(y1-py)),right=Math.min(pw,Math.ceil(x2+px)),bottom=Math.min(ph,Math.ceil(y2+py)),w=right-left,h=bottom-top;
 if(w*h>700000||bw<2||bh<2)return null;
 const seen=new Uint8Array(w*h),queue=new Int32Array(w*h),light=(x,y)=>{const n=((top+y)*pw+left+x)*4;return(data[n]+data[n+1]+data[n+2])/3>222&&Math.max(data[n],data[n+1],data[n+2])-Math.min(data[n],data[n+1],data[n+2])<40;};let best=null;
 for(const fy of [.5,.15,.85])for(const fx of [.5,.15,.85]){const sx=Math.max(0,Math.min(w-1,Math.round(x1+bw*fx)-left)),sy=Math.max(0,Math.min(h-1,Math.round(y1+bh*fy)-top)),seed=sy*w+sx;if(seen[seed]||!light(sx,sy))continue;
  let a=0,z=1,border=false,minX=w,minY=h,maxX=0,maxY=0;const sums=[0,0,0];queue[0]=seed;seen[seed]=1;
  while(a<z){const n=queue[a++],x=n%w,y=(n/w)|0;if(!x||!y||x===w-1||y===h-1)border=true;minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);const p=((top+y)*pw+left+x)*4;for(let c=0;c<3;c++)sums[c]+=data[p+c];
   for(const k of[x?n-1:-1,x<w-1?n+1:-1,y?n-w:-1,y<h-1?n+w:-1])if(k>=0&&!seen[k]&&light(k%w,(k/w)|0)){seen[k]=1;queue[z++]=k;}}
  const bounds=[left+minX,top+minY,left+maxX+1,top+maxY+1];
  if(border||z<Math.max(100,bw*bh*1.2)||bounds[0]>x1+3||bounds[1]>y1+3||bounds[2]<x2-3||bounds[3]<y2-3)continue;
  const pad=Math.max(3,Math.round(Math.min(maxX-minX,maxY-minY)*.05)),layout=[Math.min(x1,bounds[0]+pad),Math.min(y1,bounds[1]+pad),Math.max(x2,bounds[2]-pad),Math.max(y2,bounds[3]-pad)];
  if(!best||z>best.area)best={box:layout,background:sums.map(n=>Math.round(n/z)),area:z};
 }return best;
}
export function verticalLettering(box,pageHeight,category,hasBubble=false){return !hasBubble&&box[3]-box[1]>pageHeight*.22&&(box[3]-box[1])/(box[2]-box[0])>=4&&['sfx','sign','narration','text'].includes(category);}
