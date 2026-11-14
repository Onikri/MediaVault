import test from 'node:test';
import assert from 'node:assert/strict';
import {deferStreamRecovery} from '../src/stream-recovery.js';

function video(){return Object.assign(new EventTarget(),{readyState:4,error:null,paused:true,seeking:false,currentTime:100,
 buffered:{length:1,start:()=>90,end:()=>140}});}
test('expired control lease keeps paused buffered media and reconnects before reserve ends',()=>{
 const v=video();let calls=0;const cancel=deferStreamRecovery(v,()=>calls++);
 v.dispatchEvent(new Event('waiting'));assert.equal(calls,0);
 v.paused=false;v.dispatchEvent(new Event('play'));assert.equal(calls,0);
 v.currentTime=133;v.dispatchEvent(new Event('timeupdate'));assert.equal(calls,1);
 v.dispatchEvent(new Event('waiting'));assert.equal(calls,1);cancel();
});
test('uncached seek recovers immediately; cached seek retains the existing stream',()=>{
 const v=video();let calls=0;deferStreamRecovery(v,()=>calls++);
 v.seeking=true;v.currentTime=120;v.dispatchEvent(new Event('seeking'));assert.equal(calls,0);
 v.currentTime=800;v.dispatchEvent(new Event('seeking'));assert.equal(calls,1);
});
test('cleanup prevents old episode from reconnecting; genuine media errors recover immediately',()=>{
 const v=video();let calls=0;const cancel=deferStreamRecovery(v,()=>calls++);cancel();
 v.error={code:2};v.dispatchEvent(new Event('waiting'));assert.equal(calls,0);
 deferStreamRecovery(v,()=>calls++);assert.equal(calls,1);
});
