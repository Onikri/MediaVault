import test from 'node:test';import assert from 'node:assert/strict';
import {spreadPages,turnPage} from '../src/reader-layout.js';
import {sanitize} from '../src/reader-settings.js';
import {inEpisodes} from '../src/use-episode-music.js';
test('book cover remains single and subsequent spreads preserve pairs when resuming from the right-hand page',()=>{assert.deepEqual(spreadPages(0,8),[0]);assert.deepEqual(spreadPages(2,8),[1,2]);assert.deepEqual(spreadPages(7,8),[7]);assert.equal(turnPage(0,1,8,true),1);assert.equal(turnPage(1,1,8,true),3);assert.equal(turnPage(3,-1,8,true),1);assert.equal(turnPage(1,-1,8,true),0);assert.equal(sanitize({mode:'spread'}).mode,'spread');});
test('music cues use the exact episode range instead of announcing the wrong opening',()=>{assert.equal(inEpisodes(['1-12'],2),true);assert.equal(inEpisodes(['13-24'],2),false);assert.equal(inEpisodes(['1, 3-5'],4),true);assert.equal(inEpisodes(['1, 3-5'],2),false);});
