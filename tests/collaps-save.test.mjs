// Saving Collaps through the browser: synthetic CDN answers and a fake server.
// The server half (real ffmpeg remux and Drive import) is tests/test_staged_video.py.
import test from 'node:test';
import assert from 'node:assert/strict';
import {collapsTracks,stageCollaps,saveCollapsToDrive} from '../src/collaps-save.js';

const MASTER=`#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="rus0",DEFAULT=YES,AUTOSELECT=YES,URI="a0/index.m3u8?t=1"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="ukr1",DEFAULT=NO,AUTOSELECT=NO,URI="a1/index.m3u8?t=1"
#EXT-X-STREAM-INF:BANDWIDTH=1055277,RESOLUTION=1280x720,AUDIO="a"
v720/index.m3u8?t=1
#EXT-X-STREAM-INF:BANDWIDTH=416687,RESOLUTION=640x360,AUDIO="a"
v360/index.m3u8?t=1
`;
const MEDIA='#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\ns0.ts\n#EXTINF:2,\ns1.ts\n#EXT-X-ENDLIST\n';
const BASE='https://cdn.example/m/master.m3u8?a=1&tok42';

test('the chosen quality cap and dub pick the tracks the server will remux',()=>{
 assert.deepEqual(collapsTracks(MASTER,BASE,{audio:1}),{video:'https://cdn.example/m/v720/index.m3u8?t=1',audio:'https://cdn.example/m/a1/index.m3u8?t=1',height:720});
 assert.deepEqual(collapsTracks(MASTER,BASE,{quality:'480'}),{video:'https://cdn.example/m/v360/index.m3u8?t=1',audio:'https://cdn.example/m/a0/index.m3u8?t=1',height:360});
 assert.throws(()=>collapsTracks(MASTER,BASE,{quality:'240'}),/качества/);
 assert.deepEqual(collapsTracks(MEDIA,BASE),{video:BASE,audio:null,height:null});
});

function world({segmentStatus=200}={}){
 const calls=[],fetched=[];
 const fetcher=async(url,init)=>{fetched.push([url,init.credentials]);
  if(url==='https://api.nextembed.ws/embed/movie/180')return new Response('var lok = 1, k1= "tok42"; makePlayer({source:{hls:"https://cdn.example/m/master.m3u8?a=1"}})');
  if(url===BASE)return new Response(MASTER);
  if(url.endsWith('index.m3u8?t=1'))return new Response(MEDIA);
  if(url.endsWith('.ts'))return new Response(segmentStatus===200?new Uint8Array([0x47,1,2]):'',{status:segmentStatus});
  return new Response('',{status:404});};
 let state='staging',polls=0;
 const service={session:{serverVersion:63},server:'https://vm.example',
  async request(path,{method='GET',body}={}){calls.push([method,path,body]);
   if(path==='/online/exports'&&method==='POST')return {id:'e'.repeat(32),state:'staging',resources:['https://cdn.example/m/v720/s0.ts','https://cdn.example/m/v720/s1.ts','https://cdn.example/m/a1/s0.ts','https://cdn.example/m/a1/s1.ts']};
   if(path.includes('/segments/'))return {state:'staging'};
   if(path.endsWith('/start')){state='queued';return {state};}
   if(method==='DELETE'){state='cancelled';return {state};}
   if(path.startsWith('/jobs/'))return {status:'running'};
   polls++;
   if(state==='queued'){state='done';return {state:'running'};}
   if(state==='done'&&polls>2)return {state:'taken'};
   return {id:'e'.repeat(32),state,downloadUrl:'/online/exports/file/cap',filename:'Фильм.mp4'};
  },
  submitted:[],async submit(job){this.submitted.push(job);return {id:'task-1'};}};
 return {calls,fetched,fetcher,service};
}

test('the browser fetches every listed segment itself and the server assembles them',async()=>{
 const {calls,fetched,fetcher,service}=world(),progress=[];
 const job=await stageCollaps(service,'https://api.nextembed.ws/embed/movie/180?mv_audio=1',{fetcher,onProgress:text=>progress.push(text)});
 assert.equal(job.state,'done');
 const post=calls.find(c=>c[1]==='/online/exports');
 assert.equal(post[2].stream.video.url,'https://cdn.example/m/v720/index.m3u8?t=1');
 assert.equal(post[2].stream.audio.url,'https://cdn.example/m/a1/index.m3u8?t=1');
 assert.deepEqual(calls.filter(c=>c[0]==='PUT').map(c=>c[1]).sort(),[0,1,2,3].map(i=>'/online/exports/'+'e'.repeat(32)+'/segments/'+i));
 assert.ok(fetched.every(([,credentials])=>credentials==='omit'));
 assert.match(progress.at(-1),/собирает MP4/);
});

test('a refused segment stops the transfer and releases the server job',async()=>{
 const {calls,fetcher,service}=world({segmentStatus:410});
 await assert.rejects(stageCollaps(service,'https://api.nextembed.ws/embed/movie/180',{fetcher}),/HTTP 410/);
 assert.ok(calls.some(c=>c[0]==='DELETE'));
 assert.ok(!calls.some(c=>c[1].endsWith('/start')));
});

test('each episode becomes a normal Drive import that takes the browser-delivered file',async()=>{
 const {fetcher,service}=world(),url='https://api.nextembed.ws/embed/movie/180?mv_audio=1';
 const original=globalThis.fetch;globalThis.fetch=fetcher;
 try{await saveCollapsToDrive({service,job:{version:3,quality:'best',entries:[]},entries:[{number:1,url,season:1}]});}
 finally{globalThis.fetch=original;}
 assert.equal(service.submitted.length,1);
 assert.deepEqual(service.submitted[0].entries,[{number:1,url,season:1,export:'e'.repeat(32)}]);
 assert.equal(service.submitted[0].episodes,'1');
});

test('an outdated server is told to update before anything is fetched',async()=>{
 const {fetched,fetcher,service}=world();service.session.serverVersion=62;
 await assert.rejects(stageCollaps(service,'https://api.nextembed.ws/embed/movie/180',{fetcher}),/версии 63/);
 assert.equal(fetched.length,0);
});
