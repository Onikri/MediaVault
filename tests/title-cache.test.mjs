import test from 'node:test';
import assert from 'node:assert/strict';
import {createUploadService} from '../src/upload.js';
import {sealIndex,openIndex,openChunk} from '../crypto.js';

test('Drive title snapshots encrypt artwork and merge episodes imported while images are uploading',async()=>{
  const key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
  const state={admin:true,token:'fixture-token',tokenExpiresAt:Date.now()+3600000,key,salt:crypto.getRandomValues(new Uint8Array(16)),libraryId:'catalog',generation:1,
    catalog:{version:1,folderId:'root',items:[{id:'first-episode'}],storage:{collections:[{id:'title-1',folderId:'title-folder'}]},custom:{retained:true}}};
  let envelope=await sealIndex(state.catalog,key,state.salt),imageWrites=0,conflicts=0;const assets=new Map(),original=globalThis.fetch;
  globalThis.fetch=async(url,options={})=>{
    assert.equal(options.headers.Authorization,'Bearer fixture-token');const u=new URL(url);
    if(u.pathname==='/drive/v3/files/catalog')return new Response(JSON.stringify(envelope),{headers:{ETag:'"fixture-catalog"'}});
    if(u.pathname==='/drive/v3/files'){
      const value=JSON.parse(options.body);assert.equal(value.parents[0],'title-folder');assert.match(value.name,/^art-[\w-]+$/);return Response.json({id:'art-folder'});
    }
    if(u.pathname==='/upload/drive/v3/files'&&options.method==='POST'){
      const body=Buffer.from(await options.body.arrayBuffer()),boundary=options.headers['Content-Type'].split('boundary=')[1];
      const first=body.indexOf('\r\n\r\n')+4,divider=body.indexOf('\r\n--'+boundary,first),start=body.indexOf('\r\n\r\n',divider)+4,end=body.lastIndexOf('\r\n--'+boundary+'--');
      const metadata=JSON.parse(body.subarray(first,divider));assert.match(metadata.name,/^art-[\w-]+\.enc$/);assert.ok(!metadata.name.includes('Наруто'));
      assets.set('art-file',body.subarray(start,end));imageWrites++;
      const serverCatalog=await openIndex(envelope,key);serverCatalog.items.push({id:'server-episode'});envelope=await sealIndex(serverCatalog,key,state.salt);
      return Response.json({id:'art-file'});
    }
    if(u.pathname==='/upload/drive/v3/files/catalog'&&options.method==='PATCH'){assert.equal(options.headers['If-Match'],'"fixture-catalog"');if(conflicts++===0)return Response.json({error:'concurrent write'},{status:412});envelope=JSON.parse(await options.body.text());return Response.json({id:'catalog'});}
    throw Error('Unexpected fixture URL');
  };
  const service=createUploadService({getSession:()=>state,onCatalog:catalog=>{state.catalog=catalog;}});
  try{
    const url='https://art.example.test/cover.png',bytes=new TextEncoder().encode('private poster bytes');
    const stored=await service.saveTitleProfile('anime:title-1',{title:'Наруто',description:'Сохранённое русское описание',userRatings:{owner:8}},[{url,blob:new Blob([bytes],{type:'image/png'})}]);
    const catalog=await openIndex(envelope,key);assert.deepEqual(catalog.items.map(i=>i.id),['first-episode','server-episode']);assert.deepEqual(catalog.custom,{retained:true});
    assert.ok(!JSON.stringify(envelope).includes('Наруто'));assert.ok(!assets.get('art-file').includes(Buffer.from(bytes)));
    const asset=stored.artwork[url];assert.deepEqual(new Uint8Array(await openChunk(assets.get(asset.fileId),key,asset.id,0,asset.iv)),bytes);
    await service.saveTitleProfile('anime:title-1',{description:'Обновлённое описание'},[{url,blob:new Blob([bytes],{type:'image/png'})}]);
    assert.ok(conflicts>=2,'ETag conflict retries with a fresh catalog');assert.equal(imageWrites,1,'Cached images are reused');assert.equal(state.catalog.titleProfiles['anime:title-1'].userRatings.owner,8);
    state.admin=false;await assert.rejects(service.saveTitleProfile('anime:title-1',{}),/администратора/);
  }finally{service.cancel();globalThis.fetch=original;}
});
