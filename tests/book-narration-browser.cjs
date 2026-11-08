// Real ML inference: narration of a local TXT book in BookReader (Ukrainian text).
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),MODELS=process.env.TTS_MODEL_DIR||path.resolve(ROOT,'../../benchmark/tts-2026-11-08/models');
let browser,vite;
(async()=>{
 if(!fs.existsSync(path.join(MODELS,'q4/onnx/vocoder.onnx'))){console.log('Skipped: local model copy not found');return;}
 fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/book-narration.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><div id="root"></div><script type="module" src="/tests/book-narration-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/book-narration.html';
 browser=await chromium.launch({headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const page=await (await browser.newContext({viewport:{width:1000,height:800},serviceWorkers:'block'})).newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://huggingface.co/**',route=>{const a=new URL(route.request().url()).pathname,f=decodeURIComponent(a.split('/resolve/')[1].split('/').slice(1).join('/'));route.fulfill({status:200,body:fs.readFileSync(path.join(MODELS,a.startsWith('/Supertone/')?'fp32':'q4',f)),headers:{'Access-Control-Allow-Origin':'*'}});});
 for(let i=0;i<3;i++){try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});await page.getByRole('button',{name:'Слушать главу'}).waitFor({timeout:120000});break;}catch(e){if(i===2)throw e;await page.waitForTimeout(3000);}}
 await page.getByRole('button',{name:'Слушать главу'}).click();
 await page.waitForSelector('.reader-prose p.is-speaking',{timeout:240000});
 await page.getByRole('button',{name:'Роли и голоса'}).click();
 const cast=await page.locator('.narration-cast li').allInnerTexts();
 assert.ok(cast.some(t=>t.includes('Оксана'))&&cast.some(t=>t.includes('Тарас')),'speakers: '+cast.join(' | '));
 await page.waitForSelector('.reader-prose p.is-speaking:nth-child(3)',{timeout:240000});
 assert.deepEqual(errors,[]);
 console.log('TXT book narration: OK (real Supertonic inference, Ukrainian heuristic roles).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
