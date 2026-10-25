function wrap(text,width,font,measure){
 const lines=[];let line='';
 for(const word of String(text||'').trim().split(/\s+/)){
  if(measure(word,font)>width)return null;
  const next=line?line+' '+word:word;
  if(measure(next,font)>width&&line){lines.push(line);line=word;}else line=next;
 }
 if(line)lines.push(line);return lines;
}
export function fitTranslation(region,size,measure=(text,font)=>Array.from(text).length*font*.56){
 const w=Math.max(0,Number(region.w)*Number(size?.width||0)),h=Math.max(0,Number(region.h)*Number(size?.height||0));
 if(region.placement==='note'||w<30||h<24)return {mode:'note',font:0,lines:[]};
 // An inset rectangle keeps text away from oval edges and original outlines.
 const shaped=(region.shape?.length||0)>2;
 const width=w*(shaped ? .82 : 1)-10,height=h*(shaped ? .86 : 1)-8;
 for(let font=24;font>=10;font-=.5){const lineHeight=font*1.18,lines=wrap(region.text,width,font,measure);if(lines&&lines.length*lineHeight<=height)return {mode:'bubble',font,lineHeight,lines};}
 return {mode:'note',font:0,lines:[]};
}
// Kept for external demos and earlier consumers; the reader checks mode as well.
export function translationFont(region,size){return Math.min(18,fitTranslation(region,size).font||10);}
