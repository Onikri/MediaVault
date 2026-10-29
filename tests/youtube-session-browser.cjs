// Session text and API are fixtures. Exercise file selection, verification and deletion.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),DIR=path.join(ROOT,'test-output');let browser,vite;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'youtube-session.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/youtube-session.jsx"></script></html>');
 await fs.writeFile(path.join(DIR,'youtube-session.jsx'),`
 import React from'react';import{createRoot}from'react-dom/client';import YouTubeServerSession from'/src/YouTubeServerSession.jsx';import'/src/styles.css';import'/src/music-dock.css';
 const service={status:'connected',server:location.origin,request:async(p,o={})=>{const r=await fetch(p,{method:o.method||'GET',headers:{'Content-Type':'application/json'},body:o.body?JSON.stringify(o.body):undefined,signal:o.signal});const d=await r.json();if(!r.ok)throw Error(d.detail);return d;}};
 createRoot(document.getElementById('root')).render(<YouTubeServerSession enabled service={service}/>);`);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));let configured=false,uploads=0,closed=0,failed=false;
  const fixture='# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tfixture-owner-session\n';
  await page.route('**/music/youtube/session',async r=>{const method=r.request().method();if(method==='PUT'){uploads++;assert.equal(r.request().postDataJSON().cookies,fixture);configured=true;}if(method==='DELETE')configured=false;await r.fulfill({json:{configured,updated:configured?1:null}});});
  await page.route('**/music/play',async r=>{assert.equal(r.request().postDataJSON().url,'https://www.youtube.com/watch?v=tRwHpyOq4P4');await r.fulfill(failed?{status:502,json:{detail:'Fixture session expired'}}:{json:{id:'a'.repeat(43),streamUrl:'/online/fixture',mime:'audio/mp4'}});});
  await page.route('**/online/**',r=>{assert.equal(r.request().method(),'DELETE');closed++;return r.fulfill({json:{closed:true}});});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/youtube-session.html');await page.getByText('Серверная сессия не подключена',{exact:true}).waitFor();
  await page.getByLabel('Файл серверной сессии YouTube',{exact:true}).setInputFiles({name:'cookies.txt',mimeType:'text/plain',buffer:Buffer.from(fixture)});await page.getByText('Oracle получил аудиопоток Otonoke. Можно запускать музыку в мини-плеере.',{exact:true}).waitFor();assert.equal(uploads,1);assert.equal(closed,1);assert.equal(await page.getByLabel('Файл серверной сессии YouTube',{exact:true}).inputValue(),'');
  failed=true;await page.getByRole('button',{name:'Проверить Otonoke на Oracle',exact:true}).click();await page.getByText('Fixture session expired',{exact:true}).waitFor();assert.equal(await page.locator('iframe').count(),0);
  await page.getByRole('button',{name:'Удалить серверную сессию',exact:true}).click();await page.getByText('Сессия YouTube удалена с Oracle.',{exact:true}).waitFor();assert.equal(configured,false);assert.ok(await page.evaluate(()=>Object.values(localStorage).every(v=>!v.includes('fixture-owner-session'))));assert.deepEqual(errors,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.close();console.log('PASS owner session file upload, Oracle verification, safe error and deletion at '+width+'px');
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const name of ['youtube-session.html','youtube-session.jsx'])await fs.rm(path.join(DIR,name),{force:true});});
