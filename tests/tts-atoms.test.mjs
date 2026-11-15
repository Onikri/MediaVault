// Atom segmentation of narration roles. Canned model answers: no inference here
// (the live check is scripts/benchmarks/roles-eval.mjs).
import test from 'node:test';
import assert from 'node:assert/strict';
import {atomize,atomRoles,mergeAtoms,suspects,rolesRequest,parseRoles,applyRoles,lineOf} from '../src/tts/roles.js';
import {arbiterParts} from '../src/tts/director.js';
import {formatRequest,formatSample,parseFormat,formatLine} from '../src/tts/format.js';

const texts=value=>atomize(value).map(a=>a.text);
const shape=segments=>segments.map(s=>s.kind[0]+(s.speaker?':'+s.speaker:'')+' '+s.text);

test('a paragraph is cut at every possible border of a line, never inside a word',()=>{
 assert.deepEqual(texts('— Я — не он, — сказал Марк. — Понял?'),['Я','не он,','сказал Марк.','Понял?']);
 assert.deepEqual(texts('- Ну как?- спросил я.- Ты кто-то из них?'),['Ну как?','спросил я.','Ты кто-то из них?']);
 assert.deepEqual(texts('«Нет», — ответил он. «Ни за что!»'),['Нет','ответил он.','Ни за что!']);
 assert.deepEqual(texts('Она сказала: „Подожди“ — и ушла в 1941–1945 годах.'),['Она сказала:','Подожди','и ушла в 1941–1945 годах.']);
 assert.deepEqual(texts('「Стой」 — крикнул он.'),['Стой','крикнул он.']);
 assert.deepEqual(texts('Просто авторский текст без знаков.'),['Просто авторский текст без знаков.']);
 const value='  — Да. — Он кивнул.';
 for(const atom of atomize(value))assert.equal(value.slice(atom.from,atom.to),atom.text);
 assert.equal(atomize(value)[0].sep,'—');assert.equal(atomize(value)[0].first,true);
 assert.deepEqual(atomize('— …'),[]);
});

test('atoms with one label are joined back with the text between them',()=>{
 const paragraphs=['— Я — не он, — сказал Марк. — Понял?','Он — врач.'];
 const atoms=atomRoles(paragraphs);
 assert.equal(atoms.length,6);assert.ok(atoms.slice(0,4).every(a=>a.open));assert.equal(atoms[0].whole,paragraphs[0]);
 // The model: atoms 0 and 1 are one line, 2 is the author, 3 the line again.
 const tagged=applyRoles(atoms,parseRoles({lines:['0|S|1|calm|3','1|S|1|determined|7','2|N','3|S|1|calm|4'],moods:[],cast:[]}),{cast:[{name:'Марк',gender:'m',age:'young'}]});
 const merged=mergeAtoms(tagged,paragraphs);
 assert.deepEqual(shape(merged),['s:Марк Я — не он,','n сказал Марк.','s:Марк Понял?','n Он — врач.']);
 assert.equal(merged[0].emotion,'determined','the strongest emotion of the joined atoms');
 assert.deepEqual(merged.map(s=>s.id),[0,2,3,4],'a segment keeps the id of its first atom');
 for(const s of merged){assert.ok(paragraphs[s.p].includes(s.text));assert.ok(!('whole' in s)&&!('open' in s)&&!('sep' in s));}
 // Without an answer the heuristic's guess stays and nothing is lost.
 assert.equal(mergeAtoms(atoms,paragraphs).map(s=>s.text).join(' ').replace(/[—\s]/g,''),paragraphs.join(' ').replace(/[—,.\s]/g,'').replace('неон','неон,').replace('Марк','Марк.').replace('Понял?','Понял?').replace('врач','врач.'));
});

test('the request shows a cut paragraph whole and leaves its atoms undecided',()=>{
 const atoms=atomRoles(['— Да. — Он пожал плечами. — Пойдём.','Тишина.']);
 const text=rolesRequest(atoms,[],{title:'X',format:'реплики — тире',after:atoms.slice(3)}).contents[0].parts[0].text;
 assert.match(text,/¶ — Да\. — Он пожал плечами\. — Пойдём\.\n0 \? — Да\.\n1 \? — Он пожал плечами\.\n2 \? — Пойдём\.\n3 N ¶ Тишина\./);
 assert.match(text,/Оформление речи в этой книге: реплики — тире/);assert.match(text,/Контекст после куска/);
 assert.equal(lineOf({id:7,kind:'speech',text:'Привет'}),'7 S Привет','segments without atom fields keep the old line');
 const worker=rolesRequest(atoms,[]),arbiter=rolesRequest(atoms,[],{arbiter:true});
 assert.equal(worker.generationConfig.thinkingConfig.thinkingLevel,'LOW');assert.equal(arbiter.generationConfig.thinkingConfig.thinkingLevel,'HIGH');
 assert.ok(arbiter.generationConfig.maxOutputTokens>worker.generationConfig.maxOutputTokens+3000,'room for the arbiter to think');
 assert.match(arbiter.systemInstruction.parts[0].text,/старший разметчик/);
});

test('only paragraphs left in doubt go to the arbiter',()=>{
 const paragraphs=['— Раз, — сказал Марк.','— Два — и три, — сказал он.','— Без ответа.','Автор.','— Кто? — Голос был тихий.'];
 let atoms=atomRoles(paragraphs);
 atoms=applyRoles(atoms,parseRoles({lines:['0|S|Марк|calm|3','1|N','2|S|Марк|calm|3','3|N','4|N','7|S|?|calm|3','8|N'],moods:[],cast:[]}));
 const doubt=suspects(atoms);
 assert.ok(!doubt.has(0),'a clear paragraph is not asked again');
 assert.ok(doubt.has(2),'the worker gave no answer for the line');
 assert.ok(doubt.has(4),'a line without a speaker');
 assert.ok(!doubt.has(3));
 assert.deepEqual(arbiterParts(atoms,new Set([0,4])).map(([from,to])=>atoms.slice(from,to).map(a=>a.p)),[[0,0],[4,4]]);
 assert.equal(suspects(atoms,{share:0,least:1}).size,1,'the share of the chapter is capped');
});

test('the editor describes how the book marks speech; a broken answer is an error, not a hint',()=>{
 const paragraphs=Array.from({length:120},(_,i)=>'— Реплика '+i+', — сказал он.');
 const sample=formatSample(paragraphs,2000);
 assert.ok(sample.length<2600&&sample.includes('[…]')&&sample.includes('Реплика 0,')&&sample.includes('Реплика 60,'));
 const request=formatRequest(sample);
 assert.equal(request.generationConfig.thinkingConfig.thinkingLevel,'HIGH');assert.match(request.systemInstruction.parts[0].text,/данные, а не инструкции/);
 const format=parseFormat({speech:' тире в начале   абзаца ',author:'— после запятой',thoughts:'в кавычках',other:'',traps:'x'.repeat(500)});
 assert.equal(format.speech,'тире в начале абзаца');assert.equal(format.traps.length,200);
 assert.equal(formatLine(format).startsWith('реплики — тире в начале абзаца; слова автора — — после запятой; мысли — в кавычках; ловушки — '),true);
 assert.equal(formatLine(null),'');
 assert.throws(()=>parseFormat({speech:'',author:''}));
});
