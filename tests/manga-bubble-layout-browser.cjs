// Actual paper flood-fill and canvas typography; fixture text, no API inference.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'.codex-local/test-output/bubble-layout');await fs.mkdir(out,{recursive:true});
 await fs.writeFile(path.join(out,'index.html'),'<meta charset="utf-8"><script type="module">import{renderComicPage}from"/src/manga-renderer.js";window.render=renderComicPage;</script>');
 const{createServer}=await import('vite');vite=await createServer({root,cacheDir:'.codex-local/cache/bubble-layout-vite',logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});const page=await browser.newPage();await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/bubble-layout/index.html');await page.waitForFunction(()=>window.render);
 const rows=await page.evaluate(async()=>{
  const results=[];
  for(const [kind,boxes]of [['columns',[[140,110,240,330],[260,110,360,330]]],['stacked',[[180,100,280,200],[180,300,280,400]]],['diagonal',[[260,100,360,200],[140,280,240,380]]]]){
   const c=new OffscreenCanvas(500,500),ctx=c.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,500,500);ctx.strokeStyle='black';ctx.lineWidth=4;ctx.strokeRect(80,80,340,340);ctx.font='20px serif';ctx.fillStyle='black';for(const b of boxes)ctx.fillText('SOURCE',b[0],b[1]+25);
   const blob=await c.convertToBlob({type:'image/png'}),regions=boxes.map((text_bbox,i)=>({uid:'P1_B'+i,text_bbox,ru_translation:i?'Если это помешает заданию, будет хлопотно…':'Нечего, Мастер! Я вовсе не имела в виду ничего такого!',font_style:'standard_comic',text_category:'dialogue'})),snapshot=JSON.stringify(regions);
   const result=await window.render({blob,page:{width:500,height:500,regions},font:'serif',mode:'fast'});result.renderedBitmap.close();results.push({kind,unchanged:JSON.stringify(regions)===snapshot,layouts:result.typesetting.layouts});
  }return results;
 });
 for(const row of rows){assert.ok(row.unchanged);assert.equal(row.layouts.length,2,row.kind);const [a,b]=row.layouts.map(r=>r.layoutBox);assert.ok(Math.min(a[2],b[2])<=Math.max(a[0],b[0])||Math.min(a[3],b[3])<=Math.max(a[1],b[1]),row.kind);assert.ok(row.layouts.every(r=>r.fontSize>=20),JSON.stringify(row));}
 await fs.writeFile(path.join(out,'contract.json'),JSON.stringify(rows,null,2));console.log('PASS independent lettering cells in horizontal, vertical and diagonal joined bubbles');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
