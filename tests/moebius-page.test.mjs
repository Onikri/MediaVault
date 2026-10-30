import test from 'node:test';
import assert from 'node:assert/strict';
import {moebiusRuntimeUrl,moebiusLayout,moebiusPageMask} from '../src/moebius-layout.js';
import {preparePageInk} from '../src/manga-cleaning.js';
import {maskToLatent} from '../lmt/moebius/imaging.ts';
import {renderComicPage} from '../src/manga-renderer.js';

test('Moebius runtime stays under GitHub Pages subpath and works in dev',()=>{
 assert.equal(moebiusRuntimeUrl('https://onikri.github.io/MediaVault/assets/manga-moebius-ab.js'),'https://onikri.github.io/MediaVault/lmt/moebius-ort/');
 assert.equal(moebiusRuntimeUrl('http://localhost:5173/src/manga-moebius.js'),'http://localhost:5173/lmt/moebius-ort/');
});
test('page and latent max pooling keep one-pixel Japanese/Korean strokes',()=>{
 const w=3430,h=2417,mask=new Uint8Array(w*h);mask[2001*w+3001]=1;
 const pooled=moebiusPageMask(mask,w,h);assert.ok(pooled.some(Boolean));
 const thin=new Uint8Array(512*512);thin[7*512+7]=1;
 assert.equal(maskToLatent(thin,true)[0],1);assert.equal(maskToLatent(thin)[0],0);
 assert.deepEqual(moebiusLayout(846,1250),{x:82,y:0,w:347,h:512,size:512,scaleX:347/846,scaleY:512/1250});
});
function fixture(){
 const image={width:240,height:160,data:new Uint8ClampedArray(240*160*4).fill(255)};
 for(const x0 of [35,145])for(let x=x0;x<x0+40;x+=10)for(let y=45;y<60;y++)for(let dx=0;dx<4;dx++)for(let c=0;c<3;c++)image.data[(y*240+x+dx)*4+c]=0;
 const regions=[35,145].map((x,i)=>({uid:'P1_B'+(i+1),text_bbox:[x-5,40,x+45,70],ru_translation:'Да',font_style:'serif_serious'}));
 return {image,page:{page:1,width:240,height:160,regions}};
}
test('union mask contains all safe regions without modifying original',()=>{
 const {image,page}=fixture(),snapshot=image.data.slice(),merged=preparePageInk(image,page.regions);
 assert.equal(merged.patches.length,2);assert.ok(merged.maskedPixels>0);assert.ok(merged.mask[50*240+35]);assert.ok(merged.mask[50*240+145]);assert.equal(merged.mask[0],0);assert.deepEqual(image.data,snapshot);
});
// Canvas contract only: the neural comparisons use real ONNX inference separately.
function installCanvas(image){
 globalThis.ImageData=class{constructor(data,width,height){if(typeof data==='number'){height=width;width=data;data=new Uint8ClampedArray(width*height*4);}Object.assign(this,{data,width,height});}};
 globalThis.createImageBitmap=async()=>({...image,close(){}});
 globalThis.OffscreenCanvas=class{
  constructor(w,h){this.width=w;this.height=h;this.data=image.data.slice();}
  getContext(){const self=this;return {drawImage(){},getImageData(){return {...image,data:self.data.slice()};},putImageData(value){self.data=value.data.slice();},measureText(s){return {width:s.length*5};},save(){},restore(){},beginPath(){},rect(){},clip(){},fillText(){},strokeText(){}};}
  transferToImageBitmap(){return {data:this.data,width:this.width,height:this.height};}
 };
}
test('whole-page renderer calls neural provider once, restores outside mask and does not fall back per box',async()=>{
 const {image,page}=fixture();installCanvas(image);let calls=0,union;
 const result=await renderComicPage({blob:{},page,font:'serif',mode:'moebius',lama:async(input,mask)=>{calls++;assert.equal(input.width,240);union=mask;input.data.fill(180);return {provider:'fixture'};}});
 assert.equal(calls,1);assert.equal(result.inpaint.modelCalls,1);assert.equal(result.typesetting.layouts.length,2);
 for(let n=0;n<union.length;n++)if(!union[n])assert.equal(result.renderedBitmap.data[n*4],image.data[n*4]);
 calls=0;const failed=await renderComicPage({blob:{},page,font:'serif',mode:'moebius',lama:async()=>{calls++;throw Error('runtime fetch failed');}});
 assert.equal(calls,1);assert.deepEqual(failed.renderedBitmap.data,image.data);assert.equal(failed.typesetting.layouts.length,2);assert.ok(failed.typesetting.layouts.every(r=>r.fallback&&r.color==='#151515'));assert.ok(failed.warnings.some(w=>w.startsWith('Moebius:')));
});
test('debug snapshot is captured after cleanup and before typesetting',async()=>{
 const {image,page}=fixture();installCanvas(image);const Base=globalThis.OffscreenCanvas;
 globalThis.OffscreenCanvas=class extends Base{
  getContext(){const context=super.getContext();context.fillText=()=>{this.data[0]=17;};return context;}
  async convertToBlob(){return new Blob([this.data]);}
 };
 const result=await renderComicPage({blob:{},page,font:'serif',mode:'moebius',captureDebug:true,lama:async()=>({provider:'fixture'})});
 assert.equal(new Uint8Array(result.debug.cleanedImage)[0],255);
 assert.equal(result.renderedBitmap.data[0],17);
 assert.equal(result.debug.detected.regions.length,2);
});
