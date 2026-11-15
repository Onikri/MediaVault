// Algorithmic checks of the Fast inpaint rung (Telea + periodic fill) on
// synthetic backgrounds with a known answer. No model inference.
import test from 'node:test';
import assert from 'node:assert/strict';
let telea,tone,unsupported='';
try{telea=await import('../lmt/upstream/lib/inpaint/telea.ts');tone=await import('../lmt/upstream/lib/inpaint/tone.ts');}catch(error){unsupported='this Node cannot import TypeScript sources: '+error.code;}
const W=240,H=180;
function page(paint){
 const truth=new Uint8ClampedArray(W*H),mask=new Uint8Array(W*H),data=new Uint8ClampedArray(W*H*4);
 for(let y=0;y<H;y++)for(let x=0;x<W;x++)truth[y*W+x]=paint(x,y);
 for(let row=0;row<4;row++)for(let col=0;col<8;col++)for(let y=0;y<16;y++)for(let x=0;x<5;x++)mask[(40+row*28+y)*W+30+col*22+x+(y>>2)]=1;
 for(let i=0;i<W*H;i++){data[i*4]=data[i*4+1]=data[i*4+2]=mask[i]?0:truth[i];data[i*4+3]=255;}
 const error=()=>{let sum=0,n=0;for(let i=0;i<W*H;i++)if(mask[i]){sum+=Math.abs(data[i*4]-truth[i]);n++;}return sum/n;};
 return {image:{width:W,height:H,data},mask,truth,error};
}
const dots=(x,y)=>(x%6<2&&(y+(Math.floor(x/6)%2?3:0))%6<2)?70:205;
test('Telea fills every masked pixel and leaves known pixels alone',{skip:unsupported||false},()=>{
 const p=page((x,y)=>60+Math.round(150*x/W)),before=new Uint8ClampedArray(p.image.data);
 telea.teleaInpaint(p.image,p.mask,3);
 assert.ok(p.error()<4,'gradient error '+p.error());
 for(let i=0;i<W*H;i++)if(!p.mask[i])assert.equal(p.image.data[i*4],before[i*4]);
 assert.throws(()=>telea.teleaInpaint(p.image,new Uint8Array(W*H).fill(1),3),/covers too much/);
});
test('screentone is restored from its periodic twins, not smeared',{skip:unsupported||false},()=>{
 const smeared=page(dots);telea.teleaInpaint(smeared.image,smeared.mask,3);
 const p=page(dots),result=tone.periodicFill(p.image,p.mask);telea.teleaInpaint(p.image,result.remaining,3);
 assert.ok(result.shift&&result.filled>0);
 assert.ok(p.error()<smeared.error()/4,`periodic ${p.error()} vs Telea alone ${smeared.error()}`);
});
test('flat paper has no texture; gradients and edges are never made worse',{skip:unsupported||false},()=>{
 const flat=page(()=>236),none=tone.periodicFill(flat.image,flat.mask);assert.equal(none.shift,null);assert.equal(none.remaining,flat.mask);
 for(const paint of [(x,y)=>60+Math.round(150*x/W),(x,y)=>y>H/2?90:225,(x,y)=>60+Math.round(150*x/W)+((x*7+y*13)%5)]){
  const plain=page(paint);telea.teleaInpaint(plain.image,plain.mask,3);
  const p=page(paint);telea.teleaInpaint(p.image,tone.periodicFill(p.image,p.mask).remaining,3);
  assert.ok(p.error()<=plain.error()+.5,`with periodic fill ${p.error()} vs Telea alone ${plain.error()}`);
 }
});
