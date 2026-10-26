// SPDX-License-Identifier: AGPL-3.0-or-later
// Model contracts are deliberately separate: a panel is never a text mask.
export function decodeYolo26(rows,width,height,size=1024,threshold=.25){
 const scale=Math.min(size/width,size/height),rw=Math.round(width*scale),rh=Math.round(height*scale),px=Math.floor((size-rw)/2),py=Math.floor((size-rh)/2),text=[],panels=[];
 for(let i=0;i+5<rows.length;i+=6){const [x1,y1,x2,y2,confidence,label]=rows.slice(i,i+6);if(confidence<threshold||![x1,y1,x2,y2,confidence,label].every(Number.isFinite))continue;
  const b={x1:Math.max(0,Math.min(width,(x1-px)/scale)),y1:Math.max(0,Math.min(height,(y1-py)/scale)),x2:Math.max(0,Math.min(width,(x2-px)/scale)),y2:Math.max(0,Math.min(height,(y2-py)/scale)),confidence};
  if(b.x2-b.x1<3||b.y2-b.y1<3)continue;if(label===1)text.push(b);else if(label===0)panels.push(b);
 }return {text,panels};
}
export function ppSize(width,height){const ratio=Math.max(width,height)/Math.min(width,height)>2?Math.min(1,Math.sqrt(.75*960*960/(width*height))):960/Math.max(width,height);return [Math.max(32,Math.round(width*ratio/32)*32),Math.max(32,Math.round(height*ratio/32)*32)];}
// DB connected components. Axis-aligned rectangle unclip is used in the web
// runner; unlike arbitrary dilation it uses the DB area/perimeter distance.
export function decodeDb(prob,w,h,pageW,pageH){
 if(prob.length!==w*h||w*h>4000000)throw Error('Некорректная карта PP-OCR.');
 const seen=new Uint8Array(w*h),queue=new Int32Array(w*h),out=[];
 for(let seed=0;seed<prob.length;seed++)if(!seen[seed]&&prob[seed]>.15){
  let a=0,z=1,minX=w,maxX=0,minY=h,maxY=0,sum=0,count=0;queue[0]=seed;seen[seed]=1;
  while(a<z){const i=queue[a++],x=i%w,y=Math.floor(i/w);sum+=prob[i];count++;minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);
   for(const [xx,yy]of [[x-1,y],[x+1,y],[x,y-1],[x,y+1]])if(xx>=0&&xx<w&&yy>=0&&yy<h){const j=yy*w+xx;if(!seen[j]&&prob[j]>.15){seen[j]=1;queue[z++]=j;}}
  }
  const bw=maxX-minX+1,bh=maxY-minY+1,confidence=sum/count;if(count<4||confidence<.25||Math.min(bw,bh)<2)continue;
  const d=bw*bh*1.4/(2*(bw+bh));out.push({x1:Math.max(0,(minX-d)/w*pageW),y1:Math.max(0,(minY-d)/h*pageH),x2:Math.min(pageW,(maxX+1+d)/w*pageW),y2:Math.min(pageH,(maxY+1+d)/h*pageH),confidence});
  if(out.length>1000)throw Error('Слишком много строк PP-OCR. Раздели страницу.');
 }return out;
}
export function orderByPanels(text,panels,rtl=false){
 // Choose the smallest containing panel so nested frames do not absorb a page.
 const ordered=[...panels].sort((a,b)=>Math.abs(a.y1-b.y1)<Math.min(a.y2-a.y1,b.y2-b.y1)*.25?(rtl?b.x1-a.x1:a.x1-b.x1):a.y1-b.y1);
 const group=b=>{const x=(b.x1+b.x2)/2,y=(b.y1+b.y2)/2;let match=-1,area=Infinity;ordered.forEach((p,i)=>{const n=(p.x2-p.x1)*(p.y2-p.y1);if(x>=p.x1&&x<=p.x2&&y>=p.y1&&y<=p.y2&&n<area){match=i;area=n;}});return match<0?ordered.length:match;};
 return [...text].sort((a,b)=>group(a)-group(b)||a.y1-b.y1||(rtl?b.x1-a.x1:a.x1-b.x1));
}
