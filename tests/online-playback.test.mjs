import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {reportOnlinePlayback} from '../src/online-playback.js';
const flush=()=>new Promise(setImmediate);
function fixture(){const media=Object.assign(new EventTarget(),{currentTime:0,paused:true,playbackRate:1,seeking:false,ended:false});return {media,getSnapshot:()=>({time:media.currentTime,playing:!media.paused})};}

test('reports real time, pause, seek and rate; removes all listeners',async()=>{
 const player=fixture(),calls=[];
 const stop=reportOnlinePlayback({request:async(path,options)=>calls.push({path,body:options.body})},'lease',player,()=>{},100000);
 await flush();player.media.currentTime=123.7;player.media.paused=false;player.media.playbackRate=1.5;player.media.dispatchEvent(new Event('play'));await flush();
 assert.equal(calls.at(-1).body.time,123.7);assert.equal(calls.at(-1).body.rate,1.5);assert.equal(calls.at(-1).body.paused,false);
 player.media.currentTime=500;player.media.paused=true;player.media.seeking=true;player.media.dispatchEvent(new Event('seeking'));await flush();
 assert.equal(calls.at(-1).body.time,500);assert.equal(calls.at(-1).body.paused,true);assert.equal(calls.at(-1).body.seeking,true);
 player.media.dispatchEvent(new Event('waiting'));await flush();assert.equal(calls.at(-1).body.buffering,true);
 stop();const count=calls.length;player.media.dispatchEvent(new Event('play'));await flush();assert.equal(calls.length,count);
});

test('coalesces changes behind one in-flight request and reports expiration once',async()=>{
 const player=fixture(),calls=[];let release,expired=0;
 const stop=reportOnlinePlayback({request:(path,o)=>{calls.push(o.body);if(calls.length===1)return new Promise(resolve=>release=resolve);throw Object.assign(Error('closed'),{status:409});}},'lease',player,()=>expired++,100000);
 player.media.currentTime=20;player.media.paused=false;player.media.dispatchEvent(new Event('play'));
 player.media.currentTime=90;player.media.paused=true;player.media.dispatchEvent(new Event('pause'));
 assert.equal(calls.length,1);release();await flush();assert.equal(calls.length,2);assert.equal(calls[1].time,90);assert.equal(calls[1].paused,true);assert.equal(expired,1);
 player.media.dispatchEvent(new Event('play'));await flush();assert.equal(calls.length,2);stop();
});

test('Alloha wire messages use viewer state rather than the paused server video',()=>{
 const source=fs.readFileSync(new URL('../server/alloha_browser.py',import.meta.url),'utf8');
 const init=source.match(/INIT = """([\s\S]*?)"""/)[1],messages=[];let now=0;
 class Socket{static OPEN=1;readyState=1;send(value){messages.push(JSON.parse(value));}addEventListener(){}close(){}}
 const context={window:{WebSocket:Socket},location:{href:'https://alloha.yani.tv/',host:'alloha.yani.tv'},player:{currentTime:0,quality:360,currentSource:{audioId:'1'}},URL,Date:{now:()=>now}};
 vm.createContext(context);vm.runInContext('('+init+')()',context);vm.runInContext('new window.WebSocket("wss://alloha.yani.tv/session")',context);
 const bridge=context.window.__allohaDelivery;bridge.heartbeat();assert.equal(messages.at(-1).type,'paused');
 bridge.updatePlayback({time:120.9,paused:false,rate:1.5,quality:2160});assert.equal(messages.at(-1).type,'resumed');assert.equal(messages.at(-1).current_time,120);assert.equal(messages.at(-1).resolution,'2160');
 bridge.updatePlayback({time:130,paused:true,rate:1,quality:2160});assert.equal(messages.at(-1).type,'paused');now+=20000;bridge.heartbeat();assert.equal(messages.at(-1).current_time,130);
 bridge.updatePlayback({time:500,paused:false,seeking:true,rate:1,quality:2160});assert.equal(messages.at(-1).type,'paused');
 bridge.updatePlayback({time:500,paused:false,rate:1,quality:2160});assert.equal(messages.at(-1).type,'resumed');
 now+=91000;bridge.heartbeat();assert.equal(messages.at(-1).type,'paused');assert.equal(messages.at(-1).current_time,500);
});
