// Source-backed Russian names and bounded context for the paused-frame verifier.
import {musicIdentityFor} from './music-library.js';
const clean=v=>String(v??'').replace(/[\u0000-\u001f]/g,' ').trim().slice(0,220);
export const russianName=v=>typeof v==='string'&&/[А-Яа-яЁё]/.test(v)&&!/[A-Za-z\u3040-\u30ff\u3400-\u9fff]/.test(v)?clean(v).slice(0,120):'';
export function pauseContext(item,catalog,title,season){
 const group=catalog?.storage?.collections?.find(v=>v.id===item.collectionId),profile=catalog?.titleProfiles?.[(item.section||group?.section)+':'+item.collectionId];
 return {title:clean(title),aliases:(profile?.aliases||Object.values(group?.metadata?.titles||{})).slice(0,6).map(clean),season:clean(item.season||season||'неизвестен'),episode:clean(item.episode||item.episodeTitle||'неизвестна'),malId:musicIdentityFor(item,catalog),characters:profile?.characters||[]};
}
const normalize=v=>clean(v).normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
const latin=v=>clean(v).toLowerCase().match(/[a-z]+/g)?.sort().join('');
export function localizeCharacters(values,roster){
 return values.map(character=>{
  const candidates=character.candidates.map(c=>{const matches=roster.filter(r=>r.aliases.some(a=>normalize(a)===normalize(c.name)||(latin(a)&&latin(a)===latin(c.name))));const names=[...new Set(matches.map(r=>r.nameRu).filter(Boolean))];return {...c,nameRu:russianName(c.name)||(names.length===1?names[0]:'')};});
  const names=[...new Set(candidates.map(c=>c.nameRu).filter(Boolean))];
  return {...character,candidates,nameRu:!character.uncertain&&names.length===1?names[0]:'',verification:character.uncertain?'needed':names.length===1?'catalog':'needed'};
 });
}
const rosters=new Map();
export async function characterRoster(context,{server,signal}={}){
 const existing=(context.characters||[]).map(c=>({nameRu:russianName(c.name),aliases:[c.name,...c.aliases||[]]})).filter(c=>c.nameRu);
 if(!context.malId)return existing;
 const key=String(context.malId),hit=rosters.get(key);if(hit&&hit.until>Date.now())return [...existing,...hit.values];
 const bounded=AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(10000)]);
 const shiki=(server?server+'/metadata/shikimori?identity='+key+'&kind=anime&part=roles':'https://shikimori.one/api/animes/'+key+'/roles');
 const results=await Promise.allSettled([
  fetch(shiki,{signal:bounded,credentials:'omit'}).then(r=>{if(!r.ok)throw Error();return r.json();}),
  fetch('https://graphql.anilist.co',{method:'POST',credentials:'omit',signal:bounded,headers:{'Content-Type':'application/json'},body:JSON.stringify({query:'query($id:Int!){Media(idMal:$id,type:ANIME){characters(perPage:50,sort:ROLE){nodes{name{full native alternative}}}}}',variables:{id:Number(key)}})}).then(r=>{if(!r.ok)throw Error();return r.json();})
 ]);
 signal?.throwIfAborted();
 const roles=results[0].status==='fulfilled'&&Array.isArray(results[0].value)?results[0].value:[],nodes=results[1].status==='fulfilled'?results[1].value?.data?.Media?.characters?.nodes||[]:[];
 const values=roles.flatMap(r=>{const c=r.character,nameRu=russianName(c?.russian);if(!nameRu)return [];const matches=nodes.filter(n=>[n.name?.full,...n.name?.alternative||[]].some(a=>a&&(normalize(a)===normalize(c.name)||(latin(a)&&latin(a)===latin(c.name))))),n=matches.length===1?matches[0]:null;return [{nameRu,aliases:[c.name,c.russian,n?.name?.full,n?.name?.native,...n?.name?.alternative||[]].filter(Boolean).slice(0,12)}];}).slice(0,100);
 if(values.length){rosters.set(key,{values,until:Date.now()+3600000});while(rosters.size>24)rosters.delete(rosters.keys().next().value);}
 return [...existing,...values];
}
export function characterCropBox(box,width,height){
 const [x,y,r,b]=box,w=r-x,h=b-y;
 const left=Math.max(0,Math.floor((x-w*.5)*width)),top=Math.max(0,Math.floor((y-h*.25)*height));
 return {left,top,width:Math.max(1,Math.min(width,Math.ceil((r+w*.5)*width))-left),height:Math.max(1,Math.min(height,Math.ceil((b+h*2)*height))-top)};
}
