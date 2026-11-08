// Fixture harness for the owner control center. Every server answer below is
// a fixture: no account, no VM, no media. Used by control-center-browser.cjs.
import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import '/src/styles.css';import '/src/title-page.css';import '/src/import-layout.css';import '/src/discovery-polish.css';import '/src/site-layout.css';import '/src/site-mobile.css';import '/src/interface-refinement.css';
import {ThemeProvider,AppearanceSettings} from '/src/blossom/ThemeProvider.tsx';
import ControlCenter from '/src/control/ControlCenter.jsx';

const now=Math.floor(Date.now()/1000),cover='/src/blossom/blossom.jpg';
const day=i=>new Date(Date.now()-(29-i)*86400000).toISOString().slice(0,10);
const rules={rooms:{limit:16,perOwner:2,members:8,hours:6,guestsMayHost:true},guests:{days:30,watch:true,read:true}};
const db={
 rules:structuredClone(rules),
 guests:[
  {id:'a1',name:'Аня',login:'anya',createdAt:now-86400*20,expiresAt:now+86400*12,disabled:false,expired:false,enrolled:true,lastSeen:now-60,access:{scope:'all',watch:true,read:true,titles:[]}},
  {id:'b2',name:'Боря',login:'borya',createdAt:now-86400*40,expiresAt:null,disabled:false,expired:false,enrolled:true,lastSeen:now-7200,access:{scope:'titles',watch:true,read:false,titles:[{key:'anime:20',title:'Наруто',cover}]}},
  {id:'c3',name:'Вика',login:'',createdAt:now-3600,expiresAt:now+86400*7,disabled:false,expired:false,enrolled:false,lastSeen:null,access:{scope:'all',watch:true,read:true,titles:[]}},
  {id:'d4',name:'Гоша',login:'gosha',createdAt:now-86400*90,expiresAt:now-86400,disabled:false,expired:true,enrolled:true,lastSeen:now-86400*3,access:{scope:'all',watch:true,read:true,titles:[]}},
 ],
 activity:{
  a1:{watching:{category:'video',title:'Магическая битва',since:now-1520},lastActive:now-30,bytesToday:1.8e9,bytesMonth:24.6e9,titles:14,lastAddress:'93.103.12.40',lastAgent:'Mozilla/5.0 (Windows NT 10.0) Chrome/130'},
  b2:{watching:null,lastActive:now-7200,bytesToday:0,bytesMonth:8.1e9,titles:5,lastAddress:'188.230.5.7',lastAgent:'Mozilla/5.0 (iPhone) Safari/605'},
  d4:{watching:null,lastActive:now-86400*3,bytesToday:0,bytesMonth:1.2e9,titles:2},
 },
 rooms:[
  {id:'room-one',title:'Фрирен, провожающая в последний путь — 12 серия',malId:'52991',owner:'me',guest:'',createdAt:now-2400,expiresAt:now+4*3600+600,position:812,duration:1420,rate:1,playing:true,held:false,type:'hls',online:true,messages:23,everyone:false,waitAll:true,hostOnline:true,
   members:[{id:'h',name:'Ведущий',host:true,online:true,buffering:false,voice:true,muted:false,avatar:''},{id:'m1',name:'Аня',host:false,online:true,buffering:false,voice:true,muted:true,avatar:''},{id:'m2',name:'Лёша',host:false,online:true,buffering:true,voice:false,muted:false,avatar:''},{id:'m3',name:'Катя',host:false,online:false,buffering:false,voice:false,muted:false,avatar:''}]},
  {id:'room-two',title:'Наруто — 3 серия',malId:'20',owner:'guest:b2',guest:'b2',createdAt:now-600,expiresAt:now+5*3600,position:301,duration:1380,rate:1,playing:false,held:false,type:'mp4',online:true,messages:2,everyone:true,waitAll:false,hostOnline:true,
   members:[{id:'h2',name:'Боря',host:true,online:true,buffering:false,voice:false,muted:false,avatar:''},{id:'m4',name:'Дима',host:false,online:true,buffering:false,voice:false,muted:false,avatar:''}]},
 ],
};
const report={summary:{bytesToday:1.8e9,bytesWeek:9.2e9,bytesMonth:24.6e9,bytes:61e9,requests:18422,titles:14,addresses:3,lastAddress:'93.103.12.40',lastAgent:'Mozilla/5.0 (Windows NT 10.0) Chrome/130',watching:{category:'video',title:'Магическая битва',since:now-1520},lastActive:now-30},
 days:Array.from({length:30},(_,i)=>({day:day(i),bytes:i%4===0?0:Math.round((Math.sin(i/3)+1.4)*6e8),requests:200+i*13})),
 categories:{video:21e9,manga:2.6e9,music:0.9e9,api:0.1e9},
 titles:[{key:'anime:40748',title:'Магическая битва',kind:'anime',mal:'40748',cover,opens:9,plays:14,bytes:14e9,first:now-86400*12,last:now-30},{key:'manga:2',title:'Берсерк',kind:'manga',mal:'2',cover,opens:3,plays:0,bytes:2.6e9,first:now-86400*5,last:now-86400*2}],
 addresses:[{ip:'93.103.12.40',agent:'Mozilla/5.0 (Windows NT 10.0) Chrome/130',first:now-86400*20,last:now-30,requests:14000,bytes:50e9},{ip:'188.230.5.7',agent:'Mozilla/5.0 (Android 14) Chrome/130',first:now-86400*4,last:now-86400,requests:4422,bytes:11e9}],
 events:[{t:now-1520,action:'Запустил видео',title:'Магическая битва',ip:'93.103.12.40'},{t:now-1600,action:'Открыл тайтл',title:'Магическая битва',ip:'93.103.12.40'},{t:now-86400,action:'Вошёл по паролю',ip:'188.230.5.7',detail:'Mozilla/5.0 (Android 14) Chrome/130'},{t:now-86400*2,action:'Попытка открыть закрытый тайтл',title:'Ван-Пис'}]};
const jobs=[
 {id:'j1',status:'running',created:now-900,updated:now-20,progress:{title:'Магическая битва',taskType:'import',total:24,saved:9,phase:'uploading',file:'Jujutsu.Kaisen.S01E10.mkv'}},
 {id:'j2',status:'queued',created:now-500,updated:now-500,progress:{title:'Берсерк',taskType:'import',total:12}},
 {id:'j3',status:'waiting_auth',created:now-86400,updated:now-3600,progress:{title:'Ковбой Бибоп',taskType:'import',total:26,saved:20}},
 {id:'j4',status:'completed',created:now-86400*2,updated:now-86400,progress:{title:'Библиотека',taskType:'enrich',total:120,cursor:120}},
];
window.__controlCalls=[];
const reply=v=>new Promise(r=>setTimeout(()=>r(structuredClone(v)),120));
async function request(path,{method='GET',body}={}){
 window.__controlCalls.push(method+' '+path);
 const fail=(window.__controlFail||{})[path];if(fail)throw Object.assign(Error(fail),{status:500});
 if(path==='/health')return reply({version:53,controlCenter:true,siteRules:true});
 if(path==='/rooms')return reply({rooms:db.rooms,rules:db.rules.rooms});
 if(path.startsWith('/rooms/')&&method==='DELETE'){db.rooms=db.rooms.filter(r=>'/rooms/'+r.id!==path);return reply({closed:true});}
 if(path==='/guests'&&method==='POST'){const g={id:'n'+Date.now(),name:body.name,login:'',createdAt:now,expiresAt:body.days?now+body.days*86400:null,disabled:false,expired:false,enrolled:false,lastSeen:null,access:{scope:'all',watch:db.rules.guests.watch,read:db.rules.guests.read,titles:[]}};db.guests.unshift(g);return reply({guest:g,invite:'fixture-invite-token'});}
 if(path==='/guests')return reply({guests:db.guests});
 if(path==='/guests/activity')return reply({guests:db.activity});
 if(/^\/guests\/\w+\/activity$/.test(path))return reply(report);
 if(/^\/guests\/\w+\/invite$/.test(path))return reply({invite:'fixture-reinvite'});
 if(/^\/guests\/\w+$/.test(path)&&method==='POST'){const g=db.guests.find(x=>'/guests/'+x.id===path);Object.assign(g,body.disabled!=null?{disabled:body.disabled}:{},body.access?{access:body.access}:{});return reply({guest:g});}
 if(/^\/guests\/\w+$/.test(path)&&method==='DELETE'){db.guests=db.guests.filter(x=>'/guests/'+x.id!==path);return reply({});}
 if(path==='/google/connection')return reply({configured:true,state:'ready',checkedAt:now-5400});
 if(path==='/admin/rules'&&method==='PUT'){db.rules=structuredClone(body);return reply({rules:db.rules,defaults:rules});}
 if(path==='/admin/rules')return reply({rules:db.rules,defaults:rules});
 if(path.startsWith('/metadata/posters'))return reply({'52991':{cover},'20':{cover}});
 return reply({});
}
const service={status:'connected',session:{role:'owner',serverVersion:53},server:'https://fixture.test',jobs,active:true,request,cancel:async()=>{},resume:async()=>{},connect:async()=>{}};
const state={user:{given_name:'Рома',name:'Рома',email:'owner@example.test',sub:'fixture-owner'},admin:true,catalog:null};
const card=(title,text)=><section className="settings-card"><h2>{title}</h2><p className="fine">{text}</p></section>;
function Harness(){
 const [tab]=useState(()=>new URLSearchParams(location.search).get('tab')||'overview');
 return <ThemeProvider><div className="app-shell" data-view="profile"><main className="app-main">
  <ControlCenter state={state} service={service} initialTab={tab} onLogout={()=>{}} onOpenRoom={id=>{window.__openedRoom=id;}} panels={{
   account:card('Рома','owner@example.test — вход через Google выполнен.'),appearance:<AppearanceSettings/>,
   storage:card('Подключение к серверу','Фикстура раздела хранилища.'),sources:card('Kodik API','Фикстура раздела источников.'),privacy:card('Это устройство','Фикстура раздела устройства.'),
  }}/>
 </main></div></ThemeProvider>;
}
createRoot(document.getElementById('root')).render(<Harness/>);
