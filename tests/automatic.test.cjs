// Real React UI + deterministic remote API; video must never be fetched by this page.
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {chromium}=require('playwright');
let vite,browser;
const ROOT=path.resolve(__dirname,'..');
const entry=path.join(ROOT,'test-output','automatic-harness.html');

(async()=>{
  await fs.mkdir(path.dirname(entry),{recursive:true});
  await fs.writeFile(entry,`<html lang="ru"><meta name="viewport" content="width=device-width, initial-scale=1"><div id="root"></div><script type="module">
    import React from 'react';
    import {createRoot} from 'react-dom/client';
    import AutomaticImport from '/src/AutomaticImport.jsx';
    import '/src/styles.css';
    window.MEDIA_VAULT_CONFIG={importServerUrl:'https://import.example.test'};
    const state={catalog:{items:[]},admin:true,token:'OWNER',libraryId:'library-123'};
    createRoot(document.getElementById('root')).render(React.createElement('main',{style:{maxWidth:'960px',margin:'auto',padding:'20px'}},React.createElement(AutomaticImport,{state,onRefresh:()=>{window.refreshes=(window.refreshes||0)+1}})));
  </script></html>`);
  const {createServer}=await import('vite');
  vite=await createServer({root:ROOT,logLevel:'error',server:{host:'127.0.0.1',port:0},optimizeDeps:{include:['react','react-dom/client']}});
  await vite.listen();
  const port=vite.httpServer.address().port;
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
  for(const width of [320,1280]){
    const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
    const page=await context.newPage(),errors=[],unexpected=[],writes=[];
    page.on('pageerror',error=>errors.push(error.message));
    let connected=false,jobs=[];
    const cards=[{id:20,title:'Наруто',original_title:'Naruto',score:'8.0',year:'2002',kind:'tv',episodes:220,image:'',url:'https://shikimori.one/animes/20'}];
    const providers=[{id:'animego',name:'AnimeGO',status:'ok',items:[{provider:'animego',provider_name:'AnimeGO',title:'Naruto — сезон 1',url:'https://animego.org/anime/naruto-1'}]},
      {id:'animevost',name:'AnimeVost',status:'unavailable',items:[],error:'Источник временно недоступен'}];
    await context.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url());
      if(url.hostname==='127.0.0.1')return route.continue();
      if(url.hostname!=='import.example.test'){unexpected.push(url.href);return route.abort();}
      const json=(data,status=200)=>route.fulfill({status,contentType:'application/json',headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'GET,POST,DELETE,OPTIONS'},body:JSON.stringify(data)});
      if(req.method()==='OPTIONS')return json({});
      assert.equal(req.headers().authorization,'Bearer OWNER');
      if(url.pathname==='/status')return json({drive_connected:true,worker_online:true,library_connected:connected});
      if(url.pathname==='/libraries/unlock'){writes.push(req.postDataJSON());connected=true;return json({connected:true});}
      if(url.pathname==='/search')return json({items:cards,providers,metadata_error:''});
      if(url.pathname==='/anime/20')return json({...cards[0],description:'История юного ниндзя.'});
      if(url.pathname==='/jobs'&&req.method()==='GET')return json({jobs});
      if(url.pathname==='/jobs'&&req.method()==='POST'){
        const data=req.postDataJSON();writes.push(data);
        assert.equal(data.job.sources[0],'https://animego.org/anime/naruto-1');
        assert.equal(data.job.collection,'Наруто');
        assert.ok(data.request_id);
        assert.equal(data.job.passphrase,undefined);
        jobs=[{id:'job-12345678',status:'queued',progress:{}}];return json({id:jobs[0].id},202);
      }
      if(url.pathname==='/jobs/job-12345678/cancel'){jobs=[{...jobs[0],status:'cancelled',cancel:1}];return json({cancel_requested:true});}
      return json({error:'unexpected'},500);
    });
    await page.goto(`http://127.0.0.1:${port}/test-output/automatic-harness.html`);
    await page.locator('#serverPhrase').fill('fixture library phrase');
    await page.getByRole('button',{name:'Подключить автоматический импорт'}).click();
    await page.getByText('Библиотека подключена.',{exact:false}).waitFor();
    await page.locator('#animeSearch').fill(width===320?'Наруто':'Naruto');
    await page.getByRole('button',{name:'Выбрать Наруто'}).click();
    await page.getByText('История юного ниндзя.').waitFor();
    await page.getByRole('button',{name:'Naruto — сезон 1'}).click();
    await page.locator('#importVideoBtn').click();
    await page.getByText('Импорт поставлен в очередь.',{exact:false}).waitFor();
    assert.equal(writes.filter(value=>value.job).length,1);
    const state=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,local:JSON.stringify(localStorage),session:JSON.stringify(sessionStorage)}));
    assert.ok(state.scroll<=state.width+1,JSON.stringify(state));
    assert.ok(!state.local.includes('fixture library phrase')&&!state.session.includes('fixture library phrase'));
    await page.screenshot({path:path.join(ROOT,'test-output',`automatic-${width}.png`),fullPage:true});
    await page.reload(); // Queue survives closure/reopening of the UI; owned by the server.
    await page.getByText('В очереди',{exact:true}).waitFor();
    assert.equal(await page.locator('#serverPhrase').count(),0);
    jobs=[{id:'job-12345678',status:'completed',progress:{phase:'saved',completed:1,total:1},result:{saved:1,failed:0,skipped:0}}];
    await page.getByText('Готово',{exact:true}).waitFor({timeout:12000});
    assert.ok(await page.evaluate(()=>window.refreshes>=1));
    const refreshes=await page.evaluate(()=>window.refreshes);
    await page.waitForTimeout(5500); // A second completed-job poll must not refresh/toast again.
    assert.equal(await page.evaluate(()=>window.refreshes),refreshes);
    assert.deepEqual(unexpected,[],'No source video or Google requests in import UI');
    assert.deepEqual(errors,[]);
    await context.close();
    console.log('PASS automatic import UI, persistence and no video traffic at '+width+'px');
  }
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();await fs.rm(entry,{force:true});});
