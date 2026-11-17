// Live check of the role pass on a chapter written for this test (original
// text, every paragraph is a punctuation trap). Two steps, because the model
// call needs the server's keys:
//   node roles-eval.mjs request <out.json> [arbiter]   → the request body
//   node roles-eval.mjs score <answer.json>             → segments and score
// This is real model inference only when the answer comes from Google; the
// unit tests use canned answers.
import fs from 'node:fs';
import {atomRoles,mergeAtoms,rolesRequest,parseRoles,applyRoles,heuristicRoles,suspects} from '../../src/tts/roles.js';

// [paragraph, expected parts]: S speech, T thought, N author; «who» for S and T.
export const CHAPTER=[
 ['— Я — не он, — сказал Марк. — Понял?',['S:Марк','N','S:Марк']],
 ['— Да. — Лена пожала плечами. — Пойдём уже.',['S:Лена','N','S:Лена']],
 ['- Ну как дела?- спросил сторож.- Ты случайно не Веру искал?',['S:Сторож','N','S:Сторож']],
 ['— Ну… — Марк запнулся — ладно, расскажу.',['S:Марк','N','S:Марк']],
 ['— Нам нужны три вещи: хлеб — раз, вода — два, спички — три, — перечислила Лена.',['S:Лена','N']],
 ['«Только бы успеть», — подумал Марк и прибавил шагу.',['T:Марк','N']],
 ['На двери висела табличка «Закрыто», но он всё равно постучал.',['N']],
 ['— Кто там? — Голос за дверью был сиплый.',['S:Сторож','N']],
 ['— Это я — Марк! Открой — холодно же!',['S:Марк']],
 ['Старик — сторож склада — долго гремел ключами.',['N']],
 ['— Заходи, — буркнул он наконец и посторонился. — Чаю?',['S:Сторож','N','S:Сторож']],
 ['— Не откажусь – замёрз как собака, – признался Марк.',['S:Марк','N']],
 ['— Он сказал: «Жди до утра» — и ушёл, — вспомнила Лена.',['S:Лена','N']],
 ['"Ты уверена?" - спросил сторож.',['S:Сторож','N']],
 ['— Уверена.- Она кивнула.- Абсолютно.',['S:Лена','N','S:Лена']],
 ['— А если... — начал Марк.',['S:Марк','N']],
 ['— Никаких «если»! — отрезала Лена.',['S:Лена','N']],
 ['Бум! Что-то тяжёлое упало наверху.',['N']],
 ['— Ты слышал? — прошептала она. — Там кто-то есть…',['S:Лена','N','S:Лена']],
 ['Марк кивнул — медленно, не сводя глаз с потолка.',['N']],
 ['— Тогда пошли — вместе, — решил он, — и без глупостей.',['S:Марк','N','S:Марк']],
 ['— Я — человек простой, — любил повторять сторож, — мне много не надо.',['S:Сторож','N','S:Сторож']],
 ['— Стой — там — ступенька — сломана!',['S:?']],
 ['Лена — а она редко ошибалась — покачала головой.',['N']],
];
const paragraphs=CHAPTER.map(([text])=>text);
const cast=[{name:'Марк',aliases:[],gender:'m',age:'young'},{name:'Лена',aliases:[],gender:'f',age:'young'},{name:'Сторож',aliases:['старик'],gender:'m',age:'old'}];
const context={title:'Проверочная глава',language:'ru',pov:'от третьего лица'};
const shape=segments=>{const out=paragraphs.map(()=>[]);for(const s of segments)out[s.p].push((s.kind==='speech'?'S':s.kind==='thought'?'T':'N')+(s.kind==='narration'?'':':'+(s.speaker||'?')));return out;};
function score(segments,label){
 const got=shape(segments);let kinds=0,speakers=0;const wrong=[];
 CHAPTER.forEach(([text,want],p)=>{
  const strip=list=>list.map(x=>x[0]).join('');
  const kindOk=strip(got[p])===strip(want),whoOk=kindOk&&want.every((w,i)=>w.endsWith('?')||w===got[p][i]);
  if(kindOk)kinds++;if(whoOk)speakers++;
  if(!whoOk)wrong.push('  '+(p+1)+'. '+text+'\n     want '+want.join(' | ')+'\n     got  '+segments.filter(s=>s.p===p).map(s=>(s.kind==='speech'?'S':s.kind==='thought'?'T':'N')+(s.speaker?':'+s.speaker:'')+' «'+s.text+'»').join(' | '));
 });
 console.log(label+': границы и вид '+kinds+'/'+CHAPTER.length+', вместе с говорящим '+speakers+'/'+CHAPTER.length);
 if(wrong.length)console.log(wrong.join('\n'));
 return {kinds,speakers};
}
// Only as a command: other scripts import CHAPTER.
const [mode,file,extra]=String(process.argv[1]||'').endsWith('roles-eval.mjs')?process.argv.slice(2):['import'];
if(mode==='request'){
 const atoms=atomRoles(paragraphs);
 fs.writeFileSync(file,JSON.stringify(rolesRequest(atoms,cast,{...context,arbiter:extra==='arbiter'})));
 console.log('atoms',atoms.length,'request bytes',fs.statSync(file).size);
}else if(mode==='score'){
 score(heuristicRoles(paragraphs),'Правила (как было)');
 const answer=JSON.parse(fs.readFileSync(file,'utf8')),parsed=parseRoles(answer),atoms=applyRoles(atomRoles(paragraphs),parsed,{cast});
 console.log('usage',JSON.stringify(answer.usageMetadata||{}));
 score(mergeAtoms(atoms,paragraphs),'Модель по атомам');
 console.log('спорные абзацы для арбитра:',[...suspects(atoms)].map(p=>p+1).join(', ')||'нет');
}else if(mode==='arbiter'){
 // file: the workers' answer; extra: where to write the arbiter's request.
 const atoms=applyRoles(atomRoles(paragraphs),parseRoles(JSON.parse(fs.readFileSync(file,'utf8'))),{cast}),doubt=suspects(atoms),part=atoms.filter(a=>doubt.has(a.p));
 fs.writeFileSync(extra,JSON.stringify(rolesRequest(part,cast,{...context,arbiter:true,before:atoms.slice(0,part[0].id).slice(-12),after:atoms.slice(part.at(-1).id+1,part.at(-1).id+9)})));
 console.log('arbiter atoms',part.length,'paragraphs',[...doubt].map(p=>p+1).join(', '));
}else if(mode==='final'){
 // file: the workers' answer; extra: the arbiter's answer.
 let atoms=applyRoles(atomRoles(paragraphs),parseRoles(JSON.parse(fs.readFileSync(file,'utf8'))),{cast});const doubt=suspects(atoms),answer=JSON.parse(fs.readFileSync(extra,'utf8'));
 console.log('arbiter usage',JSON.stringify(answer.usageMetadata||{}));
 atoms=applyRoles(atoms,parseRoles(answer),{cast,ids:new Set(atoms.filter(a=>doubt.has(a.p)).map(a=>a.id))});
 score(mergeAtoms(atoms,paragraphs),'После арбитра');
}else if(mode!=='import')console.log('usage: request <out.json> | score <answer.json> | arbiter <answer.json> <out.json> | final <answer.json> <arbiter-answer.json>');
