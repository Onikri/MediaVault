// SPDX-License-Identifier: AGPL-3.0-or-later
// Role of a reply. One main typeface carries speech (regular), thoughts
// (italic) and emphasis; situational faces are reserved for narration boxes,
// small side chatter, sound effects and notes. Unsure → speech. Pure.
export const ROLES=['speech','thought','narration','chatter','sfx','note'];
export function classify({kind,region,loud=1,text='',style}){
 if(ROLES.includes(style))return style;
 const words=text.trim().split(/\s+/).filter(Boolean),sentence=/[,.:;]/.test(text.replace(/\.{3}/g,''));
 if(kind==='free'){
  if(words.length<=2&&!sentence&&text.length<=18)return 'sfx';
  if(loud<.85)return 'chatter';
  return 'narration';
 }
 if(/^\(.+\)$/.test(text.trim()))return 'thought';
 if(region?.kind==='bubble'&&region.rectangularity>.94&&words.length>=3)return 'narration';
 return 'speech';
}
// Glyph-size proxy from the source box: sqrt(area per character), relative to the page median.
export function loudness(items){
 const sizes=items.map(i=>{const n=[...String(i.original||'').replace(/\s/g,'')].length;return n?Math.sqrt((i.box.x2-i.box.x1)*(i.box.y2-i.box.y1)/n):0;});
 const known=sizes.filter(Boolean).sort((a,b)=>a-b),median=known.length?known[Math.floor((known.length-1)/2)]:0;
 return sizes.map(s=>s&&median?s/median:1);
}
// Tilt from the nearest axis (radians) of an ink point cloud; 0 when not clearly elongated.
export function tiltOf(points){
 const n=points.length/2;if(n<24)return 0;
 let mx=0,my=0;for(let i=0;i<n;i++){mx+=points[2*i];my+=points[2*i+1];}mx/=n;my/=n;
 let xx=0,yy=0,xy=0;for(let i=0;i<n;i++){const dx=points[2*i]-mx,dy=points[2*i+1]-my;xx+=dx*dx;yy+=dy*dy;xy+=dx*dy;}
 const spread=Math.hypot(xx-yy,2*xy),major=(xx+yy+spread)/2,minor=(xx+yy-spread)/2;
 if(minor<=0||major/minor<3)return 0;
 let angle=.5*Math.atan2(2*xy,xx-yy);
 if(angle>Math.PI/4)angle-=Math.PI/2;else if(angle<-Math.PI/4)angle+=Math.PI/2;
 const limit=Math.PI/6;return Math.abs(angle)<Math.PI/30?0:Math.max(-limit,Math.min(limit,angle));
}
