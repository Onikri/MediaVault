// Actual STORE CBZ directory/page reads and reader lifecycle. The range adapter
// substitutes for encrypted Drive transport; no Google Drive/network inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'.codex-local/test-output/chapter-handoff');await fs.mkdir(out,{recursive:true});
 await fs.writeFile(path.join(out,'index.html'),'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="./main.jsx"></script>');
 await fs.writeFile(path.join(out,'main.jsx'),`
import React,{useState}from'react';import{createRoot}from'react-dom/client';import JSZip from'jszip';import MangaReader from'/src/MangaReader.jsx';import'/src/styles.css';
const items=[],archives=new Map();window.rangeReads=[];window.first21Signal=null;window.last21Signal=null;window.wholeReads=0;
for(const chapter of[20,21]){const zip=new JSZip();zip.file('padding.bin',new Uint8Array(100000));for(let n=1;n<=2;n++){const c=document.createElement('canvas');c.width=600;c.height=900;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,600,900);x.fillStyle=chapter===20?'#662200':'#002266';x.font='36px serif';x.fillText('Chapter '+chapter+' page '+n,60,200);zip.file(n+'.png',await new Promise(r=>c.toBlob(r,'image/png')));}const blob=await zip.generateAsync({type:'blob',compression:'STORE'});const item={id:'chapter-'+chapter,name:'Глава '+chapter+'.cbz',episode:chapter,category:'manga',collectionId:'title',translationInfo:{language:'ja'},size:blob.size,chunks:[{fixture:true}]};items.push(item);archives.set(item.id,blob);}
const readRange=async(item,a,b,{signal})=>{if(item.episode===21){if(!window.first21Signal)window.first21Signal=signal;window.last21Signal=signal;}signal.throwIfAborted();await new Promise(r=>setTimeout(r,5));signal.throwIfAborted();window.rangeReads.push({id:item.id,start:a,end:b});return archives.get(item.id).slice(a,b);};const readWhole=async()=>{window.wholeReads++;throw Error('Unexpected full archive fallback');};
function Demo(){const[item,setItem]=useState(items[0]),[open,setOpen]=useState(true);window.closeReader=()=>setOpen(false);return open?<MangaReader item={item} catalog={{items}} userId="handoff" libraryId="drive-fixture" onClose={()=>setOpen(false)} onSelectItem={setItem} readWhole={readWhole} readRange={readRange}/>:<p>Закрыто</p>;}
createRoot(document.getElementById('root')).render(<Demo/>);
`);
 const{createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/chapter-handoff-vite',logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
 for(const width of[390,1366]){
  const context=await browser.newContext({viewport:{width,height:950}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>localStorage.setItem('mediavault_reader_v3:handoff:manga',JSON.stringify({nextChapter:true,translate:false,preload:2,fit:'page'})));
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/chapter-handoff/index.html');await page.waitForFunction(()=>document.querySelector('.reader-page img')?.naturalWidth===600&&window.rangeReads.some(r=>r.id==='chapter-21'));
  await require('./reader-controls.cjs').revealReader(page);await page.getByRole('button',{name:'Настройки читалки',exact:true}).click();await page.getByLabel('Перейти к главе').selectOption('chapter-21');await page.getByRole('button',{name:'Закрыть настройки читалки',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.reader-top')?.textContent.includes('21.cbz')&&document.querySelector('.reader-page img')?.naturalWidth===600);
  const result=await page.evaluate(()=>({sameLease:window.first21Signal===window.last21Signal,aborted:window.last21Signal.aborted,wholeReads:window.wholeReads,reads21:window.rangeReads.filter(r=>r.id==='chapter-21').length,alerts:[...document.querySelectorAll('[role="alert"]')].map(n=>n.textContent)}));
  assert.ok(result.sameLease);assert.equal(result.aborted,false);assert.equal(result.wholeReads,0);assert.ok(result.reads21>=3);assert.deepEqual(result.alerts,[]);assert.deepEqual(errors,[]);
  await page.evaluate(()=>window.closeReader());await page.waitForFunction(()=>window.last21Signal.aborted);await context.close();console.log('PASS Drive CBZ prefetch handoff 20 → 21, valid lazy pages and cancellation on close at '+width);
 }
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
