// SPDX-License-Identifier: AGPL-3.0-or-later
// Finds the real interior of a balloon on the cleaned page by flood-filling
// paper from the text box; needs a 2D canvas context. Coarse grid, so it costs
// a few milliseconds per balloon on a phone.
import {makeRegion,ellipseRegion,erodeRegion} from './shape.js';
import {tiltOf} from './classify.js';
const GRID=200,TOLERANCE=30;
const clampBox=(b,w,h)=>({x1:Math.max(0,Math.floor(b.x1)),y1:Math.max(0,Math.floor(b.y1)),x2:Math.min(w,Math.ceil(b.x2)),y2:Math.min(h,Math.ceil(b.y2))});
export const grow=(b,k)=>{const w=(b.x2-b.x1)*k,h=(b.y2-b.y1)*k;return {x1:b.x1-w,y1:b.y1-h,x2:b.x2+w,y2:b.y2+h};};
function lumaGrid(ctx,rect){
 const W=rect.x2-rect.x1,H=rect.y2-rect.y1,step=Math.max(1,Math.ceil(Math.max(W,H)/GRID)),gw=Math.ceil(W/step),gh=Math.ceil(H/step),data=ctx.getImageData(rect.x1,rect.y1,W,H).data,grid=new Float32Array(gw*gh);
 for(let y=0;y<gh;y++)for(let x=0;x<gw;x++){const o=(Math.min(H-1,y*step)*W+Math.min(W-1,x*step))*4;grid[y*gw+x]=.299*data[o]+.587*data[o+1]+.114*data[o+2];}
 return {grid,gw,gh,step};
}
const median=values=>{const s=Float32Array.from(values).sort();return s.length?s[s.length>>1]:255;};
// Returns {region, enclosed}. `enclosed` is false when no closed balloon surrounds the text.
export function bubbleRegion(ctx,box,bubble){
 if(bubble)return searchRegion(ctx,box,bubble,true);
 // Without a detector balloon the frame widens until the paper is enclosed.
 let found;for(const reach of [.5,1.3,3]){found=searchRegion(ctx,box,grow(box,reach),false);if(found.enclosed)break;}
 return found;
}
function searchRegion(ctx,box,frame,trusted){
 const pw=ctx.canvas.width,ph=ctx.canvas.height,text=clampBox(box,pw,ph),rect=clampBox(frame,pw,ph);
 const {grid,gw,gh,step}=lumaGrid(ctx,rect),cell=(x,y)=>y*gw+x;
 const tx1=Math.max(0,Math.floor((text.x1-rect.x1)/step)),ty1=Math.max(0,Math.floor((text.y1-rect.y1)/step)),tx2=Math.min(gw,Math.ceil((text.x2-rect.x1)/step)),ty2=Math.min(gh,Math.ceil((text.y2-rect.y1)/step));
 const inside=[];for(let y=ty1;y<ty2;y++)for(let x=tx1;x<tx2;x++)inside.push(grid[cell(x,y)]);
 const paper=median(inside),filled=new Uint8Array(gw*gh),queue=new Int32Array(gw*gh);let head=0,tail=0;
 const fallback=()=>{const region=ellipseRegion(grow(box,.075),0,'box');region.paper=paper;region.rectangularity=0;return {region,enclosed:false};};
 for(let y=ty1;y<ty2;y++)for(let x=tx1;x<tx2;x++){const i=cell(x,y);filled[i]=1;queue[tail++]=i;}
 if(!tail)return fallback();
 while(head<tail){
  const i=queue[head++],x=i%gw,y=(i/gw)|0;
  for(const [nx,ny]of[[x+1,y],[x-1,y],[x,y+1],[x,y-1]]){if(nx<0||ny<0||nx>=gw||ny>=gh)continue;const n=cell(nx,ny);if(filled[n]||Math.abs(grid[n]-paper)>TOLERANCE)continue;filled[n]=1;queue[tail++]=n;}
 }
 let border=0,minX=gw,maxX=-1,minY=gh,maxY=-1,sx=0;
 for(let i=0;i<tail;i++){const x=queue[i]%gw,y=(queue[i]/gw)|0;if((x===0&&rect.x1>0)||(y===0&&rect.y1>0)||(x===gw-1&&rect.x2<pw)||(y===gh-1&&rect.y2<ph))border++;minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);sx+=x;}
 // Paper running out through the search frame means the text is not enclosed.
 if(border/(2*(gw+gh))>(trusted?.6:.04))return fallback();
 const centre=Math.round(sx/tail),left=new Float32Array(gh),right=new Float32Array(gh);
 for(let y=0;y<gh;y++){
  let c=centre;
  if(!filled[cell(c,y)]){let found=-1;for(let d=1;d<gw&&found<0;d++){if(c-d>=0&&filled[cell(c-d,y)])found=c-d;else if(c+d<gw&&filled[cell(c+d,y)])found=c+d;}if(found<0||Math.abs(found-centre)>gw*.15)continue;c=found;}
  let a=c,b=c;while(a>0&&filled[cell(a-1,y)])a--;while(b<gw-1&&filled[cell(b+1,y)])b++;
  left[y]=rect.x1+a*step;right[y]=Math.min(rect.x2,rect.x1+(b+1)*step);
 }
 const raw=makeRegion({y0:rect.y1,step,left,right,kind:'bubble'}),rectangularity=tail/((maxX-minX+1)*(maxY-minY+1));
 const region=erodeRegion(raw,Math.max(3,.07*Math.min(raw.width,raw.height)));
 if(!(region.height>0&&region.width>0))return fallback();
 region.paper=paper;region.rectangularity=rectangularity;return {region,enclosed:true};
}
// Colour and tilt of the removed lettering: pixels that differ between the original and the cleaned page.
export function inkStats(original,cleaned,box){
 const rect=clampBox(box,cleaned.canvas.width,cleaned.canvas.height),W=rect.x2-rect.x1,H=rect.y2-rect.y1;if(W<2||H<2)return {color:null,tilt:0};
 const a=original.getImageData(rect.x1,rect.y1,W,H).data,b=cleaned.getImageData(rect.x1,rect.y1,W,H).data,step=Math.max(1,Math.ceil(Math.max(W,H)/160)),points=[];let r=0,g=0,bl=0,n=0;
 for(let y=0;y<H;y+=step)for(let x=0;x<W;x+=step){const o=(y*W+x)*4;if(Math.abs(a[o]-b[o])+Math.abs(a[o+1]-b[o+1])+Math.abs(a[o+2]-b[o+2])>90){r+=a[o];g+=a[o+1];bl+=a[o+2];n++;points.push(x,y);}}
 return {color:n>=12?[Math.round(r/n),Math.round(g/n),Math.round(bl/n)]:null,tilt:tiltOf(points)};
}
