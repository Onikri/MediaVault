import assert from 'node:assert/strict';
import {test} from 'node:test';
import {letterboxScale} from '../src/background-crop.js';
function frame(top,bottom,color=140){const data=new Uint8ClampedArray(64*36*4);for(let y=top;y<36-bottom;y++)for(let x=0;x<64;x++){const p=(y*64+x)*4;data[p]=data[p+1]=data[p+2]=color;data[p+3]=255;}return data;}
test('crops stable symmetric cinematic bars, but preserves full/dark/asymmetric frames',()=>{
 assert.ok(letterboxScale(frame(4,4),64,36)>1.25);
 assert.equal(letterboxScale(frame(0,0),64,36),1);
 assert.equal(letterboxScale(frame(4,4,12),64,36),1);
 assert.equal(letterboxScale(frame(4,0),64,36),1);
 assert.equal(letterboxScale(frame(8,8),64,36),1);
});
