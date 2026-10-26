// SPDX-License-Identifier: AGPL-3.0-or-later
import {loadMangaFont} from '../reader-fonts/catalog.js';
import {calculateFittedTextLayout} from './upstream/lib/canvas/text-fit.ts';

export function fontForStyle(style,override='auto'){
 if(override!=='auto')return override;
 return {standard_comic:'comic-relief',bold_scream:'comic-relief',handwritten_sloppy:'pangolin',serif_serious:'serif',digital_box:'mono',sfx_art:'neucha'}[style]||'comic-relief';
}
export async function drawStyledRegion(ctx,region,fontOverride='auto'){
 const [x1,y1,x2,y2]=region.bbox,a=region.appearance||{},style=region.font_style||'standard_comic';
 const id=fontForStyle(style,fontOverride),font=id==='serif'?'Georgia, "Times New Roman", serif':id==='mono'?'Consolas, "Courier New", monospace':await loadMangaFont(id);
 const bold=!!a.bold,italic=!!a.italic,w=x2-x1,h=y2-y1,angle=Math.max(-90,Math.min(90,Number(a.rotation)||0))*Math.PI/180;
 const quarter=Math.abs(angle)>Math.PI/4,baseW=quarter?h:w,baseH=quarter?w:h;
 const factor=Math.min(1,w/(baseW*Math.abs(Math.cos(angle))+baseH*Math.abs(Math.sin(angle))),h/(baseH*Math.abs(Math.cos(angle))+baseW*Math.abs(Math.sin(angle))));
 const width=baseW*factor,height=baseH*factor,maxFont=Math.min(96,Math.max(40,ctx.canvas.width/28));
 const layout=calculateFittedTextLayout(region.translation,width,height,font,undefined,bold,italic,maxFont);
 ctx.save();
 try{
  ctx.font=`${italic?'italic ':''}${bold?700:400} ${layout.fontSize}px ${font}`;
  if(layout.fontSize<4||layout.blockH>layout.maxH+.5||layout.lines.some(s=>ctx.measureText(s).width>layout.maxW+.5))throw Error('Реплика '+region.id+' не помещается. Полный перевод сохранён на ВМ; выбери другой шрифт.');
  ctx.translate((x1+x2)/2,(y1+y2)/2);ctx.rotate(angle);ctx.textBaseline='top';
  ctx.textAlign=['left','right'].includes(a.alignment)?a.alignment:'center';
  const x=ctx.textAlign==='left'?-width/2+8:ctx.textAlign==='right'?width/2-8:0;
  const y=-height/2+8+Math.max(0,(layout.maxH-layout.blockH)/2);
  const color=/^#[\da-f]{6}$/i.test(a.fill_color)?a.fill_color:'#1a1a1a';
  const stroke=/^#[\da-f]{6}$/i.test(a.stroke_color)?a.stroke_color:null;
  ctx.lineJoin='round';ctx.fillStyle=color;
  for(const [i,line]of layout.lines.entries()){
   if(stroke&&a.stroke_width>0){ctx.strokeStyle=stroke;ctx.lineWidth=Math.min(8,a.stroke_width)*2;ctx.strokeText(line,x,y+i*layout.lineH);}
   ctx.fillText(line,x,y+i*layout.lineH);
  }
  return {id:region.id,font,fontId:id,fontStyle:style,speechStyle:region.speech_style,bold,italic,rotation:a.rotation||0,alignment:ctx.textAlign,fillColor:color,strokeColor:stroke,fontSize:layout.fontSize,lines:layout.lines.length,fits:true};
 }finally{ctx.restore();}
}
