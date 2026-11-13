// The title page's save window for ranobe (RanobeExport). Server answers are
// fixtures; the Google bible/role answers are labelled MOCKS (as in
// ranobe-harness.jsx) and /reader/google/speak streams a MOCK tone instead of
// Gemini speech. Query: destination=local|drive, audio=1 (server has the VM
// narration director), language=ru|en, version=N.
import React from 'react';
import {createRoot} from 'react-dom/client';
import '/src/styles.css';import '/src/site-layout.css';import '/src/interface-refinement.css';import '/src/export-sheet.css';
import RanobeExport from '/src/RanobeExport.jsx';
const query=new URLSearchParams(location.search),language=query.get('language')||'ru';
const paragraphs=['Ночь опустилась на город, и только в окне старой библиотеки ещё горел свет.','— Ты опять опоздал, — недовольно сказала Мирэй.','— Прости, я заблудился, — виновато ответил Кайто.'];
const book={provider:'ranobehub',providerName:'RanobeHub',kind:'ranobe',title:'Повелитель',url:'https://ranobehub.org/ranobe/206',language,
 episodes:[1,2].map(n=>({number:n,season:1,title:'Глава '+n,url:'https://ranobehub.org/ranobe/206?mv_chapter='+n,language}))};
window.requests=[];window.speak=[];window.submitted=[];
function tone(){
 const rate=24000,samples=new Int16Array(rate*.3);for(let i=0;i<samples.length;i++)samples[i]=Math.sin(i/rate*2*Math.PI*220)*8000;
 return new Response(new Blob([samples.buffer]).stream());
}
const answer=value=>({candidates:[{content:{parts:[{text:JSON.stringify(value)}]}}],usageMetadata:{promptTokenCount:900,candidatesTokenCount:60}});
const service={status:'connected',session:{serverVersion:Number(query.get('version')||71),driveConnected:true,ranobeDriveAudio:query.get('audio')==='1'},
 submit:async job=>{window.submitted.push(job);return {id:'task'};},
 request:async(path,{body}={})=>{
  window.requests.push(path);
  if(path==='/reader/google/speak'){window.speak.push(body);return tone();}
  if(path==='/ranobe/chapter')return {title:'Глава '+body.url.slice(-1),language,paragraphs};
  if(path==='/reader/google/generate'){
   const system=body.request.systemInstruction.parts[0].text,user=body.request.contents[0].parts[0].text;
   if(system.includes('кастинг-директор'))return answer({tone:'городское фэнтези',pov:'third',narratorName:'',narrator:{gender:'m',age:'adult',style:'спокойный',timbre:'warm',pitch:0,energy:0,pace:1,voice:'тёплый баритон',geminiVoice:'Charon'},
    characters:[{name:'Мирэй',aliases:[],gender:'f',age:'young',importance:'main',traits:'вспыльчивая',speech:'резко',timbre:'bright',pitch:1,energy:1,pace:1.05,voice:'звонкий девичий голос',geminiVoice:'Zephyr'},
     {name:'Кайто',aliases:[],gender:'m',age:'young',importance:'main',traits:'добряк',speech:'мягко',timbre:'warm',pitch:0,energy:-1,pace:.97,voice:'мягкий юношеский голос',geminiVoice:'Achird'}],lexicon:[]});
   if(system.includes('помощник режиссёра')){
    const lines=user.split('Сегменты:\n')[1].split('\n').map(l=>/^(\d+) ([NSTQ]) (.*)$/.exec(l)).filter(Boolean),known=/^1 Мирэй/m.test(user);
    return answer({lines:lines.filter(([,,k])=>k!=='N').map(([,i,,text])=>i+'|S|'+(/Мирэй|опоздал/.test(text)?(known?'1':'Мирэй'):(known?'2':'Кайто'))+'|neutral|5'),moods:[],cast:known?[]:['Мирэй|f|young|звонкий','Кайто|m|young|мягкий']});
   }
   if(system.includes('ведёшь список персонажей'))return answer({same:[],characters:[]});
   throw Error('mock: unexpected model request');
  }
  throw Error('unexpected '+path);
 }};
const item={id:'ranobe:1',title:'Повелитель',kind:'ranobe',authors:['Маруяма'],description:'Фэнтези.'};
const state={admin:true,catalog:{items:[]},libraryId:'library-fixture',user:{sub:'fixture'}};
createRoot(document.getElementById('root')).render(<div className="export-sheet" style={{position:'static',maxWidth:460,margin:16}}><div className="export-sheet-body"><RanobeExport item={item} book={book} service={service} state={state} destination={query.get('destination')||'local'}/></div></div>);
