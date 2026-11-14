import taxonomy from '../server/catalog-taxonomy.json' with {type:'json'};

const rule=taxonomy.sourceGenres.hentai;
const norm=value=>String(value||'').normalize('NFKC').toLowerCase().replace(/[_-]/g,' ').replace(/\s+/g,' ').trim();
const excludedLabels=new Set(rule.excludeLabels.map(norm));
export const hentaiLabel=value=>['хентай','hentai','ヘンタイ'].includes(norm(value));
export function hentaiExcluded(row={}){
 if(row.hentaiExcluded||row.workFacts?.hentaiExcluded)return true;
 const labels=[...row.genres||[],...row.tags||[],...row.workFacts?.genres||[],...row.workFacts?.tags||[]];
 return labels.some(v=>excludedLabels.has(norm(v)))||(row.sources||[]).some(hentaiExcluded);
}
export function hentaiOrigin(row={},source=''){
 const kind=row.kind||'manga';if(!rule.kinds.includes(kind))return false;
 if(rule.providers.includes(row.provider))return true;
 let host='';try{host=new URL(row.sourceUrl||row.sourceURL||row.url||(source?'https://'+source:'')).hostname.toLowerCase().replace(/\.$/,'');}catch{}
 return rule.hosts.some(domain=>host===domain||host.endsWith('.'+domain))||(row.sources||[]).some(v=>hentaiOrigin({...v,kind}));
}
export function sourceGenreProjection(row,result,{allowed=true,label='Хентай',isHentai=hentaiLabel,source=''}={}){
 if(hentaiExcluded(row))return {genres:result.genres.filter(v=>!isHentai(v)),tags:result.tags.filter(v=>!isHentai(v))};
 if(allowed&&hentaiOrigin(row,source)&&!result.genres.includes(label))return {...result,genres:[...result.genres,label]};
 return result;
}
