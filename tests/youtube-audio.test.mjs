import test from 'node:test';import assert from 'node:assert/strict';
import {youtubeIdentity,openYouTubeAudio} from '../src/youtube-audio.js';
const id='dQw4w9WgXcQ',token='a'.repeat(43),resource='b'.repeat(16),server='https://media.example';
test('YouTube input normalizes a single identity without trusting arbitrary hosts',()=>{
 for(const url of ['https://youtu.be/'+id+'?t=15','https://music.youtube.com/watch?v='+id,'https://www.youtube.com/shorts/'+id])assert.equal(youtubeIdentity(url),id);
 for(const url of ['https://youtube.com.evil/watch?v='+id,'http://youtube.com/watch?v='+id,'https://user:pass@youtube.com/watch?v='+id,'https://youtube.com/watch?v='+id+'&v=duplicate'])assert.equal(youtubeIdentity(url),null);
});
test('only same-server capabilities are accepted; abort and close release the session',async()=>{
 const calls=[],data={id:token,streamUrl:'/online/'+token+'/'+resource,mime:'audio/mp4'};
 const service={server,request:async(p,o)=>{calls.push([p,o]);return data;}};
 const lease=await openYouTubeAudio(service,id);assert.equal(lease.streamUrl,server+data.streamUrl);await lease.close();assert.equal(calls.at(-1)[0],'/online/'+token);
 data.streamUrl='https://evil.example/stream';await assert.rejects(openYouTubeAudio(service,id));assert.equal(calls.at(-1)[0],'/online/'+token);
 data.streamUrl='/online/'+token+'/'+resource;const abort=new AbortController();abort.abort();await assert.rejects(openYouTubeAudio(service,id,{signal:abort.signal}));assert.equal(calls.at(-1)[0],'/online/'+token);
});
