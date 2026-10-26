import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeYolo26,decodeDb,ppSize,orderByPanels} from '../lmt/detection-geometry.js';
test('YOLO26 text and panels stay separate, padding is removed exactly once',()=>{
 const r=decodeYolo26(new Float32Array([0,256,1024,768,.9,0,256,384,512,640,.8,1,0,0,20,20,.1,1]),800,400);
 assert.equal(r.text.length,1);assert.equal(r.panels.length,1);
 assert.deepEqual([r.text[0].x1,r.text[0].y1,r.text[0].x2,r.text[0].y2],[200,100,400,300]);
 assert.equal(r.panels[0].y1,0);assert.equal(r.panels[0].y2,400);
 assert.equal(decodeYolo26(new Float32Array([0,0,1024,1024,.99,0]),800,400).text.length,0);
});
test('PP DB small noise is removed; text rectangles expand and stay on the page',()=>{
 const p=new Float32Array(100);for(let y=3;y<7;y++)for(let x=2;x<5;x++)p[y*10+x]=.8;p[99]=.8;
 const boxes=decodeDb(p,10,10,100,200);assert.equal(boxes.length,1);assert.ok(boxes[0].x1<20&&boxes[0].x2>50);assert.ok(boxes[0].y1<60&&boxes[0].y2>140);
 assert.throws(()=>decodeDb(p,20,20,100,200));const size=ppSize(1000,8000);assert.ok(size.every(n=>n%32===0));assert.ok(size[0]*size[1]<800000);assert.ok(size[1]>960);
});
test('RTL panel order never returns a panel as a text region',()=>{
 const panels=[{x1:0,y1:0,x2:100,y2:100},{x1:110,y1:0,x2:210,y2:100}],text=[{x1:10,y1:10,x2:30,y2:20,id:'left'},{x1:120,y1:20,x2:140,y2:30,id:'right'}];
 assert.deepEqual(orderByPanels(text,panels,true).map(b=>b.id),['right','left']);assert.deepEqual(orderByPanels(text,panels,false).map(b=>b.id),['left','right']);
});
