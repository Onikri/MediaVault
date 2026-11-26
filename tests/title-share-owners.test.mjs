import test from 'node:test';
import assert from 'node:assert/strict';
import {publishTitleShare,readTitleShare} from '../src/title-context.js';

// 2026-11-26 the One Piece link was created as a card-only share: the player of
// the previous title, kept alive in the background, erased or replaced the
// share payload of the title on screen. Each publisher now owns its entry.
const pico={title:{id:'pico'},kind:'video',entries:[{url:'https://video.example/pico/1',number:1}]};
const piece={title:{id:'one-piece'},kind:'video',entries:[{url:'https://video.example/op/1',number:1}]};

test('a retained player cannot erase or replace the payload of the title on screen',()=>{
 publishTitleShare(pico,'player-pico');
 publishTitleShare(piece,'player-piece');
 assert.equal(readTitleShare('one-piece'),piece);
 // The background player republishes its own title (episode change, voice…).
 publishTitleShare({...pico,entries:[...pico.entries]},'player-pico');
 assert.equal(readTitleShare('one-piece'),piece,'the visible title keeps its own episodes');
 // Activating One Piece unmounts the retained Pico player: its cleanup clears only itself.
 publishTitleShare(null,'player-pico');
 assert.equal(readTitleShare('one-piece'),piece);
 assert.equal(readTitleShare('pico'),null);
 assert.equal(readTitleShare(),piece,'the newest payload is still the default');
 publishTitleShare(null,'player-piece');
 assert.equal(readTitleShare('one-piece'),null);
 assert.equal(readTitleShare(),null);
});

test('clearing an owner that never published changes nothing',()=>{
 publishTitleShare(piece,'reader');
 publishTitleShare(null,'unknown');
 assert.equal(readTitleShare('one-piece'),piece);
 publishTitleShare(null,'reader');
});
