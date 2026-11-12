// Collaps embed pages are fixtures (tests/fixtures/players, captured 2026-11-08);
// the CDN answers are synthetic. Live playback was measured separately.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {collapsSelection,collapsStream,pageToken,preferAudio,directMaster,prepareCollaps} from '../src/collaps-direct.js';

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
 assert.equal(data.direct,true);assert.equal(data.type,'hls');assert.deepEqual(data.qualities,[720,360]);
 assert.deepEqual(data.audioNames,['rus0','ukr1'],'the dubs inside the stream, in the order Collaps numbers them');
 assert.match(data.url,/^blob:/);assert.deepEqual(asked.map(a=>a[1]),['omit','omit']);
 URL.revokeObjectURL(data.url);
 await assert.rejects(prepareCollaps('https://api.nextembed.ws/embed/movie/181',{fetcher}),/HTTP 410/);
});
