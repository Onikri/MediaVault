import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import '/src/styles.css';
import ControlCenter from '/src/control/ControlCenter.jsx';
import {compileMangaPolicy} from '/src/manga-tag-policy.js';
const initial={schemaVersion:1,excludedTerms:['Hidden phrase'],excludedPrefixes:[],tags:[{key:'journey',label:'Путешествие',aliases:['Journey','旅','여행'],category:'genre'}]};
let policy=structuredClone(initial),revision='a'.repeat(64);window.__contentCalls=[];
const service={server:location.origin,status:'connected',jobs:[],session:{serverVersion:74},request:async(path,options={})=>{
 window.__contentCalls.push({path,method:options.method||'GET'});
 if(path==='/admin/content')return {policy:structuredClone(policy),revision,job:{state:'idle'},scope:'all'};
 if(path==='/admin/content/policy'){if(options.body.revision!==revision)throw Error('Revision conflict');policy=structuredClone(options.body.policy);revision='b'.repeat(64);window.__savedContent=policy;return {policy,revision,reindexedTitles:6};}
 if(path.startsWith('/admin/content/vocabulary'))return {items:[{label:'Ecology',works:6,sources:['fixture.example'],kinds:['movie','tv','anime','manga','ranobe','book'],keys:[],category:'genres'}]};
 if(path==='/manga/tag-policy'){const compiled=compileMangaPolicy(policy);return {scope:'all',revision:'public-'+revision,policy:{...policy,tags:policy.tags.filter(row=>compiled.key(row.label)),excludedTerms:[],excludedPrefixes:[]}};}
 if(path==='/admin/content/refresh')return {state:'done',completed:1,total:1,indexed:6,sources:[{domain:'fixture.example',name:'Fixture',status:'partial',matched:1,indexed:6}]};
 if(path==='/rooms')return {rooms:[]};if(path==='/guests')return {guests:[]};if(path==='/guests/activity')return {guests:{}};
 return {};
}};
function Harness(){const [guest,setGuest]=useState(false);window.__guest=()=>setGuest(true);return <ControlCenter state={guest?{}:{admin:true,user:{sub:'fixture-owner',given_name:'Владелец'}}} guest={guest?{guest:{login:'reader',name:'Читатель'}}:null} service={service} initialTab="content" panels={{account:<p>Профиль читателя</p>}}/>;}
createRoot(document.getElementById('root')).render(<Harness/>);
