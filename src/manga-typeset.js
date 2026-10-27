// SPDX-License-Identifier: AGPL-3.0-or-later
// Worker-safe fitting; every line is measured with the actual Cyrillic font.
export function fitComicText(text,box,measure,{min=10,max=42,oval=true}={}){
 const [x,y,x2,y2]=box,w=(x2-x)*.8,h=(y2-y)*.8,words=String(text).trim().split(/\s+/);
 function attempt(size){
  const lineH=size*1.16,maxLines=Math.max(1,Math.floor(h/lineH));
  for(let count=1;count<=maxLines;count++){
   const lines=[];let index=0,failed=false;
   for(let row=0;row<count;row++){
    const normalized=count===1?0:(row+.5)/count*2-1;
    const width=w*(oval?Math.sqrt(Math.max(.4,1-normalized*normalized*.65)):1);
    let line='';
    while(index<words.length){const next=line?line+' '+words[index]:words[index];if(measure(next,size)>width)break;line=next;index++;}
    if(!line){failed=true;break;}lines.push(line);
   }
   if(!failed&&index===words.length)return {fontSize:size,lineH,lines,width:w,height:h,blockH:lines.length*lineH,fits:true};
  }
  return null;
 }
 let lo=min,hi=Math.min(max,Math.floor(h/1.16)),best=null;
 while(lo<=hi){const mid=(lo+hi)>>1,r=attempt(mid);if(r){best=r;lo=mid+1;}else hi=mid-1;}
 return best||{fits:false,lines:[],fontSize:min};
}
export const styleFont=style=>({standard_comic:'comic-relief',bold_scream:'comic-relief',handwritten_sloppy:'pangolin',sfx_art:'neucha',serif_serious:'serif',digital_box:'mono'}[style]||'comic-relief');
