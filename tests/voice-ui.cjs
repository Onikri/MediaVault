// Actual title detail and import UI, with a controlled source/Drive service. No media traffic.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require('playwright');
let vite,browser;
const ROOT=path.resolve(__dirname,'..'),entry=path.join(ROOT,'test-output','voice-harness.html');
(async()=>{
  await fs.mkdir(path.dirname(entry),{recursive:true});
  await fs.writeFile(entry,`<html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module">
import React from 'react';import {createRoot} from 'react-dom/client';import {TitleDetails} from '/src/CatalogBrowser.jsx';import '/src/styles.css';import '/src/title-page.css';import '/src/import-layout.css';
const item={id:'shikimori:57334',provider:'shikimori',providerId:'57334',providers:['shikimori'],title:'Дандадан',titles:{ru:'Дандадан',en:'Dandadan'},aliases:['Дандадан','Dandadan'],year:2024,kind:'anime',format:'TV',genres:['Комедия'],tags:['Школа'],links:[],releases:[],ids:{mal:'57334'},description:'Проверка точного тайтла и переводов.',cover:''};
window.MEDIA_VAULT_CONFIG={};
const service={server:'https://fixture.example',status:'connected',session:{driveConnected:true},request:async(path,options={})=>{
 if(!path.startsWith('/sources/'))return {};
 const response=await fetch('https://fixture.example'+path,{method:options.method||'GET',body:options.body?JSON.stringify(options.body):undefined,signal:options.signal});return response.json();},
 submit:async job=>{window.submitted=job;}};
createRoot(document.getElementById('root')).render(React.createElement('main',{style:{padding:'18px',maxWidth:'1180px',margin:'auto'}},React.createElement(TitleDetails,{value:item,state:{admin:true,user:{sub:'owner'},catalog:{items:[]},libraryId:'catalog-123',busy:''},service,onBack:()=>{},onSubmitted:()=>{window.sent=true}})));
</script></html>`);
  const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
  browser=await chromium.launch({headless:true,args:['--no-sandbox'],executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium'});
  for(const width of [320,1280]){
    const context=await browser.newContext({viewport:{width,height:950},serviceWorkers:'block'}),page=await context.newPage(),errors=[],external=[];
    let discoveryCalls=0,inspectionCalls=0;
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url());if(url.hostname==='127.0.0.1')return route.continue();
      const json=data=>route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*','access-control-allow-methods':'*','access-control-allow-headers':'*'},body:JSON.stringify(data)});
      if(url.hostname!=='fixture.example'){external.push(url.href);return json([]);}
      if(url.pathname==='/sources/discover'){
        const body=req.postDataJSON(),selected=body.title;assert.equal(selected.ids.mal,'57334');assert.equal(selected.year,2024);assert.equal(body.continuing,discoveryCalls>0);
        discoveryCalls++;const pending=discoveryCalls===1;
        return json({pending,progress:pending?128:256,complete:!pending,voices:Array.from({length:pending?20:40},(_,i)=>({id:'studio-'+i,name:'Studio '+i,kind:'voice',language:'ru',variants:Array.from({length:14},(_,j)=>({id:'variant-'+i+'-'+j,name:'Studio '+i,kind:'voice',language:'ru',player:'Kodik',sourceTitle:'Дандадан',sourceUrl:'https://source.example/dandadan',providerName:'Источник '+j,url:'https://kodikplayer.com/serial/'+(1000+i*100+j)+'/hash/720p',episodes:[{number:1},{number:3}]}))})),providers:[{provider:'source',name:'Источник A',status:'ok'}]});
      }
      if(url.pathname==='/sources/inspect'){
        const data=req.postDataJSON();assert.equal(data.dub_url,'https://kodikplayer.com/serial/4913/hash/720p');
        inspectionCalls++;
        if(!data.continuation)return json({pending:true,continuation:'public-inspection-continuation',scannedPages:128,dubs:[],episodes:[]});
        assert.equal(data.continuation,'public-inspection-continuation');
        return json({provider:'source',dubs:[{id:'a',name:'Studio 39',url:data.dub_url}],seasons:[{number:1,name:'Сезон 1'}],episodes:[1,3].map(number=>({number,url:'https://kodikplayer.com/seria/'+number+'/hash/720p',season:1})),releases:[]});
      }
      if(url.pathname==='/sources/qualities')return json({qualities:[4320,2160,1440,1080,720,480,360,240,144],best:4320,original:false});
      return json([]);
    });
    await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/voice-harness.html');
    await page.locator('#voiceGroup option').nth(40).waitFor({state:'attached'});assert.equal(await page.locator('#voiceGroup option').count(),41);
    await page.locator('#voiceGroup').selectOption('studio-39');await page.locator('#voiceSource option').nth(14).waitFor({state:'attached'});assert.equal(await page.locator('#voiceSource option').count(),15);
    await page.locator('#voiceSource').selectOption('variant-39-13');
    await page.getByText('Найдено опубликованных файлов: 2.',{exact:false}).waitFor();
    await page.locator('#serverQuality option[value="4320"]').waitFor({state:'attached'});assert.equal(await page.locator('#serverQuality option').count(),10);
    assert.equal(await page.locator('#serverQuality').inputValue(),'best');
    if(width===1280)await page.locator('#serverQuality').selectOption('2160');
    await page.locator('#importVideoBtn').click();await page.waitForFunction(()=>window.sent);
    const job=await page.evaluate(()=>window.submitted);assert.equal(job.version,3);assert.equal(job.quality,width===1280?'2160':'best');assert.equal(job.metadata.ids.mal,'57334');assert.equal(job.translation.player,'Kodik');assert.equal(job.dub,'Studio 39');assert.equal(job.translation.variantId,'variant-39-13');assert.deepEqual(job.entries.map(e=>e.number),[1,3]);
    assert.equal(discoveryCalls,2);assert.equal(inspectionCalls,2);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal overflow at '+width);
    if(width===1280){const layout=await page.locator('.import-dossier-layout').boundingBox();assert.ok(layout.width>1000,'The dossier uses the desktop content width');}
    await page.screenshot({path:path.join(ROOT,'test-output','voice-import-'+width+'.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.ok(!external.some(url=>url.includes('.mp4')||url.includes('kodikplayer.com')),'The UI never downloads source video');
    await context.close();console.log('PASS exact-title grouped voice import at '+width+'px');
  }
})().catch(error=>{require('./ci-diagnostic.cjs')(error,'tests/voice-ui.cjs','Voice selection');console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();await fs.rm(entry,{force:true});});
