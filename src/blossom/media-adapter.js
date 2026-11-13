// Translate existing records into the supplied view model, never fetch demo data.
import {mangaPolicy,globalContentPolicy} from '../manga-tag-policy.js';
export function blossomRecord(item={},profile={}){
 item=item||{};profile=profile||{};
 const score=profile.score??item.score;
 const names=(profile.genres||item.genres||[]).map(v=>typeof v==='string'?v:v.name||v.russian||'');
 const genres=[item.kind,item.section,item.category].includes('manga')||globalContentPolicy()?mangaPolicy().project(names):names;
 return {mal_id:profile.sourceId||item.ids?.mal||item.metadataId||item.id,title:profile.title||item.title||item.name||'',title_japanese:profile.originalTitle||item.titles?.native||'',synopsis:profile.description||item.description||'',score:score!==null&&score!==undefined&&score!==''&&Number.isFinite(Number(score))?Number(score):null,episodes:profile.episodes||item.episodes||null,year:profile.year||item.year||null,type:profile.format||item.format||'',status:profile.status||item.status||'',genres:genres.map(name=>({name})),images:{webp:{large_image_url:profile.cover||item.cover||''}},trailer:{...item.trailer,embed_url:profile.trailers?.find(v=>v.url)?.url||item.trailer?.embed_url||null}};
}
