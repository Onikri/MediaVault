// SPDX-License-Identifier: AGPL-3.0-or-later
import {drawFittedText,resolveFontStack} from './upstream/lib/canvas/text-fit.ts';

export async function renderTranslated(cleanedBytes,regions,scale=1){
 const bitmap=await createImageBitmap(new Blob([cleanedBytes]));
 try{
  const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
  const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0);
  const fontStack=await resolveFontStack();
  for(const region of regions){
   const box={x1:region.x*bitmap.width,y1:region.y*bitmap.height,x2:(region.x+region.w)*bitmap.width,y2:(region.y+region.h)*bitmap.height,style:region.style};
   await drawFittedText(ctx,region.text,box,region.fontFamily||fontStack,40*scale);
  }
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.95));
  if(!blob)throw Error('Не удалось собрать страницу.');
  return await blob.arrayBuffer();
 }finally{bitmap.close();}
}
