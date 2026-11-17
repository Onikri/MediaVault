// SPDX-License-Identifier: AGPL-3.0-or-later
// Composes a reply into lines that follow the balloon's shape. Pure; no DOM.
// `measure(text)` returns the advance width at font-size 1.
import {splitWords,isPreposition,isTrailingParticle,isLeadingParticle,endsWithPunctuation,NBSP} from './normalize.js';
import {hyphenate} from './hyphen-ru.js';
import {availableWidth} from './shape.js';
export const LEADING=1.2,INK=.48;
const PENALTY={hyphen:.7,join:.3,doubleHyphen:3,preposition:.06,particle:.1,punctuation:-.04,widow:.08,vertical:.6};
export function prepare(text,measure,{hyphens=false}={}){
 const words=splitWords(text),frags=[];
 words.forEach((word,index)=>{
  const parts=hyphens?hyphenate(word):[word];
  parts.forEach((part,p)=>frags.push({text:part,width:measure(part),word:index,after:p<parts.length-1?(part.endsWith('-')?'join':'hyphen'):'space'}));
 });
 const space=measure('н н')-measure('нн'),hyphen=measure('-'),pre=new Float64Array(frags.length+1);
 frags.forEach((f,i)=>pre[i+1]=pre[i]+f.width+(f.after==='space'?space:0));
 return {words,frags,space,hyphen,pre,total:Math.max(0,pre[frags.length]-space)};
}
const lineWidth=(p,k,j)=>{const last=p.frags[j-1];return p.pre[j]-p.pre[k]-(last.after==='space'?p.space:0)+(last.after==='hyphen'?p.hyphen:0);};
function breakPenalty(p,k,j,lines){
 const m=p.frags.length,last=p.frags[j-1];let cost=0;
 if(last.after!=='space'){cost+=last.after==='hyphen'?PENALTY.hyphen:PENALTY.join;if(k>0&&p.frags[k-1].after!=='space')cost+=PENALTY.doubleHyphen;}
 else if(j<m){
  const word=p.words[last.word],next=p.words[p.frags[j].word];
  if(isPreposition(word))cost+=PENALTY.preposition;
  if(isLeadingParticle(word)||isTrailingParticle(next))cost+=PENALTY.particle;
  if(endsWithPunctuation(word))cost+=PENALTY.punctuation;
 }else if(lines>1&&j-k===1&&last.text.replace(/[^\p{L}]/gu,'').length<=3&&k>0&&p.frags[k-1].after==='space')cost+=PENALTY.widow;
 return cost;
}
// Best split of the prepared text into exactly `n` lines at font-size `size`.
function compose(p,region,size,n){
 const m=p.frags.length,lineH=size*LEADING,blockH=(n-1)*lineH+2*INK*size;
 if(n>m||blockH>region.height+.01)return null;
 const centre=Math.min(Math.max(region.cy,region.top+blockH/2),region.bottom-blockH/2),avail=[],centres=[];let sum=0;
 for(let i=0;i<n;i++){const yc=centre+(i-(n-1)/2)*lineH,a=availableWidth(region,yc-INK*size,yc+INK*size)/size;if(a<=0)return null;avail.push(a);centres.push(yc);sum+=a;}
 if(sum<p.total)return null;
 const rho=Math.min(1,p.total/sum),dp=Array.from({length:n+1},()=>new Float64Array(m+1).fill(Infinity)),from=Array.from({length:n+1},()=>new Int32Array(m+1).fill(-1));
 dp[0][0]=0;
 for(let i=1;i<=n;i++)for(let j=i;j<=m-(n-i);j++){
  if(i===n&&j!==m)continue;
  for(let k=j-1;k>=i-1;k--){
   const w=lineWidth(p,k,j);if(w>avail[i-1])break;
   if(dp[i-1][k]===Infinity)continue;
   const fill=w/avail[i-1]-rho,cost=dp[i-1][k]+fill*fill*.6+breakPenalty(p,k,j,n);
   if(cost<dp[i][j]){dp[i][j]=cost;from[i][j]=k;}
  }
 }
 if(dp[n][m]===Infinity)return null;
 const lines=[];let j=m,hyphens=0;
 for(let i=n;i>=1;i--){
  const k=from[i][j],last=p.frags[j-1];let text='';
  for(let f=k;f<j;f++)text+=p.frags[f].text+(f<j-1&&p.frags[f].after==='space'?' ':'');
  if(last.after==='hyphen'){text+='-';hyphens++;}
  lines.unshift({text:text.replaceAll(NBSP,' '),width:lineWidth(p,k,j)*size,avail:avail[i-1]*size,y:centres[i-1]});j=k;
 }
 const vertical=rho-blockH/region.height;
 return {size,lines,hyphens,lineHeight:lineH,cost:dp[n][m]+PENALTY.vertical*vertical*vertical};
}
// Best layout at a given size over every admissible line count, or null.
export function layoutAt(p,region,size){
 const most=Math.min(p.frags.length,Math.floor((region.height-2*INK*size)/(size*LEADING))+1);let best=null;
 for(let n=1;n<=most;n++){const candidate=compose(p,region,size,n);if(candidate&&(!best||candidate.cost<best.cost))best=candidate;}
 return best;
}
// Largest size (0.5 px steps) at which the text fits the region.
export function maxFit(p,region,{min=5,max=96}={}){
 if(!p.frags.length||!layoutAt(p,region,min))return 0;
 let lo=min,hi=Math.min(max,region.height/(2*INK));
 if(hi<=lo)return lo;
 if(layoutAt(p,region,hi))return hi;
 while(hi-lo>.5){const mid=(lo+hi)/2;if(layoutAt(p,region,mid))lo=mid;else hi=mid;}
 return Math.floor(lo*2)/2;
}
// Keeps the line breaks found at the tightest fit and sets them at a smaller size:
// the block stays similar to the balloon instead of collapsing into a column.
export function rescale(layout,region,size){
 if(!layout||size>=layout.size)return layout;
 const k=size/layout.size,n=layout.lines.length,lineH=size*LEADING,blockH=(n-1)*lineH+2*INK*size;
 const centre=Math.min(Math.max(region.cy,region.top+blockH/2),region.bottom-blockH/2),lines=[];
 for(let i=0;i<n;i++){const y=centre+(i-(n-1)/2)*lineH,avail=availableWidth(region,y-INK*size,y+INK*size),width=layout.lines[i].width*k;if(width>avail+.01)return null;lines.push({...layout.lines[i],width,avail,y});}
 return {...layout,size,lines,lineHeight:lineH};
}
