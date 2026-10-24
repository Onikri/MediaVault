import test from 'node:test';
import assert from 'node:assert/strict';
import {describeMediaError,recognizeVideoCodec,diagnoseVideoFailure} from '../src/playback-diagnostics.js';
test('identifies unsupported media decoding errors and incompatible codecs from MP4 headers',()=>{
  assert.match(describeMediaError(4),/кодек/);
  assert.match(describeMediaError(3),/декодировать/);
  const head=new TextEncoder().encode('isom ftyp moov trak stsd hvc1 HEVC');
  assert.equal(recognizeVideoCodec(head),'HEVC / H.265');
  assert.equal(recognizeVideoCodec(new TextEncoder().encode('moov h264 mp4a')),'');
  assert.equal(recognizeVideoCodec(new TextEncoder().encode('stsd ec-3')),'Dolby AC-3 / E-AC-3');
});
test('disambiguates invalid worker sessions from unsupported browser codecs',async()=>{
  const original=globalThis.fetch;
  try{
    globalThis.fetch=async()=>({ok:false,status:503});
    assert.match(await diagnoseVideoFailure({video:{error:{code:4}},source:'https://example.test/__media__/abc'}),/Drive/);
    globalThis.fetch=async(url,opts)=>opts.method==='HEAD'
      ?{ok:true,status:200}
      :{ok:true,status:206,arrayBuffer:async()=>new TextEncoder().encode('moov hvc1').buffer};
    assert.match(await diagnoseVideoFailure({video:{error:{code:4}},source:'https://example.test/__media__/abc'}),/HEVC/);
  }finally{globalThis.fetch=original;}
});
