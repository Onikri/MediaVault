// SPDX-License-Identifier: AGPL-3.0-or-later
// Page-level sizing: one average size for dialogue, adjusted subtly to the balloon's size;
// smaller only when the text does not fit, hyphenation before shrinking. Pure.
import {prepare,layoutAt,maxFit,rescale} from './breaks.js';
import {rectRegion} from './shape.js';
export const MAIN_ROLES=new Set(['speech','thought','narration']);
const COMFORT=.9;
const quantile=(values,q)=>{const s=[...values].sort((a,b)=>a-b);return s.length?s[Math.min(s.length-1,Math.floor(q*s.length))]:0;};
export function fitPage(items,{pageWidth,minSize=Math.max(7,pageWidth*.009)}={}){
 const work=items.map(item=>{const plain=prepare(item.text,item.measure);return {item,plain,comfort:maxFit(plain,item.region)*COMFORT};});
 const main=work.filter(w=>MAIN_ROLES.has(w.item.role)&&w.comfort>0).map(w=>w.comfort);
 const extent=w=>Math.sqrt(w.item.region.width*w.item.region.height),typical=quantile(work.filter(w=>MAIN_ROLES.has(w.item.role)).map(extent),.5)||1;
 // The ceiling follows the balloons themselves: on a narrow crop or a webtoon
 // strip the width of the image says nothing about how large a line may be.
 const floor=pageWidth*.015,ceiling=Math.max(pageWidth*.042,typical*.16);
 const base=Math.min(ceiling,Math.max(floor,main.length?quantile(main,.4):pageWidth*.024));
 return {base,layouts:work.map(w=>{
  const {item,plain}=w,role=item.role,loud=item.loud>1.6?Math.min(item.loud,2)**.6:1;
  let limit=w.comfort,prepared=plain,region=item.region,overflow=false;
  const target=role==='sfx'?base*2.6:role==='chatter'?base*.8:role==='note'?base*.95:// A large balloon is lettered larger, a small one a little smaller, by the
  // balloon's own size (not by how much text it holds), so equal balloons agree.
  (role==='narration'?base*.94:base)*Math.min(1.45,Math.max(.94,1+.5*(extent(w)/typical-1)))*loud;
  if(limit<Math.min(target,base*.85)){
   const hyphenated=prepare(item.text,item.measure,{hyphens:true}),better=maxFit(hyphenated,region)*COMFORT;
   if(better>limit*1.08){limit=better;prepared=hyphenated;}
  }
  if(limit<minSize){
   // Last resort: the whole detector box, hyphenation allowed, never an exception.
   const relaxed=rectRegion(item.box,2),hyphenated=prepare(item.text,item.measure,{hyphens:true}),fit=maxFit(hyphenated,relaxed)*COMFORT;
   if(fit>limit){limit=fit;prepared=hyphenated;region=relaxed;}
   overflow=limit<=0;
  }
  const size=Math.max(0,Math.min(target,limit)),shrunk=MAIN_ROLES.has(role)&&size<base*.85;
  const tight=size>0?layoutAt(prepared,region,limit):null,layout=size>0?rescale(tight,region,size)||layoutAt(prepared,region,size):null;
  return {index:item.index,role,region,size,shrunk,overflow:overflow||!layout,hyphens:layout?.hyphens||0,lines:layout?.lines||[],lineHeight:layout?.lineHeight||0};
 })};
}
