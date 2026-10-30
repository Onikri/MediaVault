// Default: browser/worker contract with an injected provider. MIGAN_REAL=1:
// actual pinned MI-GAN ONNX WASM inference, local weights, no API mocks.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),{chromium}=require('playwright');
let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'.codex-local/test-output/migan'),real=process.env.MIGAN_REAL==='1';await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(path.join(dir,'index.html'),'<meta charset="utf-8"><canvas id="result"></canvas><script type="module">import{renderComicPage}from"/src/manga-renderer.js";import{DirectChapter}from"/src/manga-direct.js";window.render=renderComicPage;window.DirectChapter=DirectChapter;</script>');
 const{createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});const page=await browser.newPage();
 if(real){
  await page.route('https://huggingface.co/andraniksargsyan/migan/**',route=>route.fulfill({path:path.join(root,'.codex-local/cache/migan/migan_pipeline_v2.onnx'),contentType:'application/octet-stream',headers:{'access-control-allow-origin':'*'}}));
  await page.route('**/lmt/ort-wasm*',route=>route.fulfill({path:path.join(root,'dist/lmt',new URL(route.request().url()).pathname.split('/').at(-1)),contentType:route.request().url().endsWith('.wasm')?'application/wasm':'text/javascript'}));
 }
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/.codex-local/test-output/migan/index.html');await page.waitForFunction(()=>window.render&&window.DirectChapter);
 const result=await page.evaluate(async real=>{
  const c=document.getElementById('result');c.width=320;c.height=240;const ctx=c.getContext('2d');ctx.fillStyle='#eee';ctx.fillRect(0,0,320,240);ctx.fillStyle='#111';ctx.font='bold 24px sans-serif';ctx.fillText('HELLO!',35,80);ctx.fillRect(275,10,2,220);
  const blob=await new Promise(r=>c.toBlob(r)),before=ctx.getImageData(0,0,320,240).data.slice(),page={width:320,height:240,regions:[{uid:'P1_B1',text_bbox:[30,55,135,86],layout_bbox:[25,45,145,100],ru_translation:'Привет!',font_style:'standard_comic',text_category:'dialogue'}]};
  const chapter=new window.DirectChapter({entries:[],scope:'migan-test',config:{inpaint:'migan',cache:false}});let output;
  try{
   output=real?await chapter.canvasTask({blob,page,mode:'migan',captureDebug:true}):await window.render({blob,page,mode:'migan',font:'serif',captureDebug:true,lama:async image=>{image.data.fill(230);return{provider:'fixture'};}});
   const prepared=real?await chapter.canvasTask({operation:'clean-prepare',blob,page,mode:'migan'}):await window.render({blob,page,mode:'migan',cleanOnly:true,lama:async image=>{image.data.fill(230);return{provider:'fixture'};}});const reused=real?await chapter.canvasTask({blob,page,mode:'migan',preparedClean:prepared,captureDebug:true}):await window.render({blob,page,mode:'migan',font:'serif',preparedClean:prepared,captureDebug:true,lama:async()=>{throw Error('Must reuse prepared background');}});const originalMask=new Uint8Array(output.debug.maskImage),reusedMask=new Uint8Array(reused.debug.maskImage),reusedMaskMatches=originalMask.length===reusedMask.length&&originalMask.every((v,i)=>v===reusedMask[i]);const reusedCalls=reused.inpaint.modelCalls,reusedLayouts=reused.typesetting.layouts.length;reused.renderedBitmap.close();ctx.drawImage(output.renderedBitmap,0,0);output.renderedBitmap.close();const after=ctx.getImageData(0,0,320,240).data;let outsideChanges=0;for(let y=0;y<240;y++)for(let x=220;x<320;x++)if(before[(y*320+x)*4]!==after[(y*320+x)*4])outsideChanges++;
   return{realNeuralInference:real,reusedMaskMatches,reusedCalls,reusedLayouts,methods:output.inpaint.methods,unpainted:output.inpaint.unpainted,layouts:output.typesetting.layouts,execution:output.inpaint.regions[0].execution,maskBytes:output.debug.maskImage.byteLength,outsideChanges};
  }finally{chapter.close();}
 },real);
 assert.deepEqual(result.methods,['migan']);assert.equal(result.unpainted,0);assert.equal(result.reusedMaskMatches,true,'Prepared backgrounds must display the actual model mask');assert.equal(result.reusedCalls,0);assert.equal(result.reusedLayouts,1);assert.equal(result.layouts.length,1);assert.equal(result.outsideChanges,0);assert.ok(result.maskBytes>100);if(real)assert.equal(result.execution.provider,'wasm');
 await fs.writeFile(path.join(dir,real?'real-inference.json':'contract.json'),JSON.stringify(result,null,2));await page.screenshot({path:path.join(dir,real?'real-inference.png':'contract.png')});console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
