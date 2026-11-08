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
const service={status:'connected',session:{serverVersion:55},request:async(path,{body}={})=>{
 window.requests.push(path);
 if(path==='/ranobe/search')return {results:[{provider:'ranobehub',providerName:'RanobeHub',language:'ru',title:'Повелитель',aliases:['Overlord'],url:book.url}],providers:[]};
 if(path==='/ranobe/inspect')return book;
 if(path==='/ranobe/chapter')return {title:'Глава '+body.url.slice(-1),language:'ru',paragraphs};
 if(path==='/reader/google/generate')throw Error('mock: no key');
 throw Error('unexpected '+path);
}};
localStorage.setItem('mv_lmt_settings:fixture',JSON.stringify({engine:'vm'}));
createRoot(document.getElementById('root')).render(<RanobeSources item={{id:'ranobe:1',title:'Повелитель',aliases:['Overlord'],kind:'ranobe',ids:{}}} service={service} state={{user:{sub:'fixture'}}}/>);
