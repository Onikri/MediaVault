import test from 'node:test';
import assert from 'node:assert/strict';
import {numberWords,speakable,modelText,sentences} from '../src/tts/text.js';
import {heuristicRoles,splitParagraph,applyRoles,rolesRequest,parseRoles,quotations,EMOTIONS} from '../src/tts/roles.js';
import {parseBible,aliasMap,applyLexicon,mergeCast,reconcileRequest} from '../src/tts/bible.js';
import {planChunks,analyseChapter} from '../src/tts/director.js';
import {castVoices,delivery,voiceFor,designVoice,narratorCast} from '../src/tts/voices.js';
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

test('worker answer: compact lines, numbers past the list are new speakers, junk ignored',()=>{
 const segments=heuristicRoles(['— Стой! — крикнул кто-то.','«Глава первая: о мане»','Шелест страниц.']);
 const answer={candidates:[{content:{parts:[{text:JSON.stringify({lines:['0|S|2|shouting|9|laugh','2|N||neutral|1','x|S|1|joy|3'],moods:['1-3|sad|5'],cast:['Страж|m|old|хриплый бас','Страж|m|old|повтор']})}]}}]};
 const parsed=parseRoles(answer);
 assert.equal(parsed.cast.length,1,'one card per name');
 const out=applyRoles(segments,parsed,{cast:[{name:'Мирэй',gender:'f',age:'young'}]});
 assert.equal(out[0].speaker,'Страж','number 2 = first new speaker after a one-name list');
 assert.equal(out[0].emotion,'shout','emotion synonym mapped');assert.equal(out[0].intensity,1);assert.deepEqual(out[0].tags,['laugh']);assert.equal(out[0].gender,'m');
 const quote=out.find(s=>s.text.startsWith('Глава первая'));
 assert.equal(quote.kind,'narration','a quoted book title the model marked N is read by the narrator');
 assert.equal(quote.speaker,'');assert.equal(quote.emotion,'sad','author text takes the mood of its range');
 assert.throws(()=>parseRoles({candidates:[{content:{parts:[{text:'not json'}]}}]}));
 const request=rolesRequest(segments,[{name:'Мирэй',aliases:['Мира'],gender:'f',age:'young'}],{title:'X',before:segments.slice(0,1)});
 const text=request.contents[0].parts[0].text;
 assert.match(text,/1 Мирэй = Мира · f young/);assert.match(text,/Контекст перед куском/);assert.match(text,/\d+ Q Глава первая/,'an unattributed quotation is left for the model to decide');
 assert.equal(request.generationConfig.thinkingConfig.thinkingLevel,'LOW');
 assert.ok(request.generationConfig.maxOutputTokens<=8192);
});

test('nested quotations stay inside the outer one; an open quotation runs to the end',()=>{
 const value='«Самоубийство Клейна странное. Не будет ли “несчастных случаев”, если уйдёт?»';
 assert.deepEqual(quotations(value),[[0,value.length]]);
 assert.deepEqual(splitParagraph(value).map(p=>p.kind),['speech']);
 assert.equal(splitParagraph('«Первая часть письма, продолжение в следующем абзаце.')[0].kind,'speech');
 assert.deepEqual(splitParagraph('На вывеске было написано «Аптека» крупными буквами.').map(p=>p.kind),['narration']);
});

test('chapter parts: a small part at the reading position first, paragraphs never split',()=>{
 const paragraphs=Array.from({length:120},(_,i)=>i%3?'— Реплика номер '+i+', — сказал он. — И ещё одна.':'Длинный авторский абзац '+'слово '.repeat(60));
 const segments=heuristicRoles(paragraphs);
 const parts=planChunks(segments,{start:60});
 assert.equal(segments[parts[0][0]].p,60,'first part starts where the reader is');
 const size=([a,b])=>segments.slice(a,b).reduce((n,s)=>n+Math.min(s.text.length,430),0);
 assert.ok(size(parts[0])<size(parts[1]),'first part is the small one');
 const covered=parts.flatMap(([a,b])=>Array.from({length:b-a},(_,i)=>a+i)).sort((x,y)=>x-y);
 assert.deepEqual(covered,segments.map((_,i)=>i),'every segment exactly once');
 for(const [a,b] of parts)if(b<segments.length)assert.notEqual(segments[b].p,segments[b-1].p,'a part ends at a paragraph border');
});

test('director: parts go out together, a refused part is halved, new speakers are merged into the bible',async()=>{
 const paragraphs=Array.from({length:40},(_,i)=>i===25?'«Запретный абзац»':i%2?'— Реплика '+i+', — сказала Мирэй.':'Автор '+'текст '.repeat(40));
 const bible={version:2,model:'gemini-3.5-flash-lite',pov:'third',narratorName:'',tone:'',narrator:{gender:'m',age:'adult'},characters:[{name:'Мирэй',aliases:[],gender:'f',age:'young',importance:'main'}],lexicon:[]};
 let inFlight=0,peak=0;const calls=[];
 const service={request:async(path,{body})=>{
  inFlight++;peak=Math.max(peak,inFlight);await new Promise(r=>setTimeout(r,20));inFlight--;
  const system=body.request.systemInstruction.parts[0].text,user=body.request.contents[0].parts[0].text;calls.push({model:body.model,pool:body.pool,system});
  const wrap=value=>({candidates:[{content:{parts:[{text:JSON.stringify(value)}]}}],usageMetadata:{promptTokenCount:1000,candidatesTokenCount:50}});
  if(system.includes('ведёшь список'))return wrap({same:['Незнакомка=1'],characters:[{name:'Стражник',aliases:[],gender:'m',age:'adult',importance:'minor',timbre:'rough',voice:'хриплый бас',geminiVoice:'Algenib'}]});
  const rows=user.split('Сегменты:\n')[1].split('\n').map(l=>/^(\d+) ([NSTQ])/.exec(l)).filter(Boolean);
  if(user.includes('Запретный')&&rows.length>4)return {promptFeedback:{blockReason:'PROHIBITED_CONTENT'}};
  return wrap({lines:rows.filter(r=>r[2]!=='N').map(r=>r[1]+'|S|'+(Number(r[1])%4===1?'Незнакомка':Number(r[1])%4===3?'Стражник':'1')+'|calm|4'),moods:[],cast:['Незнакомка|f|young|тихий','Стражник|m|adult|хриплый']});
 }};
 const updates=[];let merged=null;
 const result=await analyseChapter({paragraphs,bookKey:'book:test',chapterKey:'ch:1',bible,meta:{title:'Тест',language:'ru'},service,userId:'u',start:10,onUpdate:v=>updates.push(v),onBible:b=>{merged=b;}});
 assert.ok(peak>=3,'parts are sent in parallel: '+peak);
 assert.ok(updates.length>=3&&updates.some(u=>!u.done&&u.stats.done>0),'answers applied as they arrive');
 assert.ok(result.stats.refused>=1,'refused part was split');assert.equal(result.stats.failed,0);
 const forbidden=result.segments.find(s=>s.text.includes('Запретный'));assert.notEqual(forbidden.source,'model','only the refused paragraph stays untagged');
 assert.ok(result.segments.filter(s=>s.source==='model').length>result.segments.length*.8);
 const speakers=new Set(result.segments.filter(s=>s.kind!=='narration').map(s=>s.speaker));
 assert.ok(speakers.has('Мирэй')&&speakers.has('Стражник')&&!speakers.has('Незнакомка'),'director merged «Незнакомка» into Мирэй: '+[...speakers]);
 assert.ok(merged.characters.some(c=>c.name==='Стражник'&&c.geminiVoice==='Algenib'));
 assert.ok(merged.characters.find(c=>c.name==='Мирэй').aliases.includes('Незнакомка'));
 const again=await analyseChapter({paragraphs,bookKey:'book:test',chapterKey:'ch:1',bible,meta:{title:'Тест'},service,userId:'u',onUpdate:()=>{}});
 assert.equal(again.cached,true,'a chapter is analysed once');
 assert.match(reconcileRequest(bible,[{name:'X',gender:'m',age:'adult',lines:['Привет']}]).contents[0].parts[0].text,/- X · m adult · «Привет»/);
});

test('casting gives distinct voices by gender and keeps the narrator apart',()=>{
 const segments=heuristicRoles(['— А, — сказала Аня.','— Б, — сказал Борис.','— В, — сказала Вера.','— Г, — сказал Глеб.']);
 const cast=castVoices(segments,[],{narrator:'M2'});
 const voices=Object.values(cast).map(c=>JSON.stringify(c.voice));
 assert.equal(new Set(voices).size,4);
 assert.ok(Object.keys(cast.Аня.voice)[0].startsWith('F'));assert.ok(Object.keys(cast.Борис.voice)[0].startsWith('M'));
 assert.ok(!voices.includes(JSON.stringify({M2:1})));
 const narration=segments.find(s=>s.kind==='narration');
 assert.deepEqual(voiceFor(narration,cast,narratorCast(null,'M2')).voice,{M2:1});
 assert.ok(delivery({kind:'speech',emotion:'whisper',intensity:1}).gain<.6);
 assert.ok(delivery({kind:'speech',emotion:'shout',intensity:1}).speed>1);
 const rows=utterancesOf(segments,{cast,narrator:narratorCast(null,'M2'),pace:1});
 assert.ok(rows.length>=segments.length&&rows.every(r=>r.text&&r.voice));
});

test('voices are designed from measured preset pitch: age, gender, timbre, pitch shift and EQ',()=>{
 const girl=designVoice({gender:'f',age:'child'}),old=designVoice({gender:'m',age:'old',timbre:'dark'}),youth=designVoice({gender:'m',age:'young',timbre:'bright'});
 assert.ok(Object.keys(girl.voice)[0].startsWith('F')&&girl.rate>1,'a child is a higher female preset');
 assert.ok(['M2','M5'].includes(Object.keys(old.voice)[0]),'an old man gets a deep preset: '+JSON.stringify(old.voice));
 assert.ok(old.eq.high<0&&youth.eq.high>0);
 assert.equal(Object.keys(youth.voice)[0],'M1');
 assert.ok(Math.abs(designVoice({gender:'f',age:'adult',pitch:3}).pitch)<=4);
 const rows=utterancesOf([{id:0,p:0,kind:'speech',speaker:'Аня',text:'Привет.',spoken:'Приве́т.',emotion:'whisper',intensity:1}],{cast:{Аня:girl},narrator:narratorCast(null,'auto'),pace:1});
 assert.equal(rows[0].text,'Приве́т.');assert.equal(rows[0].rate,girl.rate);assert.ok(rows[0].eq.low<-4&&rows[0].eq.high>3,'whisper EQ added');
});
test('the title bible is validated, aliases resolve to names and lexicon stresses only unmarked words',()=>{
 const bible=parseBible({tone:'роман',narrator:{gender:'f',age:'adult',timbre:'warm',pitch:9},characters:[{name:'Наташа Ростова',aliases:['Наташа','Натали'],gender:'f',age:'teen',importance:'main',timbre:'bright',pitch:1},{name:''}],
  lexicon:[{word:'Ростова',stressed:'Росто́ва'},{word:'Boris',stressed:'Bóris'},{word:'Пьер',stressed:'Пье́р!'}]},'gemini-3.5-flash-lite');
 assert.equal(bible.characters.length,1);assert.equal(bible.narrator.pitch,3);
 assert.deepEqual(bible.lexicon.map(e=>e.word),['Ростова']);
 assert.equal(aliasMap(bible).get('натали'),'Наташа Ростова');
 assert.equal(applyLexicon('Наташа Ростова и Пье́р.',bible),'Наташа Росто́ва и Пье́р.');
 assert.throws(()=>parseBible({characters:'x'}));
 const segments=heuristicRoles(['— Иди сюда, — сказала Натали.']);
 const out=applyRoles(segments,parseRoles({lines:['0|S|Натали|pleading|7'],moods:['1-1|calm|9'],cast:[]}),{cast:bible.characters,canonical:aliasMap(bible)});
 assert.equal(out[0].speaker,'Наташа Ростова','an alias resolves to the bible name');assert.equal(out[0].emotion,'pleading');
 assert.equal(out[1].emotion,'calm');assert.ok(out[1].intensity<=.7,'narrator tone is kept moderate');
 assert.ok(EMOTIONS.length>=24);
 const {bible:next,rename}=mergeCast(bible,{same:['Натали Ростова=1','Гость=Незнакомец'],characters:[{name:'Незнакомец',gender:'m',age:'old',importance:'minor',timbre:'dark',voice:'глухой старческий голос',geminiVoice:'Algenib'}]},[{name:'Натали Ростова'},{name:'Гость'},{name:'Незнакомец'}]);
 assert.equal(rename.get('Натали Ростова'),'Наташа Ростова');assert.equal(rename.get('Гость'),'Незнакомец');
 assert.ok(next.characters.find(c=>c.name==='Наташа Ростова').aliases.includes('Натали Ростова'));
 assert.equal(next.characters.at(-1).geminiVoice,'Algenib');
});

import {pickGeminiVoice,geminiNarrator,geminiCast,geminiRows,styleFor,pcmDecoder,GEMINI_VOICES} from '../src/tts/gemini-voice.js';

test('Gemini voices: male and female narrators, characters cast by gender without repeats',()=>{
 const gender=Object.fromEntries(GEMINI_VOICES.map(([n,g])=>[n,g]));
 assert.equal(GEMINI_VOICES.length,30);
 assert.equal(geminiNarrator(null,'m'),'Charon');assert.equal(geminiNarrator(null,'f'),'Kore');assert.equal(geminiNarrator(null,'Sulafat'),'Sulafat');
 assert.equal(gender[geminiNarrator({narrator:{gender:'f',age:'adult',timbre:'warm'}})],'f');
 assert.equal(gender[pickGeminiVoice({gender:'f',age:'old'})],'f');assert.equal(pickGeminiVoice({gender:'m',age:'old',timbre:'rough'}),'Algenib');
 const cast={Анна:{gender:'f',age:'young'},Пётр:{gender:'m',age:'young'},Мария:{gender:'f',age:'young'},Иван:{gender:'m',age:'adult'}};
 const voices=geminiCast(cast,{narrator:'Charon'});
 assert.equal(new Set(Object.values(voices)).size,4);assert.ok(!Object.values(voices).includes('Charon'));
 for(const [name,c] of Object.entries(cast))assert.equal(gender[voices[name]],c.gender,name);
 assert.equal(geminiCast(cast,{narrator:'Charon',saved:{Анна:'Gacrux',Пётр:'bad'}}).Анна,'Gacrux');
});

test('Gemini rows: verbatim text without stress marks, delivery as a direction',()=>{
 const segments=[{id:0,p:0,kind:'narration',text:'Дождь стучал по крыше.'},{id:1,p:1,kind:'speech',speaker:'Анна',emotion:'sarcastic',intensity:.8,text:'— Бежал он!',spoken:'— Бежа́л он!'}];
 const rows=geminiRows(segments,{cast:{Анна:{gender:'f',age:'young',traits:'ироничная'}},voices:{Анна:'Aoede'},narrator:'Charon',bible:{tone:'спокойный'},pace:1.2});
 assert.deepEqual(rows.map(r=>r.voice),['Charon','Aoede']);
 assert.equal(rows[1].text,'Бежал он!');
 assert.match(rows[0].style,/авторский текст.*спокойный/);assert.match(rows[1].style,/Анна \(молодая женщина\).*ироничная.*с сарказмом.*сильно.*быстрее/);
 assert.equal(styleFor({kind:'speech',emotion:'neutral'},null),'прочитать реплику героя');
 const long=geminiRows([{id:0,p:0,kind:'narration',text:'Слово. '.repeat(200)}],{cast:{},voices:{},narrator:'Charon'});
 assert.ok(long.length>1&&long.every(r=>r.text.length<=300));
});

test('PCM decoder joins a sample split across network chunks',()=>{
 const decode=pcmDecoder();
 const a=decode(new Uint8Array([0x00,0x40,0x00]));const b=decode(new Uint8Array([0xc0]));
 assert.deepEqual([...a],[0.5]);assert.deepEqual([...b],[-0.5]);
});

test('quotations: dialogue is speech, a quoted name inside a sentence stays author text',()=>{
 assert.deepEqual(splitParagraph('Он прочитал вывеску «Аптека» и вошёл.').map(p=>p.kind),['narration']);
 assert.deepEqual(splitParagraph('«Ты где был?» — спросила она.').map(p=>p.kind),['speech','narration']);
 assert.deepEqual(splitParagraph('«Нет», — ответил он. «Ни за что!»').map(p=>p.kind),['speech','narration','speech']);
 assert.deepEqual(splitParagraph('Она сказала: „Подожди меня“ — и ушла.').map(p=>p.kind),['narration','speech','narration']);
 const rows=geminiRows(heuristicRoles(['«Нет», — ответил он.']),{cast:{},voices:{},narrator:'Charon'});
 assert.deepEqual(rows.map(r=>r.text),['Нет','ответил он.'],'no leading «, —» and no punctuation-only parts');
});

import {describeVoice,NARRATOR_NOTE} from '../src/tts/gemini-voice.js';
test('voice descriptions: from the bible, and the listener’s own words win',()=>{
 assert.equal(describeVoice({gender:'m',age:'old',timbre:'rough',pitch:-2,pace:.9}),'голос пожилого человека, старческий, хрипловатый, очень низкий, говорит медленно');
 assert.equal(describeVoice({gender:'f',age:'child',timbre:'bright',pitch:1}),'детский голос, звонкий, выше обычного');
 const segments=[{id:0,p:0,kind:'narration',text:'Ночь.'},{id:1,p:1,kind:'speech',speaker:'Старик',text:'Кто там?'}];
 const cast={Старик:{gender:'m',age:'old',timbre:'rough'}},bible={narrator:{gender:'m',age:'adult',timbre:'warm',style:'спокойно'}};
 let rows=geminiRows(segments,{cast,voices:{Старик:'Algenib'},narrator:'Charon',bible});
 assert.match(rows[0].style,/голос рассказчика: тёплый, спокойно/);assert.match(rows[1].style,/голос героя: голос пожилого человека, старческий, хрипловатый/);
 rows=geminiRows(segments,{cast,voices:{Старик:'Algenib'},narrator:'Charon',bible,saved:{Старик:{voice:'Algenib',note:'шёпотом, как призрак'},[NARRATOR_NOTE]:{note:'бодрый молодой голос'}}});
 assert.match(rows[0].style,/голос рассказчика: бодрый молодой голос/);assert.match(rows[1].style,/голос героя: шёпотом, как призрак/);
 assert.equal(geminiCast(cast,{narrator:'Charon',saved:{Старик:{voice:'Puck',note:'x'}}}).Старик,'Puck','a saved {voice, note} keeps its voice');
});

const split=text=>splitParagraph(text).map(p=>p.kind[0]+':'+p.text);
test('author words inside a line go to the narrator: hyphens and dashes without spaces',()=>{
 assert.deepEqual(split('- Ну и что будем с ними делать?- спросил я управляющего, что сидел здесь с самого начала.'),
  ['s:Ну и что будем с ними делать?','n:спросил я управляющего, что сидел здесь с самого начала.']);
 assert.deepEqual(split('- Тоука, у нас в стойке лежала верёвка, не могла бы ты принести мне её?- попросил он Тоуку и она сразу убежала.- И Канеки, не мог бы ты принести стулья?'),
  ['s:Тоука, у нас в стойке лежала верёвка, не могла бы ты принести мне её?','n:попросил он Тоуку и она сразу убежала.','s:И Канеки, не мог бы ты принести стулья?']);
 assert.deepEqual(split('- Откуда ты...- недоумевал Аято.'),['s:Откуда ты...','n:недоумевал Аято.']);
 assert.deepEqual(split('- Ну как дела?- задал риторический вопрос я.- Вы случайно не Ризе искали?'),
  ['s:Ну как дела?','n:задал риторический вопрос я.','s:Вы случайно не Ризе искали?']);
});

test('author words: every dash, with and without spaces, after ? ! . … ... and ,',()=>{
 assert.deepEqual(split('― Привет,― сказал он,― как дела?'),['s:Привет,','n:сказал он,','s:как дела?']);
 assert.deepEqual(split('– Где ты?– спросила она.'),['s:Где ты?','n:спросила она.']);
 assert.deepEqual(split('—Куда?—удивился Кайто.—Стой!'),['s:Куда?','n:удивился Кайто.','s:Стой!']);
 assert.deepEqual(split('- Привет, - сказал он. - Как дела?'),['s:Привет,','n:сказал он.','s:Как дела?']);
 assert.deepEqual(split('- Слушай…- протянул Кайто, глядя в окно.- Ты ведь не уйдёшь?'),['s:Слушай…','n:протянул Кайто, глядя в окно.','s:Ты ведь не уйдёшь?']);
 assert.deepEqual(split('- Стой!- крикнула Оксана.'),['s:Стой!','n:крикнула Оксана.']);
 assert.deepEqual(split('- Где?- Спросил он.'),['s:Где?','n:Спросил он.'],'a capital verb with its subject');
 assert.deepEqual(split('- Знаешь,- говорит она,- я передумала.'),['s:Знаешь,','n:говорит она,','s:я передумала.']);
 assert.deepEqual(split('- Де ти був?- запитала Оксана.'),['s:Де ти був?','n:запитала Оксана.']);
 // Spaced en and em dashes alternate exactly as before.
 assert.deepEqual(split('— Ты опять опоздал, — недовольно сказала Мирэй. — Почему?'),['s:Ты опять опоздал,','n:недовольно сказала Мирэй.','s:Почему?']);
 assert.deepEqual(split('— Москва — столица.'),['s:Москва','n:столица.']);
});

test('author words in quotations with any dash',()=>{
 assert.deepEqual(split('«Ну как дела?»- задал риторический вопрос я. «Вы случайно не Ризе искали?»'),
  ['s:Ну как дела?','n:- задал риторический вопрос я.','s:Вы случайно не Ризе искали?']);
 assert.deepEqual(split('„Подожди“ ― попросила она.'),['s:Подожди','n:― попросила она.']);
 assert.deepEqual(split('"Стой!" - крикнул он.'),['s:Стой!','n:- крикнул он.']);
 const rows=geminiRows(heuristicRoles(['«Нет»- ответил он.']),{cast:{},voices:{},narrator:'Charon'});
 assert.deepEqual(rows.map(r=>r.text),['Нет','ответил он.']);
});

test('author words: hyphens in words, plain dashes and doubtful lines stay as they were',()=>{
 assert.deepEqual(split('- Кто-то из-за угла вышел.'),['s:Кто-то из-за угла вышел.']);
 assert.deepEqual(split('- Я - твой отец.'),['s:Я - твой отец.']);
 assert.deepEqual(split('- Где ты был?- Я сказал тебе, жди!'),['s:Где ты был?- Я сказал тебе, жди!'],'a new capital sentence is still speech');
 assert.deepEqual(split('- Где ты был?- Сказал же, дома.'),['s:Где ты был?- Сказал же, дома.'],'a capital verb without a subject');
 assert.deepEqual(split('- Пойдём.- Он сел на стул.'),['s:Пойдём.- Он сел на стул.'],'no speech or thought verb');
 assert.deepEqual(split('- Ну,- начало положено.'),['s:Ну,- начало положено.'],'a noun that looks like a verb');
 assert.deepEqual(split('- Да,- прошу тебя.'),['s:Да,- прошу тебя.'],'a present form without a subject');
 assert.deepEqual(split('- Привет- сказал он.'),['s:Привет- сказал он.'],'no punctuation before the dash');
 assert.deepEqual(split('Он шёл домой - было поздно.'),['n:Он шёл домой - было поздно.']);
 assert.deepEqual(split('Он шёл домой, - сказал он мне.'),['n:Он шёл домой, - сказал он мне.'],'author text without a dialogue dash');
 assert.deepEqual(split('Стадион «Зенит»-Арена был полон.'),['n:Стадион «Зенит»-Арена был полон.']);
});

test('author words inside a line are read by the narrator and keep the speaker around them',()=>{
 const segments=heuristicRoles(['- Ну как дела?- задал риторический вопрос я.- Вы случайно не Ризе искали?']);
 assert.deepEqual(segments.map(s=>s.kind),['speech','narration','speech']);
 const parsed=parseRoles({lines:['0|S|Канеки|neutral|3','2|S|Канеки|neutral|3'],moods:[],cast:['Канеки|m|young|спокойный']});
 const out=applyRoles(segments,parsed);
 assert.deepEqual(out.map(s=>s.speaker),['Канеки','','Канеки']);
 const rows=geminiRows(out,{cast:{Канеки:{gender:'m'}},voices:{Канеки:'Puck'},narrator:'Charon'});
 assert.deepEqual(rows.map(r=>r.voice),['Puck','Charon','Puck']);
});

test('author words with action verbs: lower case after ? ! . and a dash',()=>{
 assert.deepEqual(split('- Тоука, ты всё не так поняла.- попытался отмазаться я.'),['s:Тоука, ты всё не так поняла.','n:попытался отмазаться я.']);
 assert.deepEqual(split('- И что же?- она гневно посмотрела на меня.'),['s:И что же?','n:она гневно посмотрела на меня.']);
 assert.deepEqual(split('- Привет, братик Канеки!- поприветствовала меня Хинами.'),['s:Привет, братик Канеки!','n:поприветствовала меня Хинами.']);
 assert.deepEqual(split('- Спасительница!- я резко спрятался за Хинами.'),['s:Спасительница!','n:я резко спрятался за Хинами.']);
 assert.deepEqual(split('- Успокойся!- крикнул я.- Сейчас во всём разберёмся.'),['s:Успокойся!','n:крикнул я.','s:Сейчас во всём разберёмся.']);
 assert.deepEqual(split('- Що?- вона подивилася на мене.'),['s:Що?','n:вона подивилася на мене.']);
 // Lower case after … or a comma goes on with the line; no past verb — doubt.
 assert.deepEqual(split('- Я думал...- что ты ушёл.'),['s:Я думал...- что ты ушёл.']);
 assert.deepEqual(split('- Я думал…- что ты ушёл.'),['s:Я думал…- что ты ушёл.']);
 assert.deepEqual(split('- Да,- она ушла.'),['s:Да,- она ушла.']);
 assert.deepEqual(split('- Кто?- я?'),['s:Кто?- я?']);
 assert.deepEqual(split('- Ах, он так думает.'),['s:Ах, он так думает.']);
});
