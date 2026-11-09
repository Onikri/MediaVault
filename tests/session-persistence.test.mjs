// Sign-in memory survives cleared site storage; the open reader survives reloads.
import test from 'node:test';
import assert from 'node:assert/strict';

const store=new Map();let jar={};
globalThis.localStorage={getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k),clear:()=>store.clear()};
globalThis.location=new URL('https://onikri.github.io/MediaVault/#home');
globalThis.document={get cookie(){return Object.entries(jar).map(([k,v])=>k+'='+v).join('; ');},set cookie(value){const [pair,...attrs]=value.split('; ');const at=pair.indexOf('=');const name=pair.slice(0,at);if(attrs.some(a=>a==='Max-Age=0'))delete jar[name];else jar[name]=pair.slice(at+1);}};
globalThis.window=globalThis;globalThis.dispatchEvent??=()=>true;globalThis.CustomEvent??=class extends Event{constructor(type,init){super(type);this.detail=init?.detail;}};
const {privacyPreferences,savePrivacyPreferences,rememberedDeviceId,saveRememberedDeviceId}=await import('../src/privacy.js');
const {readerInAddress,addressWithReader}=await import('../src/ranobe-client.js');

test('Google sign-in is remembered by default until the visitor declines',()=>{
 store.clear();jar={};
 assert.deepEqual([privacyPreferences().chosen,privacyPreferences().remember],[false,true]);
 savePrivacyPreferences(false);assert.equal(privacyPreferences().remember,false);assert.equal(privacyPreferences().chosen,true);
});

test('a choice survives cleared localStorage through the preferences cookie',()=>{
 store.clear();jar={};
 savePrivacyPreferences(true);store.clear();
 const value=privacyPreferences();assert.equal(value.remember,true);assert.equal(value.chosen,true);assert.equal(value.restoredFromCookie,true);
 assert.ok(store.get('mediavault_privacy_v1'),'copied back to localStorage');
 savePrivacyPreferences(false);store.clear();assert.equal(privacyPreferences().remember,false);
});

test('the device cookie holds only a well-formed id and is cleared when memory is declined',()=>{
 store.clear();jar={};
 const id='A'.repeat(43);saveRememberedDeviceId(id);assert.equal(rememberedDeviceId(),id);
 assert.match(document.cookie,/mv_device=A{43}/);assert.doesNotMatch(document.cookie,/token|phrase|key/i);
 jar.mv_device='not an id';assert.equal(rememberedDeviceId(),'');
 saveRememberedDeviceId(id);savePrivacyPreferences(false);assert.equal(rememberedDeviceId(),'');
});

test('the open reader is kept in the title address',()=>{
 const hash='#'+new URLSearchParams({watch:'ranobe:shikimori:42'});
 const open=addressWithReader(hash,4);
 assert.equal(readerInAddress(open),4);assert.equal(new URLSearchParams(open.slice(1)).get('watch'),'ranobe:shikimori:42');
 assert.equal(readerInAddress(addressWithReader(open,-1)),-1);
 assert.equal(addressWithReader('#home',2),null,'only on a title page');
 assert.equal(readerInAddress('#watch=x&read=0'),-1);assert.equal(readerInAddress('#watch=x&read=abc'),-1);
});
