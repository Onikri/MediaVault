// Source choice when the viewer picks another voice during playback. Pure logic;
// the browser contract is tests/voice-switch-browser.cjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import {streamKey,inStreamAudio,keepsLoadedMedia,voiceSwitchState} from '../src/voice-switch.js';
import {audioNames} from '../src/collaps-direct.js';

const collaps=(audio,episode=3,season=1)=>'https://api.nextembed.ws/embed/serial/255?mv_audio='+audio+'&mv_season='+season+'&mv_episode='+episode;
const ALLOHA='https://alloha.yani.tv/?token=x&translation=66&season=1&episode=3';
const KODIK='https://kodik.info/serial/1/abc/720p?translation=610&season=1&episode=3';

test('dubs of one Collaps episode share a stream; other balancers and episodes do not',()=>{
 assert.equal(streamKey(collaps(0)),streamKey(collaps(2)));
 assert.notEqual(streamKey(collaps(0,3)),streamKey(collaps(0,4)));
 assert.notEqual(streamKey(collaps(0,3,1)),streamKey(collaps(0,3,2)));
 assert.equal(streamKey(KODIK),KODIK);
 assert.notEqual(streamKey(ALLOHA),streamKey(KODIK));
 assert.equal(streamKey(undefined),'');
});

test('Collaps dub names come from the master in order, without duplicates across quality groups',()=>{
 const master='#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="AniLibria",DEFAULT=YES,URI="a0.m3u8"\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Dream Cast",DEFAULT=NO,URI="a1.m3u8"\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="b",NAME="AniLibria",DEFAULT=YES,URI="b0.m3u8"\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="s",NAME="Русские",URI="s.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="a"\nv.m3u8\n';
 assert.deepEqual(audioNames(master),['AniLibria','Dream Cast']);
 assert.deepEqual(audioNames(''),[]);
});

test('another dub of the loaded Collaps stream is an audio track, anything else needs its own stream',()=>{
 const media={direct:true,audioNames:['AniLibria','Dream Cast','AniDub'],entry:{url:collaps(0)}};
 assert.equal(inStreamAudio(media,collaps(1)),'Dream Cast');
 assert.equal(inStreamAudio(media,collaps(0)),'AniLibria');
 assert.equal(inStreamAudio(media,collaps(7)),'','an index the stream does not carry reloads');
 assert.equal(inStreamAudio(media,collaps(1,4)),'','another episode is another stream');
 assert.equal(inStreamAudio(media,KODIK),'','Collaps → Kodik changes the balancer');
 assert.equal(inStreamAudio({...media,direct:false},collaps(1)),'','a server lease has no in-browser audio list');
 assert.equal(inStreamAudio(null,collaps(1)),'');
});

test('a picked voice prepares a new stream unless the loaded media already plays it',()=>{
 const request={url:ALLOHA,quality:'best',retry:0,server:'https://vm',sourceUrl:'https://alloha.yani.tv/'};
 const alloha={entry:{url:ALLOHA},request};
 assert.equal(keepsLoadedMedia(alloha,{...request,url:KODIK,sourceUrl:'https://kodik.info/'}),false,'Alloha → Kodik loads Kodik');
 assert.equal(keepsLoadedMedia(alloha,request),true,'picking the playing voice back keeps its stream');
 assert.equal(keepsLoadedMedia(alloha,{...request,quality:'720'}),false,'another quality is another stream');
 assert.equal(keepsLoadedMedia(alloha,{...request,retry:1}),false,'retry reconnects');
 assert.equal(keepsLoadedMedia(alloha,{...request,server:'https://other'}),false);
 assert.equal(keepsLoadedMedia(alloha,{...request,sourceUrl:'https://other/'}),false,'same address under another referer is re-prepared');
 assert.equal(keepsLoadedMedia({entry:{url:ALLOHA}},request),false,'media without a request record is never reused');
 const direct={direct:true,audioNames:['AniLibria','Dream Cast'],entry:{url:collaps(0)},request:{...request,url:collaps(0)}};
 assert.equal(keepsLoadedMedia(direct,{...request,url:collaps(1)}),true,'Collaps dub → Collaps dub switches the audio track');
 assert.equal(keepsLoadedMedia(direct,{...request,url:collaps(1),sourceUrl:'https://elsewhere/'}),true,'the browser opens Collaps itself, the referer does not matter');
 assert.equal(keepsLoadedMedia(direct,{...request,url:collaps(1,4)}),false);
 assert.equal(keepsLoadedMedia(direct,{...request,url:KODIK}),false,'Collaps → Kodik loads Kodik');
});

test('the player shows a pending voice until its own stream is loaded, and why it failed',()=>{
 const base={playing:true,bestVideo:false,voiceId:'kodik-voice',loadedVoiceId:'alloha-voice',busy:true,error:''};
 assert.deepEqual(voiceSwitchState(base),{phase:'loading',message:''});
 assert.deepEqual(voiceSwitchState({...base,busy:false}),{phase:'loading',message:''},'resolved, stream still preparing');
 assert.deepEqual(voiceSwitchState({...base,busy:false,error:'У этой озвучки пока нет доступных серий.'}),{phase:'failed',message:'У этой озвучки пока нет доступных серий.'});
 assert.deepEqual(voiceSwitchState({...base,error:'old'}),{phase:'loading',message:''},'a retry in progress is loading');
 assert.equal(voiceSwitchState({...base,loadedVoiceId:'kodik-voice'}),null,'the stream of the picked voice plays');
 assert.equal(voiceSwitchState({...base,playing:false}),null);
 assert.equal(voiceSwitchState({...base,loadedVoiceId:''}),null,'nothing loaded yet: the first start has its own loader');
 assert.equal(voiceSwitchState({...base,bestVideo:true}),null,'best-video mode keeps the video and adds the voice as audio');
});
