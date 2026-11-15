// The cleanup mask covers the lettering and nothing else. Synthetic pixels:
// no detector, no model, no real page.
import test from 'node:test';
import assert from 'node:assert/strict';
import {letterInk,prepareInkPatch,dilateInk} from '../src/manga-cleaning.js';

function canvas(w,h,tone=255){
 const data=new Uint8ClampedArray(w*h*4);
 const set=(x,y,v)=>{if(x<0||y<0||x>=w||y>=h)return;const p=(y*w+x)*4;data[p]=data[p+1]=data[p+2]=v;data[p+3]=255;};
 for(let y=0;y<h;y++)for(let x=0;x<w;x++)set(x,y,typeof tone==='function'?tone(x,y):tone);
 const fill=(x1,y1,x2,y2,v=0)=>{for(let y=y1;y<y2;y++)for(let x=x1;x<x2;x++)set(x,y,v);};
 // A "letter": a square ring with a stroke of 4 px.
 const letter=(x,y,size=14,v=0)=>{fill(x,y,x+size,y+size,v);fill(x+4,y+4,x+size-4,y+size-4,typeof tone==='function'?255:tone);};
 return {width:w,height:h,data,set,fill,letter};
}
const covered=(ink,w,x1,y1,x2,y2)=>{let n=0;for(let y=y1;y<y2;y++)for(let x=x1;x<x2;x++)n+=ink[y*w+x];return n;};

test('letters are taken; lines of the drawing, thin strokes and screentone dots are not',()=>{
 const W=140,H=150,c=canvas(W,H),box=[40,30,100,100];
 for(const [x,y] of [[48,34],[48,54],[48,74],[72,34],[72,54]])c.letter(x,y);
 c.fill(0,97,W,98);                        // a panel line running through the box
 for(let i=0;i<60;i++)c.set(20+i,20+i,0);  // a hair line crossing it diagonally...
 c.fill(88,40,89,62);                      // a thin stroke wholly inside the box
 for(let y=36;y<60;y+=5)for(let x=92;x<100;x+=5)c.set(x,y,0);   // screentone dots
 for(const y of [92,99,106])c.fill(53,y,57,y+4);                // an ellipsis running out of the box, in the column
 const {ink,glyph,stroke}=letterInk(c.data,W,H,box,255);
 assert.ok(glyph>=12&&glyph<=18,'glyph size '+glyph);assert.ok(stroke>=2.5&&stroke<=5,'stroke '+stroke);
 assert.ok(covered(ink,W,48,34,62,48)>100,'a letter is masked');assert.ok(covered(ink,W,72,54,86,68)>100);
 assert.equal(covered(ink,W,0,97,W,98),0,'the panel line stays');
 assert.equal(covered(ink,W,88,40,89,62),0,'a thin stroke of the drawing stays');
 assert.equal(covered(ink,W,91,36,100,60),0,'screentone dots stay');
 assert.equal(covered(ink,W,20,20,40,40),0,'the hair line stays');
 assert.equal(covered(ink,W,53,92,57,110),48,'the ellipsis the box clipped is taken');
});

test('a patch on flat paper is filled with the paper next to the letters and stays small',()=>{
 const W=200,H=200,c=canvas(W,H,250);
 c.fill(0,0,W,3,0);c.fill(0,H-3,W,H,0);c.fill(0,0,3,H,0);c.fill(W-3,0,W,H,0);   // a closed frame: paper is enclosed
 for(const y of [70,90,110])c.letter(92,y);
 const patch=prepareInkPatch(c,[86,64,112,130],{category:'dialogue'});
 assert.equal(patch.declined,undefined);assert.equal(patch.flat,true);assert.deepEqual([...patch.background],[250,250,250]);
 assert.ok(patch.masked<=3*18*18,'only the letters and their edge: '+patch.masked);
});

test('letters with an outline over art are painted in the outline colour; the art is not masked',()=>{
 const W=160,H=160,c=canvas(W,H,(x,y)=>(x+y)%4<2?90:170);   // hatching
 for(const y of [50,74,98]){c.fill(69,y-4,91,y+18,255);c.letter(73,y);}   // white backing, then the letter
 const patch=prepareInkPatch(c,[64,42,96,120],{category:'dialogue'});
 assert.equal(patch.declined,undefined);assert.equal(patch.maskKind,'outlined-letters');assert.equal(patch.flat,true);
 assert.ok(patch.background.every(v=>v>=240),'outline colour '+[...patch.background]);
 // Nothing outside the white backing is in the mask.
 const backing=new Uint8Array(patch.width*patch.height);
 for(let y=0;y<patch.height;y++)for(let x=0;x<patch.width;x++){const gx=x+patch.left,gy=y+patch.top;if(gx>=69&&gx<91&&[50,74,98].some(t=>gy>=t-4&&gy<t+18))backing[y*patch.width+x]=1;}
 assert.equal(patch.mask.reduce((n,v,i)=>n+(v&&!backing[i]?1:0),0),0);
});

test('dilation by a square is the same as before, in two passes',()=>{
 const w=9,h=7,mask=new Uint8Array(w*h);mask[3*w+4]=1;mask[0]=1;
 const out=dilateInk(mask,w,h,2);
 for(let y=0;y<h;y++)for(let x=0;x<w;x++)assert.equal(out[y*w+x],(Math.abs(x-4)<=2&&Math.abs(y-3)<=2)||(x<=2&&y<=2)?1:0,x+','+y);
});
