import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {MODEL_BLOB_SHA1,QUALITY_MODES,gitBlobSha1,prepareLuma,reconstructRgb}
  from '../src/neural-upscaler.js';

test('pretrained FSRCNN model has an immutable Git blob content pin',()=>{
  assert.match(MODEL_BLOB_SHA1,/^[a-f\d]{40}$/);
  assert.deepEqual(Object.keys(QUALITY_MODES),['performance','balanced','quality']);
  assert.ok(QUALITY_MODES.performance.width<QUALITY_MODES.balanced.width);
  assert.ok(QUALITY_MODES.balanced.width<QUALITY_MODES.quality.width);
});
test('verifies content hashes exactly as Git calculates them',async()=>{
  globalThis.crypto ||= webcrypto;
  const bytes=new TextEncoder().encode('a pretrained test model');
  const header=Buffer.from('blob '+bytes.length+'\0');
  const expected=createHash('sha1').update(header).update(bytes).digest('hex');
  assert.equal(await gitBlobSha1(bytes),expected);
  assert.notEqual(await gitBlobSha1(new TextEncoder().encode('tampered')),expected);
});
test('FSRCNN receives luminance tensor and reconstructs neural output with original chroma',()=>{
  const rgba=new Uint8ClampedArray([255,0,0,255,0,255,0,255]);
  const luma=prepareLuma({width:2,height:1,data:rgba});
  assert.equal(luma.length,2);
  assert.ok(Math.abs(luma[0]-0.299)<1e-6);
  assert.ok(Math.abs(luma[1]-0.587)<1e-6);
  const bright=reconstructRgb(new Uint8ClampedArray([20,40,60,255]),new Float32Array([0.7]));
  assert.equal(bright.length,4);
  assert.equal(bright[3],255);
  assert.ok(bright[0]>20&&bright[1]>40&&bright[2]>60);
  assert.throws(()=>reconstructRgb(new Uint8ClampedArray(4),new Float32Array(2)));
});
