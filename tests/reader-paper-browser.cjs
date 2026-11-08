// Real StPageFlip sheets, orientation, transitions and lifecycle; synthetic page artwork.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');
const ROOT=process.cwd(),DIR=path.join(ROOT,'.codex-local/test-output/reader-paper');let browser,vite,last;
(async()=>{
 await fs.mkdir(DIR,{recursive:true});await fs.writeFile(path.join(DIR,'index.html'),'<meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/.codex-local/test-output/reader-paper/app.jsx"></script>');
 await fs.writeFile(path.join(DIR,'app.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import Book from'/src/ReaderPaperBook.jsx';import'/src/reader-morph.css';
 function App(){const[page,setPage]=useState(0),[spread,setSpread]=useState(false),[direction,setDirection]=useState('ltr'),[open,setOpen]=useState(true);window.configure=v=>{setOpen(v.open!==false);setSpread(!!v.spread);setDirection(v.direction||'ltr');setPage(v.page||0);};window.jump=setPage;window.current=page;return <div className="immersive-reader" style={{position:'relative',height:'90vh',width:'100%',background:'#151519'}}>{open&&<Book total={6} page={page} spread={spread} direction={direction} onPage={setPage} renderPage={index=><div style={{height:'100%',width:'100%',background:index%2?'#c9c1a6':'#e3ddcd',display:'grid',placeItems:'center',fontSize:80}}>{index+1}</div>}/>}</div>;}createRoot(document.getElementById('root')).render(<App/>);
 `);
 const{createServer}=await import('vite');vite=await createServer({root:ROOT,cacheDir:'.codex-local/cache/vite-reader-paper',optimizeDeps:{force:true},logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 for(const width of[390,1440]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];last=page;page.on('pageerror',e=>errors.push(e.message));await page.addInitScript(()=>{const raf=requestAnimationFrame,cancel=cancelAnimationFrame,pending=new Set();window.flipFrames=pending;window.frameKinds=new Set();window.requestAnimationFrame=fn=>{window.frameKinds.add(fn.toString().slice(0,220));let id;id=raf(t=>{pending.delete(id);fn(t);});if(fn.toString().includes('this.running'))pending.add(id);return id;};window.cancelAnimationFrame=id=>{pending.delete(id);cancel(id);};});
  await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/reader-paper/index.html');
  for(const direction of['ltr','rtl'])for(const spread of width>=900?[false,true]:[false]){
   await page.evaluate(v=>configure(v),{direction,spread,page:0});await page.locator('.stf__wrapper.'+(spread?'--landscape':'--portrait')).waitFor();await page.waitForTimeout(60);
   await page.evaluate(()=>jump(1));await page.waitForTimeout(100);assert.ok(await page.locator('.stf__item').evaluateAll(nodes=>nodes.some(n=>n.style.transform.includes('rotate')||n.style.clipPath.includes('polygon'))),'Library draws an actual turning sheet');await page.waitForTimeout(700);assert.ok([1,2].includes(await page.evaluate(()=>current)),'Turn reaches the next page or complete spread');
   const r=await page.locator('.reader-paper-book').boundingBox();assert.ok(r.x>=-1&&r.x+r.width<=width+1);
  }
  assert.equal(await page.evaluate(()=>flipFrames.size),1,'One live renderer loop');await page.evaluate(()=>configure({open:false}));await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>flipFrames.size),0,'Destroy cancels the upstream renderer frame');assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS true single-page portrait, desktop spreads, RTL/LTR sheet turns and renderer frame cleanup at 390/1440px');
})().catch(async e=>{console.error(e);if(last){console.error(await last.evaluate(()=>[...window.frameKinds]));console.error(await last.locator('.stf__item').evaluateAll(ns=>ns.map(n=>({text:n.textContent,style:n.getAttribute('style'),class:n.className}))).catch(()=>[]));await last.screenshot({path:path.join(DIR,'failure.png')});}process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
