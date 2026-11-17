// SPDX-License-Identifier: AGPL-3.0-or-later
// MediaVault typesetter: balloon shape, role, page-wide sizing, drawing.
import {normalizeText} from './normalize.js';
import {classify,loudness} from './classify.js';
import {ellipseRegion} from './shape.js';
import {bubbleRegion,inkStats,grow} from './region.js';
import {fitPage} from './fit.js';
import {measurer,drawLayout} from './draw.js';
export const TYPESETTER='shaped-cyrillic-v3';
const OUTSIDE=new Set(['sfx','chatter']);
const lumaOf=c=>.299*c[0]+.587*c[1]+.114*c[2];
const saturated=c=>Math.max(...c)-Math.min(...c)>70;
// items: [{index,text,original,box,bubble?,kind?:'bubble'|'free',style?}]
// faceFor(role,{loud}) resolves to {stack,weight,italic,upper}; `original` is a
// 2D context of the untouched page (optional, used for ink colour and tilt).
export async function typesetPage(ctx,items,{faceFor,caps=false,original=null}={}){
 const pageWidth=ctx.canvas.width,loud=loudness(items),prepared=[];
 for(const [i,item]of items.entries()){
  const found=item.kind==='free'?null:bubbleRegion(ctx,item.box,item.bubble),kind=found?.enclosed?'bubble':'free';
  let region=found?.region||ellipseRegion(grow(item.box,.075),0,'box');
  const role=classify({kind,region,loud:loud[i],text:item.text,style:item.style}),outside=kind==='free',face=await faceFor(role,{loud:loud[i]});
  const ink=outside&&original?inkStats(original,ctx,item.box):{color:null,tilt:0},angle=OUTSIDE.has(role)?ink.tilt:0;
  if(angle){const w=item.box.x2-item.box.x1,h=item.box.y2-item.box.y1;region=ellipseRegion(item.box,.3*Math.min(w,h)*Math.abs(Math.sin(angle)),'box');}
  const light=outside?(ink.color?lumaOf(ink.color)>140:false):(region.paper??255)<100;
  const fill=outside&&ink.color&&saturated(ink.color)?`rgb(${ink.color})`:light?'#fff':'#111';
  const style={face,angle,fill,stroke:outside?(light?'#111':'#fff'):null,strokeRatio:role==='sfx'?.1:.14};
  const text=normalizeText(item.text,{caps:face.upper||(caps&&!OUTSIDE.has(role)&&role!=='note')});
  prepared.push({index:item.index,text,box:item.box,region,role,loud:loud[i],measure:measurer(ctx,face),style,kind});
 }
 const {base,layouts}=fitPage(prepared,{pageWidth});
 layouts.forEach((layout,i)=>{if(!layout.overflow)drawLayout(ctx,layout,prepared[i].style);});
 return {base:Math.round(base*10)/10,layouts:layouts.map((l,i)=>({index:l.index,role:l.role,kind:prepared[i].kind,fontSize:Math.round(l.size*10)/10,lines:l.lines.length,hyphens:l.hyphens,shrunk:l.shrunk,fits:!l.overflow,angle:Math.round((prepared[i].style.angle||0)*100)/100}))};
}
