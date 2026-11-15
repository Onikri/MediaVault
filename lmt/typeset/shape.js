// SPDX-License-Identifier: AGPL-3.0-or-later
// A region is the usable interior of a balloon: for every sampled row the
// left/right limits in page pixels, plus the optical centre. Pure; no DOM.
export function makeRegion({y0,step=1,left,right,cx,cy,kind='bubble',...rest}){
 let top=-1,bottom=-1;
 for(let i=0;i<left.length;i++)if(right[i]>left[i]){if(top<0)top=i;bottom=i;}
 const region={y0,step,left,right,kind,...rest,top:y0+Math.max(0,top)*step,bottom:y0+(bottom+1)*step};
 if(cx==null||cy==null){let sx=0,sy=0,area=0;for(let i=0;i<left.length;i++){const w=right[i]-left[i];if(w>0){area+=w;sx+=w*(left[i]+right[i])/2;sy+=w*(y0+(i+.5)*step);}}cx=area?sx/area:0;cy=area?sy/area:y0;}
 region.cx=cx;region.cy=cy;region.height=region.bottom-region.top;
 region.width=Math.max(0,...Array.from(left,(l,i)=>right[i]-l));
 return region;
}
export function ellipseRegion(box,inset=0,kind='ellipse'){
 const w=box.x2-box.x1,h=box.y2-box.y1,cx=(box.x1+box.x2)/2,cy=(box.y1+box.y2)/2,rx=Math.max(1,w/2-inset),ry=Math.max(1,h/2-inset);
 const rows=Math.max(1,Math.round(h)),left=new Float32Array(rows),right=new Float32Array(rows);
 for(let i=0;i<rows;i++){const dy=(box.y1+i+.5-cy)/ry,half=Math.abs(dy)<1?rx*Math.sqrt(1-dy*dy):0;left[i]=cx-half;right[i]=cx+half;}
 return makeRegion({y0:box.y1,left,right,cx,cy,kind});
}
export function rectRegion(box,inset=0,kind='rect'){
 const rows=Math.max(1,Math.round(box.y2-box.y1)),left=new Float32Array(rows),right=new Float32Array(rows);
 for(let i=0;i<rows;i++){const inside=i>=inset&&i<rows-inset;left[i]=inside?box.x1+inset:0;right[i]=inside?box.x2-inset:0;}
 return makeRegion({y0:box.y1,left,right,cx:(box.x1+box.x2)/2,cy:(box.y1+box.y2)/2,kind});
}
// Width available to a line centred on region.cx whose ink spans [y1,y2].
export function availableWidth(region,y1,y2){
 if(y1<region.top-.01||y2>region.bottom+.01)return 0;
 const from=Math.max(0,Math.floor((y1-region.y0)/region.step)),to=Math.min(region.left.length-1,Math.floor((y2-region.y0-.001)/region.step));
 let half=Infinity;
 for(let i=from;i<=to;i++)half=Math.min(half,region.cx-region.left[i],region.right[i]-region.cx);
 return half===Infinity?0:Math.max(0,half*2);
}
// Shrinks a region by `margin` px on every side (row spans + vertical reach).
export function erodeRegion(region,margin){
 const n=region.left.length,reach=Math.max(0,Math.round(margin/region.step)),left=new Float32Array(n),right=new Float32Array(n);
 for(let i=0;i<n;i++){
  let l=-Infinity,r=Infinity;
  for(let j=i-reach;j<=i+reach;j++){if(j<0||j>=n||region.right[j]<=region.left[j]){l=Infinity;r=-Infinity;break;}l=Math.max(l,region.left[j]);r=Math.min(r,region.right[j]);}
  left[i]=l+margin;right[i]=r-margin;if(!(right[i]>left[i])){left[i]=0;right[i]=0;}
 }
 const {y0,step,kind,paper,rectangularity,box}=region;
 return makeRegion({y0,step,left,right,kind,paper,rectangularity,box});
}
