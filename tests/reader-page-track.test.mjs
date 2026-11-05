import test from 'node:test';import assert from 'node:assert/strict';
import {pageTrackPoints,pageTrackPosition,pageAtPosition} from '../src/reader-page-track.js';
test('page points remain bounded, evenly sampled and include the chapter ends',()=>{
 for(const total of [2,18,256,10000])for(const length of [90,360,900]){const points=pageTrackPoints(total,length);assert.equal(points[0],1);assert.equal(points.at(-1),total);assert.ok(points.length<=Math.min(total,120));assert.equal(new Set(points).size,points.length);}
});
test('pointer and keyboard values round trip without shifting from the current page',()=>{
 for(const total of [2,18,256,10000])for(const page of [1,Math.ceil(total/2),total])assert.equal(pageAtPosition(pageTrackPosition(page,total),total),page);
 assert.equal(pageAtPosition(-1,40),1);assert.equal(pageAtPosition(2,40),40);assert.equal(pageAtPosition(.5,101),51);
});
