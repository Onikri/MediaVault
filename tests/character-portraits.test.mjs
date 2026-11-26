// Character portraits from the server's catalogue chain. Mocked fetch only: no network, no ML inference.
import test from 'node:test';
import assert from 'node:assert/strict';
import {loadTitleProfile,imageURL,withPortraits,characterPortraits} from '../src/title-metadata.js';

const MAL='https://cdn.myanimelist.net/images/characters/9/310307.jpg';
const role=(id,name,image,main=false)=>({roles:[main?'Main':'Supporting'],roles_russian:[],character:{id,name,russian:'Персонаж '+id,image:{original:image}}});

test('placeholders of every catalogue are no picture',()=>{
  for(const url of ['/assets/globals/missing_original.jpg','https://shikimori.io/assets/globals/missing/main.png','https://cdn.myanimelist.net/images/questionmark_23.gif?s=1',
    'https://s4.anilist.co/file/anilistcdn/character/large/default.jpg','https://st.kp.yandex.net/images/no-poster.gif'])assert.equal(imageURL(url),'',url);
  assert.equal(imageURL('/system/characters/original/40.jpg?1'),'https://shikimori.io/system/characters/original/40.jpg?1');
  assert.equal(imageURL(MAL),MAL);
});

test('server portraits fill only empty pictures and keep the character format',()=>{
  const characters=[{id:'1',name:'А',role:'Главный герой',image:'https://shikimori.io/system/characters/original/1.jpg',description:''},
    {id:'2',name:'Б',role:'Персонаж',image:'',description:''},{id:'3',name:'В',role:'Персонаж',image:'https://shikimori.io/assets/globals/missing_original.jpg',description:''}];
  const result=withPortraits(characters,{1:{image:'https://cdn.myanimelist.net/images/characters/1/1.jpg'},2:{image:MAL},3:{image:'https://s4.anilist.co/file/anilistcdn/character/large/default.jpg'}});
  assert.deepEqual(result.map(c=>Object.keys(c)),characters.map(c=>Object.keys(c)));
  assert.deepEqual(result.map(c=>c.image),[characters[0].image,MAL,characters[2].image]);
});

test('a title dossier asks the server once for the portraits Shikimori lacks, for manga too',async()=>{
  const original=globalThis.fetch,asked=[];
  globalThis.fetch=async value=>{
    const url=new URL(value);let body={data:{Media:null}};
    if(url.pathname==='/metadata/shikimori'){
      const part=url.searchParams.get('part');
      body=part==='roles'?[role(1001,'Thorfinn','/system/characters/original/1001.jpg',true),role(1002,'Bjorn','/assets/globals/missing_original.jpg'),role(1003,'Ylva','/assets/globals/missing_original.jpg')]
        :part?[]:{id:642,russian:'Сага о Винланде',name:'Vinland Saga',description:'Описание',kind:'manga',image:{original:'/system/mangas/original/642.jpg'}};
    }else if(url.pathname.startsWith('/metadata/character-art/')){asked.push(url.pathname+'?'+url.searchParams);body={portraits:{1002:{image:MAL,source:'myanimelist',match:'id'}},missing:['1003']};}
    else if(url.pathname==='/metadata/posters')body={};
    return {ok:true,json:async()=>body};
  };
  try{
    const profile=await loadTitleProfile('642','manga',{server:'https://metadata.fixture'});
    assert.deepEqual(asked,['/metadata/character-art/manga/642?ids=1002%2C1003']);
    assert.deepEqual(profile.characters.map(c=>[c.id,c.image]),[['1001','https://shikimori.io/system/characters/original/1001.jpg'],['1002',MAL],['1003','']]);
    assert.deepEqual(Object.keys(profile.characters[1]),['id','name','original','role','image','description']);
  }finally{globalThis.fetch=original;}
});

test('portrait lookups need a server, a title id and character ids',async()=>{
  const original=globalThis.fetch;let calls=0;globalThis.fetch=async()=>{calls++;return {ok:false};};
  try{
    assert.deepEqual(await characterPortraits('1','anime',['2'],{}),{});
    assert.deepEqual(await characterPortraits('x','anime',['2'],{server:'https://s'}),{});
    assert.deepEqual(await characterPortraits('1','anime',['../x'],{server:'https://s'}),{});
    assert.deepEqual(await characterPortraits('1','ranobe',['2'],{server:'https://s'}),{});
    assert.equal(calls,1);
  }finally{globalThis.fetch=original;}
});
