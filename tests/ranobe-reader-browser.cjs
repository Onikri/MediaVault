// Ranobe reading and narration in Chromium. Real ML inference (Supertonic 3 via
// the app worker, model bytes from the local verified copy); ranobe server
// answers are fixtures and the Google role pass is mocked to fail (heuristic roles).
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),MODELS=process.env.TTS_MODEL_DIR||path.resolve(ROOT,'../../benchmark/tts-2026-11-08/models'),OUT=path.join(ROOT,'.codex-local/test-output/ranobe');
let browser,vite;
(async()=>{
 if(!fs.existsSync(path.join(MODELS,'q4/onnx/vocoder.onnx'))){console.log('Skipped: local model copy not found');return;}
 fs.mkdirSync(OUT,{recursive:true});fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/ranobe.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe.html';
 browser=await chromium.launch({headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const context=await browser.newContext({viewport:{width:1100,height:850},serviceWorkers:'block'});context.setDefaultTimeout(30000);
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://huggingface.co/**',route=>{const address=new URL(route.request().url()).pathname,file=decodeURIComponent(address.split('/resolve/')[1].split('/').slice(1).join('/'));route.fulfill({status:200,body:fs.readFileSync(path.join(MODELS,address.startsWith('/Supertone/')?'fp32':'q4',file)),headers:{'Access-Control-Allow-Origin':'*'}});});
 for(let i=0;i<3;i++){try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});await page.getByRole('button',{name:/Начать читать|Продолжить/}).waitFor({timeout:120000});break;}catch(e){if(i===2)throw e;await page.waitForTimeout(3000);}}
 await page.getByRole('button',{name:/Начать читать/}).click();
 await page.locator('.ranobe-prose p').first().waitFor();
 assert.equal(await page.locator('.ranobe-prose p').count(),4);
 assert.equal(await page.locator('.ranobe-prose').getAttribute('translate'),'no');
 await page.getByRole('button',{name:'Слушать главу'}).click();
 await page.getByRole('button',{name:'Загрузить и слушать'}).click();
 page.on('console',m=>{if(m.type()==='error')console.log('console:',m.text());});await page.waitForSelector('.ranobe-prose p.is-speaking',{timeout:240000}).catch(async e=>{await page.screenshot({path:path.join(OUT,'timeout.png')});console.log(await page.locator('.narration').innerText().catch(()=>''));throw e;});
 // Roles are drawn in the text: speaker names in their colour, a live caption.
 await page.waitForSelector('.ranobe-prose .role-name',{timeout:60000});
 const names=await page.locator('.ranobe-prose .role-name').allInnerTexts();
 assert.ok(names.some(t=>t.includes('Мирэй'))||names.some(t=>t.includes('Кайто')),'role names in text: '+names.join(' | '));
 assert.ok(await page.locator('.ranobe-prose .role-speech').first().evaluate(n=>getComputedStyle(n).getPropertyValue('--role').trim().startsWith('#')),'speech has a role colour');
 await page.waitForSelector('.narration-caption b',{timeout:60000});
 assert.ok(await page.getByRole('button',{name:/Пауза озвучки|Слушать главу/}).first().isVisible(),'top-bar listen control');
 await page.getByRole('button',{name:'Роли и голоса'}).click();
 const cast=await page.locator('.narration-cast li').allInnerTexts();
 assert.ok(cast.some(t=>t.includes('Мирэй'))&&cast.some(t=>t.includes('Кайто')),'speakers found: '+cast.join(' | '));
 await page.screenshot({path:path.join(OUT,'narration.png')});
 assert.ok(await page.getByRole('button',{name:/Пример голоса: /}).count()>=2,'voice samples per character');
 // Two voices actually speak: wait until the dialogue paragraph is highlighted.
 await page.waitForSelector('.ranobe-prose p.is-speaking[data-p="1"]',{timeout:240000});
 assert.ok(await page.evaluate(()=>window.requests.includes('/reader/google/generate')),'role pass attempted (mocked)');
 assert.deepEqual(errors,[]);
 console.log('Ranobe reader + narration: OK (real Supertonic inference, fixture server, mocked Google roles).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
