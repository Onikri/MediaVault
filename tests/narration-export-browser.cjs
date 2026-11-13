// The built VM narration page (dist/narration-export.html) in Chromium, served
// and bound exactly as server/narration_runtime.py does: assets from a fixed
// origin, every other request aborted, Google only through exportGoogleRequest.
// Google answers are fixtures (no claim of real model inference): the test
// checks that the page runs the reader's director (bible kept in the profile,
// role pass, cast, the owner's voice choices) and returns a multi-voice script.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{chromium}=require('playwright');
(async()=>{
 const assets=path.resolve(__dirname,'..','dist'),origin='http://127.0.0.1:17863';
 if(!fs.existsSync(path.join(assets,'narration-export.html')))throw Error('Run npm run build first: dist/narration-export.html is missing.');
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'narration-profile-'));
 const context=await chromium.launchPersistentContext(profile,{executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const calls=[],blocked=[];
 try{
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(route.request().url().startsWith(origin+'/')){
    const target=path.resolve(assets,decodeURIComponent(url.pathname).replace(/^\/+/,''));
    if(target.startsWith(assets)&&fs.existsSync(target)&&fs.statSync(target).isFile())return route.fulfill({body:fs.readFileSync(target),contentType:target.endsWith('.js')?'text/javascript':target.endsWith('.html')?'text/html':target.endsWith('.css')?'text/css':'application/octet-stream'});
    return route.fulfill({status:404,body:''});
   }
   blocked.push(route.request().url());return route.abort();
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  // The page asks for a bible (BIBLE_SCHEMA) and then for roles; fixtures answer both.
  await page.exposeFunction('exportGoogleRequest',async(pathname,body)=>{
   const text=JSON.stringify(body.request);calls.push({path:pathname,model:body.model,bible:text.includes('geminiVoice')&&text.includes('narrator')});
   const answer=calls.at(-1).bible?{tone:'тревожный',narratorName:'',narrator:{gender:'m',age:'adult',timbre:'dark',voice:'низкий',geminiVoice:'Charon'},
    characters:[{name:'Аня',aliases:[],gender:'f',age:'young',importance:'main',traits:'смелая',speech:'быстро',timbre:'bright',pitch:1,energy:1,pace:1,voice:'звонкий',geminiVoice:'Leda'}],lexicon:[]}
    :{lines:['1|S|Аня|fear|7'],moods:[],cast:[]};
   return {candidates:[{content:{parts:[{text:JSON.stringify(answer)}]}}],usageMetadata:{promptTokenCount:10,candidatesTokenCount:5}};
  });
  await page.goto(origin+'/narration-export.html');
  await page.waitForFunction('typeof window.narrationScript==="function"');
  const direction={prefs:{geminiNarrator:'auto',narrator:'auto',pace:1,roles:true,rolesModel:'gemini-3.5-flash-lite',bibleModel:'gemini-3.5-flash-lite'},saved:{},cast:{},bible:null,language:'ru'};
  const args={paragraphs:['Он вошёл в тёмную комнату и прислушался.','— Кто здесь? — испуганно спросила Аня.'],bookKey:'https://ranobehub.org/ranobe/1',chapterKey:'https://ranobehub.org/ranobe/1/1/1',meta:{title:'Книга',authors:['Автор'],kind:'ranobe',language:'ru'},direction};
  const first=await page.evaluate(a=>window.narrationScript(a),args);
  assert.equal(first.analysis,'model');
  assert.ok(calls.some(c=>c.bible),'the VM studies the book once');
  assert.ok(calls.every(c=>c.path==='/reader/google/generate'&&/flash-lite|gemma/.test(c.model)),'only Lite/Gemma text models');
  const voices=kind=>[...new Set(first.rows.filter(r=>r.kind===kind).map(r=>r.voice))];
  assert.deepEqual(voices('narration'),['Charon']);assert.deepEqual(voices('speech'),['Leda']);
  assert.ok(first.rows.every(r=>typeof r.text==='string'&&typeof r.style==='string'&&typeof r.pause==='number'));
  // Next chapter: the bible stays in the VM profile, no second study.
  const studies=calls.filter(c=>c.bible).length;
  const owner=await page.evaluate(a=>window.narrationScript({...a,chapterKey:a.chapterKey+'/2',paragraphs:['— Это я, — тихо сказала Аня.'],direction:{...a.direction,saved:{'Аня':{voice:'Aoede',note:'шёпотом'}}}}),args);
  assert.equal(calls.filter(c=>c.bible).length,studies);
  assert.deepEqual([...new Set(owner.rows.filter(r=>r.kind==='speech').map(r=>r.voice))],['Aoede'],'the owner\'s own voice choice wins');
  assert.deepEqual(blocked,[],'the page makes no network request of its own');
  assert.deepEqual(errors,[]);
  console.log('PASS VM narration page: bible + role pass + cast → multi-voice script, Lite/Gemma only, isolated network');
 }finally{await context.close();fs.rmSync(profile,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exit(1);});
