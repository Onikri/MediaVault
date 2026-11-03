import test from 'node:test';
import assert from 'node:assert/strict';
import {musicIslandLayout} from '../src/music-island.js';
test('island follows its trigger as the navbar contracts',()=>{
 const view={width:1440,height:900},anchor={left:1320,right:1356,top:20,bottom:56,width:36,height:36};
 const first=musicIslandLayout(anchor,view,230),second=musicIslandLayout({...anchor,left:1200,right:1236},view,230);
 assert.equal(first.top,66);assert.equal(first.left-second.left,120);
 assert.equal(first.closedLeft,1320);assert.equal(first.closedWidth,36);assert.equal(first.height,230);
});
test('mobile, landscape and long settings remain inside the viewport',()=>{
 for(const view of [{width:320,height:740},{width:390,height:844},{width:844,height:320}]){
  const box=musicIslandLayout({left:view.width-50,right:view.width-18,top:20,bottom:52,width:32,height:32},view,1200);
  assert.ok(box.left>=12&&box.top>=12);assert.ok(box.left+box.width<=view.width-12);
  assert.ok(box.top+box.height<=view.height-12);assert.ok(box.height<=box.maxHeight);
 }
});
test('a floating bottom transport opens upwards without moving its trigger',()=>{
 const box=musicIslandLayout({left:1000,right:1172,top:730,bottom:766,width:172,height:36},{width:1200,height:790},245,'dock');
 assert.equal(box.top,475);assert.equal(box.closedTop,730);assert.equal(box.closedWidth,172);
});

import {cursorMusicTime} from '../src/music-timeline.js';
test('absolute cursor position selects time independently of the previous song position',()=>{const rect={left:200,width:344};assert.equal(cursorMusicTime(372,rect,200),100);assert.equal(cursorMusicTime(0,rect,200),0);assert.equal(cursorMusicTime(600,rect,200),200);assert.equal(cursorMusicTime(300,rect,0),0);});

import {musicArtworkCrop} from '../src/music-artwork.js';

test('only letterboxed YouTube artwork is zoomed, never square albums or wide frames',()=>{
 assert.equal(musicArtworkCrop('https://i.ytimg.com/vi/id/hqdefault.jpg'),1.34);
 assert.equal(musicArtworkCrop('https://i.ytimg.com/vi/id/custom.webp',480,360),1.34);
 assert.equal(musicArtworkCrop('https://i.ytimg.com/vi/id/maxresdefault.jpg',1280,720),1);
 assert.equal(musicArtworkCrop('https://i.ytimg.com/vi/id/album.jpg',512,512),1);
 assert.equal(musicArtworkCrop('https://album.example/cover.jpg',480,360),1);
 assert.equal(musicArtworkCrop(''),1);
});
