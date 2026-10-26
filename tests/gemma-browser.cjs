// Browser/API contracts use fixtures; Canvas/font rendering is real. ML is
// measured separately by the private production-pipeline smoke and Oracle runs.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let vite,browser;
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'test-output');await fs.mkdir(out,{recursive:true});
 await fs.writeFile(path.join(out,'gemma.html'),'<html><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><canvas id="styles" width="1000" height="1000" style="max-width:100%;height:auto"></canvas><script type="module" src="/test-output/gemma.jsx"></script></html>');
 await fs.writeFile(path.join(out,'gemma.jsx'),`
 import React from 'react';import{createRoot}from'react-dom/client';import JSZip from'jszip';import MangaReader from'/src/MangaReader.jsx';import{drawStyledRegion}from'/lmt/typography.js';
 const zip=new JSZip();for(let i=0;i<5;i++){const c=document.createElement('canvas');c.width=600;c.height=800;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,600,800);x.fillStyle='black';x.fillText('Fixture page '+i,100,150);zip.file(i+'.png',c.toDataURL('image/png').split(',')[1],{base64:true});}const chapter=await zip.generateAsync({type:'blob'});
 window.requests=[];const data=new Map();
 const appearance={bold:false,italic:false,fill_color:'#000000',stroke_color:'none',stroke_width:0,alignment:'center',rotation:0};
 const service={status:'connected',server:'https://gemma-fixture.example',request:async(p,o={})=>{
  if(p==='/reader/lmt/gemma/jobs'){window.requests.push(o.body);const id='j'+window.requests.length;data.set(id,o.body);return{id};}
  if(p.endsWith('/cancel'))return{};
  const input=data.get(p.split('/').at(-1));return{state:'done',result:{pages:input.pages.map(p=>({...p,regions:p.regions.map(r=>({...r,status:'translated',translation:'Полная русская реплика.',font_style:'standard_comic',speech_style:'neutral_conversational',text_category:'dialogue',speaker_gender:'unknown',connected_to_id:null,appearance}))})),cloudMs:10,usage:[]}};
 }};
 const item={id:'gemma-chapter',name:'Gemma contract fixture',category:'manga',collectionId:'gemma-title',translationInfo:{language:'en'}};
 createRoot(document.getElementById('root')).render(<MangaReader inline retainLmt item={item} catalog={{items:[item]}} userId="gemma-test" libraryId="gemma-fixture" readWhole={async()=>chapter} readerService={service} onClose={()=>{}}/>);
 const c=document.getElementById('styles'),ctx=c.getContext('2d');ctx.fillStyle='#dad6c7';ctx.fillRect(0,0,1000,1000);window.fontLayouts=[];
 for(const[i,style]of['standard_comic','bold_scream','handwritten_sloppy','serif_serious','digital_box','sfx_art'].entries())window.fontLayouts.push(await drawStyledRegion(ctx,{id:'style-'+i,bbox:[35,20+i*160,965,160+i*160],translation:'Ёжик, ты в порядке? Не открывай дверь!',font_style:style,speech_style:'neutral_conversational',appearance:{...appearance,bold:style==='bold_scream',italic:style==='sfx_art',fill_color:i===2?'#ffffff':'#151515',stroke_color:i===2?'#000000':'none',stroke_width:i===2?2:0,rotation:style==='sfx_art'?-8:0}}));window.fontsDone=true;
 `);
 const{createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 for(const width of[390,1366]){
  const context=await browser.newContext({viewport:{width,height:950}}),page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('mv_lmt_settings:gemma-test',JSON.stringify({version:6,engine:'gemma',language:'English',font:'auto',inpaint:'quality',allowDownloads:true,prefetch:4,gemmaPromptVersion:'fixture'})));
  await context.route('https://gemma-fixture.example/**',r=>r.fulfill({headers:{'access-control-allow-origin':'*'},json:{ready:true,gemma:{ready:true,promptVersion:'fixture'}}}));
  await context.route('**/lmt/index.html',r=>r.fulfill({contentType:'text/html',body:'<script>addEventListener("message",e=>{if(e.origin!==location.origin||e.source!==parent)return;const p=e.ports[0];p.onmessage=({data})=>{const c=data.config,id="P"+(c.pageIndex+1),regions=[{id:id+"_B1",bbox:[100,100,450,300],class:"text"}];if(c.operation==="gemma-prepare")p.postMessage({id:data.id,result:{id,width:600,height:800,image:btoa("fixture"),mime:"image/png",regions,detectionMs:1}});else{const bytes=data.bytes;p.postMessage({id:data.id,result:{renderedImage:bytes,renderedMime:"image/png",inputMode:"vision",regions:c.translation.regions.map(r=>({...r,x:.1,y:.1,w:.5,h:.3,text:r.translation,original:"",placement:"note"})),warnings:[],inpaint:{unpainted:0}}},[bytes]);}};p.postMessage({ready:true});});<\/script>'}));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/gemma.html');
  await page.waitForFunction(()=>window.fontsDone&&window.requests?.reduce((n,r)=>n+r.pages.length,0)===5);
  const requests=await page.evaluate(()=>window.requests);assert.equal(requests.flatMap(r=>r.pages).length,5);assert.ok(requests.every(r=>r.pages.length<=4));assert.ok(requests.some(r=>r.pages.length>1));
  assert.ok(requests.every(r=>!JSON.stringify(r).includes('sourceText')));assert.equal(await page.locator('.translation-marker').count(),0);
  const layouts=await page.evaluate(()=>window.fontLayouts);assert.deepEqual(layouts.map(r=>r.fontId),['comic-relief','comic-relief','pangolin','serif','mono','neucha']);assert.ok(layouts.every(r=>r.fits&&r.fontSize>10));
  await page.getByLabel('Настройки читалки',{exact:true}).click();assert.equal(await page.getByLabel('Где обрабатывать перевод').inputValue(),'gemma');assert.equal(await page.getByLabel('OCR LMT').count(),0);assert.equal(await page.getByLabel('Шрифт перевода манги').inputValue(),'auto');
  await page.getByLabel('Исходный язык LMT').selectOption('Japanese');assert.equal(await page.getByLabel('OCR LMT').count(),0);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,'gemma-settings-'+width+'.png')});assert.deepEqual(errors,[]);await context.close();
 }
 console.log('PASS Gemma device/API/render contract, batching, no OCR UI, real Cyrillic Canvas styles at mobile and desktop widths; ML quality measured separately');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const f of['gemma.html','gemma.jsx'])await fs.rm(path.resolve(__dirname,'../test-output/'+f),{force:true});});
