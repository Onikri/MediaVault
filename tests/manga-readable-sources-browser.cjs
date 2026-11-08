// Real React/source hook; page-readability API replies are fixtures, not live sites.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
let browser,vite;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/test-output/reader-health'),base='/.codex-local/test-output/reader-health/';await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="'+base+'fixture.jsx"></script>');
 await fs.writeFile(path.join(dir,'fixture.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import Picker from'/src/TitleSourcePicker.jsx';import useInfo from'/src/use-manga-source-info.js';import'/src/styles.css';import'/src/title-page.css';
 const sources=[0,1,2].map(n=>({url:'https://source.example/'+n,title:'Story',providerName:'Reader '+n,language:'en'})),title={id:'story',title:'Story',kind:'manga'};
 window.calls=[];window.active=0;window.peak=0;window.chosen=[];
 const service={server:'https://api.fixture',session:{serverVersion:47},request:async(url,options)=>{window.calls.push(options.body);window.active++;window.peak=Math.max(window.peak,window.active);await new Promise(r=>setTimeout(r,70));window.active--;return{chapterCount:70,volumeCount:4,readable:options.body.url.endsWith('/0'),verifiedPages:options.body.url.endsWith('/0')?1:0,readabilityError:'Images unavailable'};}};
 function Demo(){const info=useInfo(sources,title,service,0);return <main style={{maxWidth:900,padding:16,margin:'auto'}}><Picker requireVerified sources={sources} info={info} onChoose={url=>window.chosen.push(url)}/></main>;}createRoot(document.getElementById('root')).render(<Demo/>);`);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/vite-reader-health',logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of [360,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+base+'index.html');
  await page.getByText('Недоступные источники · 2',{exact:true}).waitFor();assert.equal(await page.locator('.title-source-option').count(),1);
  assert.ok(await page.locator('.title-source-option').innerText().then(t=>t.includes('Reader 0')));assert.ok(await page.evaluate(()=>window.calls.filter(c=>c.verifyPages===true).length===3&&window.calls.filter(c=>c.verifyPages===false).length===2&&window.peak<=2));
  await page.locator('.title-source-option').click();assert.deepEqual(await page.evaluate(()=>window.chosen),['https://source.example/0']);
  await page.getByText('Недоступные источники · 2',{exact:true}).click();assert.equal(await page.getByText('Images unavailable',{exact:false}).count(),2);
  await page.getByRole('button',{name:'Повторить проверку',exact:true}).first().click();assert.deepEqual(await page.evaluate(()=>window.chosen),['https://source.example/0','https://source.example/1']);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);await page.close();console.log('PASS verified reader choices, unavailable diagnostics, explicit retry and bounded checks '+width);
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
