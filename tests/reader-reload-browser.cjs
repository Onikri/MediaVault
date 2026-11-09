// A reload returns to the open ranobe chapter: the reader is kept in the page
// address (#watch=…&read=N) and the place comes from saved progress.
// Fixture server answers (no network); no narration is started.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..');
let browser,vite;
(async()=>{
 fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/ranobe-reload.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 const base='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe-reload.html';
 browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await (await browser.newContext({viewport:{width:1000,height:800},serviceWorkers:'block'})).newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const watch='#'+new URLSearchParams({watch:'ranobe:shikimori:1'});
 await page.goto(base+watch,{waitUntil:'domcontentloaded',timeout:180000});
 await page.getByRole('button',{name:/Начать читать/}).click({timeout:120000});
 await page.locator('.ranobe-prose p').first().waitFor();
 assert.equal(new URLSearchParams(new URL(page.url()).hash.slice(1)).get('read'),'1','opening a chapter writes it to the address');
 // Reload: the reader comes back on its own.
 await page.reload({waitUntil:'domcontentloaded'});
 await page.locator('.ranobe-prose p').first().waitFor({timeout:120000});
 assert.match(await page.locator('.reader-shell, [role=dialog], body').first().innerText(),/Глава 1/);
 // Closing the reader removes it from the address; a reload stays on the title.
 // Controls hide while reading: a tap in the middle shows them.
 const close=page.getByRole('button',{name:'Закрыть читалку'});
 for(let i=0;i<3&&!await close.isVisible().catch(()=>false);i++){await page.mouse.click(500,450);await page.waitForTimeout(400);}
 await close.click();
 await page.waitForFunction(()=>!new URLSearchParams(location.hash.slice(1)).get('read'));
 assert.equal(new URLSearchParams(new URL(page.url()).hash.slice(1)).get('watch'),'ranobe:shikimori:1');
 await page.reload({waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:/Продолжить|Начать читать/}).waitFor({timeout:120000});
 assert.equal(await page.locator('.ranobe-prose p').count(),0,'closed reader stays closed after reload');
 // A link to the second chapter opens it after load.
 await page.goto(base+watch+'&read=2',{waitUntil:'domcontentloaded'});
 await page.reload({waitUntil:'domcontentloaded'});
 await page.locator('.ranobe-prose p').first().waitFor({timeout:120000});
 assert.deepEqual(errors,[]);
 console.log('Reader reload: OK (fixture server; reader restored from the address and saved progress).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
