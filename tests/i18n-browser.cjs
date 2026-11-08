// Ukrainian interface switch in a real browser: ControlCenter shell, fixture panels.
// No server, account or ML. Content under translate="no" must stay as written.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),dir=path.join(ROOT,'.codex-local/test-output/i18n');let browser,vite;
(async()=>{
 await fs.mkdir(dir,{recursive:true});await fs.mkdir(path.join(ROOT,'test-output'),{recursive:true});
 await fs.writeFile(path.join(ROOT,'test-output/i18n.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/i18n-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/i18n.html';
 browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1280,height:900},reducedMotion:'reduce',serviceWorkers:'block'});context.setDefaultTimeout(20000);
 await context.addInitScript(()=>{try{localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false}));}catch{}});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});await page.getByRole('radio',{name:'Українська'}).waitFor({timeout:180000});
 assert.equal(await page.evaluate(()=>document.documentElement.lang),'ru');
 await page.getByRole('radio',{name:'Українська'}).click();
 await page.waitForFunction(()=>document.documentElement.lang==='uk');
 await page.getByRole('heading',{name:'Мова інтерфейсу'}).waitFor();
 assert.match(await page.locator('.cc-nav').innerText(),/Оформлення/);
 assert.equal(await page.getByRole('radio',{name:'Русский'}).count(),1,'native language names are not translated');
 await page.screenshot({path:path.join(dir,'uk-appearance.png')});
 await page.getByRole('button',{name:'Профіль'}).click();
 assert.equal(await page.locator('#content').innerText(),'Настройки плеера — название произведения','translate="no" content stays as written');
 await page.reload();await page.getByRole('heading',{name:'Мова інтерфейсу'}).waitFor();
 assert.equal(await page.evaluate(()=>document.documentElement.lang),'uk','choice survives reload');
 await page.locator('.cc-nav').getByRole('button',{name:/Пристрій/}).click();
 assert.equal(await page.locator('#composed').innerText(),'Серія 12');
 await page.locator('.cc-nav').getByRole('button',{name:/Оформлення/}).click();
 await page.getByRole('radio',{name:'Русский'}).click();
 await page.waitForFunction(()=>document.documentElement.lang==='ru');
 await page.getByRole('heading',{name:'Язык интерфейса'}).waitFor();
 assert.match(await page.locator('.cc-nav').innerText(),/Оформление/,'switching back restores Russian');
 assert.deepEqual(errors,[]);
 console.log('Ukrainian interface switch: OK (fixture panels, real ControlCenter shell).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
