import test from 'node:test';
import assert from 'node:assert/strict';
import {searchRanobe} from '../src/ranobe-client.js';

const item={id:'anilist:5',kind:'ranobe',title:'Mob Shisai Dakedo',aliases:[],ids:{anilist:'5'},year:2021};
const indexed={url:'https://ranobelib.me/ru/book/267220--mob',provider:'ranobelib',indexed:true};
const live={url:'https://ranobehub.org/ranobe/7',provider:'ranobehub'};

test('an indexed book arrives first and the search repeats until the live answer',async()=>{
 const answers=[{results:[indexed],providers:[],pending:true},{results:[indexed],providers:[],pending:true},{results:[indexed,live],providers:[],language:'all',checkedAt:1}];
 const bodies=[],partial=[];
 const service={request:async(path,options)=>{assert.equal(path,'/ranobe/search');bodies.push(options.body);return answers.shift();}};
 const final=await searchRanobe(service,item,'all',{onPartial:data=>partial.push(data.results.map(r=>r.url)),interval:1});
 assert.deepEqual(partial,[[indexed.url],[indexed.url]]);
 assert.deepEqual(final.results.map(r=>r.url),[indexed.url,live.url]);
 assert.equal(bodies.length,3);
 assert.deepEqual(bodies[0],{title:{id:'anilist:5',title:'Mob Shisai Dakedo',titles:{},aliases:[],ids:{anilist:'5'},year:2021,kind:'ranobe'},language:'all'});
});

test('an answer without pending is returned as before, in one request',async()=>{
 let calls=0;
 const service={request:async()=>{calls++;return {results:[live],providers:[],language:'all',checkedAt:1};}};
 const value=await searchRanobe(service,item,'all',{onPartial:()=>assert.fail('no partial answer')});
 assert.equal(calls,1);assert.deepEqual(value.results,[live]);
});

test('an aborted search stops waiting',async()=>{
 const controller=new AbortController();
 const service={request:async()=>({results:[indexed],providers:[],pending:true})};
 const running=searchRanobe(service,item,'all',{signal:controller.signal,onPartial:()=>controller.abort(),interval:10000});
 await assert.rejects(running);
});
