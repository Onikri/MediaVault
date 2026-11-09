// Ranobe page + reader + narration. Server answers are fixtures; the Google
// role pass is a labelled mock; speech synthesis is the real Supertonic model.
import React from 'react';
import {createRoot} from 'react-dom/client';
import '/src/styles.css';import '/src/site-layout.css';import '/src/interface-refinement.css';
import RanobeSources from '/src/RanobeSources.jsx';
import {RetainedMediaProvider,VideoDock} from '/src/RetainedMedia.jsx';
const paragraphs=['Ночь опустилась на город, и только в окне старой библиотеки ещё горел свет.','— Ты опять опоздал, — недовольно сказала Мирэй.','— Прости, я заблудился, — виновато ответил Кайто.','Ветер принёс запах дождя.'];
const book={provider:'ranobehub',providerName:'RanobeHub',kind:'ranobe',title:'Повелитель',aliases:['Повелитель'],url:'https://ranobehub.org/ranobe/206',language:'ru',
 episodes:[1,2].map(n=>({number:n,season:1,title:'Глава '+n,url:'https://ranobehub.org/ranobe/206?mv_chapter='+n,language:'ru',translator:''})),seasons:[{number:1,name:'Том 1'}]};
window.requests=[];window.speak=[];
// ?engine=gemini: a v59 server whose /reader/google/speak streams a MOCK tone
// (not Gemini audio) in three chunks, like the Live relay streams PCM.
const gemini=new URLSearchParams(location.search).get('engine')==='gemini';
function tone(){
 const rate=24000,samples=new Int16Array(rate*(new URLSearchParams(location.search).get('tray')?1.6:.45));for(let i=0;i<samples.length;i++)samples[i]=Math.sin(i/rate*2*Math.PI*220)*8000;
 const bytes=new Uint8Array(samples.buffer),cuts=[0,4801,9600,bytes.length];
 return new Response(new ReadableStream({async start(c){for(let i=0;i<3;i++){await new Promise(r=>setTimeout(r,60));c.enqueue(bytes.slice(cuts[i],cuts[i+1]));}c.close();}}));
}
const service={status:'connected',session:{serverVersion:gemini?59:58},request:async(path,{body}={})=>{
 window.requests.push(path);
 if(path==='/reader/google/speak'){window.speak.push(body);return tone();}
 if(path==='/ranobe/search')return {results:[{provider:'ranobehub',providerName:'RanobeHub',language:'ru',title:'Повелитель',aliases:['Overlord'],url:book.url}],providers:[]};
 if(path==='/ranobe/inspect')return book;
 if(path==='/ranobe/chapter')return {title:'Глава '+body.url.slice(-1),language:'ru',paragraphs};
 // MOCK Google answers (not model output): a title bible for the bible model,
 // speakers and emotions for the chapter model. Real models are tested live separately.
 if(path==='/reader/google/generate'){
  const answer=value=>({candidates:[{content:{parts:[{text:JSON.stringify(value)}]}}]});
  const user=JSON.parse(body.request.contents[0].parts[0].text);
  if('opening' in user)return answer({tone:'городское фэнтези',narrator:{gender:'m',age:'adult',style:'спокойный',timbre:'warm',pitch:0,energy:0,pace:1},
   characters:[{name:'Мирэй',aliases:['Мирэй-сан'],gender:'f',age:'young',importance:'main',traits:'вспыльчивая, но заботливая',speech:'резко, коротко',timbre:'bright',pitch:1,energy:1,pace:1.05},
    {name:'Кайто',aliases:[],gender:'m',age:'young',importance:'main',traits:'рассеянный добряк',speech:'мягко, виновато',timbre:'warm',pitch:0,energy:-1,pace:.97}],
   lexicon:[{word:'Мирэй',stressed:'Мирэ́й'}]});
  if('segments' in user){const req=user;
   return answer({characters:[],lines:req.segments.map(s=>({i:s.i,speaker:s.kind==='narration'?'':/Мирэй/.test(JSON.stringify(req.segments))&&s.i===1?'Мирэй':s.i===3?'Кайто':s.guess||'',emotion:s.i===1?'angry':s.i===3?'pleading':'calm',intensity:s.kind==='narration'?.4:.7}))});}
  throw Error('mock: unexpected model '+body.model);
 }
 throw Error('unexpected '+path);
}};
localStorage.setItem('mv_lmt_settings:fixture',JSON.stringify({engine:'vm'}));
const title=<RanobeSources item={{id:'ranobe:1',title:'Повелитель',aliases:['Overlord'],kind:'ranobe',ids:{}}} service={service} state={{user:{sub:'fixture'}}}/>;
// ?tray=1: the site workspace with its tray, and a second page to leave to.
function Site(){
 const [page,setPage]=React.useState('title');
 React.useEffect(()=>{const back=()=>setPage('title');addEventListener('hashchange',back);return()=>removeEventListener('hashchange',back);},[]);
 return <RetainedMediaProvider><header className="fixture-header" style={{display:"flex",justifyContent:"flex-end",gap:8,padding:8}}><VideoDock/><button type="button" onClick={()=>setPage(p=>p==='title'?'other':'title')}>{page==='title'?'Другая страница':'К тайтлу'}</button></header>{page==='title'?title:<p className="fixture-other">Другая страница сайта</p>}</RetainedMediaProvider>;
}
createRoot(document.getElementById('root')).render(new URLSearchParams(location.search).get('tray')?<Site/>:title);
