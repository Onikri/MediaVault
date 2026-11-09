// Gemini narration in Chromium: the reader streams voices from the server relay.
// MOCKED: the server and its audio (a 220 Hz tone, not Gemini speech) and the
// Google bible/roles answers. Real Gemini output is measured live separately.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'.codex-local/test-output/ranobe');
let browser,vite;
(async()=>{
 fs.mkdirSync(OUT,{recursive:true});fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/ranobe.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe.html?engine=gemini';
 browser=await chromium.launch({headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const context=await browser.newContext({viewport:{width:1100,height:850},serviceWorkers:'block'});context.setDefaultTimeout(30000);
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://huggingface.co/**',route=>{errors.push('model download '+route.request().url());route.abort();});
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});
 await page.getByRole('button',{name:/Начать читать/}).click({timeout:120000});
 await page.locator('.ranobe-prose p').first().waitFor();
 // Roles first, so voices are cast from the bible.
 await page.waitForSelector('.ranobe-prose .role-name i',{timeout:60000});
 await page.getByRole('button',{name:'Слушать главу'}).click();
 assert.equal(await page.getByRole('button',{name:'Загрузить и слушать'}).count(),0,'no model download consent for Gemini');
 await page.waitForSelector('.ranobe-prose p.is-speaking',{timeout:30000});
 await page.waitForSelector('.ranobe-prose p.is-speaking[data-p="1"]',{timeout:60000});
 await page.waitForFunction(()=>/Gemini/.test(document.querySelector('.narration-status')?.textContent||''),null,{timeout:30000});
 const speak=await page.evaluate(()=>window.speak);
 const narration=speak.find(b=>/Ночь опустилась/.test(b.text)),mirei=speak.find(b=>/опять опоздал/.test(b.text));
 assert.ok(narration&&mirei,'utterances sent: '+speak.map(b=>b.text).join(' | '));
 assert.equal(narration.voice,'Charon','warm adult male narrator from the bible');
 assert.match(narration.style,/авторский текст.*городское фэнтези/);
 assert.match(mirei.style,/Мирэй \(молодая женщина\).*вспыльчивая.*сердито/);
 assert.ok(['Aoede','Despina','Erinome','Zephyr','Callirrhoe','Autonoe'].includes(mirei.voice),'young bright female voice for Мирэй: '+mirei.voice);
 assert.ok(speak.every(b=>!/\u0301/.test(b.text)&&b.language==='ru'),'plain text without stress marks');
 // Cast panel: engine, male/female narrator options, Gemini voices per character.
 await page.getByRole('button',{name:'Роли и голоса'}).click();
 assert.equal(await page.getByLabel('Движок озвучки').inputValue(),'gemini');
 const options=await page.getByLabel('Голос рассказчика').locator('option').allInnerTexts();
 assert.ok(options.includes('Мужской · Charon')&&options.includes('Женский · Kore'),options.slice(0,4).join(' | '));
 assert.deepEqual(await page.getByLabel('Голос рассказчика').locator('optgroup').evaluateAll(g=>g.map(x=>x.label)),['Мужские голоса','Женские голоса']);
 assert.equal(await page.getByLabel('Голос: Мирэй').inputValue(),mirei.voice);
 assert.equal(await page.getByLabel('Высота голоса: Мирэй').count(),0,'no Supertonic pitch control for Gemini voices');
 // Switch the narrator to a female voice: its sample now asks for Kore.
 await page.getByLabel('Голос рассказчика').selectOption('f');
 await page.getByRole('button',{name:'Пример голоса рассказчика'}).click();
 await page.waitForFunction(()=>window.speak.some(b=>b.voice==='Kore'&&/Так звучит мой голос/.test(b.text)),null,{timeout:30000});
 await page.waitForFunction(()=>!document.querySelector('.narration-sample[aria-pressed="true"]')&&![...document.querySelectorAll('.narration-sample')].some(b=>b.disabled),null,{timeout:30000});
 await page.screenshot({path:path.join(OUT,'gemini-narration.png')});
 // Sample button plays a voice through the same relay.
 await page.getByRole('button',{name:'Пример голоса: Кайто'}).click();
 await page.waitForFunction(()=>window.speak.some(b=>/Так звучит мой голос/.test(b.text)&&b.voice!=='Kore'),null,{timeout:30000});
 assert.deepEqual(errors,[]);
 console.log('Gemini narration: OK (fixture server; MOCKED tone instead of Gemini audio; MOCKED Google bible/roles answers).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
