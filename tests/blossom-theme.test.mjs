import test from 'node:test';
import assert from 'node:assert/strict';
import {BLOSSOM,chosenPalette,paletteFromSeed,readAppearance,rgb,sanitizeAppearance,seedFromPixels} from '../src/blossom/theme.js';
import {contrast} from '../src/palette.js';
import {blossomRecord} from '../src/blossom/media-adapter.js';

test('private files without a metadata profile remain usable without invented catalog facts',()=>{
 const view=blossomRecord({id:'file-1',name:'Личная книга.txt'},null);
 assert.equal(view.title,'Личная книга.txt');assert.equal(view.mal_id,'file-1');
 assert.equal(view.score,null);assert.equal(view.episodes,null);assert.deepEqual(view.genres,[]);
 assert.equal(blossomRecord({name:'filename.mp4'},{title:'Русское название',score:8.5}).score,8.5);
});

test('default and manual palettes retain the supplied Blossom identity',()=>{
 assert.equal(BLOSSOM.canvas,'#11191c');assert.equal(BLOSSOM.blossom,'#ee3c35');assert.equal(BLOSSOM.petal,'#e6ddd8');
 assert.deepEqual(chosenPalette(sanitizeAppearance(),'#0000ff'),BLOSSOM);
 const manual=sanitizeAppearance({custom:'#2a72cc'});
 assert.deepEqual(chosenPalette(manual,'#ff0000'),chosenPalette(manual,'#00ff00'));
 assert.notEqual(chosenPalette(manual).canvas,BLOSSOM.canvas);
});
test('background mode changes surfaces, accents and text without losing contrast',()=>{
 const blue=chosenPalette({mode:'background'},'#205de0'),red=chosenPalette({mode:'background'},'#d82a3c');
 for(const role of ['canvas','surface','surfaceRaised','blossom','onSurface'])assert.notEqual(blue[role],red[role]);
 for(const seed of ['#000000','#ffffff','#ee3c35','#00ff00','#0000ff','#ff00ff','#888888']){
  const p=paletteFromSeed(seed);
  assert.ok(contrast(rgb(p.onSurface),rgb(p.surfaceRaised))>=7,'body text '+seed);
  assert.ok(contrast(rgb(p.onMuted),rgb(p.surfaceRaised))>=4.5,'muted text '+seed);
  assert.ok(contrast(rgb(p.blossomLight),rgb(p.surfaceRaised))>=4.5,'link text '+seed);
  assert.ok(contrast(rgb(p.petal),rgb(p.crimson))>=4.5,'primary button '+seed);
 }
});
test('invalid persisted settings cannot inject CSS or break startup',()=>{
 for(const value of ['{broken','null','42','"text"'])assert.deepEqual(readAppearance({getItem:()=>value}),sanitizeAppearance());
 assert.deepEqual(sanitizeAppearance({mode:'evil',preset:'unknown',custom:'red);url(https://example.test)'}),sanitizeAppearance());
 assert.equal(readAppearance({getItem:()=>'{"custom":"#ABCDEF","mode":"background"}'}).custom,'#abcdef');
 assert.deepEqual(readAppearance({getItem:()=>{throw Error('storage denied');}}),sanitizeAppearance());
});
test('monochrome backgrounds stay neutral instead of falling back to an unrelated hue',()=>{
 for(const shade of [0,80,128,255])assert.equal(seedFromPixels(Uint8ClampedArray.from(Array.from({length:32},()=>[shade,shade,shade,255]).flat())),'#'+shade.toString(16).padStart(2,'0').repeat(3));
 assert.match(seedFromPixels(new Uint8ClampedArray()),/^#[\da-f]{6}$/);
});
