import test from 'node:test';
import assert from 'node:assert/strict';
import {streamBufferPolicy,bitrateBufferPolicy,startupBufferReady} from '../src/watch-quality.js';

test('Alloha reserves more compressed video without increasing preview or saver budgets',()=>{
 const normal=streamBufferPolicy(),alloha=streamBufferPolicy({alloha:true});
 assert.equal(normal.maxBufferSize,64*1024*1024);
 assert.equal(alloha.maxBufferSize,128*1024*1024);
 assert.ok(bitrateBufferPolicy(alloha,20e6).maxBufferLength>50);
 assert.equal(streamBufferPolicy({alloha:true,memory:4}).maxBufferSize,48*1024*1024);
 for(const mode of [{preview:true},{saveData:true},{audioOnly:true}])
  assert.deepEqual(streamBufferPolicy({...mode,alloha:true}),streamBufferPolicy(mode));
});

test('startup reserve waits for contiguous media, permits ending/manual play, and has a deadline',()=>{
 const video={paused:true,currentTime:30,duration:120,buffered:{length:2,start:i=>[30,90][i],end:i=>[34,120][i]}};
 assert.equal(startupBufferReady(video,8,200),false,'four seconds is one Alloha fragment');
 video.buffered.end=i=>[38,120][i];assert.equal(startupBufferReady(video,8,200),true);
 video.buffered.end=i=>[34,120][i];assert.equal(startupBufferReady(video,8,6000),true,'a slow source must not wait forever');
 video.paused=false;assert.equal(startupBufferReady(video,8,200),true,'manual playback is not delayed');
 video.paused=true;video.duration=34;assert.equal(startupBufferReady(video,8,200),true,'short tail is enough near the end');
 assert.equal(startupBufferReady(video,0,200),true,'other players retain their current startup');
});
