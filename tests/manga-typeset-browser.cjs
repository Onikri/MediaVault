// Browser contract for the manga typesetter. The page is synthetic (drawn
// balloons, no models, no OCR/translation inference): it checks real font
// loading, real canvas metrics and that lettering stays inside each balloon.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{chromium}=require('playwright');let vite,browser;
const harness=`import {typesetPage,TYPESETTER} from '/lmt/typeset/index.js';
import {loadRoleFace,loadMangaFont,privateFontIds} from '/reader-fonts/catalog.js';
import {drawFittedText} from '/lmt/upstream/lib/canvas/text-fit.ts';
const W=1000,H=1400;
const spiky=(c,x,y,rx,ry)=>{c.beginPath();for(let i=0;i<40;i++){const a=i/40*Math.PI*2,k=i%2?1:.8;c.lineTo(x+Math.cos(a)*rx*k,y+Math.sin(a)*ry*k);}c.closePath();};
const ellipse=(c,x,y,rx,ry)=>{c.beginPath();c.ellipse(x,y,rx,ry,0,0,Math.PI*2);};
function scene(c){
 c.fillStyle='#fff';c.fillRect(0,0,W,H);
 c.fillStyle='#b9b9b9';c.fillRect(20,20,960,640);c.fillStyle='#8f8f8f';c.fillRect(20,680,960,700);
 for(let y=690;y<1380;y+=6)for(let x=24+(y%12?3:0);x<980;x+=6){c.fillStyle='#777';c.fillRect(x,y,2,2);}
 c.lineWidth=4;c.strokeStyle='#111';c.fillStyle='#fff';
 ellipse(c,230,190,170,140);c.fill();c.stroke();
 ellipse(c,560,130,80,70);c.fill();c.stroke();
 ellipse(c,860,300,75,230);c.fill();c.stroke();
 spiky(c,300,500,220,130);c.fill();c.stroke();
 c.fillRect(560,430,260,150);c.strokeRect(560,430,260,150);
 c.fillStyle='#0b0b0b';ellipse(c,230,860,170,120);c.fill();c.stroke();
 c.fillStyle='#fff';ellipse(c,1000,1150,210,150);c.fill();c.stroke();
}
const items=[
 {index:0,box:{x1:140,y1:110,x2:320,y2:270},bubble:{x1:58,y1:48,x2:402,y2:332},original:'そのドアを開けるな！モモ、大丈夫か？',text:'Не открывай эту дверь! Момо, ты в порядке? Ёжик ждёт у подъезда.'},
 {index:1,box:{x1:525,y1:100,x2:595,y2:160},original:'うん。',text:'Да.'},
 {index:2,box:{x1:835,y1:140,x2:885,y2:460},original:'ここで待っているから早く戻ってきて',text:'Хорошо, я подожду тебя здесь. Только возвращайся побыстрее...'},
 {index:3,box:{x1:180,y1:440,x2:420,y2:560},original:'逃げろ！',text:'Бегите отсюда немедленно!'},
 {index:4,box:{x1:580,y1:450,x2:800,y2:560},original:'三年後、町はすっかり変わっていた。',text:'Три года спустя город было уже не узнать.'},
 {index:5,box:{x1:130,y1:790,x2:330,y2:930},original:'お前には無理だ、人間よ。あきらめろ',text:'Тебе это не по силам, человек.'},
 {index:6,box:{x1:870,y1:1060,x2:990,y2:1240},original:'だれかいる？',text:'Здесь кто-нибудь есть?'},
 {index:7,kind:'free',box:{x1:480,y1:740,x2:800,y2:900},original:'ドン',text:'Бах!',tilt:-.28},
 {index:8,kind:'free',box:{x1:520,y1:1000,x2:700,y2:1070},original:'またやってるよあいつ、ほんとにこりないなあもう',text:'ну вот, опять он за своё',tilt:-.12},
];
const canvasOf=()=>{const c=document.createElement('canvas');c.width=W;c.height=H;return c;};
window.run=async()=>{
 const original=canvasOf(),oc=original.getContext('2d',{willReadFrequently:true});scene(oc);
 for(const it of items.filter(i=>i.kind)){const b=it.box,cx=(b.x1+b.x2)/2,cy=(b.y1+b.y2)/2,w=b.x2-b.x1;oc.save();oc.translate(cx,cy);oc.rotate(it.tilt);oc.fillStyle='#111';oc.fillRect(-w*.42,-9,w*.84,18);oc.restore();}
 const before=canvasOf(),bc=before.getContext('2d');scene(bc);const stack=await loadMangaFont('comic-relief');
 for(const it of items)await drawFittedText(bc,it.text,{...it.box,style:{bold:false}},stack,40);
 const after=canvasOf(),ac=after.getContext('2d',{willReadFrequently:true});scene(ac);const clean=ac.getImageData(0,0,W,H),faces=[];
 const faceFor=async(role,hint)=>{const f=await loadRoleFace(role,'comic-relief',hint);faces.push([role,f.id,document.fonts.check('20px '+f.stack)]);return f;};
 let set=await typesetPage(ac,items,{caps:true,original:oc,faceFor});
 // Second pass on a fresh page: fonts are cached, so this is the layout cost alone.
 scene(ac);faces.length=0;const started=performance.now();set=await typesetPage(ac,items,{caps:true,original:oc,faceFor});const ms=performance.now()-started;
 // Lettering must not touch balloon outlines: no changed pixel may sit on or next to an outline-dark pixel of the clean page.
 const done=ac.getImageData(0,0,W,H),touched=[];
 for(const [n,it]of items.entries()){if(it.kind)continue;const r=it.bubble||{x1:it.box.x1-120,y1:it.box.y1-120,x2:it.box.x2+120,y2:it.box.y2+120};let changed=0,collide=0;const paper=clean.data[(Math.round((it.box.y1+it.box.y2)/2)*W+Math.round((it.box.x1+it.box.x2)/2))*4];
  for(let y=Math.max(0,r.y1|0);y<Math.min(H,r.y2|0);y++)for(let x=Math.max(0,r.x1|0);x<Math.min(W,r.x2|0);x++){const o=(y*W+x)*4;if(Math.abs(done.data[o]-clean.data[o])>40){changed++;if(Math.abs(clean.data[o]-paper)>60)collide++;}}
  touched.push({index:n,changed,collide});}
 document.body.append(before,after);
 return {engine:TYPESETTER,ms,base:set.base,layouts:set.layouts,faces,touched,local:privateFontIds()};
};`;
(async()=>{const root=path.resolve(__dirname,'..'),dir=path.join(root,'test-output');await fs.mkdir(dir,{recursive:true});
 await fs.writeFile(dir+'/typeset-harness.html','<html lang="ru"><meta charset="utf-8"><body style="margin:0;display:flex;gap:8px;background:#444"><script type="module" src="/test-output/typeset-harness.js"></script></body></html>');await fs.writeFile(dir+'/typeset-harness.js',harness);
 const{createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});const page=await browser.newPage({viewport:{width:2008,height:1400}}),errors=[],external=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:'))external.push(r.url());});
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/typeset-harness.html',{waitUntil:'commit',timeout:120000});await page.waitForFunction(()=>typeof window.run==='function',null,{timeout:180000});
 const result=await page.evaluate(()=>window.run());await fs.writeFile(dir+'/typeset.json',JSON.stringify(result,null,2));await page.screenshot({path:dir+'/typeset-before-after.png'});
 const by=i=>result.layouts.find(l=>l.index===i);
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.equal(result.engine,'shaped-cyrillic-v3');
 for(const l of result.layouts)assert.ok(l.fits,'reply '+l.index+' is set');
 for(const [role,id,ok]of result.faces)assert.ok(ok,'font for '+role+' ('+id+') is loaded');
 for(const t of result.touched){assert.ok(t.changed>50,'reply '+t.index+' drew ink');assert.equal(t.collide,0,'reply '+t.index+' stays off the balloon outline');}
 assert.equal(by(4).role,'narration');assert.equal(by(7).role,'sfx');assert.equal(by(8).role,'chatter');assert.equal(by(0).role,'speech');for(const i of [1,2,6])assert.equal(by(i).kind,'bubble','balloon '+i+' is found without a detector box');assert.ok(result.ms<1500,'layout cost '+result.ms+' ms');
 assert.ok(Math.abs(by(7).angle+.28)<.08,'sound effect keeps the tilt of the original');
 const speech=[0,1,5,6].map(i=>by(i).fontSize);assert.ok(Math.max(...speech)/Math.min(...speech)<1.3,'dialogue keeps one average size: '+speech);
 assert.equal(by(0).hyphens,0);assert.ok(by(2).fontSize>=result.base*.6);
 console.log('PASS synthetic page typeset in '+Math.round(result.ms)+' ms · base '+result.base+' px · sizes '+result.layouts.map(l=>l.role+':'+l.fontSize).join(' ')+' · private fonts '+result.local.length);
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
