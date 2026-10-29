// Real online page loading, detector, cleanup and Canvas typesetting. Google reply
// is a fixture; server credentials are never returned to this browser harness.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),{chromium}=require('playwright');let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'test-output');await fs.mkdir(out,{recursive:true});
 await fs.writeFile(path.join(out,'online-translation.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/online-translation.jsx"></script>');
 await fs.writeFile(path.join(out,'online-translation.jsx'),`
import React from 'react';import{createRoot}from'react-dom/client';import MangaReader from'/src/MangaReader.jsx';import'/src/styles.css';
const c=document.createElement('canvas');c.width=600;c.height=850;const ctx=c.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,600,850);ctx.strokeStyle='#111';ctx.strokeRect(50,80,500,650);ctx.fillStyle='#111';ctx.font='bold 32px sans-serif';ctx.fillText('HELLO MY FRIEND',120,200);ctx.fillText('DO NOT GIVE UP!',120,245);const blob=await new Promise(resolve=>c.toBlob(resolve));window.fixtureURL=URL.createObjectURL(blob);window.requests=[];
const item={id:'online-translation',name:'Online page',onlinePages:[window.fixtureURL],category:'manga',translationInfo:{language:'en'}};
const service={server:'https://online.fixture',status:'connected',session:{serverVersion:30},request:async(path,options={})=>{
 window.requests.push({path,body:options.body});
 if(path==='/reader/google/keys')return{configured:true,keyCount:1,slots:[{slot:0}]};
 if(path==='/reader/google/generate'){
  const text=options.body.request.contents[0].parts.filter(p=>p.text).map(p=>p.text);const ids=text.filter(t=>t.startsWith('P')).flatMap(t=>t.split(': ')[1].split(','));
  return {candidates:[{finishReason:'STOP',content:{parts:[{text:JSON.stringify(ids.map(id=>({id,ru:'Не сдавайся, друг!',f:0,k:0})))}]}}]};
 }
 throw Error('Unexpected endpoint '+path);
}};
createRoot(document.getElementById('root')).render(<MangaReader item={item} catalog={{items:[item]}} userId="online-owner" libraryId="online" readerService={service} onClose={()=>{}}/>);
`);
 const{createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 for(const width of[390,1366]){
  const context=await browser.newContext({viewport:{width,height:950}}),page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>localStorage.setItem('mv_lmt_settings:online-owner',JSON.stringify({version:8,engine:'vm',directDetector:'en-fast',inpaint:'fast',font:'auto',directRenderVersion:2,cache:false})));
  await page.route('https://online.fixture/api/v1/manga-translation/status',route=>route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},json:{ready:true,configured:true,policy:'fixture-online'}}));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/online-translation.html');await page.waitForFunction(()=>document.querySelector('canvas.reader-translated-overlay')?.dataset.ready==='true');
  const calls=await page.evaluate(()=>window.requests);const generation=calls.filter(c=>c.path==='/reader/google/generate');assert.equal(generation.length,1);assert.equal(generation[0].body.slot,0);assert.equal(generation[0].body.key,undefined);assert.equal(generation[0].body.model,'gemini-3.5-flash-lite');assert.ok(!calls.some(c=>c.path==='/api/v1/chapters'));assert.deepEqual(errors,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,'online-translation-'+width+'.png')});await context.close();console.log('PASS online chapter translation with Oracle slot, actual local detector/Canvas and no Drive dependency at '+width);
 }
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
