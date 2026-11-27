const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),{chromium}=require('playwright');let browser,vite;
(async()=>{
 const root=process.cwd(),dir=path.join(root,'.codex-local/recovery-ui');await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<div id="root"></div><script type="module" src="/.codex-local/recovery-ui/app.jsx"></script>');
 await fs.writeFile(path.join(dir,'app.jsx'),`
 import React,{useState}from'react';import{createRoot}from'react-dom/client';import OnlineWatch from'/src/OnlineWatch.jsx';import OnlineViewer from'/src/OnlineViewer.jsx';import {createImportClient} from'/src/import-service.js';import useSourceDiscovery from'/src/use-source-discovery.js';import'/src/styles.css';window.MEDIA_VAULT_CONFIG={};window.calls=[];window.refreshes=0;
 const old={id:'old',player:'Alloha',url:'https://absciss.thealloha.club/?movie=1',sourceUrl:'https://publisher.example/title'};
 const fresh={...old,id:'new',url:'https://alloha.yani.tv/?movie=1'};
 const service={server:location.origin,session:{serverVersion:50},status:'connected',request:async(p,o={})=>{window.calls.push({path:p,body:o.body});if(p==='/sources/inspect')return {episodes:[{number:1,season:1,url:o.body.dub_url}]};if(p==='/sources/qualities')return {qualities:[2160,1080]};if(p==='/online/prepare'){if(o.body.url.includes('thealloha'))throw Error('Ссылка Alloha больше недоступна');return new Promise((resolve,reject)=>o.signal?.addEventListener('abort',()=>reject(new DOMException('closed','AbortError'))));}return {};}};
 let polls=0;const discoveryService={...service,request:async()=>{const pending=++polls===1;return {pending,progress:polls,voices:[{id:'dub',variants:[pending?old:fresh]}],sources:[]};}};
 function DiscoveryDemo(){const result=useSourceDiscovery({id:'expired-source',kind:'anime',title:'Source'},discoveryService);return <output id="discovered">{(result.data?.voices||[]).flatMap(v=>v.variants.map(r=>r.id)).join(',')}</output>;}
 function Demo(){const[variants,setVariants]=useState([old]);window.addHealthyVariant=()=>setVariants(v=>[...v,{...fresh,id:'another'}]);const discovery={data:{voices:[{id:'dub',name:'Дублированный',variants}]},loading:false,retry:()=>{window.refreshes++;setTimeout(()=>setVariants([old,fresh]),40);}};return <><DiscoveryDemo/><OnlineWatch item={{id:'recovery',kind:'anime',title:'Проверка Alloha'}} profile={{title:'Проверка Alloha'}} discovery={discovery} service={service} userId="test"/></>;}
 const blockedTransport=createImportClient(location.origin,()=>null,async()=>new Response(JSON.stringify({detail:'Серверное подключение ограничено'}),{status:409,headers:{'X-Alloha-Error':'client_blocked'}}));
 const blockedService={...service,request:(path,options)=>{
  window.calls.push({path,body:options.body});
  return blockedTransport.request(path,{...options,auth:false});
 }};
 function BrowserDemo(){const[number,setNumber]=useState(7);const[open,setOpen]=useState(true);window.changeBrowserEpisode=()=>setNumber(8);
  const entry={number,season:1,title:'Серия '+number,url:'https://theatre.stravers.live/?token=fixture&season=1&episode='+number+'&translation=55'};
  return open&&<OnlineViewer entries={[entry]} initial={entry} service={blockedService} kind="video" title="Чёрный список" dub="Дублированный" onClose={()=>setOpen(false)}/>;}
 const blockedEpisode={number:7,season:1,url:'https://theatre.stravers.live/?season=1&episode=7&translation=55'};
 const mirrorURL='https://mirror.example/episodes/7';
 const mirror={id:'mirror',player:'Другой плеер',provider:'kinobox',url:mirrorURL,sourceUrl:mirrorURL,episodes:[{...blockedEpisode,url:mirrorURL}]};
 const blockedVariant={id:'blocked',player:'Alloha',provider:'kinobox',url:blockedEpisode.url,sourceUrl:blockedEpisode.url,episodes:[blockedEpisode]};
 const mirrorService={...blockedService,request:async(path,options)=>{
  if(path!=='/online/prepare')return {};
  if(options.body.url===mirrorURL)return new Promise((_,reject)=>{window.failMirror=()=>reject(Error('mirror fixture failed'));});
  await new Promise(resolve=>{window.releaseBlocked=resolve;});return blockedService.request(path,options);
 }};
 function MirrorDemo(){const[include,setInclude]=useState(false);window.addMirror=()=>setInclude(true);window.mirrorAvailable=include;
  const discovery={data:{voices:[{id:'same-voice',name:'Та же озвучка',variants:include?[blockedVariant,mirror]:[blockedVariant]}]},loading:false};
  return <OnlineWatch item={{id:'mirror-test',kind:'tv',title:'Проверка зеркала'}} profile={{title:'Проверка зеркала'}} discovery={discovery} service={mirrorService} userId="test"/>;}
 const blacklistService={...service,request:async(path,options)=>{
  if(path!=='/online/prepare')return {};
  window.blacklistPreparations.push(options.body);
  return {id:'blacklist-stream',type:'hls',url:'/online/blacklist-stream/alloha-playback',allohaMode:'browser',qualities:[720]};
 }};
 function BlacklistDemo(){
  const item={id:'kinobox:741231',kind:'tv',title:'Чёрный список',ids:{kinopoisk:'741231'}};
  const discovery={data:{voices:[{id:'same-voice',name:'Дублированный',variants:[mirror,blockedVariant]}]},loading:false};
  return <OnlineWatch item={item} discovery={discovery} service={blacklistService} userId="test"/>;}
 const root=createRoot(document.getElementById('root'));root.render(<Demo/>);window.showBrowserDemo=()=>root.render(<BrowserDemo/>);window.showMirrorDemo=()=>root.render(<MirrorDemo/>);
 window.showBlacklistDemo=()=>{window.blacklistPreparations=[];root.render(<BlacklistDemo/>);};
 `);
 const {createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/recovery-ui',logLevel:'error',server:{watch:null,port:0,strictPort:false,host:'127.0.0.1'}});await vite.listen();
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
 let providerRequests=0;
 await page.route('https://theatre.stravers.live/**',route=>{providerRequests++;return route.abort();});
 await page.evaluate(()=>showBrowserDemo());
 const frame=page.locator('.online-viewer iframe');
 await page.getByText('Серверное подключение ограничено',{exact:true}).waitFor();
 assert.equal(await frame.count(),0);
 await page.getByRole('button',{name:'Повторить подключение',exact:true}).click();
 await page.waitForFunction(()=>calls.filter(c=>c.path==='/online/prepare'&&c.body?.url.includes('episode=7&translation=55')).length===2);
 await page.evaluate(()=>changeBrowserEpisode());
 await page.waitForFunction(()=>calls.some(c=>c.path==='/online/prepare'&&c.body?.url.includes('episode=8&translation=55')));
 await page.getByRole('button',{name:'Закрыть онлайн-просмотр'}).click();
 await page.evaluate(()=>showMirrorDemo());
 await page.getByRole('button',{name:'Смотреть серию 7',exact:true}).click();
 await page.waitForFunction(()=>typeof releaseBlocked==='function');await page.evaluate(()=>addMirror());
 await page.waitForFunction(()=>window.mirrorAvailable);
 await page.evaluate(()=>releaseBlocked());await page.waitForFunction(()=>typeof failMirror==='function');
 assert.equal(await frame.count(),0);
 await page.evaluate(()=>failMirror());await page.getByText('mirror fixture failed',{exact:true}).first().waitFor();
 assert.equal(await frame.count(),0);
 await page.route('**/online/blacklist-stream/alloha-playback',route=>route.fulfill({contentType:'application/vnd.apple.mpegurl',body:'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\n/fixture-segment.ts\n#EXT-X-ENDLIST\n'}));
 await page.evaluate(()=>showBlacklistDemo());
 await page.getByRole('button',{name:'Смотреть серию 7',exact:true}).click();
 await page.locator('.mv-player-media').waitFor();
 const [native]=await page.evaluate(()=>blacklistPreparations);
 assert.equal(new URL(native.url).hostname,'theatre.stravers.live');
 assert.equal(new URL(native.url).searchParams.get('episode'),'7');
 assert.equal(new URL(native.url).searchParams.get('translation'),'55');
 assert.equal(await frame.count(),0);
 assert.equal(providerRequests,0);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,refreshes:1,preparations:count,healthyPlaybackNotRestarted:true,sameVoiceMirror:true,blacklistUsesMediaVaultPlayer:true,providerFrames:0}));
})().catch(e=>{console.error(e.message.slice(0,500));process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
