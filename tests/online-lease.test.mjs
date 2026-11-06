import test from 'node:test';
import assert from 'node:assert/strict';
import {onlineClientId,keepOnlineLease} from '../src/online-lease.js';
test('viewer ID survives reload; preview uses its own slot',()=>{
 const m=new Map(),storage={getItem:k=>m.get(k),setItem:(k,v)=>m.set(k,v)};
 assert.equal(onlineClientId('viewer',storage),onlineClientId('viewer',storage));assert.notEqual(onlineClientId('preview',storage),onlineClientId('viewer',storage));
});
test('pagehide releases once with keepalive; browser restoration reconnects',async()=>{
 const events=new EventTarget(),calls=[];let expired=0;const close=keepOnlineLease({request:async(path,options)=>calls.push({path,options})},'fixture',()=>expired++,events);
 events.dispatchEvent(new Event('pagehide'));events.dispatchEvent(new Event('pageshow'));await Promise.resolve();close();assert.equal(calls.length,1);assert.equal(calls[0].path,'/online/fixture');assert.equal(calls[0].options.keepalive,true);assert.equal(expired,1);
});
test('closed leases remove listeners and do not reconnect',()=>{
 const events=new EventTarget();let calls=0,expired=0;const close=keepOnlineLease({request:async()=>calls++},'fixture',()=>expired++,events);close();events.dispatchEvent(new Event('focus'));assert.equal(calls,1);assert.equal(expired,0);
});

test('404 and 410 expire once without parallel reconnects',async()=>{
 for(const status of [404,410]){
  const events=new EventTarget();let expired=0;
  const close=keepOnlineLease({request:async(path)=>{if(path.endsWith('/heartbeat'))throw Object.assign(Error('expired'),{status});}},'fixture',()=>expired++,events);
  events.dispatchEvent(new Event('focus'));await new Promise(setImmediate);
  events.dispatchEvent(new Event('focus'));events.dispatchEvent(new Event('pageshow'));await new Promise(setImmediate);
  assert.equal(expired,1);close();
 }
});
