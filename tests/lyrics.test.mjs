import test from 'node:test';import assert from 'node:assert/strict';
import {parseLrc,lyricIndex,lyricFragments,matchLyricRecord} from '../src/lyrics.js';
import {initialStreamLevel,streamBufferPolicy,bitrateBufferPolicy} from '../src/watch-quality.js';
test('LRC retains real line timestamps, offsets, repeated lines and silent gaps',()=>{
 assert.equal(lyricIndex(parseLrc('[00:00]Строка\n[00:02]\n[00:05]Дальше').lines,3),-1,'An empty timed cue terminates the previous lyric during an instrumental gap');
 const r=parseLrc('[offset:100]\n[00:01.20][00:05.20]Тестовая строка\n[00:09]Конец');assert.equal(r.precision,'line');assert.equal(r.lines.length,3);assert.ok(Math.abs(r.lines[0].start-1.1)<1e-9);assert.ok(Math.abs(r.lines[1].start-5.1)<1e-9);assert.equal(lyricIndex(r.lines,.5),-1);assert.equal(lyricIndex(r.lines,6),1);assert.equal(lyricIndex(r.lines,40),-1);
});
test('Enhanced LRC uses supplied word onsets, preserves spaces, and never fabricates timings for plain text',()=>{
 const r=parseLrc('[00:01.00]<00:01.00>Первое <00:02.00>второе<00:03.00>\n[00:05.00]Следующая строка');assert.equal(r.precision,'word');assert.equal(r.lines[0].words[1].start,2);assert.equal(r.lines[0].words[1].end,3);assert.equal(r.lines[1].words.length,0);
 assert.equal(lyricFragments({text:'Первое второе',words:[{text:'Первое'},{text:'второе'}]}).map(p=>p.text).join(''),'Первое второе');assert.equal(parseLrc('Нет временных отметок').lines.length,0);
});
test('Word catalogue matching requires the actual title and artist and rejects unsafe paths',()=>{
 const rows=[{metadata:[['musicName',['Test']],['artists',['Singer']]],rawLyricFile:'123-45.ttml'},{metadata:[['musicName',['Test']],['artists',['Other']]],rawLyricFile:'other.ttml'},{metadata:[['musicName',['Test']],['artists',['Singer']]],rawLyricFile:'../../x.ttml'}];assert.equal(matchLyricRecord(rows,{title:'TEST',artists:['Singer']}).length,1);
});
test('Startup uses connection bitrate without a redundant speed-test fragment and respects constrained devices',()=>{
 const levels=[{bitrate:500000},{bitrate:2000000},{bitrate:5000000},{bitrate:18000000}];assert.equal(initialStreamLevel(levels,{downlink:10}),2);assert.equal(initialStreamLevel(levels,{downlink:1}),0);assert.equal(initialStreamLevel(levels,{saveData:true,downlink:100}),0);assert.equal(initialStreamLevel(levels,{memory:2}),1);assert.ok(streamBufferPolicy({memory:2}).maxBufferSize<streamBufferPolicy().maxBufferSize);assert.ok(bitrateBufferPolicy(streamBufferPolicy(),20000000).maxMaxBufferLength<28);
});
