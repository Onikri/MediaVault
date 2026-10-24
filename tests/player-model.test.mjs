import test from 'node:test';
import assert from 'node:assert/strict';
import {episodeNumber,voiceLabel,buildPlaybackLibrary,openingBounds,toWebVtt} from '../src/player-model.js';

test('groups anime by title and season, and variants by episode without modifying the catalog',()=>{
  const catalog={storage:{collections:[{id:'t1',name:'Пример аниме',parts:[
    {id:'s1',name:'Сезон 1'},{id:'s2',name:'Сезон 2'}]}]},items:[
    {id:'v2',category:'video',collectionId:'t1',partId:'s1',episode:1,name:'01 [AniLibria].mp4',voice:'AniLibria'},
    {id:'v1',category:'video',collectionId:'t1',partId:'s1',episode:1,name:'01 [StudioBand].mp4',voice:'StudioBand'},
    {id:'v3',category:'video',collectionId:'t1',partId:'s1',episode:2,name:'02.mp4'},
    {id:'v4',category:'video',collectionId:'t1',partId:'s2',episode:1,name:'01.mp4'},
    {id:'manga',category:'manga',collectionId:'t1',partId:'s1',name:'01.cbz'}
  ]};
  const original=JSON.stringify(catalog);
  const player=buildPlaybackLibrary(catalog.items[0],catalog);
  assert.equal(player.title,'Пример аниме');
  assert.deepEqual(player.seasons.map(s=>[s.name,s.episodes.length]),[['Сезон 1',2],['Сезон 2',1]]);
  assert.deepEqual(player.seasons[0].episodes[0].variants.map(v=>v.label),['AniLibria','StudioBand']);
  assert.deepEqual(player.seasons[0].episodes[0].variants.map(v=>v.item.id),['v2','v1']);
  assert.equal(JSON.stringify(catalog),original);
});
test('identifies common episode filenames, keeps standalone movies separate',()=>{
  assert.equal(episodeNumber({name:'S02E03.mkv'}),3);
  assert.equal(episodeNumber({name:'серия 12.mp4'}),12);
  assert.equal(episodeNumber({name:'001.m4v'}),1);
  assert.equal(episodeNumber({name:'Ночной фильм.mp4'}),null);
  assert.equal(voiceLabel({name:'01 [Dub Club].mp4'}),'Dub Club');
});
test('validates opening marks and converts local subtitle files without HTML injection',()=>{
  assert.deepEqual(openingBounds([90,180],240),{start:90,end:180});
  assert.equal(openingBounds([180,90]),null);
  assert.equal(openingBounds([0,180],120),null);
  assert.equal(openingBounds({start:0,end:75}).end,75);
  const sample='1\r\n00:00:01,100 --> 00:00:02,800\r\n<ok>Привет\r\n';
  assert.equal(toWebVtt(sample,'test.srt'),'WEBVTT\n\n1\n00:00:01.100 --> 00:00:02.800\n<ok>Привет\n');
  assert.match(toWebVtt('WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nHi','test.vtt'),/^WEBVTT/);
  assert.throws(()=>toWebVtt('bad','test.srt'));
});
