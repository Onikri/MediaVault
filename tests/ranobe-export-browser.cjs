// The ranobe save window offers only what works and sends what the VM needs.
// MOCKED: Google bible/roles answers are fixtures and /reader/google/speak
// streams a tone instead of Gemini speech (tests/ranobe-export-harness.jsx).
// Real: the reader's director code, the cast, WebCodecs Opus and Ogg files.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..');
let browser,vite;
(async()=>{
 fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/ranobe-export.html'),'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/tests/ranobe-export-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const base='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/ranobe-export.html?';
 async function open(query){
  const context=await browser.newContext({viewport:{width:500,height:900},serviceWorkers:'block',acceptDownloads:true});context.setDefaultTimeout(60000);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+query,{waitUntil:'domcontentloaded',timeout:180000});
  await page.getByRole('button',{name:/Сохранить/}).waitFor();
  return {context,page,errors};
 }
 const choice=page=>page.getByRole('radiogroup',{name:'Что сохранить'});

 // 1. A server without the VM director: Drive offers text only.
 {const {context,page,errors}=await open('destination=drive');
  assert.equal(await choice(page).count(),0);assert.deepEqual(errors,[]);await context.close();}
 // 2. Not Russian/Ukrainian: no audiobook anywhere.
 {const {context,page}=await open('destination=local&language=en&version=71');
  assert.equal(await choice(page).count(),0);await page.getByText('Аудиокнига озвучивается для русского и украинского текста.').waitFor();await context.close();}
 // 3. Drive with the VM director: text + audio job carries the reader's voicing.
 {const {context,page,errors}=await open('destination=drive&audio=1');
  assert.deepEqual(await choice(page).getByRole('radio').allInnerTexts(),['Текст','Аудиокнига','Текст и аудио']);
  await page.evaluate(()=>localStorage.setItem('mediavault_tts_prefs_v2',JSON.stringify({geminiNarrator:'Schedar',pace:1.1,rolesModel:'gemma-4-31b-it'})));
  await page.evaluate(()=>localStorage.setItem('mediavault_tts_gemini_cast_v1:https://ranobehub.org/ranobe/206',JSON.stringify({'Мирэй':{voice:'Leda',note:'резко'}})));
  await choice(page).getByRole('radio',{name:'Текст и аудио'}).click();
  await page.getByRole('button',{name:'Сохранить в Google Диск'}).click();
  await page.getByText(/озвучит главы голосами из читалки/).waitFor();
  const [job]=await page.evaluate(()=>window.submitted);
  assert.equal(job.output,'both');assert.equal(job.section,'ranobe');assert.equal(job.entries.length,2);
  assert.deepEqual(job.voice.prefs,{geminiNarrator:'Schedar',narrator:'auto',pace:1.1,roles:true,rolesModel:'gemma-4-31b-it',bibleModel:'gemini-3.5-flash-lite'});
  assert.equal(job.voice.language,'ru');assert.deepEqual(job.voice.saved,{'Мирэй':{voice:'Leda',note:'резко'}});
  assert.deepEqual(errors,[]);await context.close();}
 // 4. Device: one audiobook file per chapter, voiced like the reader (narrator + each hero's own voice).
 {const {context,page,errors}=await open('destination=local&version=71');
  await choice(page).getByRole('radio',{name:'Аудиокнига'}).click();
  assert.equal(await page.getByRole('radiogroup',{name:'Формат файла'}).count(),0,'no text format for audio only');
  const downloads=[];page.on('download',d=>downloads.push(d));
  await page.getByRole('button',{name:'Сохранить на устройство'}).click();
  await page.getByText(/Аудиокнига: 2 файла передано браузеру/).waitFor({timeout:120000});
  assert.deepEqual(downloads.map(d=>d.suggestedFilename()).sort(),['Повелитель — Глава 1.opus','Повелитель — Глава 2.opus']);
  for(const download of downloads){const bytes=fs.readFileSync(await download.path());assert.equal(bytes.subarray(0,4).toString(),'OggS');assert.ok(bytes.subarray(0,400).toString('utf8').includes('ALBUM=Повелитель'));}
  const speak=await page.evaluate(()=>window.speak);
  const voiceOf=text=>[...new Set(speak.filter(b=>b.text.includes(text)).map(b=>b.voice))];
  assert.deepEqual(voiceOf('Ночь опустилась'),['Charon'],'narrator');
  assert.deepEqual(voiceOf('опять опоздал'),['Zephyr'],'Мирэй');
  assert.deepEqual(voiceOf('заблудился'),['Achird'],'Кайто');
  assert.ok(speak.every(b=>b.language==='ru'&&b.style));
  assert.deepEqual(errors,[]);await context.close();}
 console.log('PASS ranobe save window: options gated by server and language; Drive job carries reader voicing; device saves one multi-voice Opus file per chapter (MOCKED Google)');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
