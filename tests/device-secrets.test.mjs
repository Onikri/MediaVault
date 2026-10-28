import test from 'node:test';
import assert from 'node:assert/strict';
import {saveDeviceSecret,readDeviceSecret,forgetDeviceSecret} from '../src/device-secrets.js';

function memory(){const records=new Map();return {records,store:async(op,key,value)=>{if(op==='get')return records.get(key);if(op==='delete')return records.delete(key);if(op==='getOrPut'){if(!records.has(key))records.set(key,value);return records.get(key);}records.set(key,value);}};}
test('device key ciphertext survives a new reader instance without exporting the wrapping key',async()=>{
 const {store,records}=memory(),secret='fixture-personal-google-secret';await saveDeviceSecret('A','google-translation',secret,{store});
 assert.equal(await readDeviceSecret('A','google-translation',{store}),secret);
 assert.ok(!JSON.stringify([...records]).includes(secret));const key=records.get('secret-wrap:google-translation:A');assert.equal(key.extractable,false);await assert.rejects(crypto.subtle.exportKey('raw',key));
 assert.equal(await readDeviceSecret('B','google-translation',{store}),'');
});
test('copying a saved secret to another account cannot decrypt it',async()=>{
 const {store,records}=memory();await saveDeviceSecret('A','google-translation','fixture-key',{store});
 records.set('secret:google-translation:B',{...records.get('secret:google-translation:A'),scope:'B'});records.set('secret-wrap:google-translation:B',records.get('secret-wrap:google-translation:A'));
 await assert.rejects(readDeviceSecret('B','google-translation',{store}));
});
test('expired and forgotten API keys are removed while other profiles remain usable',async()=>{
 const {store,records}=memory();await saveDeviceSecret('A','google-translation','fixture-a',{store,now:()=>0});await saveDeviceSecret('B','google-translation','fixture-b',{store});
 assert.equal(await readDeviceSecret('A','google-translation',{store,now:()=>91*86400000}),'');await forgetDeviceSecret('B','google-translation',{store});assert.equal(await readDeviceSecret('B','google-translation',{store}),'');assert.equal(records.has('secret-wrap:google-translation:B'),false);
 await assert.rejects(saveDeviceSecret('anonymous','google-translation','fixture',{store}));
});
