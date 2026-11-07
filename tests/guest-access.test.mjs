import test from 'node:test';
import assert from 'node:assert/strict';
globalThis.localStorage??={getItem:()=>null,setItem(){},removeItem(){}};
const {guestAllows,guestLocked}=await import('../src/guest-session.js');

test('guest access mirrors the server rule for scope and kinds',()=>{
 assert.equal(guestAllows(undefined,{kind:'anime',ids:{mal:'1'}}),true);
 const picked={scope:'titles',watch:true,read:false,titles:[{key:'anime:34599'}]};
 assert.equal(guestAllows(picked,{kind:'tv',ids:{mal:34599}}),true);
 assert.equal(guestAllows(picked,{kind:'anime',ids:{mal:'1'}}),false);
 assert.equal(guestAllows(picked,{kind:'manga',ids:{mal:'34599'}}),false);
 assert.equal(guestAllows({scope:'all',watch:false,read:true},{kind:'anime'}),false);
 assert.equal(guestLocked({role:'owner'},{kind:'anime'}),false);
 assert.equal(guestLocked({role:'guest',guest:{access:picked}},{kind:'anime',ids:{mal:'2'}}),true);
});
