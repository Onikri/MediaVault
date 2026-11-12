// Text reader layout and background listening in Chromium.
// MOCKED: the server, its audio (a tone, not Gemini speech) and the Google
// bible/roles answers. Checked: the rail never moves under the pointer, no
// subtitles over the text, and the voice keeps reading from the tray while the
// listener leaves the page, pauses, returns and closes.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'.codex-local/test-output/ranobe');
let browser,vite;
(async()=>{
 fs.mkdirSync(OUT,{recursive:true});fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/ranobe.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,hmr:false}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe.html?engine=gemini&tray=1';
 browser=await chromium.launch({headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const page=await (await browser.newContext({viewport:{width:1280,height:820},serviceWorkers:'block'})).newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});
 await page.getByRole('button',{name:/Начать читать/}).click({timeout:120000});
 await page.locator('.ranobe-prose p').first().waitFor();
 // Layout: one rail on the right; the player is in it; no subtitles.
 // The reader is embedded in the title page's stage: its rail sits on the reader's right edge.
 const box=await page.locator('.reader-rail').boundingBox(),reader=await page.locator('.ranobe-reader').boundingBox();assert.ok(box.x>reader.x+reader.width-90,'rail on the reader right edge: '+box.x);
 await page.waitForSelector('.ranobe-prose .role-name i',{timeout:60000});
 await page.getByRole('button',{name:'Слушать главу'}).click();
 await page.waitForSelector('.ranobe-prose p.is-speaking',{timeout:30000});
 assert.equal(await page.locator('.narration-caption').count(),0,'no subtitles over the text');
 assert.equal(await page.locator('.reader-rail .narration-main').count(),1,'player inside the rail');
 const prose=await page.locator('.ranobe-prose').boundingBox();assert.ok(prose.width>=760,'wide column: '+prose.width);
 // Aim at pause from below and around: nothing appears, nothing moves.
 const play=page.getByRole('button',{name:'Пауза озвучки'}),before=await play.boundingBox();
 for(const [x,y] of [[640,815],[640,790],[1250,815],[before.x+20,before.y+60],[before.x+20,before.y+22]])await page.mouse.move(x,y,{steps:4});
 await page.waitForTimeout(500);
 assert.deepEqual(await play.boundingBox(),before,'pause button stays where it was');
 assert.equal(await page.locator('.reader-bottom-float,.reader-page-track').count(),0,'no chapter slider pops up');
 // Minimize: the reader leaves the screen, the voice keeps reading.
 await page.getByRole('button',{name:'Свернуть читалку'}).click();
 await page.waitForFunction(()=>document.querySelector('.retained-media-host')?.dataset.mode==='hidden');
 const n1=await page.evaluate(()=>window.speak.length);
 await page.getByRole('button',{name:'Другая страница'}).click();
 await page.locator('.fixture-other').waitFor();
 await page.waitForFunction(n=>window.speak.length>n,n1,{timeout:30000});
 // The tray: pause, return to the same chapter, close.
 await page.getByRole('button',{name:'Плеер в фоне'}).click();
 const panel=page.getByRole('dialog',{name:'Сейчас в фоне'});
 await panel.getByText('Читает голос').waitFor();
 await panel.getByRole('button',{name:'Пауза'}).click();
 await panel.getByText('Озвучка на паузе').waitFor({timeout:10000});
 await panel.getByRole('button',{name:'Вернуться к чтению'}).click();
 await page.waitForFunction(()=>document.querySelector('.retained-media-host')?.dataset.mode==='attached',null,{timeout:30000});
 assert.match(await page.locator('.reader-prose-head').innerText(),/Глава \d/);
 assert.ok(await page.getByRole('button',{name:'Продолжить озвучку'}).isVisible(),'the same paused voice session is back');
 await page.screenshot({path:path.join(OUT,'reader-tray-return.png')});
 await page.locator('.reader-rail').getByRole('button',{name:'Закрыть читалку'}).click();
 await page.waitForFunction(()=>!document.querySelector('.retained-media-host .text-reader'),null,{timeout:10000});
 assert.deepEqual(errors,[]);
 console.log('Reader rail and tray: OK (fixture server; MOCKED tone instead of Gemini audio; MOCKED Google bible/roles answers).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
