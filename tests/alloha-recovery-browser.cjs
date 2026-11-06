const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),{chromium}=require('playwright');let browser,vite;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/recovery-ui');await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<div id="root"></div><script type="module" src="/.codex-local/recovery-ui/app.jsx"></script>');
 await fs.writeFile(path.join(dir,'app.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import OnlineWatch from'/src/OnlineWatch.jsx';import useSourceDiscovery from'/src/use-source-discovery.js';import'/src/styles.css';window.MEDIA_VAULT_CONFIG={};window.calls=[];window.refreshes=0;
 const old={id:'old',player:'Alloha',url:'https://absciss.thealloha.club/?movie=1',sourceUrl:'https://publisher.example/title'};
 const fresh={...old,id:'new',url:'https://alloha.yani.tv/?movie=1'};
 const service={server:location.origin,session:{serverVersion:50},status:'connected',request:async(p,o={})=>{window.calls.push({path:p,body:o.body});if(p==='/sources/inspect')return {episodes:[{number:1,season:1,url:o.body.dub_url}]};if(p==='/sources/qualities')return {qualities:[2160,1080]};if(p==='/online/prepare'){if(o.body.url.includes('thealloha'))throw Error('Ссылка Alloha больше недоступна');return new Promise((resolve,reject)=>o.signal?.addEventListener('abort',()=>reject(new DOMException('closed','AbortError'))));}return {};}};
 let polls=0;const discoveryService={...service,request:async()=>{const pending=++polls===1;return {pending,progress:polls,voices:[{id:'dub',variants:[pending?old:fresh]}],sources:[]};}};
 function DiscoveryDemo(){const result=useSourceDiscovery({id:'expired-source',kind:'anime',title:'Source'},discoveryService);return <output id="discovered">{(result.data?.voices||[]).flatMap(v=>v.variants.map(r=>r.id)).join(',')}</output>;}
 function Demo(){const[variants,setVariants]=useState([old]);window.addHealthyVariant=()=>setVariants(v=>[...v,{...fresh,id:'another'}]);const discovery={data:{voices:[{id:'dub',name:'Дублированный',variants}]},loading:false,retry:()=>{window.refreshes++;setTimeout(()=>setVariants([old,fresh]),40);}};return <><DiscoveryDemo/><OnlineWatch item={{id:'recovery',kind:'anime',title:'Проверка Alloha'}} profile={{title:'Проверка Alloha'}} discovery={discovery} service={service} userId="test"/></>;}createRoot(document.getElementById('root')).render(<Demo/>);
 `);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/recovery-ui',logLevel:'error',server:{port:0,strictPort:false,host:'127.0.0.1'}});await vite.listen();
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:')?r.continue():r.abort());
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/recovery-ui/index.html');
 await page.getByRole('button',{name:'Смотреть серию 1',exact:true}).evaluate(button=>button.click());
 await page.waitForFunction(()=>calls.some(c=>c.path==='/online/prepare'&&c.body.url.includes('alloha.yani.tv')));
 assert.equal(await page.evaluate(()=>refreshes),1);
 const count=await page.evaluate(()=>calls.filter(c=>c.path==='/online/prepare').length);
 await page.evaluate(()=>addHealthyVariant());await page.waitForTimeout(250);
 assert.equal(await page.evaluate(()=>calls.filter(c=>c.path==='/online/prepare').length),count,'Healthy playback must not restart when discovery appends a variant');
 await page.waitForFunction(()=>document.getElementById('discovered')?.textContent==='new');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,refreshes:1,preparations:count,healthyPlaybackNotRestarted:true}));
})().catch(e=>{console.error(e.message.slice(0,500));process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
