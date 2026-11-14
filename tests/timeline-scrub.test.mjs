import test from 'node:test';
import assert from 'node:assert/strict';
import {createTimelineScrub} from '../src/timeline-scrub.js';
test('rapid Alloha dragging previews every point but commits only the released position',()=>{
 const requests=[],scrub=createTimelineScrub(value=>requests.push(value));
 scrub.begin(10);
 for(let i=11;i<=200;i++){assert.equal(scrub.move(i),i);scrub.change(i);}
 assert.deepEqual(requests,[]);scrub.end(205);scrub.end(205);
 assert.deepEqual(requests,[205]);assert.equal(scrub.active,false);
});
test('cancelled touch leaves playback intact; keyboard and click still seek',()=>{
 const requests=[],scrub=createTimelineScrub(value=>requests.push(value));
 scrub.begin(800);scrub.cancel();scrub.end(900);assert.deepEqual(requests,[]);
 scrub.change(20);scrub.begin(30);scrub.end();assert.deepEqual(requests,[20,30]);
});
