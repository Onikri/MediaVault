// Ergonomics helpers: where an online title resumes, and layout-proof keys.
import test from 'node:test';
import assert from 'node:assert/strict';
import {titleResume} from '../src/title-resume.js';
import {keyIs,isHelpKey} from '../src/reader-keys.js';

test('an online title resumes at the last episode or chapter from the viewing history',()=>{
 const history=[
  {label:'Re:Zero, глава 12',route:'#watch=ranobe%3Aanilist%3A85737&name=re-zero',at:5,kind:'reader'},
  {label:'Атака титанов · 2 сезон · 5 серия',route:'#watch=anime%3Aanilist%3A16498&name=x',at:9,kind:'video'},
  {label:'Атака титанов · 1 сезон · 3 серия',route:'#watch=anime%3Aanilist%3A16498',at:4,kind:'video'},
  {label:'Берсерк',route:'#watch=manga%3Aanilist%3A1',at:7,kind:'reader'},
 ];
 assert.deepEqual(titleResume(history,'anime:anilist:16498'),{place:'2 сезон · серия 5',at:9,kind:'video'});
 assert.equal(titleResume(history,'ranobe:anilist:85737').place,'глава 12');
 assert.equal(titleResume([{label:'X · 1 сезон · 7 серия',route:'#watch=a',at:1}],'a').place,'серия 7','the first season is not named');
 assert.equal(titleResume(history,'manga:anilist:1'),null,'a label without a place gives no button text');
 assert.equal(titleResume(history,''),null);assert.equal(titleResume(null,'a'),null);
});

test('reader keys match by physical key, so they work on a Russian layout',()=>{
 const n=keyIs('n');
 assert.ok(n({key:'n',code:'KeyN'}));assert.ok(n({key:'т',code:'KeyN'}));assert.ok(n({key:'N',code:'KeyN',shiftKey:true}));assert.ok(!n({key:'m',code:'KeyM'}));
 const size=keyIs('+','=','-','NumpadAdd');assert.ok(size({key:'+',code:'Equal'}));assert.ok(size({key:'-',code:'Minus'}));assert.ok(size({key:'+',code:'NumpadAdd'}));
 assert.ok(keyIs('Home','End')({key:'End',code:'End'}));
 assert.ok(isHelpKey({key:'?',code:'Digit7',shiftKey:true}),'Shift+7 on a Russian layout');assert.ok(isHelpKey({key:',',code:'Slash',shiftKey:true}));assert.ok(!isHelpKey({key:'/',code:'Slash'}));
});
