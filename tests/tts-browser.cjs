// Real ML inference (not mocked): Supertonic 3 q4 in Chromium via the app's
// worker. Hugging Face requests are answered from the local verified copy in
// .codex-local/benchmark/tts-2026-11-08/models/q4 (same bytes and hashes).
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),MODELS=process.env.TTS_MODEL_DIR||path.resolve(ROOT,'../../benchmark/tts-2026-11-08/models');
let browser,vite;
(async()=>{
 if(!fs.existsSync(path.join(MODELS,'q4/onnx/vocoder.onnx'))){console.log('Skipped: local model copy not found at '+MODELS);return;}
 fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/tts.html'),'<!doctype html><meta charset="utf-8"><script type="module" src="/tests/tts-harness.jsx"></script>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/tts.html';
 browser=await chromium.launch({headless:process.env.HEADED!=='1',args:['--no-sandbox','--enable-unsafe-webgpu',...(process.env.CHROMIUM_ARGS||'').split(' ').filter(Boolean)]});
 const results={};
 for(const prefer of (process.env.TTS_PROVIDERS||'wasm,auto').split(',')){
  const page=await (await browser.newContext({serviceWorkers:'block'})).newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://huggingface.co/**',route=>{const address=new URL(route.request().url()).pathname,file=decodeURIComponent(address.split('/resolve/')[1].split('/').slice(1).join('/')),dir=address.startsWith('/Supertone/')?'fp32':'q4';route.fulfill({status:200,body:fs.readFileSync(path.join(MODELS,dir,file)),headers:{'Access-Control-Allow-Origin':'*','Content-Type':'application/octet-stream'}});});
  let value;
  for(let attempt=0;attempt<3&&!value;attempt++){
   // Vite may re-optimise dependencies and reload the page once on first use.
   try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});await page.waitForFunction(()=>typeof window.runTts==='function',null,{timeout:180000});value=await page.evaluate(prefer=>window.runTts(prefer),prefer);}
   catch(error){if(!/context was destroyed|navigat/i.test(error.message)||attempt===2)throw error;await page.waitForTimeout(3000);}
  }
  results[prefer]=value;
  for(const row of value.rows.filter(r=>!r.blend)){assert.ok(row.seconds>1.5&&row.seconds<12,'plausible duration '+JSON.stringify(row));assert.ok(row.peak>0.05,'audible '+JSON.stringify(row));}
  assert.ok(value.rows.find(r=>r.blend).seconds>0.8);
  assert.deepEqual(errors,[]);
  await page.context().close();
 }
 console.log(JSON.stringify(results,null,1));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
