// Real browser detector, native-pixel packing, cleanup and typography.
// Google responses are fixtures; this does not measure neural translation.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'.codex-local','test-output');await fs.mkdir(out,{recursive:true});
 await fs.writeFile(path.join(out,'blocks.html'),'<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/blocks.jsx"></script></html>');
 await fs.writeFile(path.join(out,'blocks.jsx'),`
import React from 'react';import{createRoot}from'react-dom/client';import JSZip from'jszip';import MangaReader from'/src/MangaReader.jsx';import'/src/styles.css';
window.sent=[];const c=document.createElement('canvas');c.width=600;c.height=900;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,600,900);x.fillStyle='black';x.font='bold 25px sans-serif';x.fillText('HELLO MY FRIEND',160,180);x.fillText('PLEASE WAIT HERE',150,215);const seam=new URLSearchParams(location.search).has('seam'),zip=new JSZip();
if(seam){c.height=1800;x.fillStyle='white';x.fillRect(0,0,600,1800);x.fillStyle='black';x.font='bold 25px sans-serif';x.fillText('PLEASE DO',200,887);x.fillText('NOT LEAVE',200,921);for(let i=0;i<2;i++){const cut=document.createElement('canvas');cut.width=600;cut.height=900;cut.getContext('2d').drawImage(c,0,i*900,600,900,0,0,600,900);zip.file((i+1)+'.png',await new Promise(r=>cut.toBlob(r,'image/png')));}}
else{const blob=await new Promise(r=>c.toBlob(r,'image/png'));for(let i=1;i<=6;i++)zip.file(i+'.png',blob);}const chapter=await zip.generateAsync({type:'blob'});
const service={server:'https://fixture.example',status:'connected',request:async(p,o={})=>{if(p==='/reader/google/diagnostics')return{keys:[],jobs:[],egressIP:'192.0.2.1'};if(p==='/reader/google/keys')return{slots:[{slot:0}]};if(p==='/reader/google/generate'){window.sent.push(o.body);const rows=o.body.request.contents[0].parts.filter(p=>p.text?.startsWith('{')).flatMap(p=>JSON.parse(p.text).regions.map(r=>({id:r.id,ru:'Подожди меня здесь!',f:0,k:0})));return{candidates:[{finishReason:'STOP',content:{parts:[{text:JSON.stringify(rows)}]}}]};}throw Error('Unexpected fixture route '+p);}};
const item={id:'blocks-chapter',name:'Проверка блоков',category:'manga',collectionId:'title',translationInfo:{language:'en'},metadata:{format:new URLSearchParams(location.search).get('webtoon')?'manhwa':'manga'}};
createRoot(document.getElementById('root')).render(<MangaReader item={item} catalog={{items:[item]}} userId="blocks-browser" libraryId="fixture" readWhole={async()=>chapter} readerService={service} onClose={()=>{}}/>);
`);
 const{createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/blocks-browser-vite',logLevel:'error',server:{host:'127.0.0.1',port:0,strictPort:false}});await vite.listen();
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
 for(const width of[390,1366])for(const scenario of['manga','webtoon','seam']){
  const webtoon=scenario!=='manga',seam=scenario==='seam';
  const context=await browser.newContext({viewport:{width,height:950}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{window.renderedRecords=[];const NativeWorker=window.Worker;window.Worker=class extends NativeWorker{constructor(...args){super(...args);this.addEventListener('message',e=>{if(e.data.result?.typesetting)window.renderedRecords.push(e.data.result.typesetting);});}};localStorage.setItem('mv_lmt_settings:blocks-browser',JSON.stringify({version:9,engine:'vm',directInput:'blocks',directModel:'gemini-3.5-flash-lite',inpaint:'fast',font:'auto',cache:true}));for(const profile of['manga','webtoon'])localStorage.setItem('mediavault_reader_v3:blocks-browser:'+profile,JSON.stringify({translate:true,diagnostics:true,mode:profile==='webtoon'?'scroll':'pages',fit:'width',direction:profile==='webtoon'?'ltr':'rtl',preload:0}));});
  await page.route('https://fixture.example/**',r=>r.fulfill({json:{ready:true,configured:true,policy:'fixture-policy'},headers:{'access-control-allow-origin':'*'}}));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/blocks.html'+(webtoon?'?webtoon=1'+(seam?'&seam=1':''):''));
  await page.waitForFunction(()=>document.querySelector('[data-page="0"] canvas.reader-translated-overlay')?.dataset.ready==='true',{timeout:45000});
  const sent=await page.evaluate(()=>window.sent);assert.equal(sent.length,1);const parts=sent[0].request.contents[0].parts;
  assert.equal(parts.filter(p=>p.inlineData).length,1,'six original pages share one sheet image');
  const mapping=JSON.parse(parts.find(p=>p.text?.startsWith('{')).text);assert.equal(mapping.regions.length,seam?1:6);assert.ok(mapping.regions.every(r=>/^P[1-6]_B1$/.test(r.id)));if(seam){await page.waitForFunction(()=>window.renderedRecords.length>=2);const layouts=await page.evaluate(()=>window.renderedRecords.map(r=>r.layouts[0]));assert.ok(layouts.every(Boolean));assert.equal(layouts[0].fontSize,layouts[1].fontSize,'joined paragraph uses the same layout across the seam');}assert.ok(mapping.originalWidth>=600);
  const image=await page.locator('[data-page="0"] .reader-image-stack>img').first().boundingBox();assert.ok(image.width<=Math.min(width,600)+1,'intrinsic width never enlarges source');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  // Observer movement during repaint must keep the source URL stable.
  const source=await page.locator('[data-page="0"] .reader-image-stack>img').first().getAttribute('src');
  if(webtoon&&!seam){await page.locator('.reader-content').evaluate(el=>el.scrollTop=1000);await page.waitForTimeout(150);await page.locator('.reader-content').evaluate(el=>el.scrollTop=0);assert.equal(await page.locator('[data-page="0"] .reader-image-stack>img').first().getAttribute('src'),source);}
  await require('./reader-controls.cjs').revealReader(page);
  const debugButton=page.getByRole('button',{name:'Отладка страницы',exact:true});
  await debugButton.click();await page.locator('.reader-debug-panel').waitFor();assert.match(await page.locator('.reader-debug-body').innerText(),/област/);
  await page.getByRole('tab',{name:'Запрос',exact:true}).click();assert.ok(await page.locator('.reader-debug-panel').innerText().then(s=>s.includes('Запрос Google')));
  await page.screenshot({path:path.join(out,'blocks-'+scenario+'-'+width+'.png')});assert.deepEqual(errors,[]);await context.close();
  console.log('PASS native detector and sheet mapping, intrinsic width, debug and stable source: '+width+' '+scenario);
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
