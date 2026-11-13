// Neutral private-editor contract. No Oracle, source pages, credentials or ML.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'.codex-local/test-output/content-management');let vite,browser;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'index.html'),'<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="/tests/content-management-harness.jsx"></script></html>');
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0,hmr:false}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of [375,900,1440]){
  const page=await browser.newPage({viewport:{width,height:1000},reducedMotion:'reduce'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://**',r=>r.fulfill({json:{}}));await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/content-management/index.html');
  await page.getByRole('heading',{name:'Управление контентом',exact:true}).waitFor();
  await page.getByLabel('Добавить названия из облака тегов').fill('Ecology\nМир океана');
  await page.getByRole('button',{name:'Добавить в справочник',exact:true}).click();
  await page.locator('.content-rule-list').getByRole('button',{name:/Ecology/}).click();
  await page.getByLabel('Отображаемое название',{exact:true}).fill('Экология');
  await page.getByRole('tab',{name:'Исключения',exact:true}).click();
  await page.getByRole('button',{name:'Удалить Hidden phrase',exact:true}).click();
  await page.getByRole('button',{name:'Сохранить и переиндексировать',exact:true}).click();
  await page.getByRole('status').filter({hasText:/Сохранено на Oracle/}).waitFor();
  const saved=await page.evaluate(()=>window.__savedContent);assert.deepEqual(saved.excludedTerms,[]);assert.equal(saved.tags.find(row=>row.key==='ecology').label,'Экология');
  await page.getByRole('tab',{name:'Теги и жанры',exact:true}).click();
  await page.locator('.content-rule-list').getByRole('button',{name:/Путешествие/}).click();
  await page.getByRole('button',{name:'Удалить тег из каталога',exact:true}).click();
  await page.getByRole('button',{name:'Отменить изменения',exact:true}).click();
  assert.ok(await page.locator('.content-rule-list').getByRole('button',{name:/Путешествие/}).count());
  await page.getByRole('tab',{name:'Источники и совпадения',exact:true}).click();
  await page.getByRole('button',{name:'Проверить источники',exact:true}).click();
  await page.getByText('Fixture',{exact:true}).waitFor();
  await page.getByText(/6 тайтлов/).waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Editor fits '+width);
  await page.screenshot({path:path.join(DIR,'sources-'+width+'.png'),fullPage:true});
  await page.getByRole('tab',{name:'Теги и жанры',exact:true}).click();await page.screenshot({path:path.join(DIR,'editor-'+width+'.png'),fullPage:true});
  await page.evaluate(()=>window.__guest());await page.getByText('Профиль читателя',{exact:true}).waitFor();
  assert.equal(await page.locator('.cc-nav').getByRole('button',{name:'Управление контентом',exact:true}).count(),0);
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS private graphical editor: bulk paste, rename, exclusions, save, undo, source matches, guest isolation and three responsive widths');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
