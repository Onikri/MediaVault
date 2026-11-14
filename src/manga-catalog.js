import {mangaPolicy,normalizeTag as normalized} from './manga-tag-policy.js';

export const mangaTagKey=value=>mangaPolicy().key(value);
export const mangaFormatLabel=value=>({manga:'Манга',manhwa:'Манхва',manhua:'Маньхуа',webtoon:'Вебтун'}[String(value).toLowerCase()]||value);
let vocabulary;
export function loadMangaTaxonomy(){
 return vocabulary||=import('../public/data/manga-tags.json',{with:{type:'json'}}).then(({default:data})=>{
  if(data.schemaVersion!==1||!Array.isArray(data.tags)||!Array.isArray(data.sources))throw Error('Справочник тегов недоступен.');
  return data;
 }).catch(error=>{vocabulary=null;throw error;});
}

export function mangaCatalogParams({query='',filters={},language='all',sourceIds=[],page=1,limit=30,sort=''}={}){
 const values={q:query.trim(),tag:filters.tag,genre:filters.genre,year:filters.year,format:filters.format,age:filters.age,language,sourceIds:[...sourceIds].sort().join(','),offset:(Math.max(1,page)-1)*limit,limit,sort};
 return new URLSearchParams(Object.entries(values).filter(([,v])=>v!==undefined&&v!==null&&v!==''));
}

export function mangaFacetOptions(snapshot,live=[],{sourceIds=[],sources={}}={}){
 const names=sourceIds.map(id=>sources[id]?.name).filter(Boolean).map(normalized);
 const domains=new Set((snapshot?.sources||[]).filter(s=>names.includes(normalized(s.name))).map(s=>s.domain));
 const entries=[...(snapshot?.tags||[]).filter(t=>!sourceIds.length||(t.sources||[]).some(s=>domains.has(s))),...live];
 const groups=new Map();
 for(const row of entries){
  const type=['genre','genres'].includes(row.category||row.type)?'genre':'tag';
  const original=row.original||row.label||row.key;if(typeof original!=='string'||!original.trim())continue;
  const key=mangaTagKey(row.key)||mangaTagKey(original);if(!key)continue;
  const label=mangaPolicy().label(key,original),id=type+':'+key;
  const prior=groups.get(id)||{key,label,type,originalLabels:[],works:0,sources:[]};
  prior.originalLabels=[...new Set([...prior.originalLabels,original,...row.originalLabels||[]])];
  prior.sources=[...new Set([...prior.sources,...row.sources||[]])];
  prior.works=Math.max(prior.works,Number(row.works)||0);groups.set(id,prior);
 }
 return [...groups.values()].sort((a,b)=>a.label.localeCompare(b.label,'ru'));
}
