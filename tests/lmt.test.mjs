import test from 'node:test';import assert from 'node:assert/strict';import{validateConfig}from'../lmt/config.js';import{prebuiltAppConfig}from'@mlc-ai/web-llm';
test('LMT requires opt-in before model traffic and validates own-server endpoints',()=>{assert.throws(()=>validateConfig({}),/Разреши/);const base={allowDownloads:true,mode:'api',serverModel:'my-free-model'};for(const host of['http://external.example/v1','https://user:pass@example.com/v1','file:///tmp','https://example.org/v1?secret=x'])assert.throws(()=>validateConfig({...base,host}));for(const host of['https://example.org/v1','http://localhost:1234/v1','http://127.0.0.1:11434/v1'])assert.doesNotThrow(()=>validateConfig({...base,host}));assert.throws(()=>validateConfig({...base,host:'https://example.org/v1',serverModel:''}),/модели/);});
test('language-specific OCR cannot silently recognize the wrong script',()=>{assert.throws(()=>validateConfig({allowDownloads:true,ocr:'manga-ocr',language:'English'}),/японского/);assert.throws(()=>validateConfig({allowDownloads:true,ocr:'pororo',language:'Japanese'}),/корейского/);assert.doesNotThrow(()=>validateConfig({allowDownloads:true,ocr:'manga-ocr',language:'Japanese'}));});
test('exposed local LLM choices are real supported WebLLM models',()=>{for(const id of ['Qwen3.5-4B-q4f32_1-MLC','Qwen3.5-0.8B-q4f32_1-MLC','Qwen3.5-0.8B-q4f16_1-MLC','Qwen3.5-2B-q4f16_1-MLC','Qwen3.5-4B-q4f16_1-MLC'])assert.ok(prebuiltAppConfig.model_list.some(x=>x.model_id===id));});

import {validateVisionResult} from '../lmt/vision.js';
test('vision result preserves explicit IDs, source text and exact region count',()=>{
 const a={id:1,sourceText:'Hello',translation:'Привет'},b={id:2,sourceText:'Bye',translation:'Пока'};
 assert.deepEqual(validateVisionResult({regions:[b,a]},2).translations,['Привет','Пока']);
 assert.throws(()=>validateVisionResult({regions:[a]},2));assert.throws(()=>validateVisionResult({regions:[a,a]},2));assert.throws(()=>validateVisionResult({regions:[a,{...b,id:3}]},2));assert.throws(()=>validateVisionResult({regions:[{...a,sourceText:null}]},1));
});
test('VLM skips irrelevant OCR script restrictions and Korean V5 covers only Korean',()=>{
 assert.doesNotThrow(()=>validateConfig({allowDownloads:true,mode:'api',apiInput:'vision',host:'https://example.org/v1',serverModel:'vision',ocr:'pororo',language:'English'}));
 assert.throws(()=>validateConfig({allowDownloads:true,ocr:'ppocrv5-korean',language:'English'}));
});

import {resolveMangaOcr} from '../src/ocr-profiles.js';
test('quality OCR defaults preserve vertical Japanese accuracy and explicit user choices',()=>{assert.equal(resolveMangaOcr('Japanese','auto'),'manga-ocr');assert.equal(resolveMangaOcr('Japanese'),'manga-ocr');assert.equal(resolveMangaOcr('Japanese','ppocrv6-manga'),'ppocrv6-manga');assert.equal(resolveMangaOcr('Korean','auto'),'ppocrv5-korean');assert.equal(resolveMangaOcr('English','auto'),'paddle');});
