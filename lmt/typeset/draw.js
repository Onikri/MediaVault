// SPDX-License-Identifier: AGPL-3.0-or-later
// Canvas rendering of a composed reply: centred on the optical centre of the
// balloon by real cap height, round-joined outline only when asked, light
// punctuation hung so the visible edge of the block stays even.
export const fontCss=(face,size)=>`${face.italic?'italic ':''}${face.weight||400} ${size}px ${face.stack}`;
// measure(text) returns the advance at font-size 1, cached per face.
export function measurer(ctx,face){
 const cache=new Map(),font=fontCss(face,100);
 return text=>{let w=cache.get(text);if(w===undefined){ctx.save();ctx.font=font;ctx.fontKerning='normal';w=ctx.measureText(text).width/100;ctx.restore();cache.set(text,w);}return w;};
}
const HANG=[[/-$/,1,1],[/\.\.\.$/,.6,1],[/^\.\.\./,.6,-1]];
export function drawLayout(ctx,layout,style){
 if(!layout.lines.length)return;
 const {size,lines,region}=layout,cx=region.cx,cy=(lines[0].y+lines.at(-1).y)/2;
 ctx.save();ctx.font=fontCss(style.face,size);ctx.textAlign='center';ctx.textBaseline='alphabetic';ctx.fontKerning='normal';ctx.lineJoin='round';ctx.lineCap='round';
 const cap=ctx.measureText('НХ').actualBoundingBoxAscent||size*.7;
 if(style.angle){ctx.translate(cx,cy);ctx.rotate(style.angle);ctx.translate(-cx,-cy);}
 const placed=lines.map(line=>{let shift=0;for(const [pattern,share,side]of HANG){const hit=line.text.match(pattern);if(hit)shift+=side*share*ctx.measureText(hit[0]).width/2;}return [line.text,cx+shift,line.y+cap/2];});
 if(style.stroke){ctx.strokeStyle=style.stroke;ctx.lineWidth=2*Math.max(1.5,size*(style.strokeRatio||.13));for(const [text,x,y]of placed)ctx.strokeText(text,x,y);}
 ctx.fillStyle=style.fill;for(const [text,x,y]of placed)ctx.fillText(text,x,y);
 ctx.restore();
}
