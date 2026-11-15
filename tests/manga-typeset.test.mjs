import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeText} from '../lmt/typeset/normalize.js';
import {hyphenate} from '../lmt/typeset/hyphen-ru.js';
import {ellipseRegion,rectRegion,erodeRegion,availableWidth} from '../lmt/typeset/shape.js';
import {prepare,layoutAt,maxFit} from '../lmt/typeset/breaks.js';
import {fitPage} from '../lmt/typeset/fit.js';
import {classify,loudness,tiltOf} from '../lmt/typeset/classify.js';

// Deterministic stand-in for canvas metrics: every glyph is 0.55 em wide.
const measure=text=>[...text].length*.55;
const bubble=(x1,y1,x2,y2,margin=10)=>erodeRegion(ellipseRegion({x1,y1,x2,y2}),margin);

test('punctuation is normalised and never left alone on a line',()=>{
 assert.equal(normalizeText('Ну - "привет" , мир… Что !?'),'Ну — «привет», мир... Что?!');
 assert.equal(normalizeText('Стой ...'),'Стой...');
 assert.equal(normalizeText('ёж',{caps:true}),'ЁЖ');
});

test('hyphenation follows syllables, keeps two letters per side and reuses hyphens',()=>{
 for(const word of ['президент','невозможно','здравствуйте','пользователь','объявление','рассказать','достопримечательности']){
  const parts=hyphenate(word);
  assert.ok(parts.length>1,word);assert.equal(parts.join(''),word);
  for(const part of parts){assert.ok(part.length>=2,`${word}: ${parts}`);assert.match(part,/[аеёиоуыэюя]/);}
 }
 assert.deepEqual(hyphenate('зонт'),['зонт']);
 assert.deepEqual(hyphenate('армия'),['ар','мия']);
 assert.deepEqual(hyphenate('как-нибудь'),['как-','нибудь']);
 assert.ok(!hyphenate('подъезд').some(p=>/^[ъь]/.test(p)));
});

test('lines follow the balloon: widest in the middle, all inside the shape',()=>{
 const region=bubble(100,100,320,340),text=normalizeText('Не открывай эту дверь! Момо, ты в порядке? Ёжик ждёт у подъезда.');
 const prepared=prepare(text,measure),size=maxFit(prepared,region),layout=layoutAt(prepared,region,size);
 assert.ok(size>=10);assert.ok(layout.lines.length>=3);assert.equal(layout.hyphens,0);
 for(const line of layout.lines)assert.ok(line.width<=line.avail+.01);
 const widths=layout.lines.map(l=>l.width),middle=Math.max(...widths.slice(1,-1));
 assert.ok(middle>=widths[0]&&middle>=widths.at(-1));
 assert.equal(layout.lines.map(l=>l.text).join(' '),text.replaceAll(' ',' '));
 assert.equal(layoutAt(prepared,region,size+2),null);
});

test('prepositions and particles stay with their word when the shape allows',()=>{
 const region=erodeRegion(rectRegion({x1:0,y1:0,x2:230,y2:200}),6),prepared=prepare(normalizeText('Он пришёл в дом и не сказал бы ни слова'),measure);
 const layout=layoutAt(prepared,region,20);
 for(const line of layout.lines.slice(0,-1))assert.doesNotMatch(line.text,/ (в|и|не|ни)$/);
 for(const line of layout.lines)assert.doesNotMatch(line.text,/^бы /);
});

test('one average size per page; hyphenation before shrinking; overflow never throws',()=>{
 const make=(index,text,region,box,role='speech')=>({index,text,region,box,role,loud:1,measure});
 const a={x1:100,y1:100,x2:320,y2:340},b={x1:400,y1:100,x2:700,y2:420},c={x1:0,y1:0,x2:90,y2:260},d={x1:0,y1:300,x2:30,y2:330};
 const page=fitPage([
  make(0,'Не открывай эту дверь! Момо, ты в порядке?',bubble(a.x1,a.y1,a.x2,a.y2),a),
  make(1,'Да.',bubble(b.x1,b.y1,b.x2,b.y2),b),
  make(2,'Хорошо, я подожду тебя здесь.',bubble(b.x1,b.y1,b.x2,b.y2),b),
  make(3,'Достопримечательности',bubble(c.x1,c.y1,c.x2,c.y2,5),c),
  make(4,'Совершенно невозможно уместить эту длинную реплику',bubble(d.x1,d.y1,d.x2,d.y2,2),d),
 ],{pageWidth:1000});
 const [long,short,medium,narrow,impossible]=page.layouts;
 assert.ok(Math.abs(short.size-medium.size)<.01,'equal balloons share a size');
 assert.ok(short.size<=page.base*1.11,'a short reply does not fill its balloon');
 assert.ok(long.size<=short.size&&long.size>=page.base*.8);
 assert.ok(narrow.hyphens>=1&&narrow.shrunk&&!narrow.overflow);
 assert.ok(narrow.lines.every(l=>!/^.-$|^-/.test(l.text)));
 assert.equal(impossible.overflow,true);
});

test('roles default to speech and only clear cases become situational',()=>{
 const region={kind:'bubble',rectangularity:.8};
 assert.equal(classify({kind:'bubble',region,text:'Привет, как дела?'}),'speech');
 assert.equal(classify({kind:'bubble',region,text:'(Что это было?)'}),'thought');
 assert.equal(classify({kind:'bubble',region:{kind:'bubble',rectangularity:.98},text:'Прошло три года.'}),'narration');
 assert.equal(classify({kind:'free',text:'БАХ!'}),'sfx');
 assert.equal(classify({kind:'free',loud:.6,text:'ну вот, опять он за своё'}),'chatter');
 assert.equal(classify({kind:'bubble',region,text:'x',style:'note'}),'note');
 const loud=loudness([{original:'ああああ',box:{x1:0,y1:0,x2:40,y2:40}},{original:'ああああ',box:{x1:0,y1:0,x2:40,y2:40}},{original:'あ',box:{x1:0,y1:0,x2:60,y2:60}}]);
 assert.ok(loud[2]>2&&loud[0]===1);
});

test('tilt is measured from the nearest axis and ignored for compact ink',()=>{
 const line=angle=>{const p=[];for(let i=-40;i<=40;i++)for(const o of [-1,0,1])p.push(i*Math.cos(angle)-o*Math.sin(angle),i*Math.sin(angle)+o*Math.cos(angle));return p;};
 assert.ok(Math.abs(tiltOf(line(.3))-.3)<.02);
 assert.ok(Math.abs(tiltOf(line(Math.PI/2+.2))-.2)<.02);
 assert.equal(tiltOf(line(.02)),0);
 const blob=[];for(let x=0;x<10;x++)for(let y=0;y<10;y++)blob.push(x,y);assert.equal(tiltOf(blob),0);
});

test('region helpers: erosion shrinks, rows outside are unavailable',()=>{
 const region=ellipseRegion({x1:0,y1:0,x2:200,y2:100}),inner=erodeRegion(region,10);
 assert.ok(availableWidth(inner,45,55)<availableWidth(region,45,55));
 assert.equal(availableWidth(inner,-5,5),0);
 assert.ok(Math.abs(inner.cx-100)<1&&Math.abs(inner.cy-50)<1);
});

test('cache identity follows the typesetter and the caps choice',async()=>{
 const {TYPESETTER}=await import('../lmt/typeset/index.js'),{resultConfig,TRANSLATION_VERSION}=await import('../src/manga-translation.js');
 assert.equal(resultConfig({engine:'lmt'}).typesetter,TYPESETTER);assert.ok(TRANSLATION_VERSION>=10);
 const {READER_TYPESETTER}=await import('../src/manga-renderer.js').catch(()=>({}));if(READER_TYPESETTER)assert.match(READER_TYPESETTER,/^shaped-/);
 assert.notEqual(resultConfig({engine:'direct'}).typesetter,resultConfig({engine:'lmt'}).typesetter);
 assert.equal(resultConfig({}).caps,true);assert.equal(resultConfig({caps:false}).caps,false);
});
