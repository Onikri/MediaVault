import test from 'node:test';
import assert from 'node:assert/strict';
import {subtitleFormat,parseVtt,cuesToVtt,hlsSubtitleText,readSubtitleTrack,subtitleFileName,vttTime,textTrackText} from '../src/subtitle-export.js';

test('subtitle formats are recognised by their content',()=>{
 assert.equal(subtitleFormat('﻿WEBVTT\n\n00:01.000 --> 00:02.000\nA'),'vtt');
 assert.equal(subtitleFormat('1\r\n00:00:01,000 --> 00:00:02,000\r\nA'),'srt');
 assert.equal(subtitleFormat('[Script Info]\nTitle: x\n[Events]'),'ass');
 assert.equal(subtitleFormat('<html>403</html>'),'');
});

test('VTT times and cues round-trip, duplicates from overlapping segments dropped',()=>{
 assert.equal(vttTime(3723.4567),'01:02:03.457');
 const {cues,map}=parseVtt('WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n1\n00:00:01.000 --> 00:00:02.500 line:90%\nПривет\nмир\n');
 assert.deepEqual(map,{mpegts:900000,local:0});
 assert.deepEqual(cues,[{start:1,end:2.5,text:'Привет\nмир',settings:'line:90%'}]);
 assert.equal(cuesToVtt([...cues,...cues]),'WEBVTT\n\n00:00:01.000 --> 00:00:02.500 line:90%\nПривет\nмир\n');
});

function server(files){
 const calls=[];
 return {calls,fetch:async url=>{calls.push(url);const body=files[url];return {ok:body!=null,status:body==null?404:200,url,text:async()=>body};}};
}

test('an HLS subtitle playlist becomes one VTT on the video timeline',async()=>{
 const base='https://cdn.example/subs/';
 const files={[base+'index.m3u8']:'#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg0.vtt\n#EXTINF:6,\nhttps://cdn.example/other/seg1.vtt\n#EXT-X-ENDLIST\n',
  [base+'seg0.vtt']:'WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n00:00:01.000 --> 00:00:02.000\nОдин\n',
  ['https://cdn.example/other/seg1.vtt']:'WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:1440000,LOCAL:00:00:00.000\n\n00:00:00.500 --> 00:00:01.500\nДва\n'};
 const {fetch,calls}=server(files);
 const result=await hlsSubtitleText(base+'index.m3u8',{fetch});
 assert.equal(calls.length,3);
 // Second segment is 6 s later by its MPEGTS (540000 / 90000).
 assert.equal(result.text,'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nОдин\n\n00:00:06.500 --> 00:00:07.500\nДва\n');
});

test('a track with a file URL is saved in its own format; a failed fetch falls back to cues',async()=>{
 const {fetch}=server({'https://vm/online/t/ru':'1\n00:00:01,000 --> 00:00:02,000\nA\n'});
 const element={src:'https://vm/online/t/ru'},track={mode:'hidden',label:'Русские',cues:[{startTime:1,endTime:2,text:'A'}]};element.track=track;
 const video={textTracks:[track],querySelectorAll:()=>[element]};
 assert.deepEqual(await readSubtitleTrack('native:0',{video,fetch}),{text:'1\n00:00:01,000 --> 00:00:02,000\nA\n',format:'srt'});
 element.src='https://vm/online/t/gone';
 assert.deepEqual(await readSubtitleTrack('native:0',{video,fetch}),{text:'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nA\n',format:'vtt'});
 assert.deepEqual(await readSubtitleTrack('local',{localFile:{name:'my.ass',text:'[Script Info]\n'}}),{text:'[Script Info]\n',format:'ass'});
});

test('cues of a disabled track are read while it is hidden for a moment',async()=>{
 const track={mode:'disabled',cues:null};
 let hidden=0;
 const result=await textTrackText(track,{wait:async()=>{hidden++;track.cues=[{startTime:0,endTime:1,text:'B'}];}});
 assert.equal(hidden,1);assert.equal(track.mode,'disabled');
 assert.match(result.text,/00:00:00.000 --> 00:00:01.000\nB/);
});

test('file names are safe on every system',()=>{
 assert.equal(subtitleFileName(['Re:Zero / 2','Серия 3','Русские?'],'srt'),'Re Zero 2 · Серия 3 · Русские.srt');
 assert.equal(subtitleFileName(['',''],'vtt'),'Субтитры.vtt');
});
