// Expand lettering only inside an enclosed light bubble. An open white page or
// gutter reaches the search boundary and is never accepted as a speech bubble.
export function paperBubble(image,box){
 const {width:pw,height:ph,data}=image,[x1,y1,x2,y2]=box.map(Math.round),bw=x2-x1,bh=y2-y1;
 let px=Math.min(pw*.5,Math.max(180,bw*2)),py=Math.min(ph*.5,Math.max(260,bh*1.2));
 while((bw+px*2)*(bh+py*2)>700000&&(px>48||py>48)){px=Math.max(48,px*.85);py=Math.max(48,py*.85);}
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
  if(!best||z>best.area){
   const rows=new Int32Array(h*2),columns=new Int32Array(w*2);for(let y=0;y<h;y++){rows[y*2]=w;rows[y*2+1]=-1;}for(let x=0;x<w;x++){columns[x*2]=h;columns[x*2+1]=-1;}
   for(let k=0;k<z;k++){const n=queue[k],x=n%w,y=(n/w)|0;rows[y*2]=Math.min(rows[y*2],x);rows[y*2+1]=Math.max(rows[y*2+1],x);columns[x*2]=Math.min(columns[x*2],y);columns[x*2+1]=Math.max(columns[x*2+1],y);}
   best={box:layout,background:sums.map(n=>Math.round(n/z)),area:z,shape:{left,top,width:w,height:h,rows,columns}};
  }
 }return best;
}
export function verticalLettering(box,pageHeight,category,hasBubble=false){return !hasBubble&&box[3]-box[1]>pageHeight*.22&&(box[3]-box[1])/(box[2]-box[0])>=4&&['sfx','sign','narration','text'].includes(category);}

// Connected paper can contain several independent captions. Give every source
// anchor its own cell before measuring text, including explicit shared layouts.
// Cleanup coordinates stay immutable; only the lettering space is partitioned.
export function partitionComicLayouts(regions){
 const out=regions.map(r=>({...r,layout_bbox:[...(r.layout_bbox||r.bubble_bbox||r.text_bbox||[])]}));
 const valid=b=>Array.isArray(b)&&b.length===4&&b.every(Number.isFinite)&&b[2]>b[0]&&b[3]>b[1];
 for(let i=0;i<out.length;i++)for(let j=i+1;j<out.length;j++){
  const a=out[i],b=out[j],x=a.layout_bbox,y=b.layout_bbox,p=a.text_bbox,q=b.text_bbox;
  if(a.flow||b.flow||a.empty_reason==='non_text'||b.empty_reason==='non_text'||![x,y,p,q].every(valid)||Math.min(x[2],y[2])<=Math.max(x[0],y[0])||Math.min(x[3],y[3])<=Math.max(x[1],y[1]))continue;
  const dx=(p[0]+p[2]-q[0]-q[2])/2,dy=(p[1]+p[3]-q[1]-q[3])/2;
  const gapX=Math.max(p[0],q[0])-Math.min(p[2],q[2]),gapY=Math.max(p[1],q[1])-Math.min(p[3],q[3]);
  // Padding around diagonal captions can overlap in both axes. Their anchors
  // still differ; only actual near-identical detector duplicates are excluded.
  const shared=Math.max(0,Math.min(p[2],q[2])-Math.max(p[0],q[0]))*Math.max(0,Math.min(p[3],q[3])-Math.max(p[1],q[1]));
  if(shared/((p[2]-p[0])*(p[3]-p[1])+(q[2]-q[0])*(q[3]-q[1])-shared)>.85)continue;
  const touching=gapX<0&&gapY<0;
  const axis=gapX>=0&&gapY<0?0:gapY>=0&&gapX<0?1:touching?(Math.abs(dx)/(p[2]-p[0]+q[2]-q[0])>=Math.abs(dy)/(p[3]-p[1]+q[3]-q[1])?0:1):Math.abs(dx)/Math.max(x[2]-x[0],y[2]-y[0])>=Math.abs(dy)/Math.max(x[3]-x[1],y[3]-y[1])?0:1;
  const first=p[axis]+p[axis+2]<=q[axis]+q[axis+2]?a:b,second=first===a?b:a;
  const edge=touching?(p[axis]+p[axis+2]+q[axis]+q[axis+2])/4:(first.text_bbox[axis+2]+second.text_bbox[axis])/2,gap=touching?3:Math.min(6,Math.max(0,(axis?gapY:gapX)/4));
  first.layout_bbox[axis+2]=Math.min(first.layout_bbox[axis+2],edge-gap/2);second.layout_bbox[axis]=Math.max(second.layout_bbox[axis],edge+gap/2);
  first.partitioned=true;second.partitioned=true;
 }
 for(const r of out)if(r.partitioned&&r.bubble_shape){
  const shape=r.bubble_shape,b=r.layout_bbox,t=r.text_bbox,pad=4;
  // The bounding rectangle of a diagonal connected bubble also contains art.
  // Project the owner's paper lobe around its source anchor, never that union's
  // centre. This keeps the lettering in its actual upper/lower/side cell.
  const tighten=(axis,spans,offset,limit,anchor)=>{
   const samples=[-.08,0,.08].map(f=>Math.round(anchor+f*(t[axis+2]-t[axis]))-offset).filter(n=>n>=0&&n<limit&&spans[n*2+1]>=spans[n*2]);if(!samples.length)return;
   const other=1-axis,base=other?shape.top:shape.left,low=base+Math.max(...samples.map(n=>spans[n*2]))+pad,high=base+Math.min(...samples.map(n=>spans[n*2+1]))-pad;
   if(high-low>12&&low<(t[other]+t[other+2])/2&&high>(t[other]+t[other+2])/2){b[other]=Math.max(b[other],low);b[other+2]=Math.min(b[other+2],high);}
  };
  tighten(0,shape.columns,shape.left,shape.width,(t[0]+t[2])/2);tighten(1,shape.rows,shape.top,shape.height,(t[1]+t[3])/2);
 }
 return out;
}

export function comicLayouts(image,regions){
 return partitionComicLayouts(regions.map(source=>{
  const region={...source};if(!Array.isArray(region.text_bbox)||region.text_bbox.length!==4||!region.text_bbox.every(Number.isFinite))return region;
  if(!region.flow&&!region.bubble_bbox&&(!region.layout_bbox||JSON.stringify(region.layout_bbox)===JSON.stringify(region.text_bbox))){const bubble=paperBubble(image,region.text_bbox);if(bubble){region.bubble_bbox=bubble.box;region.layout_bbox=bubble.box;region.bubble_shape=bubble.shape;}}
  return region;
 }));
}
