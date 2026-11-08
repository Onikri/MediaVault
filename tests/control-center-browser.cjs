// Owner control center in a real browser with fixture server answers
// (tests/control-center-harness.jsx). No account, VM, media or ML inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),dir=path.join(ROOT,'.codex-local/test-output/control-center');let browser,vite;
(async()=>{
 await fs.mkdir(dir,{recursive:true});await fs.mkdir(path.join(ROOT,'test-output'),{recursive:true});
 await fs.writeFile(path.join(ROOT,'test-output/control-center.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/control-center-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 const base='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/control-center.html';
 browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),args:['--no-sandbox']});
 for(const width of [375,900,1440]){
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',serviceWorkers:'block'});context.setDefaultTimeout(15000);
  await context.addInitScript(()=>{try{localStorage.setItem('mediavault_privacy_v1',JSON.stringify({version:1,chosen:true,remember:false}));}catch{}});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const fits=async name=>assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' fits '+width);
  const nav=label=>page.locator('.cc-nav').getByRole('button',{name:label});
  await page.goto(base);await page.locator('.cc-air').first().waitFor();await page.evaluate(()=>document.fonts.ready);
  // Overview: rooms and a watching guest share one live board; rail counters agree with it.
  assert.equal(await page.locator('.cc-air.is-room').count(),2);
  assert.match(await page.locator('.cc-air.is-guest').innerText(),/Аня[\s\S]*Магическая битва/);
  assert.equal(await nav('Комнаты').locator('.cc-count').innerText(),'2');
  assert.equal(await page.locator('.cc-health-item').count(),5);
  const before=await page.locator('.cc-air.is-room [role=progressbar]').first().getAttribute('aria-valuenow');
  await page.waitForTimeout(2100);
  assert.ok(Number(await page.locator('.cc-air.is-room [role=progressbar]').first().getAttribute('aria-valuenow'))>Number(before),'Playing room timeline advances between polls');
  await fits('Overview');await page.screenshot({path:path.join(dir,'overview-'+width+'.png'),fullPage:true});
  // Rooms: closing asks once inline, calls the server and removes the room.
  await nav('Комнаты').click();await page.locator('.cc-room').first().waitFor();await fits('Rooms');
  await page.screenshot({path:path.join(dir,'rooms-'+width+'.png'),fullPage:true});
  const second=page.locator('.cc-room').nth(1);
  await second.getByRole('button',{name:'Закрыть комнату'}).click();
  await second.getByRole('button',{name:'Закрыть',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.cc-room').length===1);
  assert.ok((await page.evaluate(()=>window.__controlCalls)).includes('DELETE /rooms/room-two'));
  assert.equal(await nav('Комнаты').locator('.cc-count').innerText(),'1');
  // Guests: create gives an invite link; detail tabs show activity and access.
  await nav('Гости').click();await page.locator('.cc-guest-list').waitFor();
  await page.getByPlaceholder('Например, Аня').fill('Женя');await page.getByRole('button',{name:'Пригласить'}).click();
  await page.locator('.cc-invite').waitFor();assert.match(await page.locator('.cc-guest-head h2').innerText(),/Женя/);
  if(width<1000){await page.getByRole('button',{name:'Все гости'}).click();}
  await page.locator('.cc-guest-list').getByRole('button',{name:/Аня/}).click();
  await page.locator('.guest-stats').waitFor();await fits('Guest detail');
  await page.getByRole('tab',{name:/Журнал/}).click();await page.getByText('Попытка открыть закрытый тайтл').waitFor();
  await page.getByRole('tab',{name:/Доступ/}).click();await page.locator('.guest-access-editor').waitFor();
  await page.screenshot({path:path.join(dir,'guests-'+width+'.png'),fullPage:true});
  // Rules: edits are marked, saved with one PUT and confirmed.
  await nav('Правила').click();await page.locator('.cc-rule').first().waitFor();
  await page.locator('#rule-members').fill('12');await page.locator('.cc-rule.is-changed').waitFor();
  await page.getByRole('button',{name:'Сохранить правила'}).click();await page.getByText('Правила сохранены и уже действуют').waitFor();
  assert.equal(await page.evaluate(()=>window.__controlCalls.filter(c=>c==='PUT /admin/rules').length),1);
  await fits('Rules');await page.screenshot({path:path.join(dir,'rules-'+width+'.png'),fullPage:true});
  await nav('Задачи').click();await page.locator('.import-queue').waitFor();await fits('Tasks');
  assert.equal(await page.locator('.cc-rail .cc-who').isVisible(),width>860,'Identity block only on the wide rail');
  assert.deepEqual(errors,[],'No page errors at '+width);
  await context.close();
 }
 console.log('control center browser contract passed');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
