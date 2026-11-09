import test from 'node:test';
import assert from 'node:assert/strict';
import {numberWords,speakable,modelText,sentences} from '../src/tts/text.js';
import {heuristicRoles,splitParagraph,applyRoles,rolesRequest,EMOTIONS} from '../src/tts/roles.js';
import {parseBible,aliasMap,applyLexicon} from '../src/tts/bible.js';
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
 const answer={candidates:[{content:{parts:[{text:JSON.stringify({characters:[{name:'Натали',gender:'f',age:'teen'}],lines:[{i:0,speaker:'Натали',emotion:'pleading',intensity:.8},{i:1,speaker:'',emotion:'calm',intensity:.9}]})}]}}]};
 const {segments:out,characters}=applyRoles(segments,answer,bible);
 assert.equal(out[0].speaker,'Наташа Ростова');assert.equal(out[0].emotion,'pleading');
 assert.equal(out[1].emotion,'calm');assert.ok(out[1].intensity<=.7,'narrator tone is kept moderate');
 assert.deepEqual(characters,[],'aliases of bible characters are not new characters');
 assert.ok(EMOTIONS.length>=24);
 const request=rolesRequest(segments,bible.characters,{title:'Война и мир',recent:['Пьер']});
 const payload=JSON.parse(request.contents[0].parts[0].text);
 assert.deepEqual(payload.characters[0].aliases,['Наташа','Натали']);assert.deepEqual(payload.recentSpeakers,['Пьер']);
 assert.equal(payload.segments.length,2,'narration is sent too, for the narrator tone');
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
