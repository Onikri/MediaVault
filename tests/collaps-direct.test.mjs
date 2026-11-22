// Collaps embed pages are fixtures (tests/fixtures/players, captured 2026-11-08);
// the CDN answers are synthetic. Live playback was measured separately.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {collapsSelection,collapsStream,pageToken,preferAudio,directMaster,prepareCollaps} from '../src/collaps-direct.js';
import {isCollapsSlate,SLATE_WIDTH,SLATE_HEIGHT,watchCollapsFrames} from '../src/collaps-video-guard.js';

const serial=readFileSync(new URL('./fixtures/players/collaps_serial.html',import.meta.url),'utf8');
const MASTER=`#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="rus0",DEFAULT=YES,AUTOSELECT=YES,URI="a0/index.m3u8?t=1"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="ukr1",DEFAULT=NO,AUTOSELECT=NO,URI="a1/index.m3u8?t=1"
#EXT-X-STREAM-INF:BANDWIDTH=1055277,RESOLUTION=1280x720,AUDIO="a"
v720/index.m3u8?t=1
#EXT-X-STREAM-INF:BANDWIDTH=416687,RESOLUTION=640x360,AUDIO="a"
https://x-bc.example/v360/index.m3u8?t=1
`;

test('only Collaps embed pages with our selectors are played directly',()=>{
 assert.deepEqual(collapsSelection('https://api.nextembed.ws/embed/serial/255?mv_audio=2&mv_season=1&mv_episode=3'),{embed:'https://api.nextembed.ws/embed/serial/255',audio:2,season:1,episode:3});
 assert.equal(collapsSelection('https://ashdi.vip/vod/1'),null);
 assert.equal(collapsSelection('http://api.nextembed.ws/embed/movie/1'),null);
 assert.equal(collapsSelection('https://api.nextembed.ws/other/movie/1'),null);
});
test('the chosen season and episode give their own stream',()=>{
 const first=collapsStream(serial,{season:1,episode:1}),second=collapsStream(serial,{season:1,episode:2});
 assert.match(first,/^https:\/\//);assert.notEqual(first,second);
 assert.equal(collapsStream(serial,{season:99,episode:1}),null);
 assert.equal(collapsStream('var x={hls:"https://cdn.example/master.m3u8?a=1"}',{}),'https://cdn.example/master.m3u8?a=1');
 assert.equal(pageToken('var lok = 1, abc123def= "8d90e12a";'),'8d90e12a');
});
test('the chosen dub becomes default and addresses become absolute',()=>{
 const text=directMaster(preferAudio(MASTER,1),'https://cdn.example/m/master.m3u8');
 assert.match(text,/NAME="ukr1",DEFAULT=YES,AUTOSELECT=YES,URI="https:\/\/cdn\.example\/m\/a1\/index\.m3u8\?t=1"/);
 assert.match(text,/NAME="rus0",DEFAULT=NO/);
 assert.match(text,/^https:\/\/cdn\.example\/m\/v720\/index\.m3u8\?t=1$/m);
 const capped=directMaster(MASTER,'https://cdn.example/m/master.m3u8',360);
 assert.doesNotMatch(capped,/v720/);assert.match(capped,/v360/);
 assert.throws(()=>directMaster(MASTER,'https://cdn.example/',240),/качества/);
 assert.throws(()=>directMaster('#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k"\n','https://cdn.example/'),/Зашифрованные/);
});
test('the browser opens the embed and the stream itself, with the page token',async()=>{
 const asked=[];
 const fetcher=async(url,init)=>{asked.push([url,init.credentials]);
  if(url==='https://api.nextembed.ws/embed/movie/180')return new Response('var lok = 1, k1= "tok42"; makePlayer({source:{hls:"https://cdn.example/m/master.m3u8?a=1"}})');
  if(url==='https://cdn.example/m/master.m3u8?a=1&tok42')return new Response(MASTER);
  return new Response('',{status:410});};
 const data=await prepareCollaps('https://api.nextembed.ws/embed/movie/180?mv_audio=0',{fetcher});
 assert.equal(data.direct,true);assert.equal(data.type,'hls');assert.deepEqual(data.qualities,[720,360]);assert.equal(data.guardSlate,false);
 assert.deepEqual(data.audioNames,['rus0','ukr1'],'the dubs inside the stream, in the order Collaps numbers them');
 assert.match(data.url,/^blob:/);assert.deepEqual(asked.map(a=>a[1]),['omit','omit']);
 URL.revokeObjectURL(data.url);
 await assert.rejects(prepareCollaps('https://api.nextembed.ws/embed/movie/181',{fetcher}),/HTTP 410/);
});

test('the current Collaps mirror keeps VTT tracks scoped to the selected season and episode',async()=>{
 const embed='https://api.embf.net/embed/movie/123';
 const hls='https://media.example/season-2/master.m3u8';
 const seasons=[{season:2,episodes:[
  {episode:1,hls,cc:[{name:'Eng. full - 1',url:'https://media.example/one.vtt'}]},
  {episode:2,hls,cc:[{name:'Рус. полные - 2',url:'https://media.example/two.vtt?token=fixture'},{name:'Unsafe',url:'https://name:password@media.example/two.vtt'}]},
 ]}];
 const fetcher=async url=>{
  if(url===embed)return new Response('makePlayer({seasons:'+JSON.stringify(seasons)+'})');
  assert.equal(url,hls);
  return new Response('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360\n360.m3u8');
 };
 const data=await prepareCollaps(embed+'?mv_season=2&mv_episode=2&mv_audio=1',{fetcher});
 try{assert.deepEqual(data.subtitles,[{id:'collaps-cc-0',name:'Рус. полные',language:'ru',url:'https://media.example/two.vtt?token=fixture'}]);}
 finally{URL.revokeObjectURL(data.url);}
});

test('Blacklist playback enables slate detection for every season and keeps HD available',async()=>{
 const embed='https://api.embf.net/embed/movie/2491';
 const cdn='https://media.example';
 const seasons=[1,10].map(season=>({season,episodes:[
  {episode:7,hls:cdn+'/'+season+'/master.m3u8',cc:[{name:'Eng. full',url:cdn+'/english.vtt'}]},
 ]}));
 const fetcher=async url=>{
  if(url===embed)return new Response('makePlayer({seasons:'+JSON.stringify(seasons)+'})');
  return new Response(MASTER);
 };
 for(const season of [1,10]){
  const data=await prepareCollaps(embed+'?mv_season='+season+'&mv_episode=7&mv_audio=1',{quality:'720',fetcher});
  try{
   const playlist=await fetch(data.url).then(response=>response.text());
   assert.equal(data.guardSlate,true);
   assert.deepEqual(data.qualities,[720,360]);
   assert.match(playlist,/NAME="ukr1",DEFAULT=YES,AUTOSELECT=YES/);
   assert.equal(data.subtitles[0].url,cdn+'/english.vtt');
  }finally{URL.revokeObjectURL(data.url);}
 }
});

function slateFrame(){
 const gray=[
  'fdfffffffffeeeff', 'fbcdeffffffa9aef', 'fffeeeeeffea89ef',
  '7cfdcbcccdd989ef', '259cdddcdeeaaadf', '55769cefffea99df',
  '655566afffd565bf', '554359ceeeebbbdf','3446beeeeeeeeeff',
 ].join('');
 return Uint8ClampedArray.from([...gray].flatMap(value=>{
  const l=parseInt(value,16)*17;
  return [l,l,l,255];
 }));
}

test('the slate guard requires both image areas and stops checking after one rejection',()=>{
 const frame=slateFrame(), white=new Uint8ClampedArray(SLATE_WIDTH*SLATE_HEIGHT*4).fill(255);
 assert.equal(isCollapsSlate(frame),true);
 assert.equal(isCollapsSlate(white),false);
 const missingQr=frame.slice();
 for(let y=0;y<4;y++)missingQr.fill(255,(y*SLATE_WIDTH+11)*4,(y*SLATE_WIDTH+16)*4);
 assert.equal(isCollapsSlate(missingQr),false);
 let current=white, rejected=0;
 const video=Object.assign(new EventTarget(),{readyState:2,videoWidth:1280,seeking:false,
  ownerDocument:{createElement:()=>({getContext:()=>({drawImage(){},getImageData:()=>({data:current})})})}});
 const stop=watchCollapsFrames(video,()=>rejected++);
 video.dispatchEvent(new Event('loadeddata'));
 assert.equal(rejected,0);
 current=frame;
 video.dispatchEvent(new Event('seeked'));
 video.dispatchEvent(new Event('playing'));
 assert.equal(rejected,1);
 stop();
});
