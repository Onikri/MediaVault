// SPDX-License-Identifier: AGPL-3.0-or-later
// Worker-safe fitting; every line is measured with the actual Cyrillic font.
export function fitComicText(text,box,measure,{min=10,max=42,oval=true}={}){
 const [x,y,x2,y2]=box,w=(x2-x)*.8,h=(y2-y)*.8,words=String(text).normalize('NFC').trim().split(/\s+/);
 const graphemes=value=>typeof Intl.Segmenter==='function'?[...new Intl.Segmenter('ru',{granularity:'grapheme'}).segment(value)].map(x=>x.segment):Array.from(value);
 function tokens(size){
  const out=[];for(const word of words){
   if(measure(word,size)<=w*(oval?.75:1)||!/^\p{L}+[,.!?…]?$/u.test(word)){out.push(word);continue;}
   const chars=graphemes(word);let part='';
   for(const c of chars){if(part&&measure(part+c+'-',size)>w*(oval?.75:1)){out.push(part+'-');part=c;}else part+=c;}if(part)out.push(part);
  }return out;
 }
 function attempt(size){
  const lineH=size*1.16,maxLines=Math.min(40,Math.max(1,Math.floor(h/lineH))),parts=tokens(size);
  for(let count=1;count<=maxLines;count++){
   const lines=[];let index=0,failed=false;
   for(let row=0;row<count;row++){
    const normalized=count===1?0:(row+.5)/count*2-1;
    const width=w*(oval?Math.sqrt(Math.max(.4,1-normalized*normalized*.65)):1);
    let line='';
    while(index<parts.length){const next=line?line+(line.endsWith('-')?'':' ')+parts[index]:parts[index];if(measure(next,size)>width)break;line=next;index++;}
    if(!line){failed=true;break;}lines.push(line);
   }
   if(!failed&&index===parts.length){
    // Rebalance orphan words without changing their order or exceeding each
    // row's oval width. Every candidate uses the real loaded Cyrillic font.
    for(let row=lines.length-2;row>=0;row--){const list=lines[row].split(' ');if(list.length<2||lines[row].endsWith('-'))continue;const word=list.pop(),a=list.join(' '),b=word+' '+lines[row+1],normalized=(row+1+.5)/count*2-1,limit=w*(oval?Math.sqrt(Math.max(.4,1-normalized*normalized*.65)):1);if(measure(b,size)<=limit&&Math.abs(measure(a,size)-measure(b,size))<Math.abs(measure(lines[row],size)-measure(lines[row+1],size))){lines[row]=a;lines[row+1]=b;}}
    return {fontSize:size,lineH,lines,width:w,height:h,blockH:lines.length*lineH,fits:true};
   }
  }
  return null;
 }
 let lo=min,hi=Math.min(max,Math.floor(h/1.16)),best=null;
 while(lo<=hi){const mid=(lo+hi)>>1,r=attempt(mid);if(r){best=r;lo=mid+1;}else hi=mid-1;}
 return best||{fits:false,lines:[],fontSize:min};
}
export const styleFont=style=>({standard_comic:'comic-relief',bold_scream:'comic-relief',handwritten_sloppy:'pangolin',sfx_art:'neucha',serif_serious:'serif',digital_box:'mono'}[style]||'comic-relief');
