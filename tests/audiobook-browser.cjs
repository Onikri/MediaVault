// Chapter → audiobook in Chromium with the Gemini engine. MOCKED: the server
// relay streams a 220 Hz tone instead of Gemini speech, and the Google
// bible/roles answers are fixtures (see tests/ranobe-harness.jsx). Real
// WebCodecs Opus encoding and Ogg writing; the file is decoded back by the browser.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'.codex-local/test-output/ranobe');
let browser,vite;
(async()=>{
 fs.mkdirSync(OUT,{recursive:true});fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/ranobe.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const context=await browser.newContext({viewport:{width:1100,height:850},serviceWorkers:'block',acceptDownloads:true});context.setDefaultTimeout(30000);
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://huggingface.co/**',route=>{errors.push('model download '+route.request().url());route.abort();});
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe.html?engine=gemini',{waitUntil:'domcontentloaded',timeout:180000});
 await page.getByRole('button',{name:/Начать читать/}).click({timeout:120000});
 await page.waitForSelector('.ranobe-prose .role-name i',{timeout:60000});
 // Listen to the first phrases, then pause: they are kept for the file.
 await page.getByRole('button',{name:'Слушать главу'}).click();
 await page.waitForSelector('.ranobe-prose p.is-speaking[data-p="1"]',{timeout:60000});
 await page.getByRole('button',{name:'Пауза озвучки'}).click();
 await page.waitForTimeout(400);
 const chapterText=b=>!/Так звучит мой голос/.test(b.text);
 const before=(await page.evaluate(()=>window.speak)).filter(chapterText).length;
 await page.getByRole('button',{name:'Сохранить главу аудиокнигой'}).click();
 const panel=page.getByRole('region',{name:'Аудиокнига из главы'});
 const ready=await panel.locator('p').nth(1).innerText();
 const match=/^Готово (\d+) из (\d+) фраз\.$/.exec(ready);
 assert.ok(match,'readiness: '+ready);
 const [stored,total]=[Number(match[1]),Number(match[2])];
 assert.ok(stored>=1&&stored<total,'some phrases already voiced: '+ready);
 assert.match(await panel.innerText(),new RegExp('Остальные '+(total-stored)+' фраз озвучит Gemini'));
 const [download]=await Promise.all([page.waitForEvent('download',{timeout:60000}),panel.getByRole('button',{name:'Сохранить файл'}).click()]);
 await panel.getByRole('status').filter({hasText:'Аудиокнига сохранена'}).waitFor();
 assert.equal(download.suggestedFilename(),'Повелитель — Глава 1.opus');
 const bytes=fs.readFileSync(await download.path());
 assert.equal(bytes.subarray(0,4).toString(),'OggS');
 const header=bytes.subarray(0,400).toString('utf8');
 assert.ok(header.includes('OpusHead')&&header.includes('TITLE=Глава 1')&&header.includes('ALBUM=Повелитель')&&header.includes('Синтезированная озвучка'),'Opus tags');
 // Every phrase of the chapter was requested once: the stored ones were not asked again.
 const speak=(await page.evaluate(()=>window.speak)).filter(chapterText);
 const texts=speak.map(b=>b.text);
 assert.equal(new Set(texts).size,total,'each phrase voiced: '+texts.join(' | '));
 assert.equal(speak.length-before,total-stored,'only the missing phrases were requested: before '+before+', after '+speak.length+', phrases '+total);
 // The browser decodes the file: one tone (0.45 s) per phrase plus pauses.
 const seconds=await page.evaluate(async data=>{const ctx=new OfflineAudioContext(1,1,48000);const buffer=await ctx.decodeAudioData(Uint8Array.from(atob(data),c=>c.charCodeAt(0)).buffer);return buffer.duration;},bytes.toString('base64'));
 assert.ok(seconds>total*.45&&seconds<total*.45+total*.5,'decoded duration '+seconds+' for '+total+' phrases');
 await page.screenshot({path:path.join(OUT,'audiobook.png')});
 // Saving again needs no request at all.
 await panel.getByRole('button',{name:'Готово'}).click();
 await page.getByRole('button',{name:'Сохранить главу аудиокнигой'}).click();
 await panel.getByText('Вся глава уже озвучена: новых запросов не будет.').waitFor();
 const count=speak.length;
 const [again]=await Promise.all([page.waitForEvent('download'),panel.getByRole('button',{name:'Сохранить файл'}).click()]);
 await again.path();
 assert.equal((await page.evaluate(()=>window.speak)).filter(chapterText).length,count,'no request for a fully voiced chapter');
 assert.deepEqual(errors,[]);
 console.log('Audiobook (Gemini): OK ('+total+' phrases, '+stored+' reused, '+seconds.toFixed(2)+' s Opus; MOCKED tone instead of Gemini audio).');

 // Neural inference is an explicit integration run, separate from the always-on
 // mocked provider contract above. No private benchmark path exists on CI.
 if(!process.env.TTS_MODEL_DIR&&!process.argv.includes('--real-tts')){console.log('SKIP real Supertonic inference: run npm run test:audiobook-ml with cached weights or set TTS_MODEL_DIR. The Gemini provider contract above uses a mocked tone.');return;}
 const MODELS=process.env.TTS_MODEL_DIR||path.join(ROOT,'.codex-local/benchmark/tts-2026-11-08/models');
 assert.ok(fs.existsSync(path.join(MODELS,'fp32/onnx/duration_predictor.onnx')),'Real Supertonic inference requested: provide the model pack with TTS_MODEL_DIR.');
 // Supertonic: real on-device inference; phrases carry pitch and EQ and are
 // rendered offline, then resampled from 44.1 kHz for Opus.
 const fresh=await browser.newContext({viewport:{width:1100,height:850},serviceWorkers:'block',acceptDownloads:true});fresh.setDefaultTimeout(30000);
 const local=await fresh.newPage();// The real Supertonic weights, served from disk like tests/ranobe-reader-browser.cjs.
 await local.route('https://huggingface.co/**',route=>{const address=new URL(route.request().url()).pathname,file=decodeURIComponent(address.split('/resolve/')[1].split('/').slice(1).join('/'));route.fulfill({status:200,body:fs.readFileSync(path.join(MODELS,address.startsWith('/Supertone/')?'fp32':'q4',file)),headers:{'Access-Control-Allow-Origin':'*'}});});local.on('pageerror',e=>errors.push(e.message));
 await local.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe.html',{waitUntil:'domcontentloaded',timeout:180000});
 await local.getByRole('button',{name:/Начать читать/}).click({timeout:120000});
 await local.locator('.ranobe-prose p').first().waitFor();
 await local.getByRole('button',{name:'Слушать главу'}).click();
 const consent=local.getByRole('button',{name:'Загрузить и слушать'});
 if(await consent.isVisible().catch(()=>false))await consent.click();
 await local.waitForSelector('.ranobe-prose p.is-speaking',{timeout:240000});
 await local.getByRole('button',{name:'Пауза озвучки'}).click();
 await local.getByRole('button',{name:'Сохранить главу аудиокнигой'}).click();
 const localPanel=local.getByRole('region',{name:'Аудиокнига из главы'});
 assert.match(await localPanel.innerText(),/озвучит Supertonic на этом устройстве/);
 const [file]=await Promise.all([local.waitForEvent('download',{timeout:240000}),localPanel.getByRole('button',{name:'Сохранить файл'}).click()]);
 const data=fs.readFileSync(await file.path());
 const localSeconds=await local.evaluate(async encoded=>{const ctx=new OfflineAudioContext(1,1,48000);const buffer=await ctx.decodeAudioData(Uint8Array.from(atob(encoded),c=>c.charCodeAt(0)).buffer);
  let peak=0;const samples=buffer.getChannelData(0);for(let i=0;i<samples.length;i+=7)peak=Math.max(peak,Math.abs(samples[i]));return {duration:buffer.duration,peak};},data.toString('base64'));
 assert.ok(localSeconds.duration>3&&localSeconds.peak>.05,'Supertonic audiobook has speech: '+JSON.stringify(localSeconds));
 assert.deepEqual(errors,[]);
 console.log('Audiobook (Supertonic): OK ('+file.suggestedFilename()+', '+localSeconds.duration.toFixed(1)+' s, real on-device inference).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
