import {paperBubble} from './manga-layout.js';
// A region owns only its glyph mask. All masks are derived from the immutable
// original; one region can never erase Russian text inserted into another.
// Square neighbourhood of `radius`, done as a row pass and a column pass.
export function dilateInk(mask,w,h,radius=1){
 const rows=new Uint8Array(mask.length),out=new Uint8Array(mask.length);
 for(let y=0;y<h;y++){let last=-Infinity;const at=y*w;
  for(let x=0;x<w;x++){if(mask[at+x])last=x;if(x-last<=radius)rows[at+x]=1;}
  last=Infinity;for(let x=w-1;x>=0;x--){if(mask[at+x])last=x;if(last-x<=radius)rows[at+x]=1;}
 }
 for(let x=0;x<w;x++){let last=-Infinity;
  for(let y=0;y<h;y++){if(rows[y*w+x])last=y;if(y-last<=radius)out[y*w+x]=1;}
  last=Infinity;for(let y=h-1;y>=0;y--){if(rows[y*w+x])last=y;if(last-y<=radius)out[y*w+x]=1;}
 }
 return out;
}

function contrastGlyphs(data,w,h,box){
 const ink=new Uint8Array(w*h),seen=new Uint8Array(w*h),queue=new Int32Array(w*h),area=(box[2]-box[0])*(box[3]-box[1]);
 const luma=(x,y)=>{const n=(y*w+x)*4;return (data[n]+data[n+1]+data[n+2])/3;};
 const stride=w+1,sums=new Float64Array((w+1)*(h+1));
 for(let y=0;y<h;y++){let row=0;for(let x=0;x<w;x++){row+=luma(x,y);sums[(y+1)*stride+x+1]=sums[y*stride+x+1]+row;}}
 for(let y=box[1];y<box[3];y++)for(let x=box[0];x<box[2];x++){
  const a=Math.max(0,x-3),b=Math.min(w,x+4),c=Math.max(0,y-3),d=Math.min(h,y+4),sum=sums[d*stride+b]-sums[c*stride+b]-sums[d*stride+a]+sums[c*stride+a],count=(b-a)*(d-c);
  const contrast=luma(x,y)-sum/count;if(Math.abs(contrast)>32)ink[y*w+x]=contrast<0?1:2;
 }
 for(let seed=0;seed<ink.length;seed++)if(ink[seed]&&!seen[seed]){
  let a=0,z=1,x1=w,y1=h,x2=0,y2=0;queue[0]=seed;seen[seed]=1;
  while(a<z){const n=queue[a++],x=n%w,y=(n/w)|0;x1=Math.min(x1,x);y1=Math.min(y1,y);x2=Math.max(x2,x);y2=Math.max(y2,y);
   for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const xx=x+dx,yy=y+dy,i=yy*w+xx;if(xx>=0&&xx<w&&yy>=0&&yy<h&&ink[i]===ink[seed]&&!seen[i]){seen[i]=1;queue[z++]=i;}}
  }
  const tall=y2-y1+1>=(box[3]-box[1])*.95,wide=x2-x1+1>=(box[2]-box[0])*.95;
  const rule=tall&&wide||(tall&&x2-x1+1<(box[2]-box[0])*.2)||(wide&&y2-y1+1<(box[3]-box[1])*.2);
  if(z<4||z>area*.4||rule)for(let k=0;k<z;k++)ink[queue[k]]=0;
 }
 return ink.map(value=>value?1:0);
}
function protectRules(mask,data,w,h,local,bounds){
  const luma=(x,y)=>{const n=(Math.max(0,Math.min(h-1,y))*w+Math.max(0,Math.min(w-1,x)))*4;return (data[n]+data[n+1]+data[n+2])/3;};
  for(let x=bounds[0];x<bounds[2];x++)if(x<local[0]||x>=local[2]){
   let count=0;for(let y=bounds[1];y<bounds[3];y++){const value=luma(x,y);if(value<80&&(x<2||luma(x-2,y)>value+35)&&(x>=w-2||luma(x+2,y)>value+35))count++;}
   if(count>=Math.max(32,(bounds[3]-bounds[1])*.85))for(let y=bounds[1];y<bounds[3];y++)for(let dx=-1;dx<=1;dx++)if(x+dx>=0&&x+dx<w)mask[y*w+x+dx]=0;
  }
  for(let y=bounds[1];y<bounds[3];y++)if(y<local[1]||y>=local[3]){
   let count=0;for(let x=bounds[0];x<bounds[2];x++){const value=luma(x,y);if(value<80&&(y<2||luma(x,y-2)>value+35)&&(y>=h-2||luma(x,y+2)>value+35))count++;}
   if(count>=Math.max(32,(bounds[2]-bounds[0])*.85))for(let x=bounds[0];x<bounds[2];x++)for(let dy=-1;dy<=1;dy++)if(y+dy>=0&&y+dy<h)mask[(y+dy)*w+x]=0;
  }
}
// Letters inside the box `local` of an RGBA patch → {ink, glyph, stroke}.
// Ink is what differs from the paper by tone; it is split into connected
// components and each is judged as a shape:
//  - a letter lies inside the box: a component that runs out of it is a line
//    of the drawing or of the balloon;
//  - a letter is about one glyph in size (two when neighbours touch);
//  - a letter has the stroke weight of the text: long thin strokes are hair,
//    speed lines or hatching;
//  - dots and marks smaller than a stroke count only next to a letter
//    (ellipsis, diacritics), never on their own (screentone).
// light: look for light letters (true) or dark ones (false) instead of the
// ones opposite to the paper; rimmed: keep only letters drawn with an outline
// of the opposite tone (white letters with a black edge and the reverse), so
// highlights and gaps of the drawing are never taken for text.
export function letterInk(data,w,h,local,paper,{light,rimmed=false}={}){
 const total=w*h,dark=light===undefined?paper>=128:!light,tone=new Uint8Array(total),label=new Int32Array(total).fill(-1),queue=new Int32Array(total),ink=new Uint8Array(total);
 const level=light===undefined?(dark?Math.min(paper-60,150):Math.max(paper+60,105)):dark?Math.max(40,Math.min(paper-45,110)):Math.min(235,Math.max(185,paper+40));
 for(let n=0;n<total;n++){const p=n*4,luma=(data[p]+data[p+1]+data[p+2])/3;tone[n]=data[p+3]>127&&(dark?luma<level:luma>level)?1:0;}
 const bw=local[2]-local[0],bh=local[3]-local[1],parts=[];
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  const seed=y*w+x;if(!tone[seed]||label[seed]>=0)continue;
  let a=0,z=1,x1=w,y1=h,x2=0,y2=0,inside=0,edge=0;queue[0]=seed;label[seed]=parts.length;
  while(a<z){
   const n=queue[a++],px=n%w,py=(n/w)|0;x1=Math.min(x1,px);y1=Math.min(y1,py);x2=Math.max(x2,px);y2=Math.max(y2,py);
   if(px>=local[0]&&px<local[2]&&py>=local[1]&&py<local[3])inside++;
   if(!px||!py||px===w-1||py===h-1||!tone[n-1]||!tone[n+1]||!tone[n-w]||!tone[n+w])edge++;
   for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){const xx=px+dx,yy=py+dy,i=yy*w+xx;if(xx>=0&&xx<w&&yy>=0&&yy<h&&tone[i]&&label[i]<0){label[i]=parts.length;queue[z++]=i;}}
  }
  parts.push({pixels:queue.slice(0,z),area:z,x1,y1,x2,y2,width:x2-x1+1,height:y2-y1+1,inside:inside/z,
   out:Math.max(0,local[0]-x1,local[1]-y1,x2-local[2]+1,y2-local[3]+1),stroke:2*z/Math.max(1,edge)});
 }
 const size=p=>Math.max(p.width,p.height),weighted=(list,value,share)=>{
  const rows=list.map(p=>[value(p),p.area]).sort((a,b)=>a[0]-b[0]),all=rows.reduce((n,r)=>n+r[1],0);let sum=0;
  for(const [v,weight] of rows){sum+=weight;if(sum>=all*share)return v;}return rows.at(-1)?.[0]||0;};
 // The text's own measure, from components that sit wholly inside the box.
 let sample=parts.filter(p=>p.out<=1&&p.area>=8&&p.area<=bw*bh*.4);
 if(!sample.length)sample=parts.filter(p=>p.inside>=.6);
 if(!sample.length)return {ink,glyph:0,stroke:0};
 const stroke=weighted(sample,p=>p.stroke,.5);
 // A word drawn in one piece (cursive sound effects, outlined letters whose
 // outlines merge) is dozens of strokes long: it says nothing about the size of
 // one letter. Taken as a letter size it lets a whole hand or collar through.
 const joined=p=>size(p)>p.stroke*20,single=sample.filter(p=>!joined(p));
 // Bars and lines say nothing about the size of a letter.
 const squat=single.filter(p=>p.stroke>=stroke*.6&&Math.max(p.width,p.height)/Math.min(p.width,p.height)<3),bold=squat.length?squat:single.filter(p=>p.stroke>=stroke*.6);
 const glyph=Math.max(6,Math.min(Math.min(bw,bh),single.length?weighted(bold.length?bold:single,size,.8):stroke*8));
 // The joined word itself is lettering: wholly inside the box, open strokes of the text's own weight.
 const word=p=>joined(p)&&p.inside>=.95&&p.out<=1&&p.area<=bw*bh*.4&&p.area<=p.width*p.height*.4&&p.stroke>=stroke*.75&&p.stroke<=stroke*1.4;
 // Letters that touch (kerned Latin, a joined kana pair) form a run one glyph
 // high (or wide) and several long; a run is a letter too.
 const letter=p=>p.inside>=.6&&p.out<=Math.max(2,glyph*.3)&&p.area<=bw*bh*.4&&(size(p)<=glyph*2.2||Math.min(p.width,p.height)<=glyph*1.3&&size(p)<=glyph*4.5&&p.stroke>=stroke*.7)
  &&!(p.stroke<stroke*.5&&size(p)>glyph*.9)
  &&!(Math.max(p.width,p.height)/Math.min(p.width,p.height)>=5&&p.stroke<stroke*.7&&size(p)>glyph*.6);
 const lumaAt=n=>{const p=n*4;return (data[p]+data[p+1]+data[p+2])/3;};
 // The edge of a letter drawn with an outline: the pixels one and two steps
 // around it are far darker (lighter) than the letter itself.
 const withRim=p=>{
  const own=new Set(p.pixels);let sum=0,count=0,core=0;
  for(const n of p.pixels){core+=lumaAt(n);const x=n%w;for(const d of [-2,-1,1,2])for(const i of [n+d,n+d*w]){if(i<0||i>=total||own.has(i)||(Math.abs(d)<=2&&i===n+d&&((i%w)-x)!==d))continue;sum+=lumaAt(i);count++;}}
  return count>0&&(dark?sum/count-core/p.area>=50:core/p.area-sum/count>=50);
 };
 const least=Math.max(6,(glyph*.18)**2),found=parts.filter(p=>(letter(p)||word(p))&&p.area>=least&&(!rimmed||withRim(p)));
 // A bar (a long vowel mark, a dash) is a letter only right next to compact
 // letters; alone under or beside the text it is a line of the drawing.
 const long=p=>Math.max(p.width,p.height)/Math.min(p.width,p.height)>=4,compact=found.filter(p=>!long(p));
 const main=found.filter(p=>!long(p)||compact.some(m=>p.x1<=m.x2+glyph*.35&&p.x2>=m.x1-glyph*.35&&p.y1<=m.y2+glyph*.35&&p.y2>=m.y1-glyph*.35));
 const reach=glyph*.4,near=p=>main.some(m=>p.x1<=m.x2+reach&&p.x2>=m.x1-reach&&p.y1<=m.y2+reach&&p.y2>=m.y1-reach);
 // A detector's box often clips the last letter or the ellipsis of a column.
 // Text goes on past the box only as more of the same: glyph-sized or smaller,
 // with the text's stroke, right next to a letter already found, within one
 // glyph of the box.
 // In line: the next letter of a column (or of a row), not something beside it.
 const inLine=(p,list,gap)=>list.some(m=>{
  const across=Math.min(p.x2,m.x2)-Math.max(p.x1,m.x1)+1,along=Math.min(p.y2,m.y2)-Math.max(p.y1,m.y1)+1;
  return across>=p.width*.5&&along>=-gap||along>=p.height*.5&&across>=-gap;
 });
 const taken=new Set(main);
 // The chain may run two glyphs past the box, one neighbour at a time.
 for(let round=0;round<4;round++)for(const p of parts){
  if(taken.has(p)||p.inside>=.6||p.out>glyph*2.3||size(p)>glyph*1.6||p.area<least||p.stroke<stroke*.6||p.area>bw*bh*.4)continue;
  // A bar as heavy as the text (the stroke of «!», a long vowel mark) continues it; a thin one is a line.
  if(Math.max(p.width,p.height)/Math.min(p.width,p.height)>=5&&size(p)>glyph*.6&&p.stroke<stroke*.85)continue;
  // A solid dot is as thick as it is wide; the perimeter estimate reads it thinner.
  const weight=Math.max(p.stroke,p.area>=p.width*p.height*.7?Math.min(p.width,p.height):0);
  if(p.area<p.width*p.height*.25||weight<stroke*.75||!inLine(p,main,glyph*1.1))continue;
  taken.add(p);main.push(p);
 }
 // Dots of an ellipsis and diacritics: as thick as the text's stroke (a
 // screentone dot is thinner), compact, and next to a letter or to a mark
 // already taken — an ellipsis is a chain.
 const marks=[],dot=p=>!taken.has(p)&&p.area<least&&p.out<=glyph*2.3&&Math.min(p.width,p.height)>=Math.max(2,stroke*.7)&&size(p)<=glyph*.45&&Math.max(p.width,p.height)/Math.min(p.width,p.height)<=3.5;
 const beside=(p,list,gap)=>list.some(m=>p.x1<=m.x2+gap&&p.x2>=m.x1-gap&&p.y1<=m.y2+gap&&p.y2>=m.y1-gap);
 for(let round=0;round<4;round++){
  let added=0;
  for(const p of parts)if(dot(p)&&(p.out<=1?beside(p,main,glyph*.6)||beside(p,marks,glyph*.5):inLine(p,main,glyph*1.1)||inLine(p,marks,glyph*.6))){taken.add(p);marks.push(p);added++;}
  if(!added)break;
 }
 // The body of «!» or «?» stands right above its dot: slanted, tapering, often
 // thinner than the letters, so it is taken by its dot.
 for(const d of [...marks])for(const p of parts){
  if(taken.has(p)||p.area<4||size(p)>glyph*1.3||p.y2>d.y1+1||d.y1-p.y2>glyph*.5)continue;
  if(Math.min(p.x2,d.x2+glyph*.25)<Math.max(p.x1,d.x1-glyph*.25)||p.height<p.width*1.5)continue;
  taken.add(p);marks.push(p);
 }
 for(const part of [...main,...marks])for(const n of part.pixels)ink[n]=1;
 // A letter touched by a line of the drawing is one component with that line
 // and was refused with it. Thin lines are peeled off (one pixel of erosion
 // removes anything up to two pixels wide); what is left is judged again as
 // letters and, when it passes, taken together with its own edge. The line
 // itself stays.
 const index=new Map(parts.map((p,i)=>[p,i])),inCore=new Uint8Array(total),inPiece=new Uint8Array(total);
 for(const p of parts){
  // Only pieces of drawing about the size of a few letters; a whole dark area is not lettering.
  if(taken.has(p)||p.inside<.2||p.area<least*2||stroke<3||p.area>glyph*glyph*24)continue;
  if(!(p.out>Math.max(2,glyph*.3)||size(p)>glyph*2.2))continue;
  const id=index.get(p),own=n=>n>=0&&n<total&&label[n]===id,core=p.pixels.filter(n=>{const x=n%w;return x>0&&x<w-1&&own(n-1)&&own(n+1)&&own(n-w)&&own(n+w);});
  for(const n of core)inCore[n]=1;
  const left=new Set(core);
  while(left.size){
   const seed=left.values().next().value,piece=[seed];left.delete(seed);inPiece[seed]=1;let x1=w,y1=h,x2=0,y2=0,inside=0,edge=0;
   for(let a=0;a<piece.length;a++){
    const n=piece[a],px=n%w,py=(n/w)|0;x1=Math.min(x1,px);y1=Math.min(y1,py);x2=Math.max(x2,px);y2=Math.max(y2,py);
    if(px>=local[0]&&px<local[2]&&py>=local[1]&&py<local[3])inside++;
    let open=false;
    for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){if(!dx&&!dy)continue;const i=n+dy*w+dx;if(px+dx<0||px+dx>=w)continue;if(left.has(i)){left.delete(i);piece.push(i);inPiece[i]=1;}else if(!dx!==!dy&&!inCore[i]&&!inPiece[i])open=true;}
    if(open)edge++;
   }
   for(const n of piece)inPiece[n]=0;
   const width=x2-x1+3,height=y2-y1+3,out=Math.max(0,local[0]-x1+1,local[1]-y1+1,x2-local[2]+2,y2-local[3]+2),weight=2*piece.length/Math.max(1,edge)+2;
   // What is left of a line of the drawing is still a line, not a letter.
   if(Math.max(width,height)/Math.min(width,height)>=4)continue;
   if(piece.length<least*.5||inside<piece.length*.6||out>Math.max(2,glyph*.3)||Math.max(width,height)>glyph*2.2||weight<stroke*.6)continue;
   for(const n of piece){ink[n]=1;for(const i of [n-1,n+1,n-w,n+w,n-w-1,n-w+1,n+w-1,n+w+1])if(own(i))ink[i]=1;}
  }
  for(const n of core)inCore[n]=0;
 }
 return {ink,glyph,stroke};
}
// The mask around the letters: two pixels for their anti-aliased edge and,
// on paper of a known tone, any fringe still darker (or lighter) than the
// paper next to it, so no ghost of the old letters is left behind.
// Width of an outline drawn around the letters (white around black text on
// art or screentone, or the reverse): the rings next to the ink are much
// lighter than the picture a little further out. 0 when there is none.
function outlineWidth(ink,data,w,h,stroke,dark){
 const reach=Math.max(3,Math.min(10,Math.round(stroke*2.5))),means=[];let inner=ink;
 for(let k=1;k<=reach+6;k++){
  // Medians: a dark object near the text must not pass for the end of an outline.
  const outer=dilateInk(inner,w,h,1),ring=[];
  for(let n=0;n<outer.length;n++)if(outer[n]&&!inner[n]){const p=n*4;ring.push((data[p]+data[p+1]+data[p+2])/3);}
  ring.sort((a,b)=>a-b);means.push(ring.length?ring[ring.length>>1]:means.at(-1)??128);inner=outer;
 }
 const rest=means.slice(reach+2).sort((a,b)=>a-b),far=rest[rest.length>>1]??means.at(-1),sign=dark?1:-1;
 // A faint outline on light screentone still shows as a silhouette once the
 // letters are gone, so a small step in tone already counts.
 if(sign*(means[0]-far)<14)return 0;
 const half=(means[0]+far)/2;let width=0;
 while(width<reach&&sign*(means[width]-half)>0)width++;
 return width;
}
// The outline of letters found in `ink`: pixels around them of the opposite
// tone (dark around light letters), followed outwards for up to `steps` pixels.
function growRim(ink,data,w,h,light,steps){
 const luma=n=>{const p=n*4;return (data[p]+data[p+1]+data[p+2])/3;};
 let sum=0,count=0;for(let n=0;n<ink.length;n++)if(ink[n]){sum+=luma(n);count++;}
 if(!count)return ink;
 const core=sum/count,mask=ink.slice();let front=ink;
 for(let step=0;step<steps;step++){
  const next=dilateInk(front,w,h,1);let added=0;
  for(let n=0;n<next.length;n++)if(next[n]&&!mask[n]){const v=luma(n);if(light?v<core-60:v>core+60){mask[n]=1;added++;}else next[n]=0;}
  if(!added)break;front=next;
 }
 return dilateInk(mask,w,h,1);
}
// The backing drawn under the letters: grown from them only into pixels of the
// backing's own tone (near white around dark letters, near black around light
// ones), at most `steps` pixels; screentone and hatching stop it.
function growBacking(ink,data,w,h,lightBacking,steps){
 const mask=ink.slice();let front=ink;
 for(let step=0;step<steps;step++){
  const next=dilateInk(front,w,h,1);let added=0;
  for(let n=0;n<next.length;n++)if(next[n]&&!mask[n]){const p=n*4,v=(data[p]+data[p+1]+data[p+2])/3;if(lightBacking?v>=200:v<=55){mask[n]=1;added++;}else next[n]=0;}
  if(!added)break;front=next;
 }
 return dilateInk(mask,w,h,1);
}
// The artist's backing under the letters, kept as drawn: the letters are
// painted in its colour. Used when the page's model time is spent, instead of
// a blurred Telea fill over the drawing.
function keptBacking(ink,backing,data,w,h,darkLetters){
 const letters=dilateInk(ink,w,h,1),core=dilateInk(ink,w,h,2),tones=[];
 for(let n=0;n<backing.length;n++)if(backing[n]&&!core[n]){const p=n*4;tones.push([(data[p]+data[p+1]+data[p+2])/3,data[p],data[p+1],data[p+2]]);}
 if(tones.length<12)return null;
 tones.sort((a,b)=>a[0]-b[0]);const pick=tones[Math.floor(tones.length*(darkLetters?.7:.3))];
 return {mask:letters,color:[pick[1],pick[2],pick[3]]};
}
function growInk(ink,data,w,h,paper,flat){
 const mask=dilateInk(ink,w,h,2);
 const dark=paper>=128;let front=mask;
 for(let step=0;step<3;step++){
  const next=dilateInk(front,w,h,1);let added=0;
  for(let n=0;n<next.length;n++)if(next[n]&&!mask[n]){const p=n*4,luma=(data[p]+data[p+1]+data[p+2])/3;if(dark?luma<paper-6:luma>paper+6){mask[n]=1;added++;}else next[n]=0;}
  if(!added)break;front=next;
 }
 return mask;
}
export function prepareInkPatch(original,box,{category='dialogue',neural=false,model,contextPad,rescue=false}={}){
 const {width:pw,height:ph}=original;
 if(!Array.isArray(box)||box.length!==4||!box.every(Number.isFinite))return {declined:'Некорректные координаты текста'};
 const [x1,y1,x2,y2]=box.map(Math.round);if(x1<0||y1<0||x2>pw||y2>ph||x2-x1<2||y2-y1<2)return {declined:'Область текста выходит за границы'};
 const pad=neural?24:contextPad||Math.max(24,Math.min(48,Math.round(Math.min(x2-x1,y2-y1)*.6))),left=Math.max(0,x1-pad),top=Math.max(0,y1-pad),w=Math.min(pw,x2+pad)-left,h=Math.min(ph,y2+pad)-top;
 const local=[x1-left,y1-top,x2-left,y2-top],data=new Uint8ClampedArray(w*h*4),border=[[],[],[]];
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
  const dst=(y*w+x)*4,src=((top+y)*pw+left+x)*4;data.set(original.data.subarray(src,src+4),dst);
  if(x>=local[0]-4&&x<local[2]+4&&y>=local[1]-4&&y<local[3]+4&&(x<local[0]||x>=local[2]||y<local[1]||y>=local[3])&&data[dst+3]>127)for(let c=0;c<3;c++)border[c].push(data[dst+c]);
 }
 const bubble=!neural?paperBubble(original,box):null,background=bubble?.background||border.map(a=>a.sort((a,b)=>a-b)[a.length>>1]??255),paper=background.reduce((a,b)=>a+b)/3;
 const deviation=border.reduce((s,a,c)=>s+a.reduce((n,v)=>n+Math.abs(v-background[c]),0)/Math.max(1,a.length),0)/3;
 // Contrast in both directions includes white outlines and dark letter cores.
 // Keep neural masks on the glyphs; a filled text rectangle destroys too much
 // drawing context on SFX over hair/halftones.
 if(model==='moebius'||model==='migan'){
  const margin=model==='migan'?Math.min(3,Math.max(2,Math.round(Math.max(pw,ph)/1200))):Math.min(8,Math.max(3,Math.ceil(Math.max(pw,ph)/512*1.5))+(category==='sfx'||category==='sign'?2:0));
  const glyphs=contrastGlyphs(data,w,h,local),mask=fillInkHoles(dilateInk(glyphs,w,h,margin),w,h,Math.max(24,(x2-x1)*(y2-y1)*.12)),bounds=[Math.max(0,local[0]-margin),Math.max(0,local[1]-margin-2),Math.min(w,local[2]+margin),Math.min(h,local[3]+margin)];
  // Extra top coverage catches upper diacritics and anti-aliased outlines.
  for(let y=2;y<h;y++)for(let x=0;x<w;x++)if(mask[y*w+x]){mask[(y-1)*w+x]=1;if(model==='moebius')mask[(y-2)*w+x]=1;}
  // Do not extend the safety margin through a long panel/bubble rule outside
  // the detected text. In particular preserve nearby vertical panel frames.
  protectRules(mask,data,w,h,local,bounds);
  const masked=mask.reduce((n,v)=>n+v,0);
  if(masked<3)return {declined:'Не выделена маска исходных букв'};
  return {left,top,width:w,height:h,data,mask,background,coverage:masked/(w*h),flat:false,masked,maskKind:'outlined-glyphs',margin};
 }
 const area=(x2-x1)*(y2-y1);
 // Only the letters: separate glyph-sized islands of ink with the text's own
 // stroke weight. Art that merely passes through the detector's box (hair, a
 // hand, the balloon's outline and its burst lines, screentone dots) is not
 // erased, so nothing but the lettering is repainted.
 const letters=letterInk(data,w,h,local,paper);
 // Lettering of the other tone with an outline (white letters edged in black
 // over hair, screentone or sky; black letters edged in white over a dark
 // drawing). Both kinds can share one box; each is taken with its own edge.
 const other=letterInk(data,w,h,local,paper,{light:paper>=128,rimmed:true}),count=ink=>ink.reduce((n,v)=>n+v,0);
 // The counters of the letters already found (the inside of О, Р, の) are not letters of their own.
 const closed=fillInkHoles(letters.ink,w,h,Math.max(24,area*.12));for(let n=0;n<other.ink.length;n++)if(closed[n])other.ink[n]=0;
 // White letters are drawn over grey or dark art, never over white paper.
 const otherInk=paper<=190&&count(other.ink)>=Math.max(24,count(letters.ink)*.2)?growRim(other.ink,data,w,h,paper>=128,Math.max(2,Math.min(8,Math.round((other.stroke||3)*1.6)))):null;
 // Light letters on a dark drawing carry a dark edge as well.
 const ownRim=paper<128&&count(letters.ink)?growRim(letters.ink,data,w,h,true,Math.max(2,Math.min(6,Math.round((letters.stroke||3)*1.2)))):null;
 // Plain paper carries no outlined lettering: light gaps there are counters and margins.
 if((otherInk||ownRim)&&!(deviation<12||bubble)){
  const union=letters.ink.slice();for(const extra of [otherInk,ownRim])if(extra)for(let n=0;n<union.length;n++)if(extra[n])union[n]=1;
  // A backing around the letters goes with them, faint as it may be.
  const edge=outlineWidth(letters.ink,data,w,h,letters.stroke,paper>=128);
  const mask=fillInkHoles(edge?growBacking(union,data,w,h,paper>=128,edge+2):union,w,h,Math.max(24,area*.12)),masked=count(mask),coverage=masked/(w*h);
  if(coverage>.6)return {declined:'Маска захватывает рисунок: область оставлена в оригинале',coverage};
  return {left,top,width:w,height:h,data,mask,background,coverage,flat:false,masked,stroke:Math.max(letters.stroke,other.stroke),maskKind:'rimmed-letters',...(rescue?{wide:dilateInk(mask,w,h,1)}:{})};
 }
 // Letters drawn with an outline over art keep that outline: only the letters
 // themselves are painted, in the outline's own colour. The artist's backing
 // stays as drawn and nothing around it is touched or blurred.
 const smooth=deviation<12||!!bubble,outline=smooth?0:outlineWidth(letters.ink,data,w,h,letters.stroke,paper>=128);
 // Lettering with an outline over the drawing is removed together with its
 // outline and the drawing under both is rebuilt: a backing left behind shows
 // the old letters as white silhouettes.
 const mask=fillInkHoles(outline?dilateInk(letters.ink,w,h,outline+1):growInk(letters.ink,data,w,h,paper,smooth),w,h,Math.max(24,area*.12)),masked=mask.reduce((n,v)=>n+v,0),coverage=masked/(w*h);
 if(masked<3)return {declined:'Не выделена безопасная маска букв'};
 // Dense lettering at an image edge loses context on one side. Keep the glyph
 // mask and the 60% Telea guard; retry once with more real surrounding pixels.
 if(coverage>.6&&!neural&&!contextPad&&(x1<pad||y1<pad||pw-x2<pad||ph-y2<pad))return prepareInkPatch(original,box,{category,neural,model,contextPad:96});
 if(coverage>.6)return {declined:'Маска захватывает рисунок: область оставлена в оригинале',coverage};
 let interiorDeviation=0,known=0;
 for(let y=local[1];y<local[3];y++)for(let x=local[0];x<local[2];x++){const n=y*w+x;if(mask[n])continue;for(let c=0;c<3;c++)interiorDeviation+=Math.abs(data[n*4+c]-background[c]);known++;}
 let flat=!!bubble||deviation<12&&interiorDeviation/Math.max(1,known*3)<12;
 // Flat paper is filled with the tone of the paper right around the letters
 // (the median of what is left of the box), not the balloon's average: an
 // average is a shade off and leaves a ghost of every letter.
 if(outline)flat=false;
 else if(flat&&known){
  const near=[[],[],[]];
  for(let y=local[1];y<local[3];y++)for(let x=local[0];x<local[2];x++){const n=y*w+x;if(!mask[n])for(let c=0;c<3;c++)near[c].push(data[n*4+c]);}
  for(let c=0;c<3;c++){near[c].sort((a,b)=>a-b);background[c]=near[c][near[c].length>>1];}
 }
 // Whatever the mask, a hole surrounded by one even tone is filled with that
 // tone: a model only invents streaks on blank paper.
 if(!flat){
  const edge=dilateInk(mask,w,h,2),tones=[[],[],[]];
  for(let n=0;n<edge.length;n++)if(edge[n]&&!mask[n])for(let c=0;c<3;c++)tones[c].push(data[n*4+c]);
  if(tones[0].length>=20){
   const middle=tones.map(t=>{t.sort((a,b)=>a-b);return t[t.length>>1];}),lo=tones[0][Math.floor(tones[0].length*.1)],hi=tones[0][Math.floor(tones[0].length*.9)];
   if(hi-lo<=14){for(let c=0;c<3;c++)background[c]=middle[c];flat=true;}
  }
 }
 const ambiguous=!flat&&(category==='sfx'||category==='sign')&&masked/area>.28;
 if(ambiguous&&!neural&&!rescue)return {declined:'Спецэффект пересекает рисунок: для безопасного удаления выбери нейросетевое восстановление',coverage};
 return {left,top,width:w,height:h,data,mask,background,coverage,flat,masked,stroke:letters.stroke,...(outline?{maskKind:'outlined-letters',...(flat?{}:{wide:mask,backing:keptBacking(letters.ink,mask,data,w,h,paper>=128)})}:{})};
}
export function compositeInkPatch(target,patch,modified,writeMask=patch.mask){
 for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++)if(writeMask[y*patch.width+x]){
  const src=(y*patch.width+x)*4,dst=((patch.top+y)*target.width+patch.left+x)*4;
  target.data.set(modified.subarray(src,src+4),dst);
 }
}
// One native-resolution union. Preparing geometry never runs neural inference.
export function preparePageInk(original,regions,options={}){
 const mask=new Uint8Array(original.width*original.height),patches=[];
 for(const region of regions){
  const patch=prepareInkPatch(original,region.text_bbox,{category:region.text_category,neural:true,...options});
  patches.push({region,patch});if(patch.declined)continue;
  for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++)if(patch.mask[y*patch.width+x])mask[(patch.top+y)*original.width+patch.left+x]=1;
 }
 return {mask,patches,maskedPixels:mask.reduce((sum,n)=>sum+n,0)};
}

// Native-resolution dynamic LaMa input: snap small ROIs rather than inflating
// every bubble to 512x512. Never resize glyphs or pass arbitrary tensor shapes.
export function lamaInputSize(width,height){
 if(!Number.isInteger(width)||!Number.isInteger(height)||width<2||height<2)throw Error('Некорректный размер LaMa');
 if(width>512||height>512)return null;
 return {width:Math.max(128,Math.ceil(width/64)*64),height:Math.max(128,Math.ceil(height/64)*64)};
}
export function lamaInputTensors(image,mask,crop){
 const plane=crop.w*crop.h,rgb=new Float32Array(3*plane),holes=new Float32Array(plane);
 for(let y=0;y<crop.h;y++)for(let x=0;x<crop.w;x++){
  const px=crop.x+x,py=crop.y+y,n=y*crop.w+x;
  if(px>=0&&px<image.width&&py>=0&&py<image.height&&mask[py*image.width+px]){holes[n]=1;continue;}
  const src=(Math.max(0,Math.min(image.height-1,py))*image.width+Math.max(0,Math.min(image.width-1,px)))*4;
  rgb[n]=image.data[src]/255;rgb[plane+n]=image.data[src+1]/255;rgb[plane*2+n]=image.data[src+2]/255;
 }
 return {rgb,holes};
}
export function applyLamaOutput(image,mask,values,tile,done){
 const {crop,commit}=tile,plane=crop.w*crop.h;
 if(values.length!==plane*3)throw Error('Некорректный ответ LaMa');
 // Preserve the original outside the glyph mask plus a two-pixel AA ring.
 const ring=dilateInk(mask,image.width,image.height,2);
 for(let y=Math.max(0,commit.y);y<Math.min(image.height,commit.y+commit.h);y++)for(let x=Math.max(0,commit.x);x<Math.min(image.width,commit.x+commit.w);x++){
  const n=y*image.width+x;if(done[n]||!ring[n])continue;
  const local=(y-crop.y)*crop.w+x-crop.x;if(local<0||local>=plane)continue;
  const alpha=mask[n]?1:2/3;
  for(let c=0;c<3;c++){const sample=values[c*plane+local];if(!Number.isFinite(sample))throw Error('LaMa вернула некорректные пиксели');image.data[n*4+c]=Math.round(alpha*Math.max(0,Math.min(255,sample*255))+(1-alpha)*image.data[n*4+c]);}
  done[n]=1;
 }
}

export function fillInkHoles(mask,w,h,maxArea){
 const out=mask.slice(),seen=new Uint8Array(mask.length),queue=new Int32Array(mask.length);
 for(let seed=0;seed<mask.length;seed++)if(!mask[seed]&&!seen[seed]){let a=0,z=1,border=false;queue[0]=seed;seen[seed]=1;
  while(a<z){const n=queue[a++],x=n%w,y=(n/w)|0;if(!x||!y||x===w-1||y===h-1)border=true;for(const i of [x?n-1:-1,x<w-1?n+1:-1,y?n-w:-1,y<h-1?n+w:-1])if(i>=0&&!mask[i]&&!seen[i]){seen[i]=1;queue[z++]=i;}}
  if(!border&&z<=maxArea)for(let k=0;k<z;k++)out[queue[k]]=1;
 }return out;
}
