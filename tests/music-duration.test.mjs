import test from 'node:test';
import assert from 'node:assert/strict';
import {knownMusicDuration} from '../src/music-duration.js';
test('failed audio can still search lyrics using verified catalogue or selected record duration',()=>{
 assert.equal(knownMusicDuration({},0,{durationMs:227000}),227);
 assert.equal(knownMusicDuration({},0,{}, {duration:'3:47'}),227);
 assert.equal(knownMusicDuration({},195,{durationMs:187000}),195,'Actual audio wins over recording metadata');
 assert.equal(knownMusicDuration({},0,{},{}),0);assert.equal(knownMusicDuration({},0,{durationMs:NaN},{duration:'LIVE'}),0);
});
