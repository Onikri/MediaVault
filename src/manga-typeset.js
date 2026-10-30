// SPDX-License-Identifier: AGPL-3.0-or-later
// Worker-safe fitting; every line is measured with the actual Cyrillic font.
import russian from 'hyphen/ru/index.js';
const splitCache=new Map();
export function russianBreaks(word){
 if(splitCache.has(word))return splitCache.get(word);
 const match=/^([А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)*)([,.!?…:;]*)$/u.exec(word),points=[];
 if(match){
  const core=match[1],parts=russian.hyphenateSync(core).split('\u00ad');let at=0;
  for(const part of parts.slice(0,-1)){
   at+=part.length;const left=core.slice(0,at).replaceAll('-',''),right=core.slice(at).replaceAll('-','');
   if(left.length>=2&&right.length>=2&&/[аеёиоуыэюя]/i.test(left)&&/[аеёиоуыэюя]/i.test(right)&&!/^[ьъыЙй]/i.test(right))points.push(at);
  }
  for(let i=1;i<core.length;i++)if(core[i-1]==='-'&&!points.includes(i)){const left=core.slice(0,i).replaceAll('-',''),right=core.slice(i).replaceAll('-','');if(left.length>=2&&right.length>=2&&/[аеёиоуыэюя]/i.test(left)&&/[аеёиоуыэюя]/i.test(right))points.push(i);}
  points.sort((a,b)=>a-b);
 }
 if(splitCache.size>2048)splitCache.clear();splitCache.set(word,points);return points;
}
// Sample the restored image, not the original border, which may cross dark hair.
export function comicInkColor(image,box){
 const values=[],step=Math.max(1,Math.floor(Math.sqrt((box[2]-box[0])*(box[3]-box[1])/256)));
 for(let y=Math.ceil(box[1]+(box[3]-box[1])*.15);y<box[3]-(box[3]-box[1])*.15;y+=step)for(let x=Math.ceil(box[0]+(box[2]-box[0])*.15);x<box[2]-(box[2]-box[0])*.15;x+=step){const n=(y*image.width+x)*4;values.push(.2126*image.data[n]+.7152*image.data[n+1]+.0722*image.data[n+2]);}
 values.sort((a,b)=>a-b);const luma=values[values.length>>1]??255;
 return {luma:Math.round(luma),dark:luma<140,outline:(values[Math.floor(values.length*.9)]??luma)-(values[Math.floor(values.length*.1)]??luma)>65};
}
export function fitComicText(text,box,measure,{min=10,max=42,oval=true}={}){
 const [x,y,x2,y2]=box,w=(x2-x)*.8,h=(y2-y)*.8,words=String(text).normalize('NFC').replace(/\.{3,}/g,'…').trim().split(/\s+/);
 const measured=new Map(),rawMeasure=measure;measure=(value,size)=>{const key=size+'|'+value;if(!measured.has(key))measured.set(key,rawMeasure(value,size));return measured.get(key);};
 function attempt(size){
  const lineH=size*1.16,maxLines=Math.min(40,Math.max(1,Math.floor(h/lineH)));
  for(let count=1;count<=maxLines;count++){
   const lines=[];let index=0,pending='',failed=false;
   for(let row=0;row<count;row++){
    const normalized=count===1?0:(row+.5)/count*2-1;
    const width=w*(oval?Math.sqrt(Math.max(.4,1-normalized*normalized*.65)):1);
    let line='';
    while(index<words.length){
     const word=pending||words[index],next=line?line+' '+word:word;
     if(measure(next,size)<=width){line=next;pending='';index++;continue;}
     if(line)break; // prefer wrapping an entire word to the next row
     const point=russianBreaks(word).filter(at=>measure(word.slice(0,at)+(word[at-1]==='-'?'':'-'),size)<=width).at(-1);
     if(point){line=word.slice(0,point)+(word[point-1]==='-'?'':'-');pending=word.slice(point);}break;
    }
    if(!line){failed=true;break;}lines.push(line);
   }
   if(!failed&&index===words.length&&!pending){
    // Rebalance orphan words without changing their order or exceeding each
    // row's oval width. Every candidate uses the real loaded Cyrillic font.
    for(let row=lines.length-2;row>=0;row--){const list=lines[row].split(' ');if(list.length<2||lines[row].endsWith('-'))continue;const word=list.pop(),a=list.join(' '),b=word+' '+lines[row+1],normalized=(row+1+.5)/count*2-1,limit=w*(oval?Math.sqrt(Math.max(.4,1-normalized*normalized*.65)):1);if(measure(b,size)<=limit&&Math.abs(measure(a,size)-measure(b,size))<Math.abs(measure(lines[row],size)-measure(lines[row+1],size))){lines[row]=a;lines[row+1]=b;}}
    return {fontSize:size,lineH,lines,width:w,height:h,blockH:lines.length*lineH,fits:true};
   }
  }
  return null;
 }
 // Oval row widths and syllable wrapping are discrete: a failed size does not
 // prove every larger size fails. Search bounded candidates from large to small
 // and memoize glyph measurements across the candidate line counts.
 for(let size=Math.min(max,Math.floor(h/1.16));size>=min;size--){const fit=attempt(size);if(fit)return fit;}
 return {fits:false,lines:[],fontSize:min};
}
export const styleFont=style=>({standard_comic:'comic-relief',bold_scream:'comic-relief',handwritten_sloppy:'marck-script',handwritten_soft:'pangolin',handwritten_narrow:'neucha',sfx_art:'ruslan-display',serif_serious:'pt-serif',digital_box:'press-start'}[style]||'comic-relief');
