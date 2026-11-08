// Ranobe page + reader + narration. Server answers are fixtures; the Google
// role pass is a labelled mock; speech synthesis is the real Supertonic model.
import React from 'react';
import {createRoot} from 'react-dom/client';
import '/src/styles.css';import '/src/site-layout.css';import '/src/interface-refinement.css';
import RanobeSources from '/src/RanobeSources.jsx';
const paragraphs=['Ночь опустилась на город, и только в окне старой библиотеки ещё горел свет.','— Ты опять опоздал, — недовольно сказала Мирэй.','— Прости, я заблудился, — виновато ответил Кайто.','Ветер принёс запах дождя.'];
const book={provider:'ranobehub',providerName:'RanobeHub',kind:'ranobe',title:'Повелитель',aliases:['Повелитель'],url:'https://ranobehub.org/ranobe/206',language:'ru',
 episodes:[1,2].map(n=>({number:n,season:1,title:'Глава '+n,url:'https://ranobehub.org/ranobe/206?mv_chapter='+n,language:'ru',translator:''})),seasons:[{number:1,name:'Том 1'}]};
window.requests=[];
const service={status:'connected',session:{serverVersion:57},request:async(path,{body}={})=>{
 window.requests.push(path);
 if(path==='/ranobe/search')return {results:[{provider:'ranobehub',providerName:'RanobeHub',language:'ru',title:'Повелитель',aliases:['Overlord'],url:book.url}],providers:[]};
 if(path==='/ranobe/inspect')return book;
 if(path==='/ranobe/chapter')return {title:'Глава '+body.url.slice(-1),language:'ru',paragraphs};
 // MOCK Google answers (not model output): a title bible for the bible model,
 // speakers and emotions for the chapter model. Real models are tested live separately.
 if(path==='/reader/google/generate'){
  const answer=value=>({candidates:[{content:{parts:[{text:JSON.stringify(value)}]}}]});
  if(body.model==='gemini-3.5-flash-lite')return answer({tone:'городское фэнтези',narrator:{gender:'m',age:'adult',style:'спокойный',timbre:'warm',pitch:0,energy:0,pace:1},
   characters:[{name:'Мирэй',aliases:['Мирэй-сан'],gender:'f',age:'young',importance:'main',traits:'вспыльчивая, но заботливая',speech:'резко, коротко',timbre:'bright',pitch:1,energy:1,pace:1.05},
    {name:'Кайто',aliases:[],gender:'m',age:'young',importance:'main',traits:'рассеянный добряк',speech:'мягко, виновато',timbre:'warm',pitch:0,energy:-1,pace:.97}],
   lexicon:[{word:'Мирэй',stressed:'Мирэ́й'}]});
  if(body.model==='gemma-4-26b-a4b-it'){const req=JSON.parse(body.request.contents[0].parts[0].text);
   return answer({characters:[],lines:req.segments.map(s=>({i:s.i,speaker:s.kind==='narration'?'':/Мирэй/.test(JSON.stringify(req.segments))&&s.i===1?'Мирэй':s.i===3?'Кайто':s.guess||'',emotion:s.i===1?'angry':s.i===3?'pleading':'calm',intensity:s.kind==='narration'?.4:.7}))});}
  throw Error('mock: unexpected model '+body.model);
 }
 // MOCK RUAccent answer: marks for the fixture words (the real model is tested on the server).
 if(path==='/tts/accent')return {engine:'RUAccent (mock)',phase:'ready',texts:body.texts.map(t=>t.replace('опустилась','опусти́лась').replace('опоздал','опозда́л').replace('библиотеки','библиоте́ки'))};
 throw Error('unexpected '+path);
}};
localStorage.setItem('mv_lmt_settings:fixture',JSON.stringify({engine:'vm'}));
createRoot(document.getElementById('root')).render(<RanobeSources item={{id:'ranobe:1',title:'Повелитель',aliases:['Overlord'],kind:'ranobe',ids:{}}} service={service} state={{user:{sub:'fixture'}}}/>);
