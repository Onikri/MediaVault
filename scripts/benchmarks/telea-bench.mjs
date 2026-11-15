// Compares two builds of the pure-JS Telea inpainter on synthetic backgrounds
// with a known clean answer. Algorithmic only: no model, no browser.
//   node scripts/benchmarks/telea-bench.mjs [baseline.ts]
// Without a baseline it reports the current build alone. Needs Node >= 22.18
// (TypeScript type stripping).
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const load=async file=>(await import(pathToFileURL(resolve(file)).href)).teleaInpaint;
const telea=await load('lmt/upstream/lib/inpaint/telea.ts'),{periodicFill}=await import(pathToFileURL(resolve('lmt/upstream/lib/inpaint/tone.ts')).href);
// Current Fast rung: periodic twins first, Telea for whatever is left (as ladder.ts runTelea does).
const current=(image,mask,radius)=>{const {remaining}=periodicFill(image,mask);telea(image,remaining,radius);},baseline=process.argv[2]?await load(process.argv[2]):null;
const W=640,H=480;
let seed=12345;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
const noise=sigma=>{let s=0;for(let i=0;i<6;i++)s+=random();return (s-3)*sigma*1.414;};
const BACKGROUNDS={
 'flat paper + grain':(x,y)=>236+noise(3),
 'linear gradient':(x,y)=>60+150*x/W+noise(2),
 'screentone 6px dots':(x,y)=>((x%6<2)&&((y+(Math.floor(x/6)%2?3:0))%6<2)?70:205)+noise(2),
 'speed lines':(x,y)=>((x+2*y)%23<3?40:215)+noise(2),
 'panel edge':(x,y)=>(y>H/2+Math.sin(x/40)*8?90:225)+noise(2),
};
// Lettering-like mask: rows of short thick strokes, as an ink mask of a text block.
function textMask(){
 const mask=new Uint8Array(W*H);
 for(let row=0;row<7;row++)for(let glyph=0;glyph<14;glyph++){
  const gx=90+glyph*33,gy=90+row*44;
  for(let stroke=0;stroke<4;stroke++){const horizontal=random()<.5,x0=gx+Math.floor(random()*18),y0=gy+Math.floor(random()*24),len=10+Math.floor(random()*14),thick=4+Math.floor(random()*4);
   for(let a=0;a<len;a++)for(let b=0;b<thick;b++){const x=horizontal?x0+a:x0+b,y=horizontal?y0+b:y0+a;if(x<W&&y<H)mask[y*W+x]=1;}}
 }
 return mask;
}
function run(inpaint,truth,mask){
 const data=new Uint8ClampedArray(W*H*4);
 for(let i=0;i<W*H;i++){const v=mask[i]?0:truth[i];data[i*4]=data[i*4+1]=data[i*4+2]=v;data[i*4+3]=255;}
 const image={width:W,height:H,data};inpaint({width:W,height:H,data:new Uint8ClampedArray(data)},mask,3); // warm-up
 const times=[];for(let n=0;n<7;n++){const copy=new Uint8ClampedArray(data),t=performance.now();inpaint({width:W,height:H,data:copy},mask,3);times.push(performance.now()-t);if(n===6)image.data=copy;}
 let error=0,count=0,unfilled=0;for(let i=0;i<W*H;i++)if(mask[i]){error+=Math.abs(image.data[i*4]-truth[i]);count++;if(image.data[i*4]===0&&truth[i]>30)unfilled++;}
 return {mae:error/count,ms:times.sort((a,b)=>a-b)[3],unfilled};
}
const rows=[];
for(const [name,paint]of Object.entries(BACKGROUNDS)){
 seed=777;const truth=new Float32Array(W*H);for(let y=0;y<H;y++)for(let x=0;x<W;x++)truth[y*W+x]=Math.max(0,Math.min(255,Math.round(paint(x,y))));
 const mask=textMask(),now=run(current,truth,mask),before=baseline?run(baseline,truth,mask):null;
 rows.push({case:name,...(before?{'baseline MAE':before.mae.toFixed(2),'baseline ms':before.ms.toFixed(1),'baseline unfilled':before.unfilled}:{}),'MAE':now.mae.toFixed(2),'ms':now.ms.toFixed(1),'unfilled':now.unfilled});
}
console.table(rows);
