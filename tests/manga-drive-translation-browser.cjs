// Manga save window, Google Drive: «С переводом» is offered only when the
// server can translate on the VM, and the job carries the reader's translation
// settings as `render`. Server answers are fixtures; nothing is translated here
// (the VM pipeline is covered by tests/test_drive_audiobook.py with a mocked renderer).
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..');
let browser,vite;
(async()=>{
 fs.mkdirSync(path.join(ROOT,'test-output'),{recursive:true});
 fs.writeFileSync(path.join(ROOT,'test-output/manga-drive.html'),'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/test-output/manga-drive.jsx"></script></html>');
 fs.writeFileSync(path.join(ROOT,'test-output/manga-drive.jsx'),`
import React from'react';import{createRoot}from'react-dom/client';import MangaImport from'/src/MangaImport.jsx';import'/src/styles.css';import'/src/export-sheet.css';import'/src/manga-export.css';
const query=new URLSearchParams(location.search),source='https://mangapoisk.me/manga/story';window.submitted=[];
const service={server:location.origin,status:'connected',session:{serverVersion:71,driveConnected:true,mangaDriveTranslation:query.get('vm')==='1'},
 submit:async job=>{window.submitted.push(job);return{id:'task'};},
 request:async(p,o={})=>{
  if(p==='/manga/inspect')return{title:'Story',url:source,language:'en',provider:'mangapoisk',providerName:'MangaPoisk',readable:true,episodes:[1,2].map(n=>({url:source+'/chapter/'+n,number:n,season:1,title:'Chapter '+n,language:'en'})),seasons:[{number:1,name:'Том 1'}],translations:[]};
  if(p.startsWith('/manga/summary'))return{chapterCount:2,volumeCount:1,readable:true};
  if(p==='/manga/search'||p.startsWith('/discovery'))return{results:[],providers:[],sources:[]};
  return{};}};
const item={id:'metadata:1',kind:'manga',title:'Story',aliases:['Story'],sources:[{id:'s',provider:'mangapoisk',providerName:'MangaPoisk',url:source,title:'Story',kind:'manga',language:'en'}]};
createRoot(document.getElementById('root')).render(<div className="export-sheet" style={{position:'static',maxWidth:480,margin:16}}><MangaImport sheet compact destination="drive" preferredSource={source} item={item} state={{admin:true,catalog:{items:[]},libraryId:'library-fixture',user:{sub:'fixture'}}} service={service}/></div>);`);
 const {createServer}=await import('vite');vite=await createServer({root:ROOT,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const base='http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/manga-drive.html?';
 for(const vm of [false,true]){
  const page=await browser.newPage({viewport:{width:500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(60000);
  await page.goto(base+(vm?'vm=1':''),{timeout:180000});
  await page.getByRole('button',{name:/Добавить 2 главы в коллекцию/}).waitFor();
  const choice=page.getByRole('radiogroup',{name:'Что сохранить'});
  if(!vm){
   assert.equal(await choice.count(),0,'no translation without the VM renderer');
   await page.getByText(/исходные страницы глав/).waitFor();
   await page.getByRole('button',{name:/Добавить 2 главы/}).click();
   await page.waitForFunction(()=>window.submitted.length===1);
   const [job]=await page.evaluate(()=>window.submitted);assert.equal(job.render,undefined);assert.equal(job.dub,'');
  }else{
   await choice.getByRole('radio',{name:'С переводом'}).click();
   await page.getByText('Настройки перевода на ВМ').click();
   assert.equal(await page.getByLabel('Формат файла').count(),0,'Drive keeps one CBZ per chapter: no file format');
   assert.equal(await page.getByLabel('Качество страниц манги').count(),0,'translated pages are rendered at source size');
   await page.getByRole('button',{name:/Добавить 2 главы/}).click();
   await page.waitForFunction(()=>window.submitted.length===1);
   const [job]=await page.evaluate(()=>window.submitted);
   assert.equal(job.section,'manga');assert.equal(job.quality,'best');assert.equal(job.dub,'Перевод MediaVault');
   assert.deepEqual(job.translation,{name:'Перевод MediaVault',kind:'manga',language:'ru'});
   assert.ok(job.render&&job.render.directModel&&job.render.language,'render carries the reader translation settings');
   assert.deepEqual(Object.keys(job.render).filter(k=>!['directModel','language','direction','directInput','directDetector','directBatchPages','inpaint','font'].includes(k)),[]);
  }
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS manga Drive save window: original only without the VM renderer; «С переводом» sends render settings with the server 71 flag');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
