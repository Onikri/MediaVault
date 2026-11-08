import test from 'node:test';
import assert from 'node:assert/strict';
import {numberWords,speakable,modelText,sentences} from '../src/tts/text.js';
import {heuristicRoles,splitParagraph,applyRoles,rolesRequest} from '../src/tts/roles.js';
import {castVoices,delivery,voiceFor} from '../src/tts/voices.js';
import {utterancesOf} from '../src/tts/player.js';

test('numbers are spelled out in Russian and Ukrainian',()=>{
 assert.equal(numberWords(2138,'ru'),'две тысячи сто тридцать восемь');
 assert.equal(numberWords(21,'uk'),'двадцять один');
 assert.equal(numberWords(1002000,'ru'),'один миллион две тысячи');
 assert.equal(speakable('В 2138 году.','ru'),'В две тысячи сто тридцать восемь году.');
});

test('model text keeps only allowed expression tags',()=>{
 assert.equal(modelText('Ха','ru',['laugh']),'<ru><laugh> Ха.</ru>'.normalize('NFKD'));
 assert.ok(!modelText('a <script> b','ru').includes('script>'));
 assert.equal(speakable('— Привет!','ru'),'Привет!');
});

test('sentences split long text without losing words',()=>{
 const text='Первое предложение. Второе! '+'очень длинное, '.repeat(40)+'конец.';
 const parts=sentences(text,120);
 assert.ok(parts.every(p=>p.length<=120));
 assert.equal(parts.join(' ').replace(/\s+/g,' '),text.replace(/\s+/g,' ').trim());
});

test('dialogue dashes and quotes become speech and author parts',()=>{
 assert.deepEqual(splitParagraph('— Ты опять опоздал, — недовольно сказала Мирэй. — Почему?').map(p=>p.kind),['speech','narration','speech']);
 assert.deepEqual(splitParagraph('Он сказал: «Пойдём». И ушёл.').map(p=>p.kind),['narration','speech','narration']);
});

test('heuristic finds speakers, gender, alternation and emotion',()=>{
 const segments=heuristicRoles([
  'Ночь опустилась на город.',
  '— Ты опять опоздал, — недовольно сказала Мирэй.',
  '— Прости, я заблудился, — виновато ответил Кайто.',
  '— Где ты был?!',
  '— Тихо, — прошептала Мирэй.',
  '— Ти знову запізнився, — сказала Оксана.']);
 const speech=segments.filter(s=>s.kind==='speech');
 assert.deepEqual(speech.map(s=>s.speaker),['Мирэй','Кайто','Мирэй','Мирэй','Оксана']);
 assert.equal(speech[0].gender,'f');assert.equal(speech[1].gender,'m');
 assert.equal(speech[2].emotion,'surprise');assert.equal(speech[3].emotion,'whisper');
 assert.equal(speech[4].gender,'f');
});

test('model answer updates speakers and emotions, ignores junk',()=>{
 const segments=heuristicRoles(['— Стой! — крикнул кто-то.']);
 const answer={candidates:[{content:{parts:[{text:JSON.stringify({characters:[{name:'Страж',gender:'m',age:'old'}],lines:[{i:0,speaker:'Страж',emotion:'shout',intensity:2,tags:['laugh','bogus']},{i:'x'}]})}]}}]};
 const {segments:out,characters}=applyRoles(segments,answer);
 assert.equal(out[0].speaker,'Страж');assert.equal(out[0].intensity,1);assert.deepEqual(out[0].tags,['laugh']);
 assert.equal(characters[0].age,'old');
 assert.throws(()=>applyRoles(segments,{candidates:[{content:{parts:[{text:'not json'}]}}]}));
 const request=rolesRequest(segments,[],{title:'X'});
 assert.equal(request.generationConfig.responseMimeType,'application/json');
});

test('casting gives distinct voices by gender and keeps the narrator apart',()=>{
 const segments=heuristicRoles(['— А, — сказала Аня.','— Б, — сказал Борис.','— В, — сказала Вера.','— Г, — сказал Глеб.']);
 const cast=castVoices(segments,[],{narrator:'M2'});
 const voices=Object.values(cast).map(c=>JSON.stringify(c.voice));
 assert.equal(new Set(voices).size,4);
 assert.ok(Object.keys(cast.Аня.voice)[0].startsWith('F'));assert.ok(Object.keys(cast.Борис.voice)[0].startsWith('M'));
 assert.ok(!voices.includes(JSON.stringify({M2:1})));
 const narration=segments.find(s=>s.kind==='narration');
 assert.deepEqual(voiceFor(narration,cast,'M2').voice,{M2:1});
 assert.ok(delivery({kind:'speech',emotion:'whisper',intensity:1}).gain<.6);
 assert.ok(delivery({kind:'speech',emotion:'shout',intensity:1}).speed>1);
 const rows=utterancesOf(segments,{cast,narrator:'M2',pace:1});
 assert.ok(rows.length>=segments.length&&rows.every(r=>r.text&&r.voice));
});
