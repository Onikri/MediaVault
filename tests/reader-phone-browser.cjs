// Text reader ergonomics on a phone and on a keyboard, in Chromium.
// MOCKED: the server, its audio and the Google answers (the ranobe harness).
// Checked: the bottom bar fits a 390 px screen, «⋯» holds what does not fit
// (with names) and its buttons work, settings open in tabs, reader keys (text
// size, the key sheet on «?») work on the desktop.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..');
let browser,vite;
async function openChapter(page,url){
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});
 for(let attempt=0;attempt<2;attempt++){
  const start=await page.evaluate(()=>performance.timeOrigin);
  await page.getByRole('button',{name:/Начать читать/}).click({timeout:120000});
  // A cold Vite server can reload the page once on discovering a lazy
  // dependency. Only retry that navigation, and keep real reader errors visible.
  await page.waitForFunction(start=>performance.timeOrigin!==start||document.querySelector('.ranobe-prose p'),start,{timeout:60000});
  if(await page.locator('.ranobe-prose p').count())return;
 }
 await page.locator('.ranobe-prose p').first().waitFor();
}
(async()=>{
 fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/ranobe.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,hmr:false}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe.html?engine=gemini&tray=1';
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true,args:['--no-sandbox']});
 const errors=[];
 // Phone
 const phone=await (await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true,serviceWorkers:'block'})).newPage();phone.on('pageerror',e=>errors.push(e.message));
 await openChapter(phone,url);
 const overflow=await phone.evaluate(()=>[...document.querySelectorAll('.reader-rail .reader-control,.reader-rail .narration-bar button')].filter(b=>b.getClientRects().length).map(b=>b.getBoundingClientRect().right).filter(r=>r>innerWidth+1));
 assert.deepEqual(overflow,[],'every bar button is on screen');
 await phone.getByRole('button',{name:'Ещё',exact:true}).click();
 const menu=phone.getByRole('menu');await menu.waitFor();
 for(const name of ['Ночной режим','Фоновая музыка','Свернуть читалку','На весь экран'])assert.equal(await menu.getByRole('button',{name,exact:true}).count(),1,name+' in «⋯»');
 const labels=await menu.locator('.reader-control-label').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height));
 assert.ok(labels.every(h=>h<24),'each name on one line: '+labels);
 await menu.getByRole('button',{name:'Ночной режим'}).click();
 await phone.waitForFunction(()=>document.querySelector('.immersive-reader')?.classList.contains('reader-theme-night'));
 await phone.getByRole('menu').waitFor({state:'detached',timeout:3000});// the menu closes after a choice
 await phone.getByRole('button',{name:'Настройки читалки'}).click();
 assert.deepEqual(await phone.getByRole('tab').allTextContents(),['Вид','Чтение','Звук']);
 assert.equal(await phone.getByLabel('Тема ранобэ').inputValue(),'night');
 await phone.getByRole('tab',{name:'Звук'}).click();
 await phone.getByText('Фоновая музыка по сценам').waitFor({timeout:3000});// music lives in the sound tab
 // Desktop keys
 const page=await (await browser.newContext({viewport:{width:1280,height:820},serviceWorkers:'block'})).newPage();page.on('pageerror',e=>errors.push(e.message));
 await openChapter(page,url);
 await page.locator('.ranobe-reader').click({position:{x:300,y:300}});
 const size=()=>page.evaluate(()=>getComputedStyle(document.querySelector('.ranobe-surface')).getPropertyValue('--book-size').trim());
 const before=await size();await page.keyboard.press('Equal');await page.waitForFunction(old=>getComputedStyle(document.querySelector('.ranobe-surface')).getPropertyValue('--book-size').trim()!==old,before);
 assert.equal(await size(),(parseInt(before)+2)+'px','«+» makes the text larger');
 await page.keyboard.press('Shift+Slash');
 const sheet=page.getByRole('dialog',{name:'Клавиши: Читалка ранобэ'});await sheet.waitFor();
 for(const label of ['Следующая глава','Крупнее или мельче текст','Ночной режим','Фоновая музыка по сценам','Полный экран'])assert.equal(await sheet.getByText(label,{exact:true}).count(),1,label+' in the key sheet');
 await page.keyboard.press('Escape');await sheet.waitFor({state:'detached'});
 assert.deepEqual(errors,[],'no page errors');
 console.log('Reader on a phone and keyboard: OK (fixture server; MOCKED Google; no inference).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
