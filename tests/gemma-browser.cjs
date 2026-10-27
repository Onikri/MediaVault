// Real Cyrillic fonts/Canvas styles, not a translation-model benchmark.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let vite,browser;
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'test-output');await fs.mkdir(out,{recursive:true});
 await fs.writeFile(path.join(out,'gemma-fonts.html'),'<html><meta name="viewport" content="width=device-width,initial-scale=1"><canvas id="styles" width="1000" height="1000" style="max-width:100%;height:auto"></canvas><script type="module" src="/test-output/gemma-fonts.js"></script></html>');
 await fs.writeFile(path.join(out,'gemma-fonts.js'),`
 import{drawStyledRegion}from'/lmt/typography.js';
 const ctx=document.getElementById('styles').getContext('2d');ctx.fillStyle='#dad6c7';ctx.fillRect(0,0,1000,1000);window.fontLayouts=[];
 for(const[i,style]of['standard_comic','bold_scream','handwritten_sloppy','serif_serious','digital_box','sfx_art'].entries())window.fontLayouts.push(await drawStyledRegion(ctx,{id:'style-'+i,bbox:[35,20+i*160,965,160+i*160],translation:'Ёжик, ты в порядке? Не открывай дверь!',font_style:style,speech_style:'neutral_conversational',appearance:{bold:style==='bold_scream',italic:style==='sfx_art',fill_color:i===2?'#ffffff':'#151515',stroke_color:i===2?'#000000':'none',stroke_width:i===2?2:0,rotation:style==='sfx_art'?-8:0,alignment:'center'}}));window.fontsDone=true;
 `);
 const{createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:7880}});await vite.listen();browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 for(const width of[390,1366]){const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/gemma-fonts.html',{timeout:60000});await page.waitForFunction(()=>window.fontsDone);const layouts=await page.evaluate(()=>window.fontLayouts);assert.deepEqual(layouts.map(r=>r.fontId),['comic-relief','comic-relief','pangolin','serif','mono','neucha']);assert.ok(layouts.every(r=>r.fits&&r.fontSize>10));assert.deepEqual(errors,[]);await page.screenshot({path:path.join(out,'gemma-fonts-'+width+'.png')});await context.close();}
 console.log('PASS real Cyrillic Canvas styles at mobile and desktop widths');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();for(const f of['gemma-fonts.html','gemma-fonts.js'])await fs.rm(path.resolve(__dirname,'../test-output/'+f),{force:true});});
