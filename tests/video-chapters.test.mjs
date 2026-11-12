import test from 'node:test';
import assert from 'node:assert/strict';
import {DOMParser} from '@xmldom/xmldom';
import {parseChapterFile,normalizeChapters,chapterIndexAt,chapterSpans,toMatroskaXml,toWebVttChapters,collapsEmbeds,chapterSubtitlePick,chapterSeconds} from '../src/video-chapters.js';

globalThis.DOMParser??=class{parseFromString(text,type){return new DOMParser({onError:()=>{}}).parseFromString(text,type);}};

const sample=[{start:0,title:'Долги Дэндзи'},{start:83,title:'Контракт с Почитой & ко'},{start:900,title:'Бой с демоном-зомби'}];

test('times in every chapter format become seconds',()=>{
 assert.equal(chapterSeconds('01:02:03.500'),3723.5);
 assert.equal(chapterSeconds('1:23'),83);
 assert.equal(chapterSeconds('00:00:01,250'),1.25);
 assert.ok(Number.isNaN(chapterSeconds('abc')));
});

test('Matroska XML written by the player is read back the same, default edition and Russian name first',()=>{
 const xml=toMatroskaXml(sample,1500,'csm-1');
 assert.match(xml,/<ChapterTimeStart>00:01:23\.000000000<\/ChapterTimeStart>/);
 assert.match(xml,/<ChapterTimeEnd>00:25:00\.000000000<\/ChapterTimeEnd>/);
 assert.match(xml,/Контракт с Почитой &amp; ко/);
 assert.equal(xml,toMatroskaXml(sample,1500,'csm-1'),'chapter UIDs are stable');
 assert.deepEqual(parseChapterFile(xml,1500),sample);
 const two='<?xml version="1.0"?><Chapters><EditionEntry><ChapterAtom><ChapterTimeStart>00:00:00.000000000</ChapterTimeStart><ChapterDisplay><ChapterString>Hidden edition</ChapterString></ChapterDisplay></ChapterAtom></EditionEntry>'
  +'<EditionEntry><EditionFlagDefault>1</EditionFlagDefault><ChapterAtom><ChapterTimeStart>00:00:00.000000000</ChapterTimeStart><ChapterDisplay><ChapterString>Prologue</ChapterString><ChapterLanguage>eng</ChapterLanguage></ChapterDisplay><ChapterDisplay><ChapterString>Пролог</ChapterString><ChapterLanguage>rus</ChapterLanguage></ChapterDisplay></ChapterAtom>'
  +'<ChapterAtom><ChapterTimeStart>00:02:00.000000000</ChapterTimeStart><ChapterFlagHidden>1</ChapterFlagHidden><ChapterDisplay><ChapterString>Скрытая</ChapterString></ChapterDisplay></ChapterAtom>'
  +'<ChapterAtom><ChapterTimeStart>00:05:00.000000000</ChapterTimeStart><ChapterDisplay><ChapterString>Погоня</ChapterString></ChapterDisplay></ChapterAtom></EditionEntry></Chapters>';
 assert.deepEqual(parseChapterFile(two),[{start:0,title:'Пролог'},{start:300,title:'Погоня'}]);
});

test('WebVTT chapters, OGM, FFmetadata and a YouTube list are accepted',()=>{
 assert.deepEqual(parseChapterFile(toWebVttChapters(sample,1500)),sample);
 assert.deepEqual(parseChapterFile('CHAPTER01=00:00:00.000\nCHAPTER01NAME=Пролог\nCHAPTER02=00:04:10.500\nCHAPTER02NAME=Погоня'),[{start:0,title:'Пролог'},{start:250.5,title:'Погоня'}]);
 assert.deepEqual(parseChapterFile(';FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=5000\ntitle=A\\=B\n[CHAPTER]\nTIMEBASE=1/1\nSTART=90\nEND=100\ntitle=Второй'),[{start:0,title:'A=B'},{start:90,title:'Второй'}]);
 assert.deepEqual(parseChapterFile('Chapters:\n00:00 Intro\n1:02:03 – Финал'),[{start:0,title:'Intro'},{start:3723,title:'Финал'}]);
 assert.throws(()=>parseChapterFile('<html></html>'),/не нашлось глав/);
});

test('chapters are sorted, deduplicated and cut at the video end',()=>{
 assert.deepEqual(normalizeChapters([{start:500,title:' B '},{start:0.5,title:'A'},{start:500.4,title:'dup'},{start:2000,title:'after end'}],1500),[{start:0,title:'A'},{start:500,title:'B'}]);
 const spans=chapterSpans(sample,1440);
 assert.deepEqual(spans.map(s=>s.end),[83,900,1440]);
 assert.equal(chapterIndexAt(sample,0),0);
 assert.equal(chapterIndexAt(sample,82.9),0);
 assert.equal(chapterIndexAt(sample,83),1);
 assert.equal(chapterIndexAt(sample,1400),2);
});

test('Collaps embeds of the title are sent with the episode, and forced tracks are never used for scenes',()=>{
 const voices=[{variants:[{url:'https://api.namy.ws/embed/kp/2040161?mv_audio=1'},{url:'https://kodik.info/serial/1'}]},{variants:[{sourceUrl:'https://api.namy.ws/embed/kp/2040161'}]}];
 assert.deepEqual(collapsEmbeds(voices,1,3),['https://api.namy.ws/embed/kp/2040161?mv_season=1&mv_episode=3']);
 assert.deepEqual(collapsEmbeds(voices,0,0),['https://api.namy.ws/embed/kp/2040161']);
 assert.equal(chapterSubtitlePick([{value:'off',label:'Выключены'},{value:'hls:0',label:'Рус. форсированные'},{value:'hls:1',label:'English'},{value:'hls:2',label:'Русские полные'}]).value,'hls:2');
 assert.equal(chapterSubtitlePick([{value:'hls:0',label:'Signs'}]),null);
});
