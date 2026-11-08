// Real ML inference: narration of a local TXT book in BookReader (Ukrainian text).
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),MODELS=process.env.TTS_MODEL_DIR||path.resolve(ROOT,'../../benchmark/tts-2026-11-08/models');
let browser,vite;
(async()=>{
 if(!fs.existsSync(path.join(MODELS,'q4/onnx/vocoder.onnx'))){console.log('Skipped: local model copy not found');return;}
 fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/book-narration.html'),'<!doctype html><html lang="ru" data-blossom><meta charset="utf-8"><div id="root"></div><script type="module" src="/tests/book-narration-harness.jsx"></script></html>');
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 const url='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/book-narration.html';
 browser=await chromium.launch({headless:true,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const page=await (await browser.newContext({viewport:{width:1000,height:800},serviceWorkers:'block'})).newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://huggingface.co/**',route=>{const a=new URL(route.request().url()).pathname,f=decodeURIComponent(a.split('/resolve/')[1].split('/').slice(1).join('/'));route.fulfill({status:200,body:fs.readFileSync(path.join(MODELS,a.startsWith('/Supertone/')?'fp32':'q4',f)),headers:{'Access-Control-Allow-Origin':'*'}});});
 for(let i=0;i<3;i++){try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:180000});await page.getByRole('button',{name:'Слушать главу'}).waitFor({timeout:120000});break;}catch(e){if(i===2)throw e;await page.waitForTimeout(3000);}}
 await page.getByRole('button',{name:'Слушать главу'}).click();
 await page.waitForSelector('.reader-prose p.is-speaking',{timeout:240000});
 await page.getByRole('button',{name:'Роли и голоса'}).click();
 const cast=await page.locator('.narration-cast li').allInnerTexts();
 assert.ok(cast.some(t=>t.includes('Оксана'))&&cast.some(t=>t.includes('Тарас')),'speakers: '+cast.join(' | '));
 await page.waitForSelector('.reader-prose p.is-speaking:nth-child(3)',{timeout:240000});
 assert.ok(await page.locator('.reader-prose .role-name').count()>=2,'speaker names drawn in the text');
 console.log('TXT book narration: OK (real Supertonic inference, Ukrainian heuristic roles).');
 // PDF (text layer via pdf.js) and EPUB (current chapter in the epub.js iframe).
 const lines=['Вітер приніс запах дощу, а десь удалині глухо прогримів грім.','— Ти знову запізнився, — невдоволено сказала Оксана.','— Пробач, я заблукав, — винувато відповів Тарас.'];
 const maker=await browser.newPage();
 await maker.setContent('<html><body style="font:18px serif;padding:40px">'+lines.map(l=>'<p>'+l+'</p>').join('')+'</body></html>');
 fs.writeFileSync(path.join(ROOT,'test-output/book-fixture.pdf'),await maker.pdf({format:'A5'}));await maker.close();
 const JSZip=require('jszip'),zip=new JSZip();
 zip.file('mimetype','application/epub+zip',{compression:'STORE'});
 zip.file('META-INF/container.xml','<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>');
 zip.file('OEBPS/content.opf','<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">mv-test</dc:identifier><dc:title>Оповідання</dc:title><dc:language>uk</dc:language></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>');
 zip.file('OEBPS/nav.xhtml','<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="c1.xhtml">Розділ перший</a></li></ol></nav></body></html>');
 zip.file('OEBPS/c1.xhtml','<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>1</title></head><body><h1>Розділ перший</h1>'+lines.map(l=>'<p>'+l+'</p>').join('')+'</body></html>');
 fs.writeFileSync(path.join(ROOT,'test-output/book-fixture.epub'),await zip.generateAsync({type:'nodebuffer'}));
 for(const format of ['pdf','epub']){
  await page.goto(url+'?format='+format,{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Слушать главу'}).waitFor({timeout:120000});
  assert.equal(await page.locator('.reader-listen').count(),1,'top-bar listen control');
  await page.getByRole('button',{name:'Слушать главу'}).click();
  await page.waitForFunction(()=>/Оксана|Вітер|Тарас/.test(document.querySelector('.narration-caption')?.textContent||''),null,{timeout:240000});
  await page.getByRole('button',{name:'Роли и голоса'}).click();
  const roles=await page.locator('.narration-cast li').allInnerTexts();
  assert.ok(roles.some(t=>t.includes('Оксана'))&&roles.some(t=>t.includes('Тарас')),format+' speakers: '+roles.join(' | '));
  if(format==='epub'){
   await page.waitForFunction(()=>[...document.querySelectorAll('.reader-epub iframe')].some(f=>f.contentDocument?.querySelector('.mv-speaking')),null,{timeout:120000});
  }
  await page.screenshot({path:path.join(ROOT,'test-output/book-'+format+'-narration.png')});
  console.log(format.toUpperCase()+' book narration: OK (real Supertonic inference, text from the '+(format==='pdf'?'pdf.js text layer':'epub.js chapter')+').');
 }
 assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
