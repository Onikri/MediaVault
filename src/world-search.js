import {mergeCatalog,rankCatalog} from './catalog.js';

export function sourceTitle(row){
 return {...row,id:row.id||row.provider+':'+row.url,providerId:row.id,providers:[row.providerName||'Suwayomi'],
  titles:row.titles||{},aliases:[...new Set([row.title,...row.aliases||[]])],genres:row.genres||[],tags:row.tags||[],links:row.links||[],ids:row.ids||{},releases:row.releases||[],
  sourceOnly:true,sources:[{url:row.url,provider:row.provider,providerName:row.providerName,language:row.language}],description:row.description||'',cover:row.cover||''};
}
const same=(a,b)=>a.kind===b.kind&&a.aliases.some(x=>x.length>3&&b.aliases.some(y=>x.normalize('NFKC').toLocaleLowerCase()===y.normalize('NFKC').toLocaleLowerCase()));
export function worldResults(metadata,sourceRows,query,selectedSources=[]){
 const rows=sourceRows.map(sourceTitle),values=mergeCatalog([...metadata,...rows]);
 for(const item of values){item.sources=rows.filter(row=>same(item,row)).flatMap(row=>row.sources);if(item.sources.length)item.sourceIds=[...new Set(rows.filter(row=>same(item,row)).map(row=>row.sourceId))];}
 return rankCatalog(selectedSources.length?values.filter(item=>item.sourceIds?.some(id=>selectedSources.includes(id))):values,query);
}
